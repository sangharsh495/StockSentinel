"""Dividend income engine: record profile, usual months, next dates, backtest and scoring."""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.quant import income as inc  # noqa: E402


def _divs(sym, dates, amt):
    return pd.DataFrame({"symbol": sym, "date": pd.to_datetime(dates), "amount": amt})


def test_quarterly_regular_payer():
    dates = [f"{y}-{m:02d}-15" for y in range(2015, 2026) for m in (2, 5, 8, 11)]
    p = inc.record_profile(_divs("Q", dates, 2.0), pd.Timestamp("2026-01-31"))
    assert p["frequency"] == "quarterly" and p["usual_months"] == [2, 5, 8, 11]
    assert p["years_paid_of_10"] == 10 and p["cuts_last_5y"] == 0 and p["streak_years"] >= 10
    assert p["record_score"] >= 75


def test_irregular_payer_scores_low_and_lapsed_payer_is_dropped():
    p = inc.record_profile(_divs("I", ["2019-03-01", "2023-09-01", "2025-06-01"], 1.0), pd.Timestamp("2026-01-31"))
    assert p["record_score"] < 55
    assert inc.record_profile(_divs("L", ["2018-03-01", "2019-03-01"], 1.0), pd.Timestamp("2026-01-31")) is None


def test_cut_is_counted():
    dates = [f"{y}-08-10" for y in range(2016, 2026)]
    amts = [5.0] * 8 + [2.0, 2.0]
    p = inc.record_profile(_divs("C", dates, amts), pd.Timestamp("2026-01-31"))
    assert p["cuts_last_5y"] == 1


def test_next_expected_dates_roll_forward():
    g = _divs("Q", ["2025-02-15", "2025-08-20"], [1.0, 3.0])
    nxt = inc.next_dates(g, [2, 8], pd.Timestamp("2025-09-01"))
    assert [n["expected_date"] for n in nxt] == ["2026-02-15", "2026-08-20"]
    assert nxt[1]["expected_amount"] == 3.0


def test_build_income_and_backtest_rank_reliability():
    rows = []
    for k in range(40):           # 40 steady yearly payers, 40 that pay on and off
        rows += [{"symbol": f"S{k}", "kind": "D", "period_end": pd.Timestamp(f"{y}-07-10"), "dividend": 2.0}
                 for y in range(2008, 2026)]
        rows += [{"symbol": f"R{k}", "kind": "D", "period_end": pd.Timestamp(f"{y}-07-10"), "dividend": 2.0}
                 for y in range(2008, 2026) if (y + k) % 3 == 0]
    fund = pd.DataFrame(rows)
    syms = sorted({r["symbol"] for r in rows})
    close = pd.DataFrame(100.0, index=pd.bdate_range("2025-01-01", "2026-01-30"), columns=syms)
    res = inc.build_income(fund, close)
    m = res["metrics"]
    assert m["payers"] > 40 and 40 <= m["month_counts"]["Jul"] <= m["payers"]
    b = m["paying_power_backtest"]["buckets"]
    assert b[-1]["paid_next_12m_pct"] > b[0]["paid_next_12m_pct"]
    top = res["predictions"][0]
    assert top["symbol"].startswith("S") and top["yield_pct"] == 2.0 and top["income_per_lakh_rs"] == 2000
