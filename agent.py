import os
import re
import traceback
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
from pydantic import BaseModel, Field
from functools import lru_cache

# LangChain Imports
from langchain_groq import ChatGroq
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain.tools import tool

import requests
import tweepy

load_dotenv()

# Initialize the web app
app = FastAPI()

# Allow cross-origin requests for the frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend static file(s)
app.mount("/static", StaticFiles(directory="."), name="static")

@app.get("/")
def get_ui():
    return FileResponse("index.html")

# X API Setup (environment variables prefixed with X_)
X_CONSUMER_KEY = os.getenv("X_CONSUMER_KEY")
X_CONSUMER_SECRET = os.getenv("X_CONSUMER_SECRET")
X_ACCESS_TOKEN = os.getenv("X_ACCESS_TOKEN")
X_ACCESS_TOKEN_SECRET = os.getenv("X_ACCESS_TOKEN_SECRET")
X_BEARER_TOKEN = os.getenv("X_BEARER_TOKEN")
BOT_X_HANDLE = os.getenv("BOT_X_HANDLE", "FantasticClaw")

# Initialize Tweepy client
twitter_client = tweepy.Client(
    bearer_token=X_BEARER_TOKEN,
    consumer_key=X_CONSUMER_KEY,
    consumer_secret=X_CONSUMER_SECRET,
    access_token=X_ACCESS_TOKEN,
    access_token_secret=X_ACCESS_TOKEN_SECRET,
    wait_on_rate_limit=True,
)

# 1. Your Scraping Tool
@tool
@lru_cache(maxsize=50)
def scrape_listing(url: str) -> str:
    """Scrapes an Amazon or marketplace webpage to extract product details and prices."""
    scraper_key = os.getenv("SCRAPER_API_KEY")
    
    if not scraper_key:
        return "Error: SCRAPER_API_KEY is missing from environment variables."
        
    payload = {
        'api_key': scraper_key, 
        'url': url, 
        'premium': 'true',
        'autoparse': 'true'
    }
    
    try:
        response = requests.get('http://api.scraperapi.com', params=payload, timeout=45)
        if response.status_code == 200:
            return response.text
        else:
            return f"Scraper got blocked with status code: {response.status_code}"
    except Exception as e:
        return f"Error scraping the page: {str(e)}"

# Create a strict blueprint for the search tool
class SearchDealsInput(BaseModel):
    query: str = Field(description="The mandatory product name or category to search for on Amazon (e.g., 'vintage chair' or 'gaming headset').")

# 2. Your Search Tool
@tool(args_schema=SearchDealsInput)
@lru_cache(maxsize=50)
def search_better_deals(query: str) -> str:
    """Searches Amazon for products based on a keyword query to find alternative deals."""
    scraper_key = os.getenv("SCRAPER_API_KEY")
    
    if not scraper_key:
        return "Error: SCRAPER_API_KEY is missing."
        
    search_url = f"https://www.amazon.com/s?k={query.replace(' ', '+')}"
    
    payload = {
        'api_key': scraper_key, 
        'url': search_url, 
        'premium': 'false', # Fast datacenter IPs for search
        'autoparse': 'true'
    }
    
    try:
        response = requests.get('http://api.scraperapi.com', params=payload, timeout=45)
        if response.status_code == 200:
            return response.text
        else:
            return f"Search blocked: {response.status_code}"
    except Exception as e:
        return f"Search error: {str(e)}"

# 1. Define the LLM engine (FIXED: Added timeout and used stable model name)
llm = ChatGroq(
    api_key=os.getenv("GROQ_API_KEY"),
    model="llama3-70b-8192",
    request_timeout=60.0
)

# 2. Define the tools the agent can use
tools = [scrape_listing, search_better_deals]

# 3. Define the instructions (prompt)
prompt = ChatPromptTemplate.from_messages([
    ("system", """You are The Fantastic Claw on X, a bot that analyzes product listings.
    
    CRITICAL RULES:
    1. First, use `scrape_listing` to analyze the user's provided URL. 
    2. If the item is a bad flip, figure out its general category (e.g., "gaming headset").
    3. You MUST then use the `search_better_deals` tool. When calling it, you MUST provide the 'query' argument with that category name.
    4. Review the search results and pick 1 or 2 cheaper alternatives.
    5. IMPORTANT FORMATTING: You MUST provide a direct link to your alternative recommendations using standard Markdown format. Construct the Amazon link using the ASIN like this: [Product Name](https://www.amazon.com/dp/ASIN)
    6. Keep your final response witty, concise, and highlight the estimated profit margin! 🦀"""),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])

