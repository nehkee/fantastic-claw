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

# --- UTILITY: HTML CLEANER ---
def clean_html_for_ai(raw_html: str) -> str:
    soup = BeautifulSoup(raw_html, "html.parser")
    for element in soup(["script", "style", "nav", "footer", "header", "aside", "noscript", "svg", "iframe"]):
        element.decompose()
    
    content = ""
    target_ids = ["productTitle", "corePrice_feature_div", "search", "rso", "centerCol", "productDescription"]
    for tid in target_ids:
        found = soup.find(id=tid) or soup.find(class_=tid)
        if found:
            content += found.get_text(separator=" | ") + "\n"

    if not content.strip():
        content = soup.get_text(separator=" | ")
    
    return re.sub(r'\s+', ' ', content).strip()[:4000]

# --- AI TOOLS ---

@tool
def scrape_listing(url: str) -> str:
    """Scrapes product details, descriptions, ratings, and pricing from a specific URL."""
    scraper_key = os.getenv("SCRAPER_API_KEY")
    payload = {'api_key': scraper_key, 'url': url, 'premium': 'true', 'country_code': 'us'}
    try:
        r = requests.get('http://api.scraperapi.com', params=payload, timeout=30)
        return clean_html_for_ai(r.text) if r.status_code == 200 else f"Scrape Error {r.status_code}"
    except Exception as e:
        return str(e)

@tool
def calculate_flipping_margin(buy_price: float, estimated_sell_price: float) -> str:
    """Calculates platform-agnostic flipping potential using a standard 13% generic marketplace fee."""
    marketplace_fee = estimated_sell_price * 0.13
    net_profit = estimated_sell_price - buy_price - marketplace_fee
    roi = (net_profit / buy_price) * 100 if buy_price > 0 else 0
    return f"FLIPPING POTENTIAL: Net Profit ${net_profit:.2f} | ROI: {roi:.2f}% | Estimated Selling Fees: ${marketplace_fee:.2f}"

@tool
def search_market_alternatives(product_name: str) -> str:
    """Searches the web for lower prices, alternative deals, and historical price context."""
    scraper_key = os.getenv("SCRAPER_API_KEY")
    query = f"{product_name} buy online price comparison"
    search_url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
    payload = {'api_key': scraper_key, 'url': search_url, 'premium': 'true'}
    try:
        r = requests.get('http://api.scraperapi.com', params=payload, timeout=30)
        return clean_html_for_ai(r.text)
    except Exception as e:
        return f"Search Error: {str(e)}"

# --- AGENT SETUP ---
llm = ChatGroq(api_key=os.getenv("GROQ_API_KEY"), model="llama-3.3-70b-versatile", temperature=0.1)
tools = [scrape_listing, calculate_flipping_margin, search_market_alternatives]

prompt = ChatPromptTemplate.from_messages([
    ("system", """You are the 'FlipIntel' Agent. 
    You must output a highly structured, professional Markdown report based on the user's requested MODE.
    
    CRITICAL RULE: ALL links you provide MUST be formatted as valid clickable Markdown links, e.g., [Store Name](https://...). Do NOT just output raw URLs.

    IF MODE IS 'BUYER':
    1. Provide a Product Description and extracted Ratings/Reviews.
    2. Provide Price History or stability estimates based on your search.
    3. List at least 3 Comparative Deals in a Markdown Table with CLICKABLE LINKS.

    IF MODE IS 'RESELLER':
    1. Do everything in the 'BUYER' mode.
    2. Additionally, use `calculate_flipping_margin` and provide a dedicated "Flipping Potential" section showing Net Profit and ROI.

    Use clean Markdown headers (##) for each section.
    """),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])

agent_executor = AgentExecutor(
    agent=create_tool_calling_agent(llm, tools, prompt), 
    tools=tools, 
    verbose=True,
    max_iterations=5,
    handle_parsing_errors=True
)

# --- ENDPOINTS ---
@app.post("/trigger-claw")
async def trigger_agent(url: str, mode: str = "buyer"):
    try:
        query = f"Execute {mode.upper()} AUDIT for: {url}. Ensure all deals have clickable Markdown links."
        response = agent_executor.invoke({"input": query})
        return {"result": response["output"]}
    except Exception as e:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": f"Internal Protocol Error: {str(e)}"})

@app.get("/health")
def health(): return {"status": "Online"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)