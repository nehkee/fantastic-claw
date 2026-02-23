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

app.mount("/static", StaticFiles(directory="."), name="static")

@app.get("/")
def get_ui():
    path = os.path.join(os.path.dirname(__file__), "index.html")
    if os.path.exists(path):
        return FileResponse(path)
    return JSONResponse(status_code=404, content={"error": "index.html not found"})

# --- UTILITY: HTML CLEANER ---
def clean_html_for_ai(raw_html: str) -> str:
    soup = BeautifulSoup(raw_html, "html.parser")
    for element in soup(["script", "style", "nav", "footer", "header", "aside", "noscript", "svg", "iframe"]):
        element.decompose()

    content = ""
    target_ids = ["productTitle", "corePrice_feature_div", "feature-bullets", "productDescription", "centerCol", "search"]
    for tid in target_ids:
        found = soup.find(id=tid)
        if found:
            content += found.get_text(separator=" ") + " "

    if not content.strip():
        content = soup.get_text(separator=" ")
    
    text = re.sub(r'\s+', ' ', content).strip()
    return text[:2500] 

# --- AI TOOLS ---

@tool
@lru_cache(maxsize=100)
def scrape_listing(url: str) -> str:
    """Scrapes product details, specs, and current pricing from a URL."""
    scraper_key = os.getenv("SCRAPER_API_KEY")
    if not scraper_key: return "Error: Missing SCRAPER_API_KEY"
    payload = {'api_key': scraper_key, 'url': url, 'premium': 'true', 'country_code': 'us'}
    try:
        response = requests.get('http://api.scraperapi.com', params=payload, timeout=30)
        return clean_html_for_ai(response.text) if response.status_code == 200 else f"Fail: {response.status_code}"
    except Exception as e:
        return f"Error: {str(e)}"

@tool
def calculate_true_net_margin(sale_price: float, cost_of_goods: float, category: str = "general") -> str:
    """Calculates Net Profit and ROI using category fees: electronics(8%), apparel(17%), general(15%)."""
    cat = category.lower()
    ref_rate = 0.08 if any(x in cat for x in ["elect", "tech", "pc"]) else (0.17 if "apparel" in cat else 0.15)
    referral_fee = sale_price * ref_rate
    fba_fee = 5.15 
    net_profit = sale_price - cost_of_goods - referral_fee - fba_fee
    roi = (net_profit / cost_of_goods) * 100 if cost_of_goods > 0 else 0
    return f"Audit: Net ${net_profit:.2f}, ROI {roi:.2f}%, Fees ${referral_fee + fba_fee:.2f}"

@tool
def find_alternative_deals(product_name: str) -> str:
    """Searches Amazon for competitive prices and similar product links."""
    scraper_key = os.getenv("SCRAPER_API_KEY")
    search_url = f"https://www.amazon.com/s?k={product_name.replace(' ', '+')}"
    payload = {'api_key': scraper_key, 'url': search_url, 'premium': 'true'}
    try:
        response = requests.get('http://api.scraperapi.com', params=payload, timeout=25)
        return clean_html_for_ai(response.text)
    except Exception as e:
        return f"Search Error: {str(e)}"

# --- AGENT SETUP ---
llm = ChatGroq(api_key=os.getenv("GROQ_API_KEY"), model="llama-3.3-70b-versatile", temperature=0.1)
tools = [scrape_listing, calculate_true_net_margin, find_alternative_deals]

prompt = ChatPromptTemplate.from_messages([
    ("system", """You are the 'Claw Protocol' Agent. 
    You MUST provide comparative product recommendations to the user.
    
    STRICT WORKFLOW:
    1. Scrape the URL.
    2. Use `find_alternative_deals` to search for the product name you just scraped.
    3. Identify at least 2 alternative products with their prices and source names.
    4. Use `calculate_true_net_margin` to compare the user's price vs. the best alternative price found.

    MANDATORY OUTPUT FORMAT:
    ### 🛡️ Protocol Analysis
    (Summary of the original product)

    ### 📊 Comparative Market Table
    | Product Name | Price | Source |
    | :--- | :--- | :--- |
    | [Original Product] | $XX.XX | [User Source] |
    | [Alternative 1] | $XX.XX | [Store Name] |
    | [Alternative 2] | $XX.XX | [Store Name] |

    ### 💰 Financial Breakdown
    (Show Net Profit and ROI)

    ### ⚖️ Final Verdict
    [STRONG BUY / WATCH / PASS]
    """),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])

agent_executor = AgentExecutor(agent=create_tool_calling_agent(llm, tools, prompt), tools=tools, verbose=True)

# --- ENDPOINTS ---
@app.post("/trigger-claw")
async def trigger_agent(url: str):
    try:
        response = agent_executor.invoke({"input": f"Perform a full comparative audit on: {url}"})
        return {"result": response["output"]}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/health")
def health(): return {"status": "Online"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)