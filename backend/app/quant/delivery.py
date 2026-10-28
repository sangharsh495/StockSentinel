"""
Delivery data from NSE's public daily archive (sec_bhavdata_full files).

Delivery % = share of traded volume actually taken into demat (not
squared off intraday). A jump in delivery with rising price is a classic
sign of real buying. The archive starts in 2020; earlier days are left
empty and the models handle missing values natively.
"""

import io
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Iterable, List, Optional

import httpx
import numpy as np
import pandas as pd

from app.quant.data import CACHE_DIR

logger = logging.getLogger(__name__)

URL = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{d}.csv"
UA = "Mozilla/5.0 (compatible; StockSentinel/1.0; personal research app)"
CACHE_FILE = os.path.join(CACHE_DIR, "delivery.pkl")
ARCHIVE_START = pd.Timestamp("2020-01-01")


def _fetch_day(client: httpx.Client, day: pd.Timestamp, symbols: set) -> Optional[pd.DataFrame]:
    url = URL.format(d=day.strftime("%d%m%Y"))
    for attempt in range(3):
        try:
            r = client.get(url)
            if r.status_code == 404:
                return pd.DataFrame()  # holiday / no file: remember as empty
            if r.status_code == 200:
                df = pd.read_csv(io.StringIO(r.text), skipinitialspace=True)
                df.columns = [c.strip() for c in df.columns]
                df["SERIES"] = df["SERIES"].astype(str).str.strip()
                df["SYMBOL"] = df["SYMBOL"].astype(str).str.strip()
                df = df[(df["SERIES"] == "EQ") & (df["SYMBOL"].isin(symbols))]
                out = pd.DataFrame({
                    "date": day, "symbol": df["SYMBOL"],
                    "deliv_pct": pd.to_numeric(df["DELIV_PER"], errors="coerce"),
                    "deliv_qty": pd.to_numeric(df["DELIV_QTY"], errors="coerce"),
                    "trades": pd.to_numeric(df["NO_OF_TRADES"], errors="coerce"),
                    "qty": pd.to_numeric(df["TTL_TRD_QNTY"], errors="coerce"),
                })
                return out
        except (httpx.HTTPError, ValueError, KeyError) as e:
            logger.debug(f"{url}: {e}")
        time.sleep(2 ** attempt)
    return None  # failed: retry next run


def load_delivery(dates: Iterable[pd.Timestamp], symbols: List[str], workers: int = 4) -> pd.DataFrame:
    """Long frame (date, symbol, deliv_pct, deliv_qty, trades, qty); cached and incremental."""
    have = pd.read_pickle(CACHE_FILE) if os.path.exists(CACHE_FILE) else {"rows": pd.DataFrame(), "done": set()}
    rows, done = have["rows"], set(have["done"])
    todo = [pd.Timestamp(d) for d in dates if pd.Timestamp(d) >= ARCHIVE_START and pd.Timestamp(d) not in done]
    if todo:
        logger.info(f"Downloading delivery data for {len(todo)} days")
        syms = set(symbols)
        new = []
        with httpx.Client(headers={"User-Agent": UA}, timeout=30) as client:
            with ThreadPoolExecutor(workers) as ex:
                for day, df in zip(todo, ex.map(lambda d: _fetch_day(client, d, syms), todo)):
                    if df is None:
                        continue
                    done.add(day)
                    if not df.empty:
                        new.append(df)
        if new:
            rows = pd.concat([rows] + new, ignore_index=True).drop_duplicates(["date", "symbol"], keep="last")
        os.makedirs(CACHE_DIR, exist_ok=True)
        pd.to_pickle({"rows": rows, "done": done}, CACHE_FILE)
    return rows


def delivery_features(prices: Dict[str, pd.DataFrame]) -> Optional[pd.DataFrame]:
    """Point-in-time delivery features as a (date, symbol) panel."""
    close = prices["Close"]
    try:
        raw = load_delivery(close.index, list(close.columns))
    except Exception as e:  # network down: models still run without these
        logger.warning(f"Delivery data unavailable: {e}")
        return None
    if raw is None or raw.empty:
        return None
    wide = {k: raw.pivot_table(index="date", columns="symbol", values=k).reindex(index=close.index, columns=close.columns)
            for k in ("deliv_pct", "deliv_qty", "trades", "qty")}
    dp = wide["deliv_pct"]
    f = {
        "deliv_pct": dp,
        "deliv_pct_5": dp.rolling(5, min_periods=3).mean(),
        "deliv_pct_vs_60": dp.rolling(5, min_periods=3).mean() - dp.rolling(60, min_periods=30).mean(),
        "deliv_qty_surge": np.log(wide["deliv_qty"].rolling(5, min_periods=3).mean()
                                  / wide["deliv_qty"].rolling(60, min_periods=30).mean()),
        "avg_trade_size_chg": np.log((wide["qty"] / wide["trades"]).rolling(5, min_periods=3).mean()
                                     / (wide["qty"] / wide["trades"]).rolling(60, min_periods=30).mean()),
    }
    # Delivery-backed price move: 5-day return x delivery surge sign
    ret5 = np.log(close / close.shift(5))
    f["deliv_backed_move"] = ret5 * f["deliv_pct_vs_60"]
    f["rank_deliv_pct_vs_60"] = f["deliv_pct_vs_60"].rank(axis=1, pct=True)
    panel = pd.concat({k: v.replace([np.inf, -np.inf], np.nan).stack(future_stack=True) for k, v in f.items()}, axis=1)
    panel.index.names = ["date", "symbol"]
    return panel