# 4. Build the agent and the executor
agent = create_tool_calling_agent(llm, tools, prompt)
agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

# Helper function to extract URLs from text
def extract_urls(text: str) -> list:
    """Extract URLs from text"""
    url_pattern = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
    return re.findall(url_pattern, text)

# Simple market values fallback
MARKET_VALUES = {
    "laptop": 1000, "headphones": 150, "phone": 700,
    "monitor": 300, "keyboard": 100, "mouse": 50, "desk": 400,
}

def extract_price_from_text(text: str) -> Optional[float]:
    """Extract numeric price value from text"""
    m = re.search(r"\$?([\d,]+\.?\d*)", text)
    if not m: return None
    try:
        return float(m.group(1).replace(",", ""))
    except Exception:
        return None

def local_analyze(url: str) -> str:
    """Fallback analysis that scrapes the page and compares price to simple market values."""
    scraped = scrape_listing(url)
    price = extract_price_from_text(scraped)
    title_lower = scraped.lower()
    category = "unknown"
    for cat in MARKET_VALUES.keys():
        if cat in title_lower:
            category = cat
            break

    market = MARKET_VALUES.get(category)
    if price is None or market is None:
        return f"Quick scan completed. Unable to determine market comparison automatically."

    pct = (market - price) / market * 100
    verdict = "Underpriced!" if pct >= 20 else "Overpriced."
    return f"Scan: ${price}. Market: ${market}. Verdict: {verdict}"

# REST API Endpoints
@app.get("/health")
def health_check():
    return {"status": "The Fantastic Claw is awake!", "version": "1.0.1"}

@app.get("/health/config-status")
def config_status():
    groq_set = bool(os.getenv("GROQ_API_KEY"))
    x_creds = all([X_CONSUMER_KEY, X_CONSUMER_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET, X_BEARER_TOKEN])
    return {"groq_api_key_set": groq_set, "x_credentials_set": x_creds}

@app.post("/trigger-claw")
def trigger_agent(url: str):
    print(f"Triggered scan for: {url}")
    try:
        response = agent_executor.invoke({"input": f"Check this listing: {url}. Is it a good flip?"})
        return {"result": response["output"]}
    except Exception as e:
        tb = traceback.format_exc()
        print("Agent invoke failed:", tb)
        # Fallback to local logic if LLM connection fails
        return {"result": local_analyze(url), "note": "Connection issues, using fallback analysis."}

# Model for posting to X
class PostToXRequest(BaseModel):
    text: str
    in_reply_to: Optional[str] = None
    reply_to_username: Optional[str] = None

@app.post("/post-to-x")
def post_to_x(payload: PostToXRequest):
    try:
        text = payload.text
        if payload.reply_to_username:
            text = f"@{payload.reply_to_username} {text}"
        resp = twitter_client.create_tweet(text=text, in_reply_to_tweet_id=payload.in_reply_to)
        return {"status": "posted", "tweet_id": resp.data.get('id') if hasattr(resp, 'data') else None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/x-webhook")
async def x_webhook(request: Request):
    data = await request.json()
    if data.get("for_user_id"):
        return {"challenge_response": data.get("challenge_token")}
    
    try:
        if "data" in data and "text" in data["data"]:
            post_text = data["data"]["text"]
            post_id = data["data"]["id"]
            urls = extract_urls(post_text)
            
            if urls:
                url = urls[0]
                try:
                    agent_response = agent_executor.invoke({
                        "input": f"Analyze this product listing for flipping potential: {url}. Be concise and witty!"
                    })
                    reply_text = agent_response["output"][:280]
                except Exception:
                    reply_text = local_analyze(url)[:280]
                
                twitter_client.create_tweet(
                    text=f"@{data['includes']['users'][0]['username']} {reply_text}",
                    in_reply_to_tweet_id=post_id
                )
                return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/x-webhook")
def verify_x_webhook(crc_token: str = None):
    if not crc_token: return {"error": "Missing crc_token"}
    import hmac, hashlib, base64
    consumer_secret = os.getenv("X_CONSUMER_SECRET")
    hash_object = hmac.new(consumer_secret.encode('utf-8'), crc_token.encode('utf-8'), hashlib.sha256)
    hash_digest = base64.b64encode(hash_object.digest()).decode('utf-8')
    return {"response_token": f"sha256={hash_digest}"}