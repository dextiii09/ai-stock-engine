import urllib.request
import json

def check_url(url):
    print(f"Testing URL: {url}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "AiStock/1.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            print(f"Success! Retrieved {len(data)} records.")
            if data:
                print("First record keys:", list(data[0].keys()))
                print("Market code in record:", data[0].get("cftc_contract_market_code"))
            return True
    except Exception as e:
        print(f"FAILED: {e}")
        if hasattr(e, "read"):
            try:
                print("Error response:", e.read().decode())
            except:
                pass
        return False

# Test the URLs from cot_client.py
# 1. Gold (Disaggregated) code "088691"
gold_endpoint = "https://publicreporting.cftc.gov/resource/kh3c-gbw2.json"
gold_url = f"{gold_endpoint}?cftc_contract_market_code=088691&$order=report_date_as_yyyy_mm_dd%20DESC&$limit=1"

# 2. NQ (TFF) code "209742"
nq_endpoint = "https://publicreporting.cftc.gov/resource/yw9f-hn96.json"
nq_url = f"{nq_endpoint}?cftc_contract_market_code=209742&$order=report_date_as_yyyy_mm_dd%20DESC&$limit=1"

print("--- Test 1: Gold ---")
check_url(gold_url)

print("\n--- Test 2: NQ ---")
check_url(nq_url)
