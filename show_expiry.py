"""Show token expiration for all configured models."""
import os
import base64
import json
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Get the JWT token
jwt = os.getenv('OPENROUTER_API_KEY')

# Decode JWT payload
payload = jwt.split('.')[1]
payload += '=' * (4 - len(payload) % 4)
decoded = json.loads(base64.urlsafe_b64decode(payload))

# Extract timestamps
exp = decoded.get('exp', 0)
iat = decoded.get('iat', 0)
exp_date = datetime.fromtimestamp(exp)
iat_date = datetime.fromtimestamp(iat)
now = datetime.now()

# Configured models from config.py
models = [
    "deepmind/biollama-3-70b",
    "gemini-2.5-pro", 
    "claude-opus-4.5",
    "grok-3",
]
chairman = "claude-opus-4.5"

print("="*65)
print("JWT TOKEN EXPIRATION FOR CONFIGURED MODELS")
print("="*65)
print()
print(f"{'Model':<30} {'Token Expiration':<25}")
print("-"*65)

for model in models:
    print(f"{model:<30} {exp_date.strftime('%d-%b-%Y %H:%M:%S'):<25}")

print("-"*65)
print(f"{'Chairman: ' + chairman:<30} {exp_date.strftime('%d-%b-%Y %H:%M:%S'):<25}")
print("="*65)
print()
print(f"Token Issued:    {iat_date.strftime('%d-%b-%Y %H:%M:%S')}")
print(f"Token Expires:   {exp_date.strftime('%d-%b-%Y %H:%M:%S')}")
print(f"Current Time:    {now.strftime('%d-%b-%Y %H:%M:%S')}")
print()

remaining = (exp_date - now).total_seconds()
if remaining < 0:
    print(f"⚠️  STATUS: EXPIRED ({abs(remaining)/60:.0f} minutes ago)")
else:
    mins = remaining / 60
    print(f"✅ STATUS: VALID ({mins:.0f} minutes remaining)")
