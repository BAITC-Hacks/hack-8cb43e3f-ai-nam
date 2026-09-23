"""Run the local app. Network deployment is explicitly configured in .env."""
import argparse
import os
from pathlib import Path
from dotenv import load_dotenv
import uvicorn

if __name__ == "__main__":
    load_dotenv(Path(__file__).parent / ".env")
    parser = argparse.ArgumentParser(description="AI-NAM server")
    parser.add_argument("--host", default=os.getenv("AI_NAM_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("AI_NAM_PORT", "8765")))
    args = parser.parse_args()
    uvicorn.run("app.main:app", host=args.host, port=args.port, proxy_headers=False, log_level="info")
