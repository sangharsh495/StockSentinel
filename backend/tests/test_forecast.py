"""
Range engine, corporate-action adjustment, scanner, scorecard and live status.
"""

import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.quant.live_watch import IST, classify, market_open  # noqa: E402
from app.quant.market_data import adjust_for_corporate_actions  # noqa: E402
from app.quant.ranges import backtest_coverage, todays_ranges  # noqa: E402
from app.quant.scanner import compute_signals, run_scanner, score_past_picks  # noqa: E402


def _random_walk(n_days=900, n=40, seed=0, vol=0.02):
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2021-01-01", periods=n_days)
    # each stock its own volatility, changing over time (regimes)
    v = vol * rng.uniform(0.5, 2, n) * (1 + 0.5 * np.sin(np.arange(n_days) / 90))[:, None]
    lr = rng.standard_t(5, (n_days, n)) * v / np.sqrt(5 / 3)
    close = pd.DataFrame(100 * np.exp(np.cumsum(lr, axis=0)), index=days,
                         columns=[f"S{i:02d}" for i in range(n)])
    return close


def test_conformal_ranges_keep_their_promise_on_fresh_data():
    close = _random_walk()
    for h in (1, 5):
        r80 = backtest_coverage(close, h, 0.8)
        r95 = backtest_coverage(close, h, 0.95)
        assert abs(r80["coverage"] - 0.80) < 0.03, r80
        assert abs(r95["coverage"] - 0.95) < 0.02, r95


def test_todays_ranges_contain_last_price_and_widen_with_horizon():
    close = _random_walk()
    r = todays_ranges(close, ["S00"])["S00"]
    p = close["S00"].iloc[-1]
    for h in ("1d", "5d", "20d"):
        lo, hi = r[h]["p80"]
        assert lo < p < hi
        lo95, hi95 = r[h]["p95"]
        assert lo95 < lo and hi95 > hi
    assert (r["20d"]["p80"][1] - r["20d"]["p80"][0]) > (r["1d"]["p80"][1] - r["1d"]["p80"][0])


def _wide(close, deliv=40.0):
    open_ = close.shift(1).fillna(close.iloc[0])
    return {"Open": open_, "High": close * 1.01, "Low": close * 0.99, "Close": close.copy(),
            "PrevClose": close.shift(1), "Volume": close * 0 + 1e5,
            "TurnoverLacs": close * 0 + 2000.0, "DelivPct": close * 0 + deliv}


def test_split_is_detected_and_reversed():
    close = _random_walk(n_days=300, n=3)
    raw = close.copy()
    d = raw.index[200]
    raw.loc[d:, "S01"] = raw.loc[d:, "S01"] / 2          # 1:1 bonus: price halves
    w = _wide(raw)
    w["Open"].loc[d, "S01"] = raw.loc[d, "S01"]           # opens at the new, halved level
    adj = adjust_for_corporate_actions(w)
    ret = adj["Close"]["S01"].pct_change(fill_method=None)
    assert ret.abs().max() < 0.2                           # no fake -50% crash
    assert adj["Actions"].loc[d, "S01"] == 2.0
    # a 20% move (price band) is NOT treated as a corporate action
    assert (adj["Actions"]["S00"] == 1).all() and (adj["Actions"]["S02"] == 1).all()


def test_scanner_runs_and_scores_picks():
    close = _random_walk(n_days=700, n=60, seed=3)
    w = _wide(close)
    out = run_scanner(w)
    assert out["model_key"] == "market_scanner"
    assert out["metrics"]["liquid_universe"] == 60
    picks = out["predictions"]
    assert all(p["category"] in out["metrics"]["category_track_record"] for p in picks)
    # on pure noise no setup should look like a significant edge
    for name, rec in out["metrics"]["category_track_record"].items():
        five = rec.get("5d", {})
        if five.get("events", 0) >= 30:
            assert abs(five["success_pct"] - 50) < 6, (name, five)
    # scorecard on a past day
    log = [{"date": close.index[600], "symbol": "S01", "category": "momentum_leader"},
           {"date": close.index[-2], "symbol": "S02", "category": "momentum_leader"}]  # too recent
    card = score_past_picks(w, log)
    assert card["status"] == "ok" and card["scored_picks"] == 1


def test_live_status_helpers():
    assert market_open(datetime(2026, 10, 29, 10, 0, tzinfo=IST))
    assert not market_open(datetime(2026, 10, 31, 10, 0, tzinfo=IST))    # Saturday
    assert not market_open(datetime(2026, 10, 29, 16, 0, tzinfo=IST))    # after close
    assert classify(105, 95, 104) == "above_range"
    assert classify(94, 95, 104) == "below_range"
    assert classify(100, 95, 104) == "inside_range"


def test_signals_are_point_in_time():
    close = _random_walk(n_days=400, n=20, seed=5)
    w = _wide(close)
    cut = close.index[300]
    a = compute_signals(w)["rsi_14"].loc[:cut]
    w2 = {k: v.copy() for k, v in w.items()}
    for k in ("Open", "High", "Low", "Close"):
        w2[k].loc[w2[k].index > cut] *= 3
    b = compute_signals(w2)["rsi_14"].loc[:cut]
    pd.testing.assert_frame_equal(a, b)
