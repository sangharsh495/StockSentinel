"""
Price data loader — daily OHLCV for the universe plus Nifty and India VIX.

Returns "wide" frames: one DataFrame per field (Close, Volume, ...) with
dates as rows and symbols as columns. Results are cached to disk so
repeated training runs don't re-download years of history.
"""

import logging
import os
import time
from typing import Dict, List, Optional

import pandas as pd

from app.quant.universe import NIFTY_INDEX, UNIVERSE, VIX_INDEX, yf_ticker

logger = logging.getLogger(__name__)

CACHE_DIR = os.environ.get(
    "QUANT_CACHE_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".quant_cache"),
)
FIELDS = ["Open", "High", "Low", "Close", "Volume"]


def _download(tickers: List[str], period: str) -> pd.DataFrame:
    import yfinance as yf

    for attempt in range(3):
        try:
            df = yf.download(
                tickers, period=period, interval="1d", auto_adjust=True,
                progress=False, group_by="column", threads=True,
            )
            if df is not None and not df.empty:
                return df
        except Exception as e:  # network hiccup — retry with backoff
            logger.warning(f"yfinance download failed (attempt {attempt + 1}): {e}")
        time.sleep(2 ** attempt)
    raise RuntimeError("Could not download price data from yfinance")


def load_prices(
    symbols: Optional[List[str]] = None,
    period: str = "10y",
    use_cache: bool = True,
    max_cache_age_hours: float = 12,
) -> Dict[str, pd.DataFrame]:
    """
    Load daily prices. Returns {"Open": df, ..., "Volume": df, "nifty": df, "vix": series}.
    Stock columns are plain NSE symbols (e.g. "RELIANCE").
    """
    symbols = symbols or UNIVERSE
    cache_file = os.path.join(CACHE_DIR, f"prices_{period}_{len(symbols)}.pkl")

    if use_cache and os.path.exists(cache_file):
        age_h = (time.time() - os.path.getmtime(cache_file)) / 3600
        if age_h < max_cache_age_hours:
            return pd.read_pickle(cache_file)

    tickers = [yf_ticker(s) for s in symbols] + [NIFTY_INDEX, VIX_INDEX]
    raw = _download(tickers, period)

    out: Dict[str, pd.DataFrame] = {}
    rename = {yf_ticker(s): s for s in symbols}
    for field in FIELDS:
        wide = raw[field].rename(columns=rename)
        out[field] = wide[[s for s in symbols if s in wide.columns]]

    out["nifty"] = pd.DataFrame({f: raw[f][NIFTY_INDEX] for f in FIELDS})
    out["vix"] = raw["Close"][VIX_INDEX]

    # Index is the trading calendar: keep only days the Nifty traded.
    cal = out["nifty"]["Close"].dropna().index
    for k in list(out):
        out[k] = out[k].reindex(cal)

    # Drop symbols with almost no history (failed tickers, new listings).
    close = out["Close"]
    keep = [c for c in close.columns if close[c].notna().sum() >= 300]
    dropped = sorted(set(close.columns) - set(keep))
    if dropped:
        logger.info(f"Dropping {len(dropped)} symbols with too little history: {dropped}")
    for field in FIELDS:
        out[field] = out[field][keep]

    if use_cache:
        os.makedirs(CACHE_DIR, exist_ok=True)
        pd.to_pickle(out, cache_file)
    return out
