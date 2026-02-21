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

# --- UTILITY: CLEANING THE HTML ---
def clean_html(raw_html: str) -> str:
    """Removes scripts, styles, and extra whitespace to save tokens/speed up Groq."""
    soup = BeautifulSoup(raw_html, "html.parser")
    for script_or_style in soup(["script", "style", "meta", "link", "noscript"]):
        script_or_style.decompose()
    text = soup.get_text(separator=" ")
    # Clean up massive whitespace gaps
    return re.sub(r'\s+', ' ', text).strip()[:7000]

# --- TOOLS ---

@tool
@lru_cache(maxsize=100)
def scrape_listing(url: str) -> str:
    """Scrapes Amazon product details. Use this FIRST."""
    scraper_key = os.getenv("SCRAPER_API_KEY")
    if not scraper_key: return "Error: Missing API Key"
    
    payload = {'api_key': scraper_key, 'url': url, 'premium': 'true'}
    try:
        response = requests.get('http://api.scraperapi.com', params=payload, timeout=30)
        if response.status_code == 200:
            return clean_html(response.text)
        return f"Scraper Error: {response.status_code}"
    except Exception as e:
        return f"Conn Error: {str(e)}"

class SearchDealsInput(BaseModel):
    query: str = Field(description="The product name/category to search for.")

@tool(args_schema=SearchDealsInput)
@lru_cache(maxsize=100)
def search_better_deals(query: str) -> str:
    """Searches Amazon for alternatives."""
    scraper_key = os.getenv("SCRAPER_API_KEY")
    search_url = f"https://www.amazon.com/s?k={query.replace(' ', '+')}"
    
    payload = {'api_key': scraper_key, 'url': search_url, 'premium': 'false'}
    try:
        response = requests.get('http://api.scraperapi.com', params=payload, timeout=30)
        if response.status_code == 200:
            return clean_html(response.text)
        return "Search failed."
    except Exception:
        return "Search error."

# --- AGENT SETUP ---

llm = ChatGroq(
    api_key=os.getenv("GROQ_API_KEY"),
    model="llama-3.3-70b-versatile",
    temperature=0.1, # Lower temperature = more focus, less rambling
    request_timeout=60.0
)

tools = [scrape_listing, search_better_deals]

prompt = ChatPromptTemplate.from_messages([
    ("system", """You are The Fantastic Claw. 
    1. Scrape the URL. Extract Product Name & Price.
    2. Search for the same product to find lower prices.
    3. Compare everything. 
    4. Provide 2 alternative links using [Name](https://www.amazon.com/dp/ASIN).
    
    BE CONCISE. NO YAPPING. JUST THE DEALS. 🦀"""),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])

agent = create_tool_calling_agent(llm, tools, prompt)
agent_executor = AgentExecutor(
    agent=agent, 
    tools=tools, 
    verbose=True, 
    max_iterations=3, # Stops the agent from looping forever
    handle_parsing_errors=True # Crucial for speed
)

# --- ENDPOINTS ---

@app.post("/trigger-claw")
async def trigger_agent(url: str):
    try:
        response = agent_executor.invoke({"input": f"Analyze: {url}"})
        return {"result": response["output"]}
    except Exception as e:
        # Check logs for the specific error
        print(f"CRASH LOG: {traceback.format_exc()}")
        return JSONResponse(status_code=500, content={"error": "The Claw is jammed. Check logs."})

@app.get("/health")
def health():
    return {"status": "online"}