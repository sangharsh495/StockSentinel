"""
Dividend income engine: who pays, how regularly, in which months, how much,
and whether that payer has proven reliable.

For every company with a dividend in the last 3 years:
- payment history by calendar year (10 years), streak, cuts, 5-year growth;
- usual pay months (months with an ex-date in at least 2 of the last 3
  years) and how often it pays (quarterly / half-yearly / yearly / irregular);
- next expected ex-dates and amounts (same month as before, last amount);
- yield on today's price and the cash a Rs 1 lakh holding would bring in;
- an Income Score 0-100: 80 points from the payment record alone, 20 from
  today's yield, payout safety and cash cover.

Backtest ("paying power"): at every 30 June since 2012 the record-based
part of the score is computed from dividends known by then, and we check
what happened over the next 12 months: did the company pay, and did it
avoid cutting its dividend by more than 10%? Survivorship caveat: only
companies still listed today are in the data, so past reliability is
somewhat overstated.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from app.quant.multibagger import clean_json

logger = logging.getLogger(__name__)

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _dividends(fund: Optional[pd.DataFrame]) -> pd.DataFrame:
    if fund is None or not len(fund) or "dividend" not in fund:
        return pd.DataFrame(columns=["symbol", "date", "amount"])
    d = fund[(fund["kind"] == "D")].dropna(subset=["dividend"])
    d = d[d["dividend"] > 0]
    return pd.DataFrame({"symbol": d["symbol"].values, "date": pd.to_datetime(d["period_end"]).values,
                         "amount": d["dividend"].astype(float).values}).sort_values(["symbol", "date"])


def record_profile(g: pd.DataFrame, asof: pd.Timestamp) -> Optional[Dict]:
    """Everything that can be said from the payment record alone, using payments up to `asof`."""
    g = g[g["date"] <= asof]
    if g.empty or g["date"].max() < asof - pd.Timedelta(days=3 * 365):
        return None
    year_end = asof.year if asof.month == 12 else asof.year - 1          # last complete calendar year
    yearly = g.groupby(g["date"].dt.year)["amount"].sum()
    paid = lambda y: bool(yearly.get(y, 0) > 0)  # noqa: E731
    last5 = sum(paid(y) for y in range(year_end - 4, year_end + 1))
    last10 = sum(paid(y) for y in range(year_end - 9, year_end + 1))
    streak = 0
    for y in range(year_end, year_end - 30, -1):
        if not paid(y):
            break
        streak += 1
    # trailing-12-month totals, to judge cuts and growth on the same basis
    def ttm(end):
        return float(g[(g["date"] > end - pd.Timedelta(days=365)) & (g["date"] <= end)]["amount"].sum())

    ttm_now = ttm(asof)
    ttm_hist = [ttm(asof - pd.Timedelta(days=365 * k)) for k in range(6)]
    cuts5 = sum(1 for k in range(5) if ttm_hist[k + 1] > 0 and ttm_hist[k] < 0.9 * ttm_hist[k + 1])
    recent = g[g["date"] > asof - pd.Timedelta(days=3 * 365)]
    month_years = recent.groupby(recent["date"].dt.month)["date"].apply(lambda s: s.dt.year.nunique())
    usual = sorted(int(m) for m, n in month_years.items() if n >= 2)
    if not usual:
        last12 = g[g["date"] > asof - pd.Timedelta(days=365)]
        usual = sorted(set(int(m) for m in last12["date"].dt.month))
    per_year = len(recent) / 3
    freq = ("quarterly" if per_year >= 3.5 else "half-yearly" if per_year >= 1.7 else
            "yearly" if per_year >= 0.8 else "irregular")
    in_usual = float(recent["date"].dt.month.isin(usual).mean()) if len(recent) else 0.0

    score = (35 * last5 / 5 + 10 * last10 / 10 + 10 * in_usual
             + (10 if ttm_hist[5] > 0 and ttm_now >= ttm_hist[5] else 5 if ttm_hist[3] > 0 and ttm_now >= ttm_hist[3] else 0)
             + max(0, 15 - 5 * cuts5))
    return {
        "years_paid_of_5": int(last5), "years_paid_of_10": int(last10), "streak_years": int(streak),
        "cuts_last_5y": int(cuts5), "frequency": freq, "payments_per_year": round(per_year, 1),
        "usual_months": usual, "in_usual_months_pct": round(in_usual * 100),
        "dps_ttm": round(ttm_now, 2),
        "dps_5y_growth_pct": round((ttm_now / ttm_hist[5] - 1) * 100, 1) if ttm_hist[5] > 0 else None,
        "by_year": {int(y): round(float(v), 2) for y, v in yearly.items() if y >= year_end - 9},
        "record_score": round(score, 1),
    }


def backtest_record_score(divs: pd.DataFrame, start_year: int = 2012) -> Dict:
    """At each 30 June: record score from data known then -> paid and not cut over the next 12 months."""
    last = divs["date"].max() if len(divs) else None
    if last is None:
        return {"snapshots": 0}
    rows = []
    for year in range(start_year, last.year + 1):
        t = pd.Timestamp(year=year, month=6, day=30)
        if t + pd.Timedelta(days=365) > last:
            break
        for sym, g in divs.groupby("symbol"):
            p = record_profile(g, t)
            if p is None:
                continue
            nxt = g[(g["date"] > t) & (g["date"] <= t + pd.Timedelta(days=365))]["amount"].sum()
            rows.append((p["record_score"], nxt > 0, nxt >= 0.9 * p["dps_ttm"] if p["dps_ttm"] > 0 else nxt > 0))
    if not rows:
        return {"snapshots": 0}
    a = np.array(rows, dtype=float)
    out = {"snapshots": int(len(a)), "years": f"{start_year}-{last.year - 1}", "buckets": []}
    for lo, hi in ((0, 40), (40, 55), (55, 65), (65, 72), (72, 81)):
        m = (a[:, 0] >= lo) & (a[:, 0] < hi)
        if m.sum() >= 30:
            out["buckets"].append({"record_score_from": lo, "record_score_to": min(hi, 80), "cases": int(m.sum()),
                                   "paid_next_12m_pct": round(float(a[m, 1].mean()) * 100, 1),
                                   "no_cut_next_12m_pct": round(float(a[m, 2].mean()) * 100, 1)})
    top = a[:, 0] >= 72
    out["top_bucket_paid_pct"] = round(float(a[top, 1].mean()) * 100, 1) if top.any() else None
    out["top_bucket_no_cut_pct"] = round(float(a[top, 2].mean()) * 100, 1) if top.any() else None
    out["note"] = "Only companies listed today are in the data, so past reliability is somewhat overstated."
    return out


def next_dates(g: pd.DataFrame, usual: List[int], today: pd.Timestamp) -> List[Dict]:
    """Next expected ex-date per usual month: same day-of-month as last time, amount as last time."""
    out = []
    for m in usual:
        prev = g[g["date"].dt.month == m]
        if prev.empty:
            continue
        last = prev.iloc[-1]
        year = today.year if (m, last["date"].day) >= (today.month, today.day) else today.year + 1
        day = min(int(last["date"].day), 28)
        out.append({"month": m, "month_name": MONTHS[m - 1], "expected_date": f"{year}-{m:02d}-{day:02d}",
                    "expected_amount": round(float(last["amount"]), 2), "last_paid": str(last["date"].date())})
    return sorted(out, key=lambda x: x["expected_date"])


def build_income(fund: Optional[pd.DataFrame], close: pd.DataFrame, cards: Optional[List[Dict]] = None) -> Dict:
    t0 = datetime.now(timezone.utc)
    divs = _dividends(fund)
    divs = divs[divs["symbol"].isin(close.columns)]
    today = close.index[-1]
    price = close.ffill().iloc[-1]
    card_by = {c["symbol"]: c for c in (cards or [])}
    backtest = backtest_record_score(divs)
    profiles = []
    for sym, g in divs.groupby("symbol"):
        p = record_profile(g, today)
        if p is None or pd.isna(price.get(sym)) or price[sym] <= 0:
            continue
        px = float(price[sym])
        yld = p["dps_ttm"] / px
        c = card_by.get(sym) or {}
        cdiv = c.get("dividend") or {}
        payout = cdiv.get("payout_pct")
        cover_ok = (c.get("checks") or {}).get("dividend_cash_covered")
        gov = (c.get("governance") or {}).get("grade")
        verdict_1y = ((c.get("verdicts") or {}).get("1y") or {}).get("verdict")
        now_pts = (5 if yld >= 0.02 else 0) + (5 if yld >= 0.04 else 0) + \
                  (5 if payout is not None and 0 < payout < 80 else 0) + (5 if cover_ok == 1 else 0)
        score = round(min(100.0, p["record_score"] + now_pts), 1)
        if score >= 75 and yld >= 0.02 and gov in ("A", "B") and verdict_1y != "sell":
            income_verdict, label = "income_buy", "STRONG INCOME"
        elif score >= 75:
            income_verdict, label = "reliable_wait", "RELIABLE · WAIT"
        elif score >= 55:
            income_verdict, label = "fairly_regular", "FAIRLY REGULAR"
        else:
            income_verdict, label = "irregular", "IRREGULAR"
        stars = "★" * int(round(score / 20)) + "☆" * (5 - int(round(score / 20)))
        profiles.append({
            "symbol": sym, "as_of": str(today.date()), "rank": 0, "probability": round(score / 100, 3),
            "income_score": score, "income_verdict": income_verdict, "rating_badge": label, "stars": stars,
            "price": round(px, 2), "yield_pct": round(yld * 100, 2),
            "income_per_lakh_rs": round(yld * 100000), "payout_pct": payout, "cash_covered": cover_ok == 1,
            "governance": gov, "verdict_1y": verdict_1y, "next_expected": next_dates(g, p["usual_months"], today),
            **p,
        })
    profiles.sort(key=lambda x: -x["income_score"])
    for i, p in enumerate(profiles, 1):
        p["rank"] = i
    month_counts = {MONTHS[m - 1]: sum(1 for p in profiles if m in p["usual_months"]) for m in range(1, 13)}
    return clean_json({
        "model_key": "dividend_income", "strategy": "income", "horizon_days": 250,
        "description": "Dividend payers by month with payment record, yield and a tested Income Score.",
        "model_type": "dividend_record", "trained_at": t0.isoformat(), "data_end": str(today.date()),
        "edge_verified": bool(backtest.get("top_bucket_paid_pct") and backtest["top_bucket_paid_pct"] >= 90),
        "metrics": {"payers": len(profiles), "month_counts": month_counts, "paying_power_backtest": backtest,
                    "score_parts": {"record": 80, "today": 20},
                    "verdict_rules": {
                        "STRONG INCOME": "score >= 75, yield >= 2%, governance A/B, 1-year verdict not Sell",
                        "RELIABLE · WAIT": "score >= 75 but yield, governance or the 1-year verdict is not there yet",
                        "FAIRLY REGULAR": "score 55-75", "IRREGULAR": "score below 55"}},
        "backtest": None, "folds": None, "predictions": profiles,
    })
