"""Test Vertex AI API key and discover available models."""

import httpx
import json
import os
from dotenv import load_dotenv

load_dotenv()
os.environ['SSL_CERT_FILE'] = ''

KEY = os.getenv("VERTEX_API_KEY") or os.getenv("GOOGLE_API_KEY")
if not KEY:
    raise RuntimeError("VERTEX_API_KEY or GOOGLE_API_KEY not set. Add one to your .env file.")

PROJECT = os.getenv("VERTEX_PROJECT", "pbeat04059418-qa-0173-ai-hub-r")
HEADERS = {"x-goog-api-key": KEY, "Content-Type": "application/json"}

BODY = {"contents": [{"role": "user", "parts": [{"text": "Say hello in one word"}]}]}

# Regions where Vertex AI Gemini is commonly available
REGIONS = ["us-central1", "europe-west4", "europe-west1", "us-east4", "asia-northeast1"]

# Model IDs to probe (including medical/health and latest Gemini)
MODEL_IDS = [
    "gemini-2.0-flash",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
    "gemini-pro",
    "medlm-large",       # Google's Medical LLM
    "medlm-medium",      # Google's Medical LLM (medium)
    "med-palm-2",        # MedPaLM 2
    "medpalm2",          # alt name
]

print("=" * 80)
print("Vertex AI Model Discovery")
print("=" * 80)

# 1) Test model list endpoint per region
for region in REGIONS:
    # Try list models
    list_url = f"https://{region}-aiplatform.googleapis.com/v1/projects/{PROJECT}/locations/{region}/models"
    try:
        resp = httpx.get(list_url, headers=HEADERS, verify=False, timeout=10)
        print(f"\n[LIST] {region:20s} -> {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            models = data.get("models", [])
            print(f"  Found {len(models)} custom/deployed models")
            for m in models[:10]:
                print(f"    - {m.get('displayName', m.get('name', '?'))}")
        elif resp.status_code == 403:
            msg = resp.json().get("error", {}).get("message", "")[:120]
            print(f"  DENIED: {msg}")
    except Exception as e:
        print(f"  ERROR: {e}")

# 2) Probe specific models per region
print("\n" + "=" * 80)
print("Model Availability Probes")
print("=" * 80)

for region in REGIONS[:2]:  # Just test top 2 regions
    print(f"\n--- Region: {region} ---")
    for model_id in MODEL_IDS:
        url = f"https://{region}-aiplatform.googleapis.com/v1/projects/{PROJECT}/locations/{region}/publishers/google/models/{model_id}:generateContent"
        try:
            resp = httpx.post(url, headers=HEADERS, json=BODY, verify=False, timeout=15)
            status = resp.status_code
            if status == 200:
                text = resp.json().get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "?")
                print(f"  ✅ {model_id:25s} -> {status}  Response: {text[:50]}")
            elif status == 403:
                msg = resp.json().get("error", {}).get("message", "")
                if "not exist" in msg.lower():
                    print(f"  ❌ {model_id:25s} -> {status}  (not available)")
                else:
                    print(f"  🔒 {model_id:25s} -> {status}  (permission denied)")
            elif status == 404:
                print(f"  ❌ {model_id:25s} -> {status}  (model not found)")
            else:
                print(f"  ⚠️  {model_id:25s} -> {status}")
        except Exception as e:
            print(f"  ❌ {model_id:25s} -> ERROR: {e}")

# 3) Try v1beta1 model list
print("\n" + "=" * 80)
print("Publisher Model Catalog (v1beta1)")
print("=" * 80)

for region in REGIONS[:2]:
    url = f"https://{region}-aiplatform.googleapis.com/v1beta1/publishers/google/models"
    try:
        resp = httpx.get(url, headers=HEADERS, verify=False, timeout=15)
        print(f"\n[CATALOG] {region:20s} -> {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            for m in data.get("publisherModels", [])[:20]:
                name = m.get("name", "?")
                print(f"    {name}")
    except Exception as e:
        print(f"  ERROR: {e}")
