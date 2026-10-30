"""
Company fundamentals (annual results, balance sheet, cash flow) from Yahoo.

Point-in-time rule: a report is only "known" from its period end plus a
safe filing lag. SEBI gives listed companies 60 days for annual (Q4)
results and 45 days for quarterly results, so we use 75 and 60 days. A
model can therefore never see numbers before the market could.

Cached on disk; each stock is refreshed at most once a week.
"""

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

from app.quant.data import CACHE_DIR
from app.quant.universe import yf_ticker

logger = logging.getLogger(__name__)
CACHE_FILE = os.path.join(CACHE_DIR, "fundamentals.pkl")
ANNUAL_LAG = pd.Timedelta(days=75)
QUARTER_LAG = pd.Timedelta(days=60)

INCOME = {"Total Revenue": "revenue", "Operating Income": "op_income", "Net Income": "net_income"}
BALANCE = {"Total Debt": "debt", "Stockholders Equity": "equity", "Ordinary Shares Number": "shares"}
CASH = {"Operating Cash Flow": "ocf", "Free Cash Flow": "fcf"}
CACHE_VERSION = 2          # 2: dividends added


def _rows(frame: Optional[pd.DataFrame], names: Dict[str, str]) -> Dict[pd.Timestamp, dict]:
    out: Dict[pd.Timestamp, dict] = {}
    if frame is None or frame.empty:
        return out
    for col in frame.columns:
        rec = {}
        for src, dst in names.items():
            if src in frame.index:
                v = pd.to_numeric(frame.at[src, col], errors="coerce")
                rec[dst] = float(v) if pd.notna(v) else np.nan
        out[pd.Timestamp(col).normalize()] = rec
    return out


def fetch_one(symbol: str) -> List[dict]:
    """All annual and quarterly records Yahoo has for one stock."""
    import yfinance as yf

    t = yf.Ticker(yf_ticker(symbol))
    recs: List[dict] = []
    inc, bal, cf = _rows(t.income_stmt, INCOME), _rows(t.balance_sheet, BALANCE), _rows(t.cashflow, CASH)
    for end in sorted(set(inc) | set(bal) | set(cf)):
        r = {"symbol": symbol, "kind": "A", "period_end": end, "available": end + ANNUAL_LAG}
        r.update(inc.get(end, {}))
        r.update(bal.get(end, {}))
        r.update(cf.get(end, {}))
        recs.append(r)
    for end, vals in _rows(t.quarterly_income_stmt, INCOME).items():
        recs.append({"symbol": symbol, "kind": "Q", "period_end": end, "available": end + QUARTER_LAG, **vals})
    # Dividends per share by ex-date (split-adjusted by Yahoo, like our prices).
    # Known on the ex-date at the latest (they are announced before it).
    div = t.dividends
    if div is not None and len(div):
        for ts, amt in div.items():
            d = pd.Timestamp(ts).tz_localize(None).normalize() if pd.Timestamp(ts).tzinfo else pd.Timestamp(ts).normalize()
            recs.append({"symbol": symbol, "kind": "D", "period_end": d, "available": d, "dividend": float(amt)})
    return recs


def load_fundamentals(symbols: Iterable[str], max_age_days: float = 7, max_fetch: int = 4000,
                      workers: int = 3) -> pd.DataFrame:
    """Rows: symbol, kind (A/Q), period_end, available, revenue, op_income, net_income, debt, equity, shares, ocf, fcf."""
    cache = pd.read_pickle(CACHE_FILE) if os.path.exists(CACHE_FILE) else {}
    now = time.time()
    stale = [s for s in symbols if now - cache.get(s, {}).get("fetched", 0) > max_age_days * 86400
             or cache.get(s, {}).get("v", 1) < CACHE_VERSION]
    stale = stale[:max_fetch]
    if stale:
        logger.info(f"Fetching fundamentals for {len(stale)} stocks")

        def get(s):
            for attempt in range(3):
                try:
                    return s, fetch_one(s)
                except Exception as e:      # rate limits, missing tickers
                    logger.debug(f"fundamentals {s}: {e}")
                    time.sleep(2 ** attempt)
            return s, None

        with ThreadPoolExecutor(workers) as ex:
            for i, (s, recs) in enumerate(ex.map(get, stale)):
                if recs is not None:
                    cache[s] = {"fetched": now, "rows": recs, "v": CACHE_VERSION}
                if i % 200 == 199:
                    os.makedirs(CACHE_DIR, exist_ok=True)
                    pd.to_pickle(cache, CACHE_FILE)
        os.makedirs(CACHE_DIR, exist_ok=True)
        pd.to_pickle(cache, CACHE_FILE)
    rows = [r for v in cache.values() for r in v.get("rows", [])]
    cols = ["symbol", "kind", "period_end", "available", *INCOME.values(), *BALANCE.values(), *CASH.values(),
            "dividend"]
    df = pd.DataFrame(rows)
    for c in cols:
        if c not in df.columns:
            df[c] = np.nan
    return df[cols]


