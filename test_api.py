"""
Quick API Test for Bayer myGenAssist
Handles corporate SSL/proxy requirements
"""

import os
import ssl
import httpx
from dotenv import load_dotenv

load_dotenv()

# Disable SSL verification for corporate environments (if needed)
# NOTE: This is for testing only - in production, use proper certificates

JWT = os.getenv('OPENROUTER_API_KEY')
BAYER_API_BASE = 'https://chat.int.bayer.com/api/v2'
USER_ID = int(os.getenv('BAYER_USER_ID', '0')) or None

def test_api():
    """Test if API connection works."""
    print("="*60)
    print("Testing Bayer myGenAssist API Connection")
    print("="*60)
    
    headers = {
        'Authorization': f'Bearer {JWT}',
        'Content-Type': 'application/json',
    }
    
    payload = {
        'model': 'gpt-5-mini',
        'messages': [{'role': 'user', 'content': 'Respond with just: API OK'}],
    }
    
    try:
        # Try with SSL verification disabled (for corporate environments)
        with httpx.Client(timeout=30.0, verify=False) as client:
            print("\nSending test request to API...")
            response = client.post(
                f'{BAYER_API_BASE}/chat/completions',
                headers=headers,
                json=payload
            )
            
            print(f"Status Code: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                content = data.get('choices', [{}])[0].get('message', {}).get('content', '')
                print(f"✅ API Connection Successful!")
                print(f"Response: {content}")
                return True
            elif response.status_code == 401:
                print("❌ Authentication Failed - JWT token may have expired")
                print(f"Response: {response.text[:500]}")
                return False
            else:
                print(f"❌ API Error")
                print(f"Response: {response.text[:500]}")
                return False
                
    except Exception as e:
        print(f"❌ Connection Error: {e}")
        return False


def list_tokens():
    """List existing API tokens."""
    print("\n" + "="*60)
    print("Listing Existing API Tokens")
    print("="*60)
    
    headers = {
        'Authorization': f'Bearer {JWT}',
        'accept': 'application/json',
    }
    
    try:
        with httpx.Client(timeout=30.0, verify=False) as client:
            response = client.get(f'{BAYER_API_BASE}/tokens/{USER_ID}', headers=headers)
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.text}")
            return response.json() if response.status_code == 200 else None
    except Exception as e:
        print(f"Error: {e}")
        return None


def create_persistent_token(token_name: str = "llm-council-api"):
    """Create a persistent API token."""
    print("\n" + "="*60)
    print(f"Creating Persistent Token: {token_name}")
    print("="*60)
    
    headers = {
        'Authorization': f'Bearer {JWT}',
        'accept': 'application/json',
    }
    
    url = f'{BAYER_API_BASE}/tokens/{USER_ID}?token_name={token_name}'
    
    try:
        with httpx.Client(timeout=30.0, verify=False) as client:
            response = client.put(url, headers=headers)
            print(f"Status Code: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print("\n" + "="*60)
                print("✅ SUCCESS! Persistent Token Created!")
                print("="*60)
                print(f"\nFull Response: {data}")
                
                # Look for the token in the response
                if 'token' in data:
                    print(f"\n📋 Copy this to your .env file:")
                    print(f"OPENROUTER_API_KEY={data['token']}")
                elif 'api_key' in data:
                    print(f"\n📋 Copy this to your .env file:")
                    print(f"OPENROUTER_API_KEY={data['api_key']}")
                    
                return data
            else:
                print(f"❌ Failed to create token")
                print(f"Response: {response.text}")
                return None
    except Exception as e:
        print(f"Error: {e}")
        return None


if __name__ == "__main__":
    import sys
    import urllib3
    
    # Suppress SSL warnings for corporate environments
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    print("\nBayer myGenAssist Token Manager")
    print(f"User ID: {USER_ID}")
    print("-"*40)
    
    # Check if JWT is present
    if not JWT or JWT == "your-bayer-api-key-here":
        print("❌ No API key found in .env file!")
        print("Please add your JWT token to the .env file first.")
        sys.exit(1)
    
    print(f"JWT Token: {JWT[:50]}...")
    
    # Run tests
    arg = sys.argv[1] if len(sys.argv) > 1 else "test"
    
    if arg == "test":
        test_api()
    elif arg == "list":
        list_tokens()
    elif arg == "create":
        create_persistent_token()
    elif arg == "all":
        if test_api():
            print("\n\nAPI working! Now listing tokens...")
            list_tokens()
            print("\n\nCreating persistent token...")
            create_persistent_token()
    else:
        print(f"Usage: python {sys.argv[0]} [test|list|create|all]")
