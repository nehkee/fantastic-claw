import os
from dotenv import load_dotenv
from fastapi import FastAPI
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_openai_functions_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain.tools import tool
import requests
from bs4 import BeautifulSoup

load_dotenv()

# Initialize the web app
app = FastAPI()

# 1. Your Scraping Tool
@tool
def scrape_listing(url: str) -> str:
    """Scrapes a product listing page for title and price."""
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(url, headers=headers)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Mock return for example
    return f"Found: Vintage Chair listed for $50 on {url}"

# 2. Configure the Agent
llm = ChatOpenAI(model="gpt-4o")
tools = [scrape_listing]
prompt = ChatPromptTemplate.from_messages([
    ("system", "You are The Fantastic Claw. Analyze the listing and decide if it's a good deal."),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])
agent = create_openai_functions_agent(llm, tools, prompt)
agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

# 3. Create a Web Endpoint to trigger the agent
@app.get("/")
def health_check():
    return {"status": "The Fantastic Claw is awake and listening!"}

@app.post("/trigger-claw")
def trigger_agent(url: str):
    """Hit this endpoint to make the agent scrape a specific URL"""
    print(f"Triggered scan for: {url}")
    response = agent_executor.invoke({"input": f"Check this listing: {url}. Is it a good flip?"})
    return {"result": response["output"]}
