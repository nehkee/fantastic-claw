import os
import re
import traceback
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

import requests
import tweepy

load_dotenv()

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="."), name="static")

@app.get("/")
def get_ui():
    return FileResponse("index.html")

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
    return re.sub(r'\s+', ' ', text).strip()[:4000] # Cut down to 4k to save tokens!

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

# Using the lightning-fast, highly efficient 8B model to reset your rate limits
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
agent_executor = AgentExecutor(
    agent=agent, 
    tools=tools, 
    verbose=True, 
    max_iterations=4,
    handle_parsing_errors=True
)

# --- TELEGRAM LOGIC ---

def send_telegram_message(chat_id: int, text: str):
    """Helper function to push messages to Telegram"""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Error: TELEGRAM_BOT_TOKEN missing")
        return
        
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    # We disable web page preview so the chat isn't cluttered with massive link cards
    payload = {
        "chat_id": chat_id, 
        "text": text, 
        "parse_mode": "Markdown",
        "disable_web_page_preview": True 
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Telegram API Error: {e}")

def process_telegram_query(chat_id: int, text: str):
    """The background task that runs the AI without timing out the webhook"""
    urls = extract_urls(text)
    
    if not urls:
        send_telegram_message(chat_id, "🦀 *Awaiting Protocol...*\nPlease send a valid product URL for deep-scan extraction.")
        return
        
    url = urls[0]
    
    # Send a loading message so the user knows the bot is working
    send_telegram_message(chat_id, "🔄 *Tunnel Established*\nBypassing anti-bot protocols and consulting the LLM...\n_This usually takes 10-15 seconds._")
    
    try:
        response = agent_executor.invoke({"input": f"Perform a professional flip analysis on: {url}"})
        result_text = response["output"]
        send_telegram_message(chat_id, result_text[:4000]) # Telegram max is 4096
    except Exception as e:
        error_msg = f"⚠️ *CRITICAL EXCEPTION*\n\nThe Claw jammed. Check target URL integrity.\n`{str(e)}`"
        send_telegram_message(chat_id, error_msg)

@app.post("/telegram-webhook")
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    """Receives the instant ping from Telegram and hands it off to the background"""
    data = await request.json()
    
    if "message" in data and "text" in data["message"]:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"]["text"]
        
        # Add the heavy lifting to the background task queue
        background_tasks.add_task(process_telegram_query, chat_id, text)
        
    # Return 200 OK instantly to keep Telegram happy!
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