"""
Bayer myGenAssist API Token Manager

This script helps manage API tokens for the LLM Council application.
The Bayer API supports creating persistent API tokens that don't expire like JWT tokens.

Usage:
1. First, get a fresh JWT token by logging into https://chat.int.bayer.com
2. Run this script to create/retrieve your persistent API token
3. Update .env with the persistent token

API Endpoint: https://chat.int.bayer.com/api/v2/tokens/{user_id}
"""

import os
import httpx
import asyncio
from dotenv import load_dotenv

load_dotenv()

# User Configuration
USER_ID = 211  # Your Bayer user ID
CWID = "EOVBK"  # Your CWID

# API Configuration
BAYER_API_BASE = "https://chat.int.bayer.com/api/v2"
TOKEN_ENDPOINT = f"{BAYER_API_BASE}/tokens/{USER_ID}"

# Get current JWT from .env (used to authenticate token creation)
CURRENT_JWT = os.getenv("OPENROUTER_API_KEY")


async def list_tokens():
    """List all existing API tokens for your user."""
    headers = {
        "Authorization": f"Bearer {CURRENT_JWT}",
        "accept": "application/json",
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(TOKEN_ENDPOINT, headers=headers)
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text}")
        return response.json() if response.status_code == 200 else None


async def create_token(token_name: str):
    """
    Create a new persistent API token.
    
    Args:
        token_name: Name for the token (e.g., 'llm-council-api')
    """
    headers = {
        "Authorization": f"Bearer {CURRENT_JWT}",
        "accept": "application/json",
        "Content-Type": "application/json",
    }
    
    url = f"{TOKEN_ENDPOINT}?token_name={token_name}"
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.put(url, headers=headers)
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text}")
        
        if response.status_code == 200:
            data = response.json()
            print("\n" + "="*60)
            print("SUCCESS! Save this API token to your .env file:")
            print("="*60)
            if 'token' in data:
                print(f"\nOPENROUTER_API_KEY={data['token']}")
            else:
                print(f"\nFull response: {data}")
            print("\n" + "="*60)
            return data
        return None


async def delete_token(token_name: str):
    """Delete an existing API token."""
    headers = {
        "Authorization": f"Bearer {CURRENT_JWT}",
        "accept": "application/json",
    }
    
    url = f"{TOKEN_ENDPOINT}?token_name={token_name}"
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.delete(url, headers=headers)
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text}")
        return response.status_code == 200


async def test_api_connection():
    """Test if the current API key works."""
    headers = {
        "Authorization": f"Bearer {CURRENT_JWT}",
        "Content-Type": "application/json",
    }
    
    payload = {
        "model": "gpt-5-mini",
        "messages": [{"role": "user", "content": "Hello, respond with just 'API OK'"}],
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(
                f"{BAYER_API_BASE}/chat/completions",
                headers=headers,
                json=payload
            )
            print(f"Status: {response.status_code}")
            if response.status_code == 200:
                print("✅ API connection successful!")
                data = response.json()
                content = data.get('choices', [{}])[0].get('message', {}).get('content', '')
                print(f"Response: {content}")
            else:
                print(f"❌ API error: {response.text}")
        except Exception as e:
            print(f"❌ Connection error: {e}")


async def main():
    print("="*60)
    print("Bayer myGenAssist API Token Manager")
    print(f"User ID: {USER_ID} | CWID: {CWID}")
    print("="*60)
    
    print("\nOptions:")
    print("1. Test current API connection")
    print("2. List existing tokens")
    print("3. Create new persistent token (llm-council-api)")
    print("4. Delete a token")
    
    choice = input("\nEnter choice (1-4): ").strip()
    
    if choice == "1":
        print("\nTesting API connection...")
        await test_api_connection()
    elif choice == "2":
        print("\nListing tokens...")
        await list_tokens()
    elif choice == "3":
        print("\nCreating persistent token 'llm-council-api'...")
        await create_token("llm-council-api")
    elif choice == "4":
        token_name = input("Enter token name to delete: ").strip()
        await delete_token(token_name)
    else:
        print("Invalid choice")


if __name__ == "__main__":
    asyncio.run(main())
