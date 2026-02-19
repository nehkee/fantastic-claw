# LangChain Price Analysis Agent

An AI-powered agent that scrapes product listings and analyzes pricing to identify underpriced items using LangChain and GPT-4o (or Claude).

## Features

- **Autonomous Agent**: Uses LangChain to create an AI agent that can reason about pricing
- **Web Scraping**: BeautifulSoup-based tool to extract product title, price, and description from URLs
- **Price Analysis**: Comparative analysis against mock market values
- **Alerts**: Automatic detection and alerting of underpriced items
- **Flexible LLM**: Works with OpenAI's GPT-4o or Anthropic's Claude

## Project Structure

```
fantastic-claw/
├── agent.py              # Main agent with real web scraping and web API
├── demo.py               # Demo script with mock data (no API calls needed initially)
├── requirements.txt      # Python dependencies
├── index.html            # Frontend UI
└── README.md             # This file
```

## Prerequisites

- Python 3.10+
- OpenAI API key (for GPT-4o) OR Anthropic API key (for Claude)

## Installation

1. **Clone/Navigate to the project**:
   ```bash
   cd fantastic-claw
   ```

2. **Create a virtual environment** (recommended):
   ```bash
   python -m venv venv
   # On Windows:
   venv\Scripts\activate
   # On macOS/Linux:
   source venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables**:

Create a local `.env` file in the project root (do not commit it). Example contents:

```
OPENAI_API_KEY=sk-...
X_CONSUMER_KEY=...
X_CONSUMER_SECRET=...
X_ACCESS_TOKEN=...
X_ACCESS_TOKEN_SECRET=...
X_BEARER_TOKEN=...
BOT_X_HANDLE=FantasticClaw
```

Then restart the service so the variables are picked up.

## Usage

### Web Service + Frontend (Recommended)

The project now runs as a FastAPI web service that serves a polished frontend at `/ui`, provides API endpoints for triggering analysis, and can post results to X.

Run locally:

```bash
pip install -r requirements.txt
uvicorn agent:app --host 0.0.0.0 --port 8000 --reload
```

Open the frontend: http://localhost:8000/ui

Available API endpoints:

- `GET /` — serves the frontend UI (index.html)
- `GET /health` — health check JSON response
- `GET /health/config-status` — shows whether `OPENAI_API_KEY` and X credentials are configured
- `POST /trigger-claw?url=<url>` — run analysis on a product URL (returns `{ result: ... }`)
- `POST /post-to-x` — post text to X (JSON body: `{ "text": "...", "in_reply_to": null, "reply_to_username": null }`)

Example manual trigger:

```bash
curl -X POST "http://localhost:8000/trigger-claw?url=https://example.com/product"
```

Example post to X (requires X credentials in `.env`):

```bash
curl -X POST http://localhost:8000/post-to-x \
    -H "Content-Type: application/json" \
    -d '{"text":"Test post from Fantastic Claw"}'
```

### Option: Demo Script (No API key required)

The demo script uses mock product data and doesn't require real web scraping:

```bash
python demo.py
```

This demonstrates:
- An underpriced laptop (50% below market value) → **ALERT**
- Fairly priced headphones → Good deal
- Overpriced used phone → Overpriced

## How It Works

### Architecture

```
User Input (URL)
    ↓
LangChain Agent
    ↓
Scrape Tool (scrape_listing) → Uses BeautifulSoup
    ↓
LLM (GPT-4o/Claude) Analyzes Results
    ↓
Price Comparison Logic
    ↓
Alert if Underpriced (20%+ below market value)
```

### Custom Tool: `scrape_listing`

The `scrape_listing` tool:
- Takes a URL as input
- Uses BeautifulSoup to parse HTML
- Extracts: product title, price, description
- Returns formatted product information

```python
@tool
def scrape_listing(url: str) -> str:
    """Scrape product information from a URL"""
    # Implementation using requests + BeautifulSoup
```

### Pricing Logic

- **Underpriced**: Listed price is 20%+ below market value → **ALERT**
- **Good Deal**: Listed price is 10-20% below market value
- **Fairly Priced**: Listed price is within 10% of market value
- **Overpriced**: Listed price is above market value

## Switching LLMs

### Using Claude (Anthropic)

In `agent.py`, replace the LLM initialization:

```python
# Replace this:
from langchain_openai import ChatOpenAI
llm = ChatOpenAI(model="gpt-4o", api_key=os.getenv("OPENAI_API_KEY"))

# With this:
from langchain_anthropic import ChatAnthropic
llm = ChatAnthropic(model="claude-3-5-sonnet-20241022")
```

Also uncomment the `ANTHROPIC_API_KEY` in your `.env` file.

## Customization

### Adding Market Values

Edit the `MARKET_VALUES` dictionary in `agent.py`:

```python
MARKET_VALUES = {
    "laptop": 1000,
    "headphones": 150,
    "phone": 700,
    "monitor": 300,
    # Add more categories as needed
}
```

### Customizing Web Scraping

The `scrape_listing` function uses generic CSS patterns. Customize for specific websites:

```python
# For Amazon
amazon_title = soup.find("h1", {"class": "product-title"})

# For eBay
ebay_price = soup.find("span", {"class": "notranslate BOLD"})
```

### Adjusting Price Thresholds

Change the alert threshold in the system prompt:

```python
system_prompt = """...
- If listed price is 15%+ below market value: Item is UNDERPRICED
...
"""
```

## Troubleshooting

### ImportError for BeautifulSoup or requests
```bash
pip install beautifulsoup4 requests
```

### API Key not found
Make sure `.env` file exists and contains valid API keys:
```bash
cat .env
```

Check configuration status:
```bash
curl http://localhost:8000/config-status
```

If `openai_api_key_set` is `false`, add your key to `.env` and restart the server.

### Website doesn't scrape correctly
Some websites block scraping or have dynamic content. The scraper will:
1. Try normal HTTPS with full SSL verification
2. If SSL fails (e.g., custom CA chains), retry with verification disabled and note it in the result
3. If both fail, return an error message

For JavaScript-heavy sites, consider using Playwright instead of BeautifulSoup.

### Rate limiting
If the agent makes too many requests or hits rate limits, add delays between requests or use exponential backoff in the retry logic.

## Example Output

```
====================================================================
LangChain Price Analysis Agent - DEMO
====================================================================

TEST: Underpriced Laptop
Description: High-end laptop at 50% discount

🚨 UNDERPRICED ITEM DETECTED! 🚨

Analysis of Dell XPS 13 Laptop:
- Listed Price: $450
- Market Value: ~$900
- Savings: 50% below market
- Category: Laptop

RECOMMENDATION: BUY IMMEDIATELY
This is an exceptional deal on a premium laptop!
```

## Next Steps

1. ✅ Run the demo to see it in action
2. 🔑 Add your API key to `.env`
3. 🌐 Test with real product URLs
4. 🛠️ Customize scraping patterns for your target sites
5. 📊 Extend with more sophisticated pricing models

## Dependencies

- **langchain**: AI agent framework
- **langgraph**: Graph-based agent workflows
- **openai**: GPT-4o LLM
- **beautifulsoup4**: Web scraping
- **requests**: HTTP requests
- **python-dotenv**: Environment variable management

## License

MIT

## Notes

- Always respect website `robots.txt` and terms of service when scraping
- Consider using Playwright for JavaScript-heavy websites
- Add rate limiting to avoid being blocked by servers
- The demo uses mock data for testing without real scraping
