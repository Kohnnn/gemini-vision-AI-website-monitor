"""
Check if Playwright server is running correctly
"""
import requests
import sys
import time

def check_playwright_server(url="http://localhost:11435", max_retries=3):
    """
    Check if the Playwright server is running at the specified URL
    """
    print(f"Checking Playwright server at {url}...")
    
    for retry in range(max_retries):
        try:
            response = requests.get(f"{url}/status", timeout=5)
            if response.status_code == 200:
                data = response.json()
                print(f"✓ Playwright server is running!")
                print(f"Status: {data.get('status', 'unknown')}")
                return True
            else:
                print(f"✗ Playwright server returned status code {response.status_code}")
        except requests.exceptions.ConnectionError:
            print(f"✗ Playwright server not running (connection error)")
        except requests.exceptions.Timeout:
            print(f"✗ Playwright server not responding (timeout)")
        except Exception as e:
            print(f"✗ Error checking Playwright server: {str(e)}")
        
        if retry < max_retries - 1:
            print(f"Retrying in {retry + 1} seconds...")
            time.sleep(retry + 1)
    
    print("\nPlaywright server check failed after retries.")
    print("Troubleshooting tips:")
    print("1. Make sure the server is started with 'start_playwright_server.bat' or 'start_playwright_server.sh'")
    print("2. Check if port 11435 is blocked by a firewall")
    print("3. Run 'python -m playwright install chromium' to install Playwright dependencies")
    print("4. Check if Node.js is installed and accessible in your PATH")
    return False

def check_local_playwright():
    """
    Check if local Playwright Python package is installed correctly
    """
    print("\nChecking local Playwright Python installation...")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        print("✓ Local Playwright Python is working correctly")
        return True
    except ImportError:
        print("✗ Playwright Python package is not installed")
        print("  Run: pip install playwright")
        return False
    except Exception as e:
        print(f"✗ Error with local Playwright Python: {str(e)}")
        print("  Run: python -m playwright install")
        return False

if __name__ == "__main__":
    server_ok = check_playwright_server()
    local_ok = check_local_playwright()
    
    if server_ok or local_ok:
        print("\nAt least one Playwright method is available.")
        sys.exit(0)
    else:
        print("\nNeither Playwright server nor local Playwright is working correctly.")
        sys.exit(1) 