"""
FII / DII / Client / Pro positioning from NSE's daily participant-wise
open interest file (public archive, from 2020).

Gives market-level features such as "what share of FII index-futures
positions are long", a widely watched sentiment gauge, and how fast it
is changing.
"""

import io
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Iterable, Optional

import httpx
import numpy as np
import pandas as pd

from app.quant.data import CACHE_DIR

logger = logging.getLogger(__name__)

URL = "https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_{d}.csv"
UA = "Mozilla/5.0 (compatible; StockSentinel/1.0; personal research app)"
CACHE_FILE = os.path.join(CACHE_DIR, "participants.pkl")
ARCHIVE_START = pd.Timestamp("2020-01-01")


def _fetch(client: httpx.Client, day: pd.Timestamp):
    for attempt in range(3):
        try:
            r = client.get(URL.format(d=day.strftime("%d%m%Y")))
            if r.status_code == 404:
                return {}
            if r.status_code == 200:
                df = pd.read_csv(io.StringIO(r.text), skiprows=1)
                df.columns = [c.strip() for c in df.columns]
                df["Client Type"] = df["Client Type"].astype(str).str.strip()
                out = {}
                for who in ("FII", "DII", "Client", "Pro"):
                    row = df[df["Client Type"] == who]
                    if row.empty:
                        continue
                    row = row.iloc[0]
                    for col in df.columns[1:]:
                        out[f"{who}|{col}"] = float(str(row[col]).replace(",", ""))
                return out
        except (httpx.HTTPError, ValueError, KeyError) as e:
            logger.debug(f"participants {day.date()}: {e}")
        time.sleep(2 ** attempt)
    return None


def load_participants(dates: Iterable[pd.Timestamp], workers: int = 4) -> pd.DataFrame:
    have = pd.read_pickle(CACHE_FILE) if os.path.exists(CACHE_FILE) else {}
    todo = [pd.Timestamp(d) for d in dates if pd.Timestamp(d) >= ARCHIVE_START and pd.Timestamp(d) not in have]
    if todo:
        logger.info(f"Downloading participant OI for {len(todo)} days")
        with httpx.Client(headers={"User-Agent": UA}, timeout=30) as client:
            with ThreadPoolExecutor(workers) as ex:
                for day, rec in zip(todo, ex.map(lambda d: _fetch(client, d), todo)):
                    if rec is not None:
                        have[day] = rec
        os.makedirs(CACHE_DIR, exist_ok=True)
        pd.to_pickle(have, CACHE_FILE)
    df = pd.DataFrame.from_dict({k: v for k, v in have.items() if v}, orient="index").sort_index()
    return df


def _ratio(df, who, long_col, short_col):
    lo, sh = df.get(f"{who}|{long_col}"), df.get(f"{who}|{short_col}")
    if lo is None or sh is None:
        return None
    return lo / (lo + sh).replace(0, np.nan)


def participant_features(cal: pd.DatetimeIndex) -> Optional[pd.DataFrame]:
    try:
        df = load_participants(cal)
    except Exception as e:
        logger.warning(f"Participant OI unavailable: {e}")
        return None
    if df.empty:
        return None
    df = df.reindex(cal)
    f = pd.DataFrame(index=cal)
    for who in ("FII", "Client", "Pro"):
        r = _ratio(df, who, "Future Index Long", "Future Index Short")
        if r is not None:
            f[f"{who.lower()}_idxfut_long_ratio"] = r
            f[f"{who.lower()}_idxfut_long_chg5"] = r - r.shift(5)
    # FII index options: (calls long - calls short) - (puts long - puts short), scaled
    c = df.get("FII|Option Index Call Long") - df.get("FII|Option Index Call Short")
    p = df.get("FII|Option Index Put Long") - df.get("FII|Option Index Put Short")
    tot = df.get("FII|Total Long Contracts") + df.get("FII|Total Short Contracts")
    f["fii_idxopt_net_bias"] = (c - p) / tot.replace(0, np.nan)
    f["fii_stockfut_long_ratio"] = _ratio(df, "FII", "Future Stock Long", "Future Stock Short")
    # 1-year percentile of FII index-futures long ratio (regime-free)
    if "fii_idxfut_long_ratio" in f:
        f["fii_idxfut_long_pct_1y"] = f["fii_idxfut_long_ratio"].rolling(250, min_periods=60).rank(pct=True)
    return f
