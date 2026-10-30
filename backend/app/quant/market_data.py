"""
Whole-market daily data from NSE's official archive (sec_bhavdata_full).

Every EQ-series stock, every trading day since 2020: open, high, low,
close, volume, turnover and delivery %. Cached on disk and updated
incrementally.

Corporate actions: the files carry raw prices, so a 1:1 bonus looks like
a 50% crash. NSE's PREV_CLOSE on an ex-date is already adjusted for the
action, so  factor_t = PREV_CLOSE_t / CLOSE_(t-1)  reveals it; all earlier
prices are multiplied by the cumulative product of these factors
(standard back-adjustment).
"""

import io
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Iterable, Optional

import httpx
import numpy as np
import pandas as pd

from app.quant.data import CACHE_DIR

logger = logging.getLogger(__name__)

URL = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{d}.csv"
UA = "Mozilla/5.0 (compatible; StockSentinel/1.0; personal research app)"
CACHE_FILE = os.path.join(CACHE_DIR, "market_bhav.pkl")
START = pd.Timestamp("2020-01-01")
FIELDS = {"OPEN_PRICE": "Open", "HIGH_PRICE": "High", "LOW_PRICE": "Low", "CLOSE_PRICE": "Close",
          "PREV_CLOSE": "PrevClose", "TTL_TRD_QNTY": "Volume", "TURNOVER_LACS": "TurnoverLacs",
          "DELIV_PER": "DelivPct"}


def _fetch(client: httpx.Client, day: pd.Timestamp) -> Optional[pd.DataFrame]:
    for attempt in range(3):
        try:
            r = client.get(URL.format(d=day.strftime("%d%m%Y")))
            if r.status_code == 404:
                return pd.DataFrame()       # holiday / no file
            if r.status_code == 200:
                df = pd.read_csv(io.StringIO(r.text), skipinitialspace=True)
                df.columns = [c.strip() for c in df.columns]
                df["SERIES"] = df["SERIES"].astype(str).str.strip()
                df = df[df["SERIES"] == "EQ"]
                out = pd.DataFrame({"symbol": df["SYMBOL"].astype(str).str.strip()})
                for src, dst in FIELDS.items():
                    out[dst] = pd.to_numeric(df[src], errors="coerce").astype("float32").values
                out["date"] = day
                return out
        except (ValueError, KeyError) as e:
            # The file exists but can't be read (NSE published a malformed
            # file for a few days): remember it as empty instead of
            # retrying it every night.
            logger.warning(f"bhav {day.date()}: unreadable file, skipped ({e})")
            return pd.DataFrame()
        except httpx.HTTPError as e:
            logger.debug(f"bhav {day.date()}: {e}")
        time.sleep(2 ** attempt)
    return None                              # failed: retry next run


def update_market(dates: Iterable[pd.Timestamp], workers: int = 6) -> Dict[str, pd.DataFrame]:
    """Download missing days, return wide frames {field: DataFrame(date x symbol)}."""
    have = pd.read_pickle(CACHE_FILE) if os.path.exists(CACHE_FILE) else {"rows": [], "done": set()}
    done = set(have["done"])
    # NSE's own files decide which days exist: also try every weekday up to
    # today, so a lagging Yahoo calendar can't hide the latest session.
    # (Holidays simply return 404 and are remembered as empty.)
    today = pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None).normalize()
    extra = pd.bdate_range(max(START, today - pd.Timedelta(days=10)), today)
    wanted = {pd.Timestamp(d) for d in dates} | set(extra)
    todo = sorted(d for d in wanted if d >= START and d not in done)
    if todo:
        logger.info(f"Downloading NSE daily files for {len(todo)} days")
        new = []
        with httpx.Client(headers={"User-Agent": UA}, timeout=30) as client:
            with ThreadPoolExecutor(workers) as ex:
                for day, df in zip(todo, ex.map(lambda d: _fetch(client, d), todo)):
                    if df is None:
                        continue
                    done.add(day)
                    if not df.empty:
                        new.append(df)
        rows = have["rows"] + new
        os.makedirs(CACHE_DIR, exist_ok=True)
        pd.to_pickle({"rows": rows, "done": done}, CACHE_FILE)
    else:
        rows = have["rows"]
    if not rows:
        return {}
    long = pd.concat(rows, ignore_index=True).drop_duplicates(["date", "symbol"], keep="last")
    wide = {f: long.pivot(index="date", columns="symbol", values=f).sort_index() for f in FIELDS.values()}
    return adjust_for_corporate_actions(wide)


