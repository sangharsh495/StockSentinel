"""
Shareholding Tracker — Tracks promoter, insider, institutional (FII/DII), and public ownership patterns.

Extracts:
  - Promoter / Insider holding %
  - Institutional holding %
  - Top institutional holders (Funds / Institutions, Shares, Portfolio %)
  - Retail & Public float %
  - Ownership Stability Rating (Buffett alignment)
"""

import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, Optional, List
import yfinance as yf

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=3)
_shareholding_cache: Dict[str, Dict[str, Any]] = {}


def _fetch_shareholding_sync(symbol: str, exchange: str) -> Dict[str, Any]:
    """Synchronously fetches shareholding data using yfinance."""
    ticker_str = symbol.upper()
    if exchange.upper() == "NSE" and not ticker_str.endswith(".NS"):
        ticker_str = f"{ticker_str}.NS"
    elif exchange.upper() == "BSE" and not ticker_str.endswith(".BO"):
        ticker_str = f"{ticker_str}.BO"

    t = yf.Ticker(ticker_str)
    
    insider_pct = 0.0
    inst_pct = 0.0
    float_pct = 0.0

    try:
        major = t.major_holders
        if major is not None and not major.empty:
            # major_holders can be a DataFrame with 2 columns: Value, Metric
            for idx, row in major.iterrows():
                row_str = " ".join([str(val) for val in row.values]).lower()
                val = row.iloc[0]
                try:
                    num = float(str(val).replace("%", "").strip())
                    if "insider" in row_str:
                        insider_pct = num
                    elif "institutions" in row_str and "float" not in row_str:
                        inst_pct = num
                    elif "float" in row_str:
                        float_pct = num
                except (ValueError, TypeError):
                    continue
    except Exception as e:
        logger.warning(f"Error fetching major holders for {symbol}: {e}")

    # Fallback to info dict if major_holders empty
    try:
        info = t.info or {}
        if insider_pct == 0.0:
            insider_pct = round((info.get("heldPercentInsiders") or 0.0) * 100, 2)
        if inst_pct == 0.0:
            inst_pct = round((info.get("heldPercentInstitutions") or 0.0) * 100, 2)
    except Exception:
        pass

    # Public/Retail float approximation
    public_pct = max(0.0, round(100.0 - (insider_pct + inst_pct), 2))

    # Top Institutional Holders
    top_holders: List[Dict[str, Any]] = []
    try:
        inst_holders = t.institutional_holders
        if inst_holders is not None and not inst_holders.empty:
            for _, row in inst_holders.head(5).iterrows():
                holder_name = str(row.get("Holder", row.iloc[0] if len(row) > 0 else "Institutional Investor"))
                shares = int(row.get("Shares", 0)) if "Shares" in row else 0
                top_holders.append({
                    "holder": holder_name,
                    "shares": shares,
                    "date_reported": str(row.get("Date Reported", ""))
                })
    except Exception as e:
        logger.debug(f"Could not parse top institutional holders for {symbol}: {e}")

    # Buffett Skin-in-the-Game Assessment
    if insider_pct >= 50.0:
        verdict = "STRONG PROMOTER COMMITTED (High Skin in the Game)"
        alignment = "EXCELLENT"
    elif insider_pct >= 30.0:
        verdict = "MODERATE PROMOTER HOLDING (Aligned Management)"
        alignment = "GOOD"
    elif inst_pct >= 40.0:
        verdict = "INSTITUTIONALLY DOMINATED (High FII/DII Confidence)"
        alignment = "FAIR"
    else:
        verdict = "DISPERSED / RETAIL DOMINATED"
        alignment = "CAUTION"

    return {
        "symbol": symbol.upper(),
        "exchange": exchange.upper(),
        "promoter_insider_pct": round(insider_pct, 2),
        "institutional_pct": round(inst_pct, 2),
        "public_retail_pct": public_pct,
        "skin_in_the_game_alignment": alignment,
        "verdict": verdict,
        "top_institutions": top_holders,
    }


class ShareholdingTracker:
    async def get_shareholding(self, symbol: str, exchange: str = "NSE") -> Dict[str, Any]:
        """Asynchronously returns shareholding breakdown."""
        cache_key = f"{symbol.upper()}_{exchange.upper()}"
        if cache_key in _shareholding_cache:
            return _shareholding_cache[cache_key]

        loop = asyncio.get_event_loop()
        try:
            data = await loop.run_in_executor(_executor, _fetch_shareholding_sync, symbol, exchange)
        except Exception as e:
            logger.error(f"Shareholding fetch failed for {symbol}: {e}")
            data = {
                "symbol": symbol.upper(),
                "exchange": exchange.upper(),
                "promoter_insider_pct": 0.0,
                "institutional_pct": 0.0,
                "public_retail_pct": 100.0,
                "skin_in_the_game_alignment": "UNKNOWN",
                "verdict": "Shareholding data unavailable",
                "top_institutions": [],
            }

        _shareholding_cache[cache_key] = data
        return data


shareholding_tracker = ShareholdingTracker()
