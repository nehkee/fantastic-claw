import os
import re
import traceback
import requests
import hmac
import hashlib
from dotenv import load_dotenv
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
from pydantic import BaseModel, Field
from functools import lru_cache
from bs4 import BeautifulSoup

# LangChain Imports
from langchain_groq import ChatGroq
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain.tools import tool

load_dotenv()

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="."), name="static")

# --- ENVIRONMENT VARIABLES ---
COINBASE_COMMERCE_API_KEY = os.getenv("COINBASE_COMMERCE_API_KEY")
COINBASE_WEBHOOK_SECRET = os.getenv("COINBASE_WEBHOOK_SECRET")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# --- MOCK DATABASE ---
# In production, replace this with PostgreSQL or Redis so data persists across server restarts
user_scan_counts = {}
pro_users = set()

# --- UTILITY: DATA EXTRACTION ---
def extract_urls(text: str) -> list:
    """Extract URLs from text"""
    url_pattern = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
    return re.findall(url_pattern, text)

def clean_html_for_ai(raw_html: str) -> str:
    soup = BeautifulSoup(raw_html, "html.parser")
    for element in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        element.decompose()
    text = soup.get_text(separator=" ")
    return re.sub(r'\s+', ' ', text).strip()[:4000]

# --- TOOLS ---
@tool
@lru_cache(maxsize=100)
def scrape_listing(url: str) -> str:
    """Scrapes product details and pricing from a URL."""
    scraper_key = os.getenv("SCRAPER_API_KEY")
    if not scraper_key: return "Error: Missing API Key"
    
    payload = {'api_key': scraper_key, 'url': url, 'premium': 'true', 'autoparse': 'true'}
    try:
        response = requests.get('http://api.scraperapi.com', params=payload, timeout=25)
        if response.status_code == 403: 
            return "Error: ScraperAPI credits exhausted. Check dashboard."
        return clean_html_for_ai(response.text) if response.status_code == 200 else f"Scrape failed with status: {response.status_code}"
    except Exception as e:
        return f"Scraper Exception: {str(e)}"

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
        if response.status_code == 403: 
            return "Error: ScraperAPI credits exhausted."
        return clean_html_for_ai(response.text) if response.status_code == 200 else f"Search failed with status: {response.status_code}"
    except Exception as e:
        return f"Search Exception: {str(e)}"

# --- AGENT SETUP ---
llm = ChatGroq(
    api_key=os.getenv("GROQ_API_KEY"),
    model="llama-3.1-8b-instant",
    temperature=0.1, 
    request_timeout=60.0
)

tools = [scrape_listing, search_better_deals]

prompt = ChatPromptTemplate.from_messages([
    ("system", """You are a professional Retail Arbitrage Analyst. 
    Analyze the provided product and find cheaper alternatives to determine flip potential.
    
    OUTPUT REQUIREMENTS:
    1. Use a clean, professional spatial arrangement.
    2. Do NOT use emojis.
    3. For every alternative, you MUST provide the Price and a Direct Link.
    4. Construct links using: [Product Name](https://www.amazon.com/dp/ASIN)
    
    STRUCTURE:
    ### Product Verdict
    (Statement of Good/Bad Flip)
    
    ### Financial Breakdown
    - Original Price:
    - Current Deal:
    - Estimated Market Value:
    - Potential Profit:
    
    ### Market Analysis
    (Witty professional summary of demand and quality)
    
    ### Comparative Deals
    | Product Name | Price | Link |
    |--------------|-------|------|
    | Alternative 1 | $XX.XX | [Link] |
    """),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])

agent = create_tool_calling_agent(llm, tools, prompt)
agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True, max_iterations=4, handle_parsing_errors=True)


