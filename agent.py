import os
import re
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_openai_functions_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain.tools import tool
import requests
import urllib3
import openai
import traceback
from bs4 import BeautifulSoup
import tweepy
from urllib.parse import urlparse

load_dotenv()

# Web framework setup
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
from pydantic import BaseModel

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
# Mount the project root so `index.html` is available at /ui
app.mount("/static", StaticFiles(directory="."), name="static")

@app.get("/ui")
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
def scrape_listing(url: str) -> str:
    """Scrapes a product listing page for title and price."""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        insecure_note = ""
        try:
            response = requests.get(url, headers=headers, timeout=10, verify=True)
            response.raise_for_status()
        except requests.exceptions.SSLError:
            # Try again without SSL verification (some test sites have missing CA chains)
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            insecure_note = " (SSL verify disabled)"
            response = requests.get(url, headers=headers, timeout=10, verify=False)
            response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Extract title
        title = soup.find("h1") or soup.find("title")
        title_text = title.get_text(strip=True)[:100] if title else "Unknown"
        
        # Extract price
        price_text = "N/A"
        for element in soup.find_all(["span", "div", "p"]):
            text = element.get_text()
            if "$" in text:
                price_match = re.search(r"\$[\d,]+\.?\d*", text)
                if price_match:
                    price_text = price_match.group(0)
                    break
        
        return f"Title: {title_text} | Price: {price_text} | URL: {url}{insecure_note}"
    except Exception as e:
        return f"Error scraping URL: {str(e)}"

# 2. Configure the Agent
llm = ChatOpenAI(model="gpt-4o")
tools = [scrape_listing]
prompt = ChatPromptTemplate.from_messages([
    ("system", "You are The Fantastic Claw on X, a bot that analyzes product listings. Keep responses concise (280 chars). Analyze if it's a good flip/deal and be witty!"),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])
agent = create_openai_functions_agent(llm, tools, prompt)
agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

# Helper function to extract URLs from text
def extract_urls(text: str) -> list:
    """Extract URLs from text"""
    url_pattern = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
    return re.findall(url_pattern, text)


# Simple market values fallback (used when LLM is unavailable)
MARKET_VALUES = {
    "laptop": 1000,
    "headphones": 150,
    "phone": 700,
    "monitor": 300,
    "keyboard": 100,
    "mouse": 50,
    "desk": 400,
}


