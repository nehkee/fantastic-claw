import traceback
import agent

if __name__ == "__main__":
    url = "https://example.com/product-1"
    try:
        print("Calling trigger_agent() with:", url)
        result = agent.trigger_agent(url)
        print("Result:", result)
    except Exception:
        print("Exception raised when running trigger_agent():")
        traceback.print_exc()
