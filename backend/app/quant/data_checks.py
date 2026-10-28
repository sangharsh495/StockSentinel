"""
Cross-source data checks: never trust one feed blindly.

1. IPO GMP: investorgain vs ipowatch. When both report a GMP we show the
   consensus and how far apart they are; a big gap is flagged on the IPO
   (the grey market is unofficial, so disagreement means low confidence).
2. Stock prices: Yahoo Finance closes vs NSE's official daily file
   (sec_bhavdata_full). Stocks whose prices disagree are flagged, and the
   check reports how fresh each source is.
"""

import io
import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

import httpx
import pandas as pd
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

UA = "Mozilla/5.0 (compatible; StockSentinel/1.0; personal research app)"
IPOWATCH_GMP = "https://ipowatch.in/ipo-grey-market-premium-latest-ipo-gmp/"
NSE_BHAV = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{d}.csv"

GMP_DISAGREE_PTS = 5.0     # sources more than 5% of issue price apart -> flagged
GMP_DISAGREE_REL = 0.30    # ...or >3% apart AND one GMP is 30%+ off the other
PRICE_DISAGREE_PCT = 1.0   # Yahoo vs NSE close more than 1% apart -> flagged


def _num(s) -> Optional[float]:
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", str(s or "").replace("₹", ""))
    return float(m.group().replace(",", "")) if m else None


def norm_name(name: str) -> str:
    n = (name or "").lower()
    n = re.sub(r"\b(open|upcoming|closed|close|listed|allotment|ipo|limited|ltd|india|private|pvt)\b", "", n)
    return re.sub(r"[^a-z0-9]", "", n)


# ---------------------------------------------------------------------------
# 1. GMP from a second source
# ---------------------------------------------------------------------------
def parse_ipowatch(html: str) -> List[Dict]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for tb in soup.find_all("table"):
        rows = tb.find_all("tr")
        if not rows:
            continue
        head = [c.get_text(" ", strip=True).lower() for c in rows[0].find_all(["td", "th"])]
        if not head or "company" not in head[0] or not any("gmp" in h for h in head):
            continue
        gi = next(i for i, h in enumerate(head) if "gmp" in h)
        pi = next((i for i, h in enumerate(head) if "price" in h), None)
        for r in rows[1:]:
            cells = [c.get_text(" ", strip=True) for c in r.find_all(["td", "th"])]
            if len(cells) <= gi:
                continue
            out.append({"name": cells[0], "key": norm_name(cells[0]), "gmp": _num(cells[gi]),
                        "price": _num(cells[pi]) if pi is not None and pi < len(cells) else None})
    return out


def fetch_ipowatch() -> List[Dict]:
    try:
        r = httpx.get(IPOWATCH_GMP, headers={"User-Agent": UA}, timeout=30, follow_redirects=True)
        return parse_ipowatch(r.text) if r.status_code == 200 else []
    except httpx.HTTPError as e:
        logger.warning(f"ipowatch unavailable: {e}")
        return []


def gmp_consensus(primary_gmp: Optional[float], issue_price: Optional[float],
                  second: Optional[Dict]) -> Dict:
    """Compare our GMP with the second source for one IPO."""
    out = {"gmp_sources": {"investorgain": primary_gmp}, "gmp_check": "single_source"}
    if not second or second.get("gmp") is None or primary_gmp is None:
        return out
    g2 = second["gmp"]
    out["gmp_sources"]["ipowatch"] = g2
    out["gmp_consensus"] = round((primary_gmp + g2) / 2, 2)
    if issue_price:
        gap = abs(primary_gmp - g2) / issue_price * 100
        out["gmp_gap_pct_points"] = round(gap, 2)
        rel = abs(primary_gmp - g2) / max(abs(primary_gmp), abs(g2), 1e-9)
        out["gmp_relative_gap"] = round(rel, 3)
        disagree = gap > GMP_DISAGREE_PTS or (gap > 3.0 and rel > GMP_DISAGREE_REL)
        out["gmp_check"] = "disagree" if disagree else "agree"
        if out["gmp_check"] == "disagree":
            out["gmp_warning"] = (f"GMP sources disagree by {gap:.1f}% of issue price "
                                  f"(₹{primary_gmp:g} vs ₹{g2:g}); treat the estimate with caution.")
    return out


def attach_gmp_checks(current_rows: List[Dict]) -> Dict:
    """Adds gmp_check fields to each current IPO row (in place); returns a summary."""
    second = {r["key"]: r for r in fetch_ipowatch() if r.get("key")}
    counts = {"agree": 0, "disagree": 0, "single_source": 0}
    for row in current_rows:
        key = norm_name(row.get("name", ""))
        match = second.get(key) or next(
            (v for k, v in second.items() if key and (k.startswith(key[:12]) or key.startswith(k[:12]))), None)
        row.update(gmp_consensus(row.get("gmp"), row.get("issue_price"), match))
        counts[row["gmp_check"]] = counts.get(row["gmp_check"], 0) + 1
    return {"second_source": "ipowatch.in", "second_source_rows": len(second), **counts}


# ---------------------------------------------------------------------------
# 2. Prices: Yahoo vs NSE official close
# ---------------------------------------------------------------------------
def fetch_nse_close(day: pd.Timestamp) -> Optional[pd.Series]:
    url = NSE_BHAV.format(d=day.strftime("%d%m%Y"))
    try:
        r = httpx.get(url, headers={"User-Agent": UA}, timeout=30)
    except httpx.HTTPError as e:
        logger.warning(f"NSE file unavailable: {e}")
        return None
    if r.status_code != 200:
        return None
    df = pd.read_csv(io.StringIO(r.text), skipinitialspace=True)
    df.columns = [c.strip() for c in df.columns]
    df = df[df["SERIES"].astype(str).str.strip() == "EQ"]
    return pd.Series(pd.to_numeric(df["CLOSE_PRICE"], errors="coerce").values,
                     index=df["SYMBOL"].astype(str).str.strip())


def price_check(prices: Dict[str, pd.DataFrame], lookback_days: int = 5) -> Dict:
    """Compare Yahoo's latest close with NSE's official file for the same day."""
    close = prices["Close"]
    for day in list(close.index[-lookback_days:])[::-1]:
        nse = fetch_nse_close(pd.Timestamp(day))
        if nse is None or nse.empty:
            continue
        yahoo = close.loc[day].dropna()
        common = yahoo.index.intersection(nse.index)
        diff = ((yahoo[common] / nse[common] - 1) * 100).round(3)
        bad = diff[diff.abs() > PRICE_DISAGREE_PCT]
        return {
            "date": str(pd.Timestamp(day).date()),
            "compared": int(len(common)),
            "agree": int(len(common) - len(bad)),
            "disagree": {s: float(v) for s, v in bad.sort_values().items()},
            "missing_in_nse": sorted(set(yahoo.index) - set(nse.index)),
            "median_abs_diff_pct": float(diff.abs().median()) if len(diff) else None,
            "yahoo_latest_date": str(close.index[-1].date()),
            "status": "ok" if len(bad) == 0 else "warnings",
        }
    return {"status": "unavailable", "detail": "NSE daily file not reachable for recent days"}


def build_report(prices: Optional[Dict[str, pd.DataFrame]], ipo_summary: Optional[Dict]) -> Dict:
    report = {"checked_at": datetime.now(timezone.utc).isoformat()}
    if prices is not None:
        try:
            report["prices"] = price_check(prices)
        except Exception as e:  # a failed check must never stop training
            report["prices"] = {"status": "error", "detail": str(e)[:200]}
    if ipo_summary is not None:
        report["ipo_gmp"] = ipo_summary
    return report