def extract_price_from_text(text: str) -> Optional[float]:
    """Extract numeric price value from text"""
    m = re.search(r"\$?([\d,]+\.?\d*)", text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except Exception:
        return None


def local_analyze(url: str) -> str:
    """Fallback analysis that scrapes the page and compares price to simple market values."""
    scraped = scrape_listing(url)
    price = extract_price_from_text(scraped)
    title = scraped.split("|", 1)[0] if scraped else "Unknown"
    # crude category detection
    title_lower = scraped.lower()
    category = "unknown"
    for cat in MARKET_VALUES.keys():
        if cat in title_lower:
            category = cat
            break

    market = MARKET_VALUES.get(category)
    if price is None or market is None:
        return f"Quick scan: {scraped} -- Unable to determine market comparison (price or category missing)."

    pct = (market - price) / market * 100
    verdict = ""
    if pct >= 20:
        verdict = f"ALERT: Underpriced ({pct:.0f}% below market). Good flip!"
    elif pct >= 10:
        verdict = f"Good deal ({pct:.0f}% below market)."
    elif abs(pct) <= 10:
        verdict = "Fairly priced."
    else:
        verdict = "Overpriced."

    return f"{scraped}\nMarket ({category}): ${market}. {verdict}"

# 3. REST API Endpoints
@app.get("/")
def health_check():
    return {"status": "The Fantastic Claw is awake and listening on X!", "version": "1.0.0"}


@app.get("/config-status")
def config_status():
    """Return whether key environment variables are present."""
    openai_set = bool(os.getenv("OPENAI_API_KEY"))
    x_creds = all([X_CONSUMER_KEY, X_CONSUMER_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET, X_BEARER_TOKEN])
    return {"openai_api_key_set": openai_set, "x_credentials_set": x_creds}

@app.post("/trigger-claw")
def trigger_agent(url: str):
    """Hit this endpoint to make the agent scrape a specific URL"""
    print(f"Triggered scan for: {url}")
    try:
        response = agent_executor.invoke({"input": f"Check this listing: {url}. Is it a good flip?"})
        return {"result": response["output"]}
    except Exception as e:
        # Log full traceback for diagnostics
        tb = traceback.format_exc()
        print("Agent invoke failed (exception):", tb)
        try:
            with open("agent_error_trace.log", "a", encoding="utf-8") as fh:
                fh.write(tb + "\n---\n")
        except Exception:
            pass

        err = str(e)
        # Detect common OpenAI auth errors by message content
        if any(k in err for k in ["invalid_api_key", "Incorrect API key", "AuthenticationError", "401"]):
            fallback = local_analyze(url)
            return {"result": fallback, "note": "LLM unavailable, returned local analysis"}

        return JSONResponse(status_code=500, content={"error": err})


# Model for posting to X
class PostToXRequest(BaseModel):
    text: str
    in_reply_to: Optional[str] = None
    reply_to_username: Optional[str] = None


@app.post("/post-to-x")
def post_to_x(payload: PostToXRequest):
    """Post text to X (optionally as a reply). Returns tweet id on success."""
    try:
        text = payload.text
        if payload.reply_to_username:
            text = f"@{payload.reply_to_username} {text}"
        resp = twitter_client.create_tweet(text=text, in_reply_to_tweet_id=payload.in_reply_to)
        tweet_id = None
        if hasattr(resp, 'data') and resp.data:
            tweet_id = resp.data.get('id')
        return {"status": "posted", "tweet_id": tweet_id}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

# 4. Twitter Integration - Webhook for mentions
@app.post("/x-webhook")
async def x_webhook(request: Request):
    """
    Handles incoming posts that mention the bot.
    X sends a POST request when someone posts: @FantasticClaw [url] 
    """
    data = await request.json()
    
    # Verify the webhook (X sends a challenge token)
    if data.get("for_user_id"):
        # Handle challenge verification
        return {"challenge_response": data.get("challenge_token")}
    
    try:
        # Extract post data
        if "data" in data and "text" in data["data"]:
            post_text = data["data"]["text"]
            post_id = data["data"]["id"]
            author_id = data["data"]["author_id"]
            
            print(f"New mention: {post_text}")
            
            # Extract URLs from the post
            urls = extract_urls(post_text)
            
            if urls:
                # Process the first URL found
                url = urls[0]
                
                # Call the agent
                try:
                    agent_response = agent_executor.invoke({
                        "input": f"Analyze this product listing for flipping potential: {url}. Be concise and witty!"
                    })
                    reply_text = agent_response["output"][:280]  # X limit
                except openai.error.AuthenticationError:
                    print("OpenAI auth error when handling webhook; using local fallback")
                    reply_text = local_analyze(url)[:280]
                except Exception as e:
                    print(f"Agent error in webhook: {str(e)}; using local fallback")
                    reply_text = local_analyze(url)[:280]
                
                # Reply to the post
                try:
                    twitter_client.create_tweet(
                        text=f"@{data['includes']['users'][0]['username']} {reply_text}",
                        in_reply_to_tweet_id=post_id
                    )
                    print(f"Replied to post {post_id}")
                except Exception as e:
                    print(f"Error replying to post: {str(e)}")
                
                return {"status": "success", "response": reply_text}
            else:
                # No URL found, ask user to provide one
                twitter_client.create_tweet(
                    text=f"@{data['includes']['users'][0]['username']} No URL found! Please tag me with a product link 🦀",
                    in_reply_to_tweet_id=post_id
                )
                return {"status": "no_url_provided"}
    
    except Exception as e:
        print(f"Error processing webhook: {str(e)}")
        return {"status": "error", "message": str(e)}

@app.get("/x-webhook")
def verify_x_webhook(crc_token: str = None):
    """
    X sends a GET request to verify the webhook URL.
    Must return the CRC token in HMAC_SHA256 format.
    """
    if not crc_token:
        return {"error": "Missing crc_token"}
    
    import hmac
    import hashlib
    import base64
    
    consumer_secret = os.getenv("X_CONSUMER_SECRET")
    hash_object = hmac.new(
        consumer_secret.encode('utf-8'),
        crc_token.encode('utf-8'),
        hashlib.sha256
    )
    hash_digest = base64.b64encode(hash_object.digest()).decode('utf-8')
    
    return {
        "response_token": f"sha256={hash_digest}"
    }
