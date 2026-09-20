"""
Chart Service — fetches multi-timeframe historical price points via yfinance
with smart in-memory TTL caching.
"""

import time
import logging
import asyncio
from typing import Dict, Any, List, Optional
from concurrent.futures import ThreadPoolExecutor

import yfinance as yf

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=3)
_chart_cache: Dict[str, Dict[str, Any]] = {}  # key -> {data, expires_at}
CACHE_TTL_SECONDS = 300  # 5 minutes


class ChartService:
    """Provides time-series data points for stock charts."""

    RANGE_CONFIGS = {
        "1D": {"period": "1d", "interval": "5m", "label_fmt": "%H:%M"},
        "1W": {"period": "5d", "interval": "30m", "label_fmt": "%d %b %H:%M"},
        "1M": {"period": "1mo", "interval": "1d", "label_fmt": "%d %b"},
        "3M": {"period": "3mo", "interval": "1d", "label_fmt": "%d %b"},
        "1Y": {"period": "1y", "interval": "1wk", "label_fmt": "%b %Y"},
        "5Y": {"period": "5y", "interval": "1mo", "label_fmt": "%b %Y"},
    }

    @staticmethod
    def get_yf_ticker(symbol: str, exchange: str = "NSE") -> str:
        """Resolve yfinance ticker identifier."""
        clean = symbol.strip().upper()
        if clean.startswith("^"):
            return clean
        if exchange.upper() == "NSE":
            return f"{clean}.NS"
        elif exchange.upper() == "BSE":
            return f"{clean}.BO"
        return clean  # US stocks (NYSE, NASDAQ)

    async def get_chart_data(self, symbol: str, exchange: str = "NSE", range_key: str = "1M") -> Dict[str, Any]:
        """Fetch chart data points for the given range."""
        range_upper = range_key.upper() if range_key.upper() in self.RANGE_CONFIGS else "1M"
        yf_ticker = self.get_yf_ticker(symbol, exchange)
        cache_key = f"{yf_ticker}_{range_upper}"

        # Check cache
        now = time.time()
        if cache_key in _chart_cache:
            cached = _chart_cache[cache_key]
            if now < cached["expires_at"]:
                return cached["data"]

        # Fetch in thread pool
        cfg = self.RANGE_CONFIGS[range_upper]
        loop = asyncio.get_event_loop()

        def _fetch_sync():
            try:
                ticker = yf.Ticker(yf_ticker)
                hist = ticker.history(period=cfg["period"], interval=cfg["interval"])
                if hist.empty:
                    # Fallback without suffix if failed
                    if "." in yf_ticker:
                        fallback_ticker = yf.Ticker(symbol)
                        hist = fallback_ticker.history(period=cfg["period"], interval=cfg["interval"])

                if hist.empty:
                    return None

                points = []
                labels = []
                for idx, row in hist.iterrows():
                    val = float(row["Close"])
                    if not (val != val):  # not NaN
                        points.append(round(val, 2))
                        labels.append(idx.strftime(cfg["label_fmt"]))

                if not points:
                    return None

                start_price = points[0]
                end_price = points[-1]
                change_pct = round(((end_price - start_price) / start_price) * 100, 2) if start_price else 0.0

                return {
                    "symbol": symbol.upper(),
                    "range": range_upper,
                    "points": points,
                    "labels": labels,
                    "min_price": min(points),
                    "max_price": max(points),
                    "current_price": end_price,
                    "change_pct": change_pct,
                }
            except Exception as e:
                logger.warning(f"Error fetching yfinance chart for {yf_ticker}: {e}")
                return None

        result = await loop.run_in_executor(_executor, _fetch_sync)

        if not result:
            # Generate synthetic fallback if yfinance fails
            result = {
                "symbol": symbol.upper(),
                "range": range_upper,
                "points": [],
                "labels": [],
                "min_price": 0.0,
                "max_price": 0.0,
                "current_price": 0.0,
                "change_pct": 0.0,
                "empty": True,
            }

        _chart_cache[cache_key] = {
            "data": result,
            "expires_at": now + CACHE_TTL_SECONDS,
        }
        return result


chart_service = ChartService()
