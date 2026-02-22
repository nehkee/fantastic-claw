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
    return FileResponse("index.html")

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
    for element in soup(["script", "style", "nav", "footer", "noscript"]):
        element.decompose()
    text = soup.get_text(separator=" ")
    return re.sub(r'\s+', ' ', text).strip()[:4000]

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
    Analyze the product, find cheaper alternatives using your search tool, and calculate TRUE NET profit.
    
    PROTOCOLS:
    1. NEVER use markdown tables.
    2. ALWAYS use bullet points for lists.
    3. YOU MUST list the Original Product AND at least 2 cheaper Alternative Products.
    4. CLEAN ALL URLs. Remove tracking parameters.
    5. ALWAYS use the `calculate_true_net_margin` tool to ensure FBA fees are deducted. Do not hallucinate math.
    
    OUTPUT FORMAT:
    ### Net Financial Breakdown
    • Original Price: $XX.XX
    • Best Alternative Cost: $XX.XX
    • **True Net Profit:** $XX.XX
    
    ### Historical Context
    (Summarize 90-day Keepa data)
    
    ### Source Links
    • **Original:** $XX.XX - [View Deal](url)
    • **Alt 1:** $XX.XX - [View Deal](url)
    • **Alt 2:** $XX.XX - [View Deal](url)
    """),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])

agent_executor = AgentExecutor(agent=create_tool_calling_agent(llm, tools, prompt), tools=tools, max_iterations=5, handle_parsing_errors=True)

# --- COINBASE COMMERCE LOGIC ---
def generate_usdc_invoice(chat_id: int, amount_usd: float):
    url = "https://api.commerce.coinbase.com/charges"
    payload = {
        "name": "Fantastic Claw - Pro Tier",
        "description": "1 Month Unlimited Scans",
        "pricing_type": "fixed_price",
        "local_price": {"amount": str(amount_usd), "currency": "USD"},
        "metadata": {"chat_id": str(chat_id)}
    }
    headers = {"X-CC-Api-Key": COINBASE_COMMERCE_API_KEY, "X-CC-Version": "2018-03-22", "Content-Type": "application/json", "Accept": "application/json"}
    try:
        response = requests.post(url, json=payload, headers=headers)
        data = response.json()
        checkout_url = data["data"]["hosted_url"]
        send_telegram_message(chat_id, f"*Upgrade to Pro*\n\nYour 3 free scans have been exhausted. Pay exactly `${amount_usd} USDC` via Coinbase to unlock unlimited scans.\n\n[Click here to pay securely]({checkout_url})")
    except Exception as e:
        print(f"Coinbase API Error: {e}")

@app.post("/coinbase-webhook")
async def coinbase_webhook(request: Request):
    payload_body = await request.body()
    signature = request.headers.get("X-CC-Webhook-Signature", "")
    try:
        mac = hmac.new(COINBASE_WEBHOOK_SECRET.encode('utf-8'), payload_body, hashlib.sha256)
        if not hmac.compare_digest(mac.hexdigest(), signature): return JSONResponse(status_code=400, content={"error": "Invalid signature"})
        data = await request.json()
        if data.get("event", {}).get("type") == "charge:confirmed":
            chat_id_str = data.get("event", {}).get("data", {}).get("metadata", {}).get("chat_id")
            if chat_id_str:
                chat_id = int(chat_id_str)
                pro_users.add(chat_id)
                send_telegram_message(chat_id, "*Payment Confirmed!*\n\nYou are now a Fantastic Claw PRO user. Your API limits have been removed. Happy hunting!")
        return {"status": "ok"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

# --- TELEGRAM LOGIC ---
def send_telegram_message(chat_id: int, text: str):
    if not TELEGRAM_BOT_TOKEN: return
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": True})

def process_telegram_query(chat_id: int, text: str):
    if chat_id not in pro_users:
        scans_used = user_scan_counts.get(chat_id, 0)
        if scans_used >= 3:
            generate_usdc_invoice(chat_id, 15.00)
            return
        user_scan_counts[chat_id] = scans_used + 1

    urls = extract_urls(text)
    if not urls:
        send_telegram_message(chat_id, "*Awaiting Protocol...*\nPlease send a valid product URL.")
        return
        
    url = urls[0]
    send_telegram_message(chat_id, "*Tunnel Established*\nBypassing anti-bot protocols and calculating True Net FBA Margins...")
    try:
        response = agent_executor.invoke({"input": f"Analyze: {url}"})
        send_telegram_message(chat_id, response["output"][:4000]) 
    except Exception as e:
        send_telegram_message(chat_id, f"*CRITICAL EXCEPTION*\n\nThe Claw jammed.\n`{str(e)}`")

@app.post("/telegram-webhook")
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    if "message" in data and "text" in data["message"]:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"]["text"]
        background_tasks.add_task(process_telegram_query, chat_id, text)
    return {"status": "ok"}

# --- WEB TERMINAL ENDPOINT ---
@app.post("/trigger-claw")
async def trigger_agent(url: str):
    try:
        response = agent_executor.invoke({"input": f"Perform a professional flip analysis on: {url}"})
        return {"result": response["output"]}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"SYSTEM HALT: {str(e)}"})

# --- CHROME EXTENSION ENDPOINT ---
@app.post("/extension-scan")
async def extension_scan(url: str):
    try:
        response = agent_executor.invoke({"input": f"Provide a brief True Net Profit analysis for: {url}"})
        return {"result": response["output"]}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Failed: {str(e)}"})

@app.get("/health")
def health():
    return {"status": "Online"}