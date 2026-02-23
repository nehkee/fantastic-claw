import os
import re
import requests
import traceback
from typing import Optional
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from pydantic import BaseModel, Field
from functools import lru_cache
from bs4 import BeautifulSoup
from apscheduler.schedulers.background import BackgroundScheduler

# LangChain Imports
from langchain_groq import ChatGroq
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain.tools import tool

load_dotenv()

# --- BACKGROUND SCHEDULER ---
scheduler = BackgroundScheduler()

def run_sniper_monitors():
    print("[SYSTEM] Executing background sniper price monitors...")

@asynccontextmanager
async def lifespan(app: FastAPI):
    if not scheduler.running:
        scheduler.add_job(run_sniper_monitors, 'interval', minutes=15)
        scheduler.start()
    yield
    scheduler.shutdown()

# --- APP INITIALIZATION ---
app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files (index.html)
app.mount("/static", StaticFiles(directory="."), name="static")

@app.get("/")
def get_ui():
    path = os.path.join(os.path.dirname(__file__), "index.html")
    if os.path.exists(path):
        return FileResponse(path)
    return JSONResponse(status_code=404, content={"error": "index.html not found"})

# --- UTILITY: HTML CLEANER ---
def clean_html_for_ai(raw_html: str) -> str:
    """Strips noise and isolates product data to save tokens."""
    soup = BeautifulSoup(raw_html, "html.parser")
    for element in soup(["script", "style", "nav", "footer", "header", "aside", "noscript", "svg", "iframe"]):
        element.decompose()

    # Target high-signal IDs for marketplaces
    content = ""
    target_ids = ["productTitle", "corePrice_feature_div", "feature-bullets", "productDescription", "centerCol"]
    for tid in target_ids:
        found = soup.find(id=tid)
        if found:
            content += found.get_text(separator=" ") + " "

    if not content.strip():
        content = soup.get_text(separator=" ")
    
    text = re.sub(r'\s+', ' ', content).strip()
    return text[:2000] # Increased context slightly for better reasoning

# --- AI TOOLS ---

@tool
@lru_cache(maxsize=100)
def scrape_listing(url: str) -> str:
    """Scrapes product details, specs, and current pricing from a URL."""
    scraper_key = os.getenv("SCRAPER_API_KEY")
    if not scraper_key: return "Error: Missing SCRAPER_API_KEY"
    
    # Using premium=true and country_code=us for high-fidelity retail data
    payload = {'api_key': scraper_key, 'url': url, 'premium': 'true', 'country_code': 'us'}
    try:
        response = requests.get('http://api.scraperapi.com', params=payload, timeout=30)
        if response.status_code == 200:
            return clean_html_for_ai(response.text)
        return f"Scrape failed with status: {response.status_code}"
    except Exception as e:
        return f"Scraper error: {str(e)}"

@tool
def calculate_true_net_margin(sale_price: float, cost_of_goods: float, category: str = "general") -> str:
    """
    Calculates precise Net Profit and ROI using category-specific referral fees.
    Categories: 'electronics' (8%), 'apparel' (17%), 'general' (15%).
    """
    cat = category.lower()
    if any(x in cat for x in ["elect", "tech", "pc", "phone"]):
        ref_rate = 0.08
    elif any(x in cat for x in ["apparel", "cloth", "shoe"]):
        ref_rate = 0.17
    else:
        ref_rate = 0.15

    referral_fee = sale_price * ref_rate
    fba_fee = 5.15 # Average standard size FBA fulfillment cost
    
    net_profit = sale_price - cost_of_goods - referral_fee - fba_fee
    roi = (net_profit / cost_of_goods) * 100 if cost_of_goods > 0 else 0
    
    return (f"Financial Audit ({cat.upper()}): "
            f"Net Profit: ${net_profit:.2f} | ROI: {roi:.2f}% | "
            f"Fees: ${referral_fee:.2f} (Ref) + ${fba_fee:.2f} (FBA)")

@tool
def retrieve_comparative_deals(product_name: str) -> str:
    """Searches the web for the current 'Market Floor' price of a specific product name."""
    scraper_key = os.getenv("SCRAPER_API_KEY")
    search_url = f"https://www.google.com/search?q={product_name.replace(' ', '+')}+price+comparison"
    payload = {'api_key': scraper_key, 'url': search_url, 'premium': 'true'}
    try:
        response = requests.get('http://api.scraperapi.com', params=payload, timeout=25)
        return clean_html_for_ai(response.text)
    except Exception as e:
        return f"Market search failed: {str(e)}"

# --- AGENT SETUP ---
llm = ChatGroq(
    api_key=os.getenv("GROQ_API_KEY"), 
    model="llama-3.3-70b-versatile", # Upgraded to flagship model for investment-grade logic
    temperature=0.1
)

tools = [scrape_listing, calculate_true_net_margin, retrieve_comparative_deals]

prompt = ChatPromptTemplate.from_messages([
    ("system", """You are the 'Claw Protocol' Enterprise Agent. 
    Your mission is to validate retail arbitrage opportunities with clinical precision.
    
    CORE PROTOCOL:
    1. SCRAPE the user's URL to find the current item and price.
    2. CATEGORIZE the item (Electronics, Apparel, or General) to apply correct fees.
    3. COMPARE: Use `retrieve_comparative_deals` to find the absolute market floor.
    4. CALCULATE: Use `calculate_true_net_margin` using the target market price as 'sale_price' and the input URL price as 'cost_of_goods'.
    
    FORMATTING:
    - Use Markdown headers and bold text for clarity.
    - Provide a 'Final Recommendation': [STRONG BUY], [WATCH], or [PASS].
    - ROI > 20% is a [STRONG BUY].
    """),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])

agent_executor = AgentExecutor(
    agent=create_tool_calling_agent(llm, tools, prompt), 
    tools=tools, 
    verbose=True,
    handle_parsing_errors=True
)

# --- ENDPOINTS ---

@app.post("/trigger-claw")
async def trigger_agent(url: str):
    try:
        # We prompt the agent to perform the full 4-step protocol
        input_msg = f"Execute a full arbitrage audit on this listing: {url}"
        response = agent_executor.invoke({"input": input_msg})
        return {"result": response["output"]}
    except Exception as e:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": f"Internal Protocol Error: {str(e)}"})

@app.get("/health")
def health():
    return {"status": "Operational", "engine": "Llama-3.3-70B"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)