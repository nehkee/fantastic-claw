import os
import re
import csv
import io
import requests
import hmac
import hashlib
import traceback
from dotenv import load_dotenv
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from typing import Optional
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
    scheduler.add_job(run_sniper_monitors, 'interval', minutes=15)
    scheduler.start()
    yield
    scheduler.shutdown()

# --- APP INITIALIZATION ---
app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="."), name="static")

# --- SERVE THE FRONTEND WEB UI ---
@app.get("/")
def get_ui():
    # Fix for Render: Ensure it finds index.html in the current directory
    path = os.path.join(os.path.dirname(__file__), "index.html")
    if os.path.exists(path):
        return FileResponse(path)
    return JSONResponse(status_code=404, content={"error": "index.html not found"})

# --- ENVIRONMENT VARIABLES ---
COINBASE_COMMERCE_API_KEY = os.getenv("COINBASE_COMMERCE_API_KEY")
COINBASE_WEBHOOK_SECRET = os.getenv("COINBASE_WEBHOOK_SECRET")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# --- MOCK DATABASE ---
user_scan_counts = {}
pro_users = set()

# --- UTILITY ---
def extract_urls(text: str) -> list:
    url_pattern = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
    return re.findall(url_pattern, text)

def clean_html_for_ai(raw_html: str) -> str:
    soup = BeautifulSoup(raw_html, "html.parser")
    
    # 1. Aggressively remove non-essential clutter
    for element in soup(["script", "style", "nav", "footer", "header", "aside", "noscript", "svg", "iframe"]):
        element.decompose()

    # 2. Target specific Amazon content areas for high signal
    content = ""
    target_ids = ["productTitle", "corePrice_feature_div", "feature-bullets", "productDescription"]
    for tid in target_ids:
        found = soup.find(id=tid)
        if found:
            content += found.get_text(separator=" ") + " "

    # 3. Fallback and token safety (Max 1500 chars to stay under 6k token limit)
    if not content.strip():
        content = soup.get_text(separator=" ")
    
    text = re.sub(r'\s+', ' ', content).strip()
    return text[:1500] 

# --- AI TOOLS ---
@tool
@lru_cache(maxsize=100)
def scrape_listing(url: str) -> str:
    """Scrapes product details and pricing from a URL."""
    scraper_key = os.getenv("SCRAPER_API_KEY")
    if not scraper_key: return "Error: Missing API Key"
    payload = {'api_key': scraper_key, 'url': url, 'premium': 'true', 'autoparse': 'true'}
    try:
        response = requests.get('http://api.scraperapi.com', params=payload, timeout=25)
        if response.status_code == 403: return "Error: ScraperAPI credits exhausted."
        return clean_html_for_ai(response.text) if response.status_code == 200 else "Scrape failed."
    except Exception as e:
        return str(e)

class SearchDealsInput(BaseModel):
    query: str = Field(description="The product name/category to search.")

@tool(args_schema=SearchDealsInput)
@lru_cache(maxsize=100)
def search_better_deals(query: str) -> str:
    """Searches for alternatives. Returns product names, prices, and ASIN IDs."""
    scraper_key = os.getenv("SCRAPER_API_KEY")
    search_url = f"https://www.amazon.com/s?k={query.replace(' ', '+')}"
    payload = {'api_key': scraper_key, 'url': search_url, 'premium': 'false', 'autoparse': 'true'}
    try:
        response = requests.get('http://api.scraperapi.com', params=payload, timeout=25)
        if response.status_code == 403: return "Error: ScraperAPI credits exhausted."
        return clean_html_for_ai(response.text) if response.status_code == 200 else "Search failed."
    except Exception as e:
        return str(e)

@tool
def calculate_true_net_margin(sale_price: float, cost_of_goods: float, weight_lbs: float = 1.0) -> str:
    """Calculates True Net FBA Margin deducting the 15% referral fee and estimated FBA fees."""
    referral_fee = sale_price * 0.15
    fba_fee = 3.22 + (weight_lbs * 0.50)
    net_profit = sale_price - cost_of_goods - referral_fee - fba_fee
    margin = (net_profit / sale_price) * 100 if sale_price > 0 else 0
    return f"Net FBA Profit: ${net_profit:.2f} | True Margin: {margin:.2f}% (FBA Fee: ${fba_fee:.2f}, Referral: ${referral_fee:.2f})"

@tool
def get_historical_price(asin: str) -> str:
    """Mock Keepa Integration: Checks 90-day price history for an ASIN."""
    return f"Historical Data for {asin}: The 90-day average is steady. No immediate price crash detected."

# --- AGENT SETUP ---
llm = ChatGroq(api_key=os.getenv("GROQ_API_KEY"), model="llama-3.1-8b-instant", temperature=0.1, request_timeout=60.0)
tools = [scrape_listing, search_better_deals, calculate_true_net_margin, get_historical_price]

prompt = ChatPromptTemplate.from_messages([
    ("system", """You are an Enterprise Retail Arbitrage Agent. 
    Analyze the product, find cheaper alternatives using your search tool, and provide a DETAILED comparison.
    
    CRITICAL INSTRUCTION: You MUST use the `search_better_deals` tool to find alternative prices before you provide your final answer.
    
    PROTOCOLS:
    1. ALWAYS include the full Product Name for every link provided.
    2. List the Original Product AND at least 2 cheaper Alternative Products.
    3. Use the `calculate_true_net_margin` tool to ensure math accuracy.
    4. Clean all URLs by removing tracking parameters (delete everything after '?').
    
    OUTPUT FORMAT:
    ### Net Financial Breakdown
    • **Original:** [Full Product Name] at $XX.XX
    • **Best Alt:** [Alternative Name] at $XX.XX
    • **True Net Profit:** $XX.XX
    
    ### Historical Context
    (Briefly summarize 90-day stability)
    
    ### Source Links
    • **Original:** $XX.XX - [View Product](url)
    • **Alt 1:** $XX.XX - [Product Name](url)
    • **Alt 2:** $XX.XX - [Product Name](url)
    """),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])

agent_executor = AgentExecutor(agent=create_tool_calling_agent(llm, tools, prompt), tools=tools, max_iterations=5, handle_parsing_errors=True)

# --- WEB TERMINAL & EXTENSION ENDPOINTS ---
@app.post("/trigger-claw")
async def trigger_agent(url: str):
    try:
        response = agent_executor.invoke({"input": f"Perform a professional flip analysis on: {url}"})
        return {"result": response["output"]}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"SYSTEM HALT: {str(e)}"})

@app.post("/extension-scan")
async def extension_scan(url: str):
    try:
        response = agent_executor.invoke({"input": f"Analyze this specific product and find cheaper alternatives: {url}"})
        return {"result": response["output"]}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Failed: {str(e)}"})

# --- REMAINING ROUTES (TELEGRAM, COINBASE, HEALTH) ---
# ... (Keep your existing Telegram and Coinbase logic here)

@app.get("/health")
def health():
    return {"status": "Online"}