def _slog(x):
    return np.sign(x) * np.log1p(np.abs(x))


def annual_features(fund: pd.DataFrame) -> pd.DataFrame:
    """
    One row per (symbol, annual report) with growth/quality features computed
    from that report and the ones before it. Index: (symbol, available).
    """
    a = fund[fund["kind"] == "A"].sort_values(["symbol", "period_end"]).copy()
    if a.empty:
        return pd.DataFrame()
    g = a.groupby("symbol")
    prev = g.shift(1)
    prev2 = g.shift(2)
    pos = lambda s: s.where(s > 0)  # noqa: E731
    a["rev_growth"] = np.log(pos(a["revenue"]) / pos(prev["revenue"]))
    a["rev_growth_prev"] = np.log(pos(prev["revenue"]) / pos(prev2["revenue"]))
    a["rev_accel"] = a["rev_growth"] - a["rev_growth_prev"]
    # profit growth scaled by revenue (works through losses, unlike a % change)
    a["profit_growth"] = (a["net_income"] - prev["net_income"]) / pos(prev["revenue"])
    a["op_margin"] = a["op_income"] / pos(a["revenue"])
    a["margin_change"] = a["op_margin"] - (prev["op_income"] / pos(prev["revenue"]))
    a["roe"] = a["net_income"] / pos(a["equity"])
    a["debt_to_equity"] = a["debt"] / pos(a["equity"])
    a["cash_conversion"] = a["ocf"] / a["net_income"].abs().replace(0, np.nan)
    a["dilution"] = np.log(pos(a["shares"]) / pos(prev["shares"]))
    a["turned_profitable"] = ((a["net_income"] > 0) & (prev["net_income"] <= 0)).astype(float)
    a["fcf_positive"] = (a["fcf"] > 0).astype(float).where(a["fcf"].notna())
    keep = ["symbol", "available", "period_end", "revenue", "net_income", "shares", "rev_growth",
            "rev_accel", "profit_growth", "op_margin", "margin_change", "roe", "debt_to_equity",
            "cash_conversion", "dilution", "turned_profitable", "fcf_positive"]
    return a[keep]


FUND_FEATURES = ["rev_growth", "rev_accel", "profit_growth", "op_margin", "margin_change", "roe",
                 "debt_to_equity", "cash_conversion", "dilution", "turned_profitable", "fcf_positive",
                 "log_mcap", "earnings_yield", "sales_yield"]


def point_in_time(fund: pd.DataFrame, dates: pd.DatetimeIndex, close: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """
    Wide frames {feature: DataFrame(dates x symbols)} using only reports
    available on each date, plus valuation from that day's price.
    """
    af = annual_features(fund)
    out = {f: pd.DataFrame(np.nan, index=dates, columns=close.columns) for f in FUND_FEATURES}
    if af.empty:
        return out
    af = af[af["symbol"].isin(close.columns)]
    for f in FUND_FEATURES[:11] + ["revenue", "net_income", "shares"]:
        wide = af.pivot_table(index="available", columns="symbol", values=f, aggfunc="last")
        wide = wide.reindex(wide.index.union(dates)).sort_index().ffill().reindex(dates)
        wide = wide.reindex(columns=close.columns)
        if f in out:
            out[f] = wide
        else:
            out["_" + f] = wide
    px = close.reindex(dates)
    mcap = px * out.pop("_shares")
    out["log_mcap"] = np.log(mcap.where(mcap > 0))
    out["earnings_yield"] = out.pop("_net_income") / mcap
    out["sales_yield"] = out.pop("_revenue") / mcap
    return out


def latest_quarter_growth(fund: pd.DataFrame) -> Dict[str, dict]:
    """Latest quarter vs the same quarter a year earlier (shown as evidence, not used by the models)."""
    q = fund[fund["kind"] == "Q"].sort_values("period_end")
    out = {}
    for s, g in q.groupby("symbol"):
        g = g.set_index("period_end")
        last = g.index[-1]
        prior = g.index[(g.index <= last - pd.Timedelta(days=350)) & (g.index >= last - pd.Timedelta(days=380))]
        if len(prior) and g.at[prior[0], "revenue"] and g.at[prior[0], "revenue"] > 0:
            r0, r1 = g.at[prior[0], "revenue"], g.at[last, "revenue"]
            n0, n1 = g.at[prior[0], "net_income"], g.at[last, "net_income"]
            out[s] = {"quarter": str(last.date()),
                      "revenue_yoy_pct": round((r1 / r0 - 1) * 100, 1) if pd.notna(r1) else None,
                      "profit_now": None if pd.isna(n1) else float(n1),
                      "profit_year_ago": None if pd.isna(n0) else float(n0)}
    return out
