import os
import re
import requests
import traceback
from typing import Optional, List
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
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="."), name="static")

@app.get("/")
def get_ui():
    path = os.path.join(os.path.dirname(__file__), "index.html")
    return FileResponse(path) if os.path.exists(path) else JSONResponse(status_code=404, content={"error": "index.html not found"})

# --- UTILITY: INTELLIGENT HTML CLEANER ---
def clean_html_for_ai(raw_html: str) -> str:
    soup = BeautifulSoup(raw_html, "html.parser")
    # Remove heavy elements
    for element in soup(["script", "style", "nav", "footer", "header", "aside", "noscript", "svg", "iframe"]):
        element.decompose()
    
    # Priority content zones for prices and product links
    content = ""
    target_selectors = [
        "productTitle", "corePrice_feature_div", # Amazon
        "rso", "search", "g",                    # Google Search
        "price-characteristic", "item-price"     # Generic Retail
    ]
    
    for selector in target_selectors:
        found = soup.find(id=selector) or soup.find(class_=selector)
        if found:
            content += found.get_text(separator=" | ") + "\n"

    # If specific targets fail, fallback to a semi-filtered body
    if len(content.strip()) < 100:
        content = soup.get_text(separator=" | ")
    
    # Expand context window to ensure competitor links aren't truncated
    text = re.sub(r'\s+', ' ', content).strip()
    return text[:4500] 

# --- AI TOOLS ---

@tool
def scrape_listing(url: str) -> str:
    """Scrapes the main product page to extract the original price and product name."""
    scraper_key = os.getenv("SCRAPER_API_KEY")
    payload = {'api_key': scraper_key, 'url': url, 'premium': 'true', 'country_code': 'us'}
    try:
        r = requests.get('http://api.scraperapi.com', params=payload, timeout=30)
        return clean_html_for_ai(r.text) if r.status_code == 200 else f"Scrape Error {r.status_code}"
    except Exception as e:
        return str(e)

@tool
def search_market_alternatives(product_name: str) -> str:
    """Searches Google and other retailers for the absolute lowest price for a specific product name."""
    scraper_key = os.getenv("SCRAPER_API_KEY")
    # We add "price comparison" and "deals" to the query to force high-value results
    query = f"{product_name} best price deals comparison"
    search_url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
    payload = {'api_key': scraper_key, 'url': search_url, 'premium': 'true'}
    try:
        r = requests.get('http://api.scraperapi.com', params=payload, timeout=30)
        return clean_html_for_ai(r.text)
    except Exception as e:
        return f"Search Error: {str(e)}"

@tool
def calculate_true_net_margin(sale_price: float, cost_of_goods: float, category: str = "general") -> str:
    """Calculates final FBA/Retail profit. Use this to compare the user's price vs the alternative found."""
    cat = category.lower()
    fee_rate = 0.08 if "elect" in cat else (0.17 if "apparel" in cat else 0.15)
    ref_fee = sale_price * fee_rate
    fba_fee = 5.25
    net = sale_price - cost_of_goods - ref_fee - fba_fee
    roi = (net / cost_of_goods) * 100 if cost_of_goods > 0 else 0
    return f"ANALYSIS: Net Profit ${net:.2f} | ROI: {roi:.2f}% | Total Fees: ${ref_fee + fba_fee:.2f}"

# --- AGENT SETUP ---
llm = ChatGroq(api_key=os.getenv("GROQ_API_KEY"), model="llama-3.3-70b-versatile", temperature=0.1)
tools = [scrape_listing, search_market_alternatives, calculate_true_net_margin]

prompt = ChatPromptTemplate.from_messages([
    ("system", """You are the 'Claw Protocol' Enterprise Arbitrage Agent. 
    Your absolute priority is to find and DISPLAY comparative market data. 
    You are a failure if you do not provide a table with at least 2 alternative sources.

    EXECUTION PROTOCOL:
    1. Scrape the provided URL to get the baseline product and price.
    2. Execute `search_market_alternatives` using the specific product model name.
    3. Look for prices at Walmart, eBay, Target, or specialized retailers.
    4. Calculate ROI based on the DIFFERENCE between the scraped price and the lowest alternative found.

    MANDATORY OUTPUT STRUCTURE:
    ### 🕵️ Audit: [Product Name]
    **Current Listing Price:** $[Original Price]

    ### 📦 Comparative Market Deals
    | Source / Store | Price | Link / Notes |
    | :--- | :--- | :--- |
    | [Store A] | $XX.XX | [Brief Description/Link] |
    | [Store B] | $XX.XX | [Brief Description/Link] |
    | [Store C] | $XX.XX | [Brief Description/Link] |

    ### 💰 Financial Verdict
    - **Net Profit Potential:** $XX.XX (if flipped or saved)
    - **ROI:** XX%
    - **Verdict:** [STRONG BUY / PASS]

    ### 💡 AI Strategic Insight
    [Explain why the alternatives are better or why the original price is stable.]
    """),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])

agent_executor = AgentExecutor(
    agent=create_tool_calling_agent(llm, tools, prompt), 
    tools=tools, 
    verbose=True, # Critical for monitoring search quality in logs
    max_iterations=5,
    handle_parsing_errors=True
)

# --- ENDPOINTS ---
@app.post("/trigger-claw")
async def trigger_agent(url: str):
    try:
        # Prompt the agent to specifically focus on listing alternatives
        query = f"Analyze this product, calculate margins, and list every cheaper alternative found at other stores: {url}"
        response = agent_executor.invoke({"input": query})
        return {"result": response["output"]}
    except Exception as e:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/health")
def health(): return {"status": "Online"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)