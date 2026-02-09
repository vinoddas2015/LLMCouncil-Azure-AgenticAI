"""
JWT Token Refresh Helper for Bayer myGenAssist

Since you don't have privileges to create persistent tokens,
use this script to quickly update your JWT token.

Usage:
1. Log into https://chat.int.bayer.com
2. Open browser DevTools (F12) > Network tab
3. Make any request and find the Authorization header
4. Copy the Bearer token (starts with 'eyJ...')
5. Run: python refresh_token.py "eyJ..."
"""

import sys
import os

ENV_FILE = ".env"

def update_token(new_token: str):
    """Update the JWT token in .env file."""
    
    if not new_token.startswith("eyJ"):
        print("❌ Invalid token format. Token should start with 'eyJ...'")
        return False
    
    # Read current .env
    with open(ENV_FILE, 'r') as f:
        content = f.read()
    
    # Find and replace the token line
    lines = content.split('\n')
    new_lines = []
    token_updated = False
    
    for line in lines:
        if line.startswith('OPENROUTER_API_KEY='):
            new_lines.append(f'OPENROUTER_API_KEY={new_token}')
            token_updated = True
        else:
            new_lines.append(line)
    
    if not token_updated:
        new_lines.append(f'OPENROUTER_API_KEY={new_token}')
    
    # Write back
    with open(ENV_FILE, 'w') as f:
        f.write('\n'.join(new_lines))
    
    print("✅ Token updated successfully in .env file!")
    print(f"Token preview: {new_token[:50]}...")
    
    # Test the new token
    print("\nTesting new token...")
    os.system(f'"{sys.executable}" test_api.py test')
    
    return True


def show_instructions():
    """Show instructions for getting a new JWT token."""
    print("""
╔══════════════════════════════════════════════════════════════╗
║         JWT TOKEN REFRESH INSTRUCTIONS                        ║
╠══════════════════════════════════════════════════════════════╣
║                                                               ║
║  1. Open https://chat.int.bayer.com in your browser          ║
║                                                               ║
║  2. Log in with your Bayer credentials                       ║
║                                                               ║
║  3. Open Developer Tools:                                     ║
║     • Press F12 or Ctrl+Shift+I                              ║
║     • Go to "Network" tab                                     ║
║                                                               ║
║  4. Make any chat request in myGenAssist                     ║
║                                                               ║
║  5. In Network tab, click on the request to                  ║
║     'chat/completions' or similar                             ║
║                                                               ║
║  6. Look in "Headers" section for:                           ║
║     Authorization: Bearer eyJ...                              ║
║                                                               ║
║  7. Copy the token (everything after 'Bearer ')              ║
║                                                               ║
║  8. Run: python refresh_token.py "eyJ..."                    ║
║                                                               ║
╚══════════════════════════════════════════════════════════════╝
""")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        show_instructions()
        print("\nUsage: python refresh_token.py <new_jwt_token>")
        print("       python refresh_token.py --help")
    elif sys.argv[1] == "--help":
        show_instructions()
    else:
        update_token(sys.argv[1])
