"""
List all available models from the Bayer myGenAssist API.
Tries multiple endpoint patterns (v2 and v3).
"""

import os
import json
import httpx
import urllib3
from dotenv import load_dotenv

load_dotenv()
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

API_KEY = os.getenv("OPENROUTER_API_KEY")
BASE = "https://chat.int.bayer.com"

# Endpoints to try — covering v2 and v3 patterns
ENDPOINTS = [
    "/api/v2/models",
    "/api/v3/models",
    "/api/v2/chat/models",
    "/api/v3/chat/models",
    "/api/models",
    "/v2/models",
    "/v3/models",
]

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Accept": "application/json",
}


def try_endpoint(client, url):
    try:
        resp = client.get(url, headers=headers)
        print(f"  {url}  →  HTTP {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            return data
        elif resp.status_code != 404:
            print(f"    Body (first 500 chars): {resp.text[:500]}")
    except Exception as e:
        print(f"  {url}  →  ERROR: {e}")
    return None


def main():
    if not API_KEY:
        print("❌ No API key. Set OPENROUTER_API_KEY in .env")
        return

    print(f"API Key: {API_KEY[:25]}...")
    print(f"\n{'='*70}")
    print("Probing myGenAssist for model endpoints...")
    print(f"{'='*70}\n")

    with httpx.Client(timeout=30, verify=False) as client:
        for ep in ENDPOINTS:
            result = try_endpoint(client, f"{BASE}{ep}")
            if result:
                print(f"\n✅ Found models at {ep}\n")
                models = result.get("data", result.get("models", []))
                print(f"Total models: {len(models)}\n")
                print(f"{'ID':<30} {'Name':<35} {'Type':<18} {'Status':<12} {'In $/M':<10} {'Out $/M':<10} {'Tools':<6} {'Reasoning'}")
                print("-" * 145)
                for m in models:
                    mid = m.get("id", "?")
                    name = m.get("name", "?")
                    mtype = m.get("model_type", "?")
                    status = m.get("model_status", "?")
                    inc = m.get("input_cost_per_million_token", "?")
                    outc = m.get("output_cost_per_million_token", "?")
                    tools = "✓" if m.get("supports_tools") else ""
                    reason = "✓" if m.get("supports_reasoning") else ""
                    print(f"{mid:<30} {name:<35} {mtype:<18} {status:<12} {str(inc):<10} {str(outc):<10} {tools:<6} {reason}")
                return

    # If none worked, try the OpenAI-compatible approach
    print("\n--- Trying OpenAI-compatible /v1/models pattern ---")
    with httpx.Client(timeout=30, verify=False) as client:
        for prefix in ["/api/v1", "/v1", "/api"]:
            result = try_endpoint(client, f"{BASE}{prefix}/models")
            if result:
                print(f"\n✅ Found models at {prefix}/models:\n")
                print(json.dumps(result, indent=2)[:5000])
                return

    print("\n❌ No model-listing endpoint found.")
    print("   You may need to check the Scalar docs while authenticated.")


if __name__ == "__main__":
    main()