# Factors that splits and bonuses produce: bonus a:b -> (a+b)/b, split 1:k -> k.
# Ratios below 1.5 (bonus 1:3, 1:4, 1:5 ...) are left out on purpose: they look
# exactly like NSE's 20%/25% price-band moves, so they can't be told apart.
STANDARD_RATIOS = np.array(sorted({1.5, 2, 2.5, 3, 4, 5, 6, 8, 10, 20}))


def detect_actions(close: pd.DataFrame, open_: pd.DataFrame) -> pd.DataFrame:
    """
    Factor per (day, stock): >1 where an overnight gap matches a standard
    split/bonus ratio (within 4%) and is too large to be ordinary news
    (more than a 15% gap), else 1. Consolidations use the inverse ratios.
    """
    gap = close.shift(1) / open_                       # yesterday's close / today's open
    factor = pd.DataFrame(1.0, index=close.index, columns=close.columns)
    # "up" = share consolidations (rare); only ratios of 2x or more are trusted there.
    for direction, g in (("down", gap), ("up", (1 / gap).where(1 / gap > 1.95))):
        vals = g.values
        with np.errstate(invalid="ignore", divide="ignore"):
            idx = np.abs(np.log(vals[..., None]) - np.log(STANDARD_RATIOS)).argmin(axis=-1)
            nearest = STANDARD_RATIOS[idx]
            match = (np.abs(vals / nearest - 1) < 0.03) & (vals > 1.45)
        f = np.where(match, nearest if direction == "down" else 1 / nearest, 1.0)
        factor = factor * pd.DataFrame(f, index=close.index, columns=close.columns)
    return factor


def adjust_for_corporate_actions(wide: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    close, open_ = wide["Close"].astype(float), wide["Open"].astype(float)
    factor = detect_actions(close, open_).fillna(1.0)
    # Divide every price BEFORE an ex-date by that day's factor (cumulative from the end).
    cum = factor[::-1].cumprod()[::-1].shift(-1).fillna(1.0)
    out = dict(wide)
    for f in ("Open", "High", "Low", "Close", "PrevClose"):
        out[f] = wide[f].astype(float) / cum
    out["Volume"] = wide["Volume"].astype(float) * cum
    out["AdjFactor"] = cum
    out["Actions"] = factor
    return out


EQUITY_LIST_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
EQUITY_LIST_FILE = os.path.join(CACHE_DIR, "equity_list.pkl")


def equity_symbols(max_age_days: float = 7) -> Optional[set]:
    """NSE's official list of listed companies (no ETFs, liquid funds or bonds). None if unavailable."""
    if os.path.exists(EQUITY_LIST_FILE) and time.time() - os.path.getmtime(EQUITY_LIST_FILE) < max_age_days * 86400:
        return pd.read_pickle(EQUITY_LIST_FILE)
    try:
        r = httpx.get(EQUITY_LIST_URL, headers={"User-Agent": UA}, timeout=30)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        syms = set(df["SYMBOL"].astype(str).str.strip())
        if len(syms) < 1000:
            raise ValueError(f"only {len(syms)} symbols")
        os.makedirs(CACHE_DIR, exist_ok=True)
        pd.to_pickle(syms, EQUITY_LIST_FILE)
        return syms
    except Exception as e:
        logger.warning(f"Equity list unavailable ({e}); falling back to the cached copy")
        return pd.read_pickle(EQUITY_LIST_FILE) if os.path.exists(EQUITY_LIST_FILE) else None


def equities_only(W: Dict[str, pd.DataFrame], allowed: Optional[set] = None) -> Dict[str, pd.DataFrame]:
    """Keep only company shares: drops ETFs, liquid funds and other non-company EQ-series symbols."""
    allowed = allowed if allowed is not None else equity_symbols()
    if not allowed:
        return W
    cols = W["Close"].columns
    if cols.isin(list(allowed)).mean() < 0.5:      # not NSE symbols at all (e.g. test data): leave as is
        return W
    out = {}
    for k, v in W.items():
        out[k] = v[[c for c in v.columns if c in allowed]] if isinstance(v, pd.DataFrame) else v
    return out
