"""
Demo script with mock data to test the price analysis agent
No real web scraping needed - simulates product listings
"""

import os
from unittest.mock import patch
from dotenv import load_dotenv

from langchain.tools import tool
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

load_dotenv()

# Mock product data
MOCK_PRODUCTS = {
    "laptop_deal": {
        "title": "Dell XPS 13 Laptop - Intel i7, 16GB RAM, 512GB SSD",
        "price": "$450",
        "description": "Excellent condition Dell XPS 13 with Intel Core i7 processor, 16GB RAM, and 512GB SSD. Barely used, comes with original charger and box.",
        "category": "laptop",
        "market_value": 900,
    },
    "headphones_normal": {
        "title": "Sony WH-1000XM5 Wireless Headphones",
        "price": "$220",
        "description": "Premium noise-cancelling wireless headphones with 30-hour battery life. Great sound quality.",
        "category": "headphones",
        "market_value": 350,
    },
    "phone_overpriced": {
        "title": "iPhone 12 64GB - Used",
        "price": "$750",
        "description": "iPhone 12 in decent condition, some cosmetic scratches but fully functional.",
        "category": "phone",
        "market_value": 500,
    },
}


@tool
def scrape_listing(url: str) -> str:
    """
    Mock scraping function that returns predefined product data.
    In production, this would use BeautifulSoup to scrape real URLs.
    """
    # Determine which mock product to return based on URL
    if "laptop" in url.lower() or "deal" in url.lower():
        product = MOCK_PRODUCTS["laptop_deal"]
    elif "headphones" in url.lower():
        product = MOCK_PRODUCTS["headphones_normal"]
    elif "phone" in url.lower():
        product = MOCK_PRODUCTS["phone_overpriced"]
    else:
        # Default mock product
        product = {
            "title": "Generic Product",
            "price": "$100",
            "description": "A product listing",
            "category": "unknown",
            "market_value": 150,
        }
    
    return f"""Title: {product['title']}
Price: {product['price']}
Description: {product['description']}
Market Value (Reference): ${product['market_value']}"""


def initialize_demo_agent():
    """Initialize the LangChain agent for demo"""
    
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError(
            "OPENAI_API_KEY not found in .env file.\n"
            "Please create .env from .env.example and add your API key."
        )
    
    llm = ChatOpenAI(
        model="gpt-4o",
        temperature=0,
        api_key=api_key
    )
    
    tools = [scrape_listing]
    
    system_prompt = """You are a price analysis expert. Your job is to:
1. Scrape product listings from provided URLs
2. Analyze the product information
3. Compare the listed price against market values
4. Identify if items are underpriced or overpriced

Analysis guidelines:
- If listed price is 20%+ below market value: Item is UNDERPRICED - issue an ALERT
- If listed price is 10-20% below market value: Item is a GOOD DEAL
- If listed price is within 10% of market value: Item is FAIRLY PRICED
- If listed price is above market value: Item is OVERPRICED

For each analysis, provide:
1. Product category and estimated market value
2. Price comparison analysis
3. Recommendation (BUY, CONSIDER, or AVOID)
4. An ALERT if significantly underpriced"""

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("user", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad"),
    ])
    
    agent = create_tool_calling_agent(llm, tools, prompt)
    agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)
    
    return agent_executor


def run_demo():
    """Run demo analysis on mock products"""
    
    print("\n" + "="*70)
    print("LangChain Price Analysis Agent - DEMO")
    print("="*70)
    print("\nThis demo uses mock product data to show the agent in action.")
    print("No real web scraping or external URLs required.\n")
    
    try:
        agent_executor = initialize_demo_agent()
    except Exception as e:
        print(f"Error: Could not initialize agent: {str(e)}")
        print("Make sure you have set OPENAI_API_KEY in your .env file")
        return
    
    # Test cases
    test_cases = [
        {
            "name": "Underpriced Laptop",
            "url": "https://marketplace.com/laptop-dell-xps-13",
            "description": "High-end laptop at 50% discount"
        },
        {
            "name": "Fair Price Headphones",
            "url": "https://marketplace.com/headphones-sony",
            "description": "Premium headphones at reasonable price"
        },
        {
            "name": "Overpriced Phone",
            "url": "https://marketplace.com/iphone-12-used",
            "description": "Used phone priced higher than market value"
        },
    ]
    
    for test in test_cases:
        print("\n" + "="*70)
        print(f"TEST: {test['name']}")
        print(f"Description: {test['description']}")
        print("="*70 + "\n")
        
        prompt = f"""Please analyze this product listing for pricing:
URL: {test['url']}

Provide a detailed price analysis and recommendation."""
        
        try:
            response = agent_executor.invoke({"input": prompt})
            output = response.get("output", "")
            
            # Highlight alerts
            if "ALERT" in output.upper():
                print("\n" + "🚨 " * 20)
                print("⚠️  UNDERPRICED ITEM DETECTED! ⚠️")
                print("🚨 " * 20 + "\n")
            
            print(output)
            
        except Exception as e:
            print(f"Error during analysis: {str(e)}")
    
    print("\n" + "="*70)
    print("Demo completed!")
    print("="*70 + "\n")


if __name__ == "__main__":
    run_demo()
