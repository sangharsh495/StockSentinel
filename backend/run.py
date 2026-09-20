#!/usr/bin/env python3
"""
StockSentinel Backend Server Launcher
Starts Uvicorn directly with asyncio loop and no file-watcher locks.
"""

import sys
import os
from pathlib import Path

# Add backend directory to path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import uvicorn

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    print(f"🚀 Launching StockSentinel API Server on http://127.0.0.1:{port} (docs at http://127.0.0.1:{port}/docs) ...")
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=False,
        loop="asyncio",
        log_level="info",
    )
