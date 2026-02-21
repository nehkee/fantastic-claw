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

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="."), name="static")

@app.get("/")
def get_ui():
    return FileResponse("index.html")

# X API Setup
X_CONSUMER_KEY = os.getenv("X_CONSUMER_KEY")
X_CONSUMER_SECRET = os.getenv("X_CONSUMER_SECRET")
X_ACCESS_TOKEN = os.getenv("X_ACCESS_TOKEN")
X_ACCESS_TOKEN_SECRET = os.getenv("X_ACCESS_TOKEN_SECRET")
X_BEARER_TOKEN = os.getenv("X_BEARER_TOKEN")

twitter_client = tweepy.Client(
    bearer_token=X_BEARER_TOKEN,
    consumer_key=X_CONSUMER_KEY,
    consumer_secret=X_CONSUMER_SECRET,
    access_token=X_ACCESS_TOKEN,
    access_token_secret=X_ACCESS_TOKEN_SECRET,
    wait_on_rate_limit=True,
)

# --- TOOLS ---

@tool
@lru_cache(maxsize=100)
def scrape_listing(url: str) -> str:
    """Scrapes Amazon product details. Use this FIRST."""
    scraper_key = os.getenv("SCRAPER_API_KEY")
    if not scraper_key: return "Error: Missing API Key"
    
    # We use premium for the main listing to ensure we get the price/details
    payload = {'api_key': scraper_key, 'url': url, 'premium': 'true', 'autoparse': 'true'}
    try:
        response = requests.get('http://api.scraperapi.com', params=payload, timeout=30)
        # We only return the first 10k chars to avoid overwhelming the LLM context
        return response.text[:10000] if response.status_code == 200 else f"Scraper Error: {response.status_code}"
    except Exception as e:
        return f"Conn Error: {str(e)}"

class SearchDealsInput(BaseModel):
    query: str = Field(description="The product name/category to search for.")

@tool(args_schema=SearchDealsInput)
@lru_cache(maxsize=100)
def search_better_deals(query: str) -> str:
    """Searches Amazon for alternatives. Use this to find better prices."""
    scraper_key = os.getenv("SCRAPER_API_KEY")
    search_url = f"https://www.amazon.com/s?k={query.replace(' ', '+')}"
    
    # Fast datacenter IPs for search results
    payload = {'api_key': scraper_key, 'url': search_url, 'premium': 'false', 'autoparse': 'true'}
    try:
        response = requests.get('http://api.scraperapi.com', params=payload, timeout=30)
        return response.text[:10000]
    except Exception:
        return "Search failed."

# --- AGENT SETUP ---

# Optimized for speed and large context handling
llm = ChatGroq(
    api_key=os.getenv("GROQ_API_KEY"),
    model="llama-3.3-70b-versatile",
    temperature=0.2,
    request_timeout=60.0 # Critical for avoiding the "Connection error"
)

tools = [scrape_listing, search_better_deals]

prompt = ChatPromptTemplate.from_messages([
    ("system", """You are The Fantastic Claw, an expert Amazon deal hunter. 
    
    PROCESS:
    1. Scrape the user's URL. Extract the product name and current price.
    2. ALWAYS use 'search_better_deals' with the product name to find lower prices.
    3. Compare results. If the user's link is expensive, point it out.
    4. MANDATORY: Provide 2 alternative links using [Product Name](https://www.amazon.com/dp/ASIN).
    
    Tone: Witty, sharp, and profit-focused. Use emojis. 🦀"""),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])

agent = create_tool_calling_agent(llm, tools, prompt)
agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True, max_iterations=5)

# --- LOGIC & ENDPOINTS ---

@app.post("/trigger-claw")
async def trigger_agent(url: str):
    try:
        # We increase the timeout here for the agent execution itself
        response = agent_executor.invoke({"input": f"Analyze this: {url}"})
        return {"result": response["output"]}
    except Exception as e:
        print(f"Error: {traceback.format_exc()}")
        return JSONResponse(status_code=500, content={"error": "The Claw is jammed. Check logs."})

@app.get("/health")
def health():
    return {"status": "online"}

# (Include your existing X-webhook and CRC verification code here as previously written)