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
def clean_html_for_ai(raw_html: str) -> str:
    """Strips the junk but keeps the meat: Title, Price, and Features."""
    soup = BeautifulSoup(raw_html, "html.parser")
    # Remove heavy code but leave the core product content
    for element in soup(["script", "style", "nav", "footer", "header"]):
        element.decompose()
    
    # Target common Amazon/Marketplace body areas
    text = soup.get_text(separator=" ")
    return re.sub(r'\s+', ' ', text).strip()[:8000]

# --- TOOLS ---

@tool
@lru_cache(maxsize=100)
def scrape_listing(url: str) -> str:
    """Scrapes product details and pricing from a URL. Use this first to understand the item."""
    scraper_key = os.getenv("SCRAPER_API_KEY")
    if not scraper_key: return "Error: Missing SCRAPER_API_KEY"
    
    payload = {'api_key': scraper_key, 'url': url, 'premium': 'true', 'autoparse': 'true'}
    try:
        response = requests.get('http://api.scraperapi.com', params=payload, timeout=40)
        if response.status_code == 200:
            return clean_html_for_ai(response.text)
        return f"Scraper got stuck (Status: {response.status_code}). Please try again."
    except Exception as e:
        return f"Connection error during scraping: {str(e)}"

class SearchDealsInput(BaseModel):
    query: str = Field(description="The product name or category to search for better prices.")

@tool(args_schema=SearchDealsInput)
@lru_cache(maxsize=100)
def search_better_deals(query: str) -> str:
    """Searches for cheaper versions of the same product to calculate flip potential."""
    scraper_key = os.getenv("SCRAPER_API_KEY")
    search_url = f"https://www.amazon.com/s?k={query.replace(' ', '+')}"
    
    payload = {'api_key': scraper_key, 'url': search_url, 'premium': 'false', 'autoparse': 'true'}
    try:
        response = requests.get('http://api.scraperapi.com', params=payload, timeout=40)
        return clean_html_for_ai(response.text)
    except Exception:
        return "Search failed to find alternatives."

# --- AGENT SETUP ---

llm = ChatGroq(
    api_key=os.getenv("GROQ_API_KEY"),
    model="llama-3.3-70b-versatile",
    temperature=0.3, # Slight creativity for wit, but stays grounded
    request_timeout=90.0 # Gave it 1.5 mins to handle slow scraper responses
)

tools = [scrape_listing, search_better_deals]

prompt = ChatPromptTemplate.from_messages([
    ("system", """You are 'The Fantastic Claw', the world's sharpest deal analyst on X.
    
    YOUR MISSION:
    1. ANALYZE: Use scrape_listing to get the product name and its CURRENT price.
    2. HUNT: Use search_better_deals to find at least 2 cheaper alternatives or the 'market rate'.
    3. CALCULATE: Determine if the original link is a 'Good Flip' by comparing it to the alternatives. Estimate the profit margin.
    4. REPORT: Give a witty, high-energy review. 
    
    MANDATORY OUTPUT FORMAT:
    - 🦀 **The Verdict**: (Good Flip/Bad Flip/Fair Price)
    - 💰 **Profit Potential**: (Explain the markup/savings)
    - 🔍 **Analysis**: (Quick witty review of the product)
    - 🚀 **Cheaper Alternatives**: 
        1. [Product Name](https://www.amazon.com/dp/ASIN)
        2. [Product Name](https://www.amazon.com/dp/ASIN)
    
    Keep it under 280 characters if possible for X, but provide the full analysis for the UI!"""),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])

agent = create_tool_calling_agent(llm, tools, prompt)
agent_executor = AgentExecutor(
    agent=agent, 
    tools=tools, 
    verbose=True, 
    max_iterations=8, # INCREASED: Gives the AI more room to actually finish the search and comparison
    handle_parsing_errors=True
)

# --- ENDPOINTS ---

@app.post("/trigger-claw")
async def trigger_agent(url: str):
    try:
        print(f"The Claw is grabbing: {url}")
        response = agent_executor.invoke({"input": f"Analyze this listing for flip potential: {url}"})
        return {"result": response["output"]}
    except Exception:
        print(f"CRASH LOG: {traceback.format_exc()}")
        return JSONResponse(status_code=500, content={"error": "The Claw is jammed. The page might be too heavy or the API is timing out."})

@app.get("/health")
def health():
    return {"status": "The Fantastic Claw is online and hungry for deals! 🦀"}