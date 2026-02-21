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
    """Strips the junk but keeps the meat: Title, Price, and ASINs."""
    soup = BeautifulSoup(raw_html, "html.parser")
    for element in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        element.decompose()
    
    # We specifically look for ASINs in the text or links to help the agent build URLs
    text = soup.get_text(separator=" ")
    return re.sub(r'\s+', ' ', text).strip()[:10000]

# --- TOOLS ---

@tool
@lru_cache(maxsize=100)
def scrape_listing(url: str) -> str:
    """Scrapes product details and pricing from a URL."""
    scraper_key = os.getenv("SCRAPER_API_KEY")
    if not scraper_key: return "Error: Missing API Key"
    
    payload = {'api_key': scraper_key, 'url': url, 'premium': 'true', 'autoparse': 'true'}
    try:
        response = requests.get('http://api.scraperapi.com', params=payload, timeout=40)
        return clean_html_for_ai(response.text) if response.status_code == 200 else "Scrape failed."
    except Exception as e:
        return f"Error: {str(e)}"

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
        response = requests.get('http://api.scraperapi.com', params=payload, timeout=40)
        return clean_html_for_ai(response.text)
    except Exception:
        return "Search failed."

# --- AGENT SETUP ---

llm = ChatGroq(
    api_key=os.getenv("GROQ_API_KEY"),
    model="llama-3.3-70b-versatile",
    temperature=0.1, 
    request_timeout=90.0
)

tools = [scrape_listing, search_better_deals]

prompt = ChatPromptTemplate.from_messages([
    ("system", """You are a professional Retail Arbitrage Analyst. 
    Analyze the provided product and find cheaper alternatives to determine flip potential.
    
    OUTPUT REQUIREMENTS:
    1. Use a clean, professional spatial arrangement (Markdown headers and lists).
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
    | Alternative 2 | $XX.XX | [Link] |
    """),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])

agent = create_tool_calling_agent(llm, tools, prompt)
agent_executor = AgentExecutor(
    agent=agent, 
    tools=tools, 
    verbose=True, 
    max_iterations=10, 
    handle_parsing_errors=True
)

# --- ENDPOINTS ---

@app.post("/trigger-claw")
async def trigger_agent(url: str):
    try:
        response = agent_executor.invoke({"input": f"Perform a professional flip analysis on: {url}"})
        return {"result": response["output"]}
    except Exception:
        return JSONResponse(status_code=500, content={"error": "Analysis timed out. Please try again."})

@app.get("/health")
def health():
    return {"status": "Online"}