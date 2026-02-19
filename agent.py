"""
LangChain AI Agent for Price Analysis
Scrapes product listings and evaluates if items are underpriced
"""

import os
import re
from typing import Any
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup

from langchain.tools import tool
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

# Load environment variables
load_dotenv()

# Mock market values database
MARKET_VALUES = {
    "laptop": 1000,
    "headphones": 150,
    "phone": 700,
    "monitor": 300,
    "keyboard": 100,
    "mouse": 50,
    "desk": 400,
}


@tool
def scrape_listing(url: str) -> str:
    """
    Scrape product information from a URL using BeautifulSoup.
    Extracts title, price, and description.
    
    Args:
        url: The URL of the product listing to scrape
        
    Returns:
        A formatted string with product title, price, and description
    """
    try:
        # Set headers to mimic a browser request
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, "html.parser")
        
        # Common extraction patterns for product pages
        # (These would be customized for specific websites)
        
        # Try to extract title
        title = None
        for tag in ["h1", "h2"]:
            title_elem = soup.find(tag, class_=re.compile("title|product|name", re.I))
            if title_elem:
                title = title_elem.get_text(strip=True)
                break
        
        if not title:
            title = soup.find("title")
            if title:
                title = title.get_text(strip=True)
        
        # Try to extract price
        price = None
        price_patterns = [
            re.compile(r"\$[\d,]+\.?\d*"),
            re.compile(r"price[:\s]*\$?[\d,]+\.?\d*", re.I),
        ]
        
        for tag in ["span", "div", "p"]:
            for elem in soup.find_all(tag):
                text = elem.get_text()
                for pattern in price_patterns:
                    match = pattern.search(text)
                    if match:
                        price = match.group(0)
                        break
                if price:
                    break
            if price:
                break
        
        # Try to extract description
        description = None
        for tag in ["div", "p", "section"]:
            desc_elem = soup.find(tag, class_=re.compile("description|details|info", re.I))
            if desc_elem:
                description = desc_elem.get_text(strip=True)[:500]  # Limit to 500 chars
                break
        
        if not description:
            # Fall back to any paragraph
            paragraphs = soup.find_all("p")
            if paragraphs:
                description = paragraphs[0].get_text(strip=True)[:500]
        
        # Format the result
        result = f"Title: {title or 'N/A'}\n"
        result += f"Price: {price or 'N/A'}\n"
        result += f"Description: {description or 'N/A'}"
        
        return result
        
    except requests.RequestException as e:
        return f"Error: Failed to fetch URL - {str(e)}"
    except Exception as e:
        return f"Error: Failed to scrape listing - {str(e)}"


def extract_price_from_text(text: str) -> float | None:
    """Extract numeric price value from text"""
    match = re.search(r"\$?([\d,]+\.?\d*)", text)
    if match:
        try:
            return float(match.group(1).replace(",", ""))
        except ValueError:
            return None
    return None


def initialize_agent():
    """Initialize the LangChain agent with tools"""
    
    # Initialize the LLM (GPT-4o or Claude)
    # For Claude, use: from langchain_anthropic import ChatAnthropic
    # llm = ChatAnthropic(model="claude-3-5-sonnet-20241022")
    
    llm = ChatOpenAI(
        model="gpt-4o",
        temperature=0,
        api_key=os.getenv("OPENAI_API_KEY")
    )
    
    # Define tools
    tools = [scrape_listing]
    
    # Create system prompt
    system_prompt = """You are a price analysis expert. Your job is to:
1. Scrape product listings from provided URLs
2. Analyze the product information
3. Compare the listed price against market values
4. Identify if items are underpriced

For each product analysis:
- Extract the title, price, and description
- Estimate the product category (laptop, phone, headphones, etc.)
- Look up the typical market value
- Determine if the item is underpriced (listed price is significantly lower than market value)
- If underpriced, generate an ALERT message

Be thorough and analytical in your assessment."""

    # Create prompt template
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("user", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad"),
    ])
    
    # Create the agent
    agent = create_tool_calling_agent(llm, tools, prompt)
    agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)
    
    return agent_executor, extract_price_from_text


def analyze_listing(agent_executor: AgentExecutor, url: str):
    """
    Analyze a product listing and print alerts if underpriced
    """
    print(f"\n{'='*60}")
    print(f"Analyzing: {url}")
    print(f"{'='*60}\n")
    
    prompt = f"""Please analyze this product listing for pricing:
URL: {url}

Steps:
1. Scrape the listing to get title, price, and description
2. Analyze the product to identify its category
3. Compare against typical market prices
4. If the item is significantly underpriced (20%+ below market value), generate an ALERT with details"""
    
    try:
        response = agent_executor.invoke({"input": prompt})
        output = response.get("output", "")
        
        # Check for underpriced items and print alerts
        if "ALERT" in output.upper() or "underpriced" in output.lower():
            print("\n" + "⚠️ " * 20)
            print("🚨 UNDERPRICED ITEM DETECTED! 🚨")
            print("⚠️ " * 20)
            print(output)
            print("⚠️ " * 20 + "\n")
        else:
            print(output)
            
    except Exception as e:
        print(f"Error analyzing listing: {str(e)}")


def main():
    """Main function to demonstrate the agent"""
    
    print("LangChain Price Analysis Agent")
    print("="*60)
    
    # Initialize the agent
    agent_executor, extract_price = initialize_agent()
    
    # Example: Analyze mock listings
    # In a real scenario, you would provide actual product URLs
    test_urls = [
        "https://www.amazon.com/example-laptop",
        "https://www.ebay.com/example-headphones",
    ]
    
    # Interactive mode
    while True:
        print("\nOptions:")
        print("1. Analyze a product URL")
        print("2. Exit")
        
        choice = input("\nEnter your choice (1-2): ").strip()
        
        if choice == "1":
            url = input("Enter product URL: ").strip()
            if url:
                analyze_listing(agent_executor, url)
        elif choice == "2":
            print("Exiting...")
            break
        else:
            print("Invalid choice. Please try again.")


if __name__ == "__main__":
    main()