# --- COINBASE COMMERCE LOGIC ---
def generate_usdc_invoice(chat_id: int, amount_usd: float):
    """Generates a Coinbase Commerce checkout link pegged to USD"""
    url = "https://api.commerce.coinbase.com/charges"
    
    payload = {
        "name": "Fantastic Claw - Pro Tier",
        "description": "1 Month Unlimited Scans",
        "pricing_type": "fixed_price",
        "local_price": {
            "amount": str(amount_usd),
            "currency": "USD"
        },
        "metadata": {
            "chat_id": str(chat_id) # Embed the Telegram ID to verify who paid later
        }
    }
    
    headers = {
        "X-CC-Api-Key": COINBASE_COMMERCE_API_KEY,
        "X-CC-Version": "2018-03-22",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        data = response.json()
        
        checkout_url = data["data"]["hosted_url"]
        msg = f"*Upgrade to Pro*\n\nYour 3 free scans have been exhausted. Pay exactly `${amount_usd} USDC` via Coinbase to unlock unlimited scans.\n\n[Click here to pay securely]({checkout_url})"
        send_telegram_message(chat_id, msg)
        
    except Exception as e:
        print(f"Coinbase API Error: {e}")

@app.post("/coinbase-webhook")
async def coinbase_webhook(request: Request):
    """Listens for the blockchain confirmation from Coinbase"""
    payload_body = await request.body()
    signature = request.headers.get("X-CC-Webhook-Signature", "")
    
    try:
        # Security: Prevent fake payment payloads
        mac = hmac.new(COINBASE_WEBHOOK_SECRET.encode('utf-8'), payload_body, hashlib.sha256)
        if not hmac.compare_digest(mac.hexdigest(), signature):
            return JSONResponse(status_code=400, content={"error": "Invalid signature"})
            
        data = await request.json()
        event_type = data.get("event", {}).get("type")
        
        # "charge:confirmed" means the USDC has cleared on the blockchain
        if event_type == "charge:confirmed":
            charge_data = data.get("event", {}).get("data", {})
            chat_id_str = charge_data.get("metadata", {}).get("chat_id")
            
            if chat_id_str:
                chat_id = int(chat_id_str)
                
                # Update the database to mark user as PRO
                pro_users.add(chat_id)
                
                # Ping the user in Telegram automatically
                send_telegram_message(chat_id, "*Payment Confirmed!*\n\nYou are now a Fantastic Claw PRO user. Your API limits have been removed. Happy hunting!")
                
        return {"status": "ok"}
        
    except Exception as e:
        print(f"Webhook Error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


# --- TELEGRAM LOGIC ---
def send_telegram_message(chat_id: int, text: str):
    if not TELEGRAM_BOT_TOKEN: return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = { "chat_id": chat_id, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": True }
    requests.post(url, json=payload)

def process_telegram_query(chat_id: int, text: str):
    # 1. Check the Paywall first
    if chat_id not in pro_users:
        scans_used = user_scan_counts.get(chat_id, 0)
        
        # Trigger paywall on the 4th scan
        if scans_used >= 3:
            generate_usdc_invoice(chat_id, 15.00)
            return
            
        # Increment the user's scan count
        user_scan_counts[chat_id] = scans_used + 1

    # 2. Extract URLs and analyze
    urls = extract_urls(text)
    
    if not urls:
        msg = "*Awaiting Protocol...*\nPlease send a valid product URL for deep-scan extraction."
        if chat_id not in pro_users:
            msg += f"\n_(Free scans remaining: {3 - user_scan_counts.get(chat_id, 0)})_"
        send_telegram_message(chat_id, msg)
        return
        
    url = urls[0]
    send_telegram_message(chat_id, "*Tunnel Established*\nBypassing anti-bot protocols and consulting the LLM...\n_This usually takes 10-15 seconds._")
    
    try:
        response = agent_executor.invoke({"input": f"Perform a professional flip analysis on: {url}"})
        send_telegram_message(chat_id, response["output"][:4000]) 
    except Exception as e:
        send_telegram_message(chat_id, f"*CRITICAL EXCEPTION*\n\nThe Claw jammed. Check target URL integrity.\n`{str(e)}`")

@app.post("/telegram-webhook")
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    if "message" in data and "text" in data["message"]:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"]["text"]
        background_tasks.add_task(process_telegram_query, chat_id, text)
    return {"status": "ok"}


# --- WEB/UI ENDPOINTS ---
@app.post("/trigger-claw")
async def trigger_agent(url: str):
    try:
        response = agent_executor.invoke({"input": f"Perform a professional flip analysis on: {url}"})
        return {"result": response["output"]}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"SYSTEM HALT: {str(e)}"})

@app.get("/health")
def health():
    return {"status": "Online"}