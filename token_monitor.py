"""
Token Monitor for Bayer myGenAssist API

Runs in the background and alerts you before token expiration.
Also provides easy token refresh functionality.

Usage:
  python token_monitor.py          # Run monitor (alerts at 10, 5, 2 min before expiry)
  python token_monitor.py --check  # Quick check without monitoring
  python token_monitor.py --refresh <token>  # Update token in .env
"""

import os
import sys
import base64
import json
import time
import winsound
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Alert thresholds (minutes before expiration)
ALERT_THRESHOLDS = [30, 15, 10, 5, 2, 1]

def decode_jwt(jwt_token):
    """Decode JWT and return expiration info."""
    try:
        payload = jwt_token.split('.')[1]
        payload += '=' * (4 - len(payload) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(payload))
        return {
            'exp': datetime.fromtimestamp(decoded.get('exp', 0)),
            'iat': datetime.fromtimestamp(decoded.get('iat', 0)),
            'email': decoded.get('email', 'N/A'),
            'cwid': decoded.get('https://bayer.com/cwid', 'N/A'),
        }
    except Exception as e:
        return None


def get_remaining_minutes(exp_date):
    """Get minutes remaining until expiration."""
    return (exp_date - datetime.now()).total_seconds() / 60


def show_status(token_info, remaining_mins):
    """Display current token status."""
    os.system('cls' if os.name == 'nt' else 'clear')
    
    print("="*65)
    print("🔐 BAYER myGenAssist TOKEN MONITOR")
    print("="*65)
    print()
    print(f"  User:       {token_info['email']}")
    print(f"  CWID:       {token_info['cwid']}")
    print(f"  Issued:     {token_info['iat'].strftime('%d-%b-%Y %H:%M:%S')}")
    print(f"  Expires:    {token_info['exp'].strftime('%d-%b-%Y %H:%M:%S')}")
    print(f"  Current:    {datetime.now().strftime('%d-%b-%Y %H:%M:%S')}")
    print()
    
    if remaining_mins <= 0:
        print("  ⛔ STATUS:   EXPIRED")
        print()
        print("  Token has expired! Please refresh immediately.")
    elif remaining_mins <= 5:
        print(f"  🔴 STATUS:   CRITICAL - {remaining_mins:.0f} minutes remaining!")
    elif remaining_mins <= 15:
        print(f"  🟠 STATUS:   WARNING - {remaining_mins:.0f} minutes remaining")
    elif remaining_mins <= 30:
        print(f"  🟡 STATUS:   ATTENTION - {remaining_mins:.0f} minutes remaining")
    else:
        print(f"  🟢 STATUS:   OK - {remaining_mins:.0f} minutes remaining")
    
    print()
    print("-"*65)
    print("  Press Ctrl+C to stop monitoring")
    print("  To refresh: python token_monitor.py --refresh <new_token>")
    print("-"*65)


def alert_user(message, remaining_mins):
    """Alert user with sound and message."""
    print(f"\n⚠️  ALERT: {message}")
    
    # Windows beep alert
    try:
        if remaining_mins <= 2:
            # Urgent: 3 beeps
            for _ in range(3):
                winsound.Beep(1000, 500)
                time.sleep(0.2)
        elif remaining_mins <= 5:
            # Warning: 2 beeps
            for _ in range(2):
                winsound.Beep(800, 300)
                time.sleep(0.2)
        else:
            # Notice: 1 beep
            winsound.Beep(600, 200)
    except:
        pass  # No sound on non-Windows or if winsound fails


def refresh_token(new_token):
    """Update token in .env file."""
    env_file = ".env"
    
    if not new_token.startswith("eyJ"):
        print("❌ Invalid token format. Token should start with 'eyJ...'")
        return False
    
    # Verify new token is valid
    token_info = decode_jwt(new_token)
    if not token_info:
        print("❌ Could not decode token. Please check the token format.")
        return False
    
    remaining = get_remaining_minutes(token_info['exp'])
    if remaining <= 0:
        print("❌ This token is already expired!")
        return False
    
    # Read and update .env
    with open(env_file, 'r') as f:
        lines = f.readlines()
    
    with open(env_file, 'w') as f:
        for line in lines:
            if line.startswith('OPENROUTER_API_KEY='):
                f.write(f'OPENROUTER_API_KEY={new_token}\n')
            else:
                f.write(line)
    
    print("✅ Token updated successfully!")
    print(f"   New expiration: {token_info['exp'].strftime('%d-%b-%Y %H:%M:%S')}")
    print(f"   Valid for: {remaining:.0f} minutes")
    return True


