"""
Quarterly results surprises (actual EPS vs analyst estimate) from Yahoo.

Feature rule: a result is only "known" from the trading day AFTER its
announcement date (announcements often come after market hours), so the
models can't peek at results before the market could react to them.
"""

import logging
import os
import time
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from app.quant.data import CACHE_DIR
from app.quant.universe import yf_ticker

logger = logging.getLogger(__name__)
CACHE_FILE = os.path.join(CACHE_DIR, "earnings.pkl")


def load_earnings(symbols: List[str], max_age_h: float = 72) -> pd.DataFrame:
    """Rows: symbol, announce_date (IST date), eps_est, eps_actual, surprise_pct."""
    if os.path.exists(CACHE_FILE) and (time.time() - os.path.getmtime(CACHE_FILE)) / 3600 < max_age_h:
        cached = pd.read_pickle(CACHE_FILE)
        if set(symbols) <= set(cached["symbol"].unique()) | set(cached.attrs.get("empty", [])):
            return cached
    import yfinance as yf

    rows, empty = [], []
    for s in symbols:
        try:
            e = yf.Ticker(yf_ticker(s)).get_earnings_dates(limit=40)
        except Exception as ex:
            logger.debug(f"earnings {s}: {ex}")
            e = None
        if e is None or e.empty:
            empty.append(s)
            continue
        e = e.dropna(subset=["Reported EPS"])
        for ts, r in e.iterrows():
            est, act = r.get("EPS Estimate"), r.get("Reported EPS")
            ist = pd.Timestamp(ts).tz_convert("Asia/Kolkata")
            rows.append({
                "symbol": s, "announce_date": pd.Timestamp(ist.date()),
                "announce_hour_ist": ist.hour,
                "eps_est": est, "eps_actual": act,
                "surprise_pct": r.get("Surprise(%)"),
            })
        time.sleep(0.3)
    df = pd.DataFrame(rows)
    df.attrs["empty"] = empty
    os.makedirs(CACHE_DIR, exist_ok=True)
    pd.to_pickle(df, CACHE_FILE)
    return df


def earnings_features(prices: Dict[str, pd.DataFrame]) -> Optional[pd.DataFrame]:
    close = prices["Close"]
    cal = close.index
    try:
        ev = load_earnings(list(close.columns))
    except Exception as e:
        logger.warning(f"Earnings data unavailable: {e}")
        return None
    if ev is None or ev.empty:
        return None
    parts = []
    for sym, g in ev.groupby("symbol"):
        if sym not in close.columns:
            continue
        g = g.sort_values("announce_date")
        # first trading day strictly after the announcement date
        pos = cal.searchsorted(g["announce_date"].values, side="right")
        ok = pos < len(cal)
        g = g[ok].assign(eff=cal[pos[ok]])
        if g.empty:
            continue
        sp = g["surprise_pct"].clip(-100, 100)
        eps_yoy = g["eps_actual"] / g["eps_actual"].shift(4).where(g["eps_actual"].shift(4) > 0) - 1
        ev_df = pd.DataFrame({
            "last_surprise_pct": sp.values,
            "surprise_avg_4q": sp.rolling(4, min_periods=1).mean().values,
            "beat_streak": (sp > 0).astype(int).groupby((sp <= 0).cumsum()).cumsum().values,
            "eps_yoy_growth": eps_yoy.clip(-2, 5).values,
            "event_day": g["eff"].values,
        }, index=pd.DatetimeIndex(g["eff"].values)).groupby(level=0).last()
        daily = ev_df.reindex(cal).ffill()
        daily["days_since_results"] = (cal - pd.DatetimeIndex(daily["event_day"])).days
        daily = daily.drop(columns="event_day")
        daily["symbol"] = sym
        parts.append(daily)
    if not parts:
        return None
    out = pd.concat(parts)
    out.index.name = "date"
    out = out.set_index("symbol", append=True)
    # Old results lose meaning: blank them after ~100 days (next quarter is due)
    stale = out["days_since_results"] > 100
    out.loc[stale, ["last_surprise_pct", "surprise_avg_4q", "beat_streak"]] = np.nan
    out["post_results_window"] = (out["days_since_results"] <= 30).astype(float)
    return out.astype(float)
