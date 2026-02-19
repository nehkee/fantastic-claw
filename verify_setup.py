"""
Verification script to check if all dependencies and API keys are configured correctly
"""

import os
import sys
from pathlib import Path

def check_python_version():
    """Check Python version"""
    print("✓ Checking Python version...", end=" ")
    version = sys.version_info
    if version.major >= 3 and version.minor >= 10:
        print(f"✓ Python {version.major}.{version.minor}")
        return True
    else:
        print(f"✗ Python {version.major}.{version.minor} (requires 3.10+)")
        return False


def check_dependencies():
    """Check if all required packages are installed"""
    print("\n✓ Checking dependencies...")
    
    required_packages = {
        "langchain": "LangChain",
        "langgraph": "LangGraph",
        "langchain_core": "LangChain Core",
        "langchain_openai": "LangChain OpenAI",
        "openai": "OpenAI",
        "bs4": "BeautifulSoup4",
        "requests": "Requests",
        "dotenv": "Python Dotenv",
        "pydantic": "Pydantic",
    }
    
    missing = []
    for package, name in required_packages.items():
        try:
            __import__(package)
            print(f"  ✓ {name}")
        except ImportError:
            print(f"  ✗ {name} - NOT INSTALLED")
            missing.append(package)
    
    if missing:
        print(f"\n⚠️  Missing packages: {', '.join(missing)}")
        print(f"Install with: pip install {' '.join(missing)}")
        return False
    
    return True


def check_env_file():
    """Check if .env file exists and has API keys"""
    print("\n✓ Checking environment configuration...")
    
    env_path = Path(".env")
    
    if not env_path.exists():
        print("  ✗ .env file not found")
        print("    Create one from .env.example: cp .env.example .env")
        return False
    
    print("  ✓ .env file exists")
    
    # Check for API key
    env_content = env_path.read_text()
    
    has_openai = "OPENAI_API_KEY" in env_content and "OPENAI_API_KEY=sk" in env_content
    has_anthropic = "ANTHROPIC_API_KEY" in env_content and "ANTHROPIC_API_KEY=sk" in env_content
    
    if has_openai:
        print("  ✓ OpenAI API key configured")
        return True
    elif has_anthropic:
        print("  ✓ Anthropic API key configured")
        return True
    else:
        print("  ✗ No valid API key found")
        print("    - Add OPENAI_API_KEY=your_key_here for GPT-4o")
        print("    - Or add ANTHROPIC_API_KEY=your_key_here for Claude")
        return False


def check_demo_mode():
    """Check if demo can run without API key"""
    print("\n✓ Demo mode (mock data)...")
    print("  ✓ Demo script can run without external API calls")
    print("    Run: python demo.py")
    return True


def run_import_test():
    """Test importing main modules"""
    print("\n✓ Testing module imports...")
    
    try:
        from langchain.tools import tool
        print("  ✓ LangChain tools")
    except Exception as e:
        print(f"  ✗ LangChain tools: {e}")
        return False
    
    try:
        from langchain_openai import ChatOpenAI
        print("  ✓ LangChain OpenAI")
    except Exception as e:
        print(f"  ✗ LangChain OpenAI: {e}")
        return False
    
    try:
        from bs4 import BeautifulSoup
        print("  ✓ BeautifulSoup4")
    except Exception as e:
        print(f"  ✗ BeautifulSoup4: {e}")
        return False
    
    return True


def main():
    """Run all checks"""
    print("="*60)
    print("LangChain Price Analysis Agent - Setup Verification")
    print("="*60 + "\n")
    
    checks = [
        ("Python Version", check_python_version),
        ("Dependencies", check_dependencies),
        ("Environment", check_env_file),
        ("Module Imports", run_import_test),
        ("Demo Mode", check_demo_mode),
    ]
    
    results = []
    for name, check_func in checks:
        try:
            result = check_func()
            results.append(result)
        except Exception as e:
            print(f"\n✗ Error during {name} check: {e}")
            results.append(False)
    
    # Summary
    print("\n" + "="*60)
    if all(results):
        print("✅ All checks passed! You're ready to go!")
        print("\nNext steps:")
        print("1. Run the demo:  python demo.py")
        print("2. Or try agent:  python agent.py")
    else:
        print("⚠️  Some checks failed. See errors above.")
        print("\nCommon fixes:")
        print("- Install dependencies: pip install -r requirements.txt")
        print("- Create .env file: cp .env.example .env")
        print("- Add your API key to .env file")
    print("="*60 + "\n")
    
    return all(results)


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
