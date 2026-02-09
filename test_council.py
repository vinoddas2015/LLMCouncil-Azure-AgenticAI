"""Quick test for full council flow"""
import asyncio
from dotenv import load_dotenv
load_dotenv()

from backend.council import run_full_council

async def test():
    print('Running full council test...')
    try:
        s1, s2, s3, meta = await run_full_council('What is 2+2?')
        print(f'Stage 1: {len(s1)} responses')
        print(f'Stage 2: {len(s2)} rankings')
        print(f'Stage 3 model: {s3.get("model", "N/A")}')
        response = s3.get("response", "")
        print(f'Stage 3 response preview: {response[:300]}...')
        if "Error" in response:
            print("!!! ERROR DETECTED IN STAGE 3 !!!")
    except Exception as e:
        print(f'ERROR: {e}')
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test())
