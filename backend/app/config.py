"""
Configuration module — loads all environment variables.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")

    # Finnhub
    FINNHUB_API_KEY: str = os.getenv("FINNHUB_API_KEY", "")

    # Google Gemini
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

    # Groq API
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")

    # Firebase (base64-encoded service account JSON)
    FIREBASE_CREDENTIALS: str = os.getenv("FIREBASE_CREDENTIALS", "")

    # Render external URL (for self-ping)
    RENDER_EXTERNAL_URL: str = os.getenv("RENDER_EXTERNAL_URL", "")

    # App settings
    APP_NAME: str = "StockSentinel API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

    # Market hours (IST)
    INDIA_MARKET_OPEN_HOUR: int = 9
    INDIA_MARKET_OPEN_MINUTE: int = 15
    INDIA_MARKET_CLOSE_HOUR: int = 15
    INDIA_MARKET_CLOSE_MINUTE: int = 30

    # Rate limiting
    NSE_REQUEST_DELAY: float = 2.0  # seconds between NSE requests
    BSE_REQUEST_DELAY: float = 2.0
    YFINANCE_CHUNK_SIZE: int = 50
    GEMINI_BATCH_SIZE: int = 5
    GEMINI_RPM_LIMIT: int = 15  # requests per minute (conservative)

    # News retention (days) — keep DB small
    NEWS_RETENTION_DAYS: int = 7
    JOB_LOG_RETENTION_DAYS: int = 3


settings = Settings()
