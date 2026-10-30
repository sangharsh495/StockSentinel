"""Stock Report Card: checks, dividends, verdict rules and governance."""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.quant import report_card as rc  # noqa: E402
from tests.test_multibagger import _market  # noqa: E402


def test_at_least_50_distinct_checks():
    assert len(rc.CHECKS) >= 50
    assert len(set(rc.CHECK_IDS)) == len(rc.CHECK_IDS)
    assert {"governance", "dividend", "trend", "quality", "valuation"} <= {c[1] for c in rc.CHECKS}


def test_rule_handles_missing_values():
    df = pd.DataFrame({"x": [0.5, 2.0, np.nan, 1.2]})
    out = rc._rule("x", lambda v: v < 1, lambda v: v > 1.5)(df)
    assert list(out) == [1, -1, 0, 0]


def test_dividend_frames_trailing_sum_and_streak():
    idx = pd.bdate_range("2019-01-01", periods=1500)
    fund = pd.DataFrame([{"symbol": "A", "kind": "D", "period_end": idx[k], "available": idx[k], "dividend": 2.0}
                         for k in (100, 350, 600, 850, 1100, 1350)])
    d = rc.dividend_frames(fund, idx, ["A", "B"])
    assert d["dps_ttm"]["A"].iloc[1360] == 2.0 and d["dps_ttm"]["B"].iloc[-1] == 0
    assert d["div_years"]["A"].iloc[1360] >= 4


def test_report_cards_run_and_unverified_periods_hold():
    W = _market(n_days=800, n=120, seed=7)
    res = rc.run_report_cards(W, None, top_n=5)
    m = res["metrics"]
    assert res["model_key"] == "stock_report_card" and m["check_count"] == len(rc.CHECKS)
    assert set(m["horizon_tests"]) == set(rc.HORIZONS)
    card = res["predictions"][0]
    assert set(card["verdicts"]) == set(rc.HORIZONS) and len(card["checks"]) == len(rc.CHECKS)
    for h, t in m["horizon_tests"].items():
        if not t["verified"]:
            assert all(p["verdicts"][h]["verdict"] == "hold" for p in res["predictions"])


def test_governance_grade():
    row = pd.Series({c: 0 for c in rc.CHECK_IDS})
    assert rc.governance_grade(row)[0] == "not enough data"
    for c in ("no_dilution", "no_circuit_games", "low_debt", "moderate_debt", "cash_backed_profit"):
        row[c] = 1
    assert rc.governance_grade(row)[0] == "A"


def test_live_verdict_ledger_scores_after_the_period():
    W = _market(n_days=400, n=60, seed=9)
    days = W["Close"].index
    rows = [{"date": days[300], "symbol": "S001", "horizon": "1w", "verdict": "buy"},
            {"date": days[300], "symbol": "S002", "horizon": "1w", "verdict": "sell"},
            {"date": days[-2], "symbol": "S003", "horizon": "1w", "verdict": "buy"},      # too recent
            {"date": days[300], "symbol": "S004", "horizon": "1y", "verdict": "buy"}]     # too recent for 1 year
    card = rc.score_verdict_log(W, rows)
    assert card["status"] == "ok" and card["logged_calls"] == 4
    assert card["1w"]["buy"]["scored"] == 1 and card["1w"]["sell"]["scored"] == 1 and "1y" not in card