def quick_check():
    """Quick token status check."""
    load_dotenv()
    jwt = os.getenv('OPENROUTER_API_KEY')
    
    if not jwt:
        print("❌ No token found in .env")
        return
    
    token_info = decode_jwt(jwt)
    if not token_info:
        print("❌ Invalid token format")
        return
    
    remaining = get_remaining_minutes(token_info['exp'])
    
    print()
    print(f"Token Expires: {token_info['exp'].strftime('%d-%b-%Y %H:%M:%S')}")
    print(f"Current Time:  {datetime.now().strftime('%d-%b-%Y %H:%M:%S')}")
    
    if remaining <= 0:
        print(f"Status: ⛔ EXPIRED ({abs(remaining):.0f} minutes ago)")
    elif remaining <= 5:
        print(f"Status: 🔴 CRITICAL ({remaining:.0f} minutes remaining)")
    elif remaining <= 15:
        print(f"Status: 🟠 WARNING ({remaining:.0f} minutes remaining)")
    else:
        print(f"Status: 🟢 OK ({remaining:.0f} minutes remaining)")


def run_monitor():
    """Run continuous token monitor."""
    load_dotenv()
    jwt = os.getenv('OPENROUTER_API_KEY')
    
    if not jwt:
        print("❌ No token found in .env")
        return
    
    token_info = decode_jwt(jwt)
    if not token_info:
        print("❌ Invalid token format")
        return
    
    alerted_thresholds = set()
    
    print("Starting token monitor... (Press Ctrl+C to stop)")
    
    try:
        while True:
            # Reload token in case it was updated
            load_dotenv(override=True)
            jwt = os.getenv('OPENROUTER_API_KEY')
            token_info = decode_jwt(jwt)
            
            if not token_info:
                print("❌ Token became invalid!")
                break
            
            remaining = get_remaining_minutes(token_info['exp'])
            
            # Check alert thresholds
            for threshold in ALERT_THRESHOLDS:
                if remaining <= threshold and threshold not in alerted_thresholds:
                    alerted_thresholds.add(threshold)
                    alert_user(f"Token expires in {threshold} minute(s)!", remaining)
            
            # Show status
            show_status(token_info, remaining)
            
            if remaining <= 0:
                alert_user("TOKEN HAS EXPIRED!", 0)
                print("\n" + "="*65)
                print("HOW TO REFRESH:")
                print("="*65)
                print("1. Go to https://chat.int.bayer.com")
                print("2. Open DevTools (F12) → Network tab")
                print("3. Make a chat request")
                print("4. Copy Authorization Bearer token")
                print("5. Run: python token_monitor.py --refresh <token>")
                print("="*65)
                break
            
            # Sleep for appropriate interval
            if remaining <= 2:
                time.sleep(10)  # Check every 10 seconds when critical
            elif remaining <= 10:
                time.sleep(30)  # Check every 30 seconds
            else:
                time.sleep(60)  # Check every minute
                
    except KeyboardInterrupt:
        print("\n\nMonitor stopped.")


def show_help():
    """Show usage instructions."""
    print("""
╔══════════════════════════════════════════════════════════════╗
║              TOKEN MONITOR - USAGE                            ║
╠══════════════════════════════════════════════════════════════╣
║                                                               ║
║  python token_monitor.py                                      ║
║      Run continuous monitor with alerts                       ║
║                                                               ║
║  python token_monitor.py --check                              ║
║      Quick status check (no monitoring)                       ║
║                                                               ║
║  python token_monitor.py --refresh <token>                    ║
║      Update .env with new token                               ║
║                                                               ║
║  python token_monitor.py --help                               ║
║      Show this help message                                   ║
║                                                               ║
╚══════════════════════════════════════════════════════════════╝

HOW TO GET A NEW TOKEN:
-----------------------
1. Open https://chat.int.bayer.com in your browser
2. Log in with your Bayer credentials
3. Open Developer Tools (F12) → Network tab
4. Make any chat request
5. Click on the request, find Authorization header
6. Copy the token (starts with 'eyJ...')
7. Run: python token_monitor.py --refresh "eyJ..."
""")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        run_monitor()
    elif sys.argv[1] == "--check":
        quick_check()
    elif sys.argv[1] == "--refresh" and len(sys.argv) >= 3:
        refresh_token(sys.argv[2])
    elif sys.argv[1] == "--help":
        show_help()
    else:
        show_help()
