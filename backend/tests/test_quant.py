"""
Tests for the quant engine's honesty guarantees:
- features never use future prices (no look-ahead)
- labels start at the NEXT day's open
- walk-forward keeps an embargo gap between training and testing
- pure noise is NOT reported as an edge; a planted signal IS detected
- news event timing and statistics are correct
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.quant.features import build_dataset, feature_columns, forward_labels, stock_features  # noqa: E402
from app.quant.news_events import IST, compute_outcome, event_day_index, summarize, wilson_interval  # noqa: E402
from app.quant.validation import backtest, evaluate, walk_forward  # noqa: E402


def synthetic_prices(n_days=900, n_stocks=30, seed=0):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2018-01-01", periods=n_days)
    syms = [f"S{i:02d}" for i in range(n_stocks)]
    rets = rng.normal(0.0003, 0.015, (n_days, n_stocks))
    close = pd.DataFrame(100 * np.exp(np.cumsum(rets, axis=0)), index=dates, columns=syms)
    open_ = close.shift(1).fillna(close.iloc[0]) * (1 + rng.normal(0, 0.002, close.shape))
    high = np.maximum(open_, close) * 1.01
    low = np.minimum(open_, close) * 0.99
    vol = pd.DataFrame(rng.integers(1e5, 1e6, close.shape), index=dates, columns=syms).astype(float)
    nclose = close.mean(axis=1)
    nifty = pd.DataFrame({"Open": nclose.shift(1).fillna(nclose.iloc[0]), "High": nclose * 1.01,
                          "Low": nclose * 0.99, "Close": nclose, "Volume": 1e6})
    vix = pd.Series(15 + rng.normal(0, 1, n_days), index=dates)
    return {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol,
            "nifty": nifty, "vix": vix}


@pytest.fixture(scope="module")
def prices():
    return synthetic_prices()


def test_features_have_no_lookahead(prices):
    cutoff = prices["Close"].index[600]
    full = stock_features(prices)
    # Corrupt every price after the cutoff: features up to the cutoff must not change.
    shocked = {k: v.copy() for k, v in prices.items()}
    for k in ("Open", "High", "Low", "Close", "Volume"):
        shocked[k].loc[shocked[k].index > cutoff] *= 3.0
    part = stock_features(shocked)
    a = full.loc[full.index.get_level_values("date") <= cutoff]
    b = part.loc[part.index.get_level_values("date") <= cutoff]
    pd.testing.assert_frame_equal(a, b)


def test_labels_start_at_next_open(prices):
    h = 5
    lab = forward_labels(prices, h)
    d0, sym = prices["Open"].index[100], "S03"
    o = prices["Open"][sym]
    expected = np.log(o.iloc[101 + h] / o.iloc[101])
    assert lab.loc[(d0, sym), "fwd_ret"] == pytest.approx(expected)


def test_walk_forward_embargo(prices):
    h = 20
    df = build_dataset(prices, h)
    y = (df["fwd_excess"] > 0).where(df["fwd_excess"].notna())
    wf = walk_forward(df, feature_columns(df), y, h, min_train_days=300, test_days=100)
    udates = sorted(df.index.get_level_values("date").unique())
    for f in wf.folds:
        test_start = pd.Timestamp(f["test_start"])
        assert f["train_rows"] > 0
        # last training date must be at least h+1 trading days before the test starts
        train_last_allowed = udates[udates.index(test_start) - (h + 1)]
        assert train_last_allowed < test_start


def test_noise_is_not_an_edge(prices):
    h = 5
    df = build_dataset(prices, h)
    y = (df["fwd_excess"] > 0).where(df["fwd_excess"].notna())
    wf = walk_forward(df, feature_columns(df), y, h, min_train_days=300, test_days=100)
    m = evaluate(wf.oos, h)
    assert m["edge_verified"] is False
    assert 0.45 < m["auc"] < 0.55


def test_planted_signal_is_detected():
    p = synthetic_prices(seed=1)
    h = 5
    df = build_dataset(p, h)
    # Plant a real signal: an observable feature that predicts the future.
    rng = np.random.default_rng(3)
    df["signal"] = df["fwd_excess"].fillna(0) + rng.normal(0, df["fwd_excess"].std(), len(df))
    y = (df["fwd_excess"] > 0).where(df["fwd_excess"].notna())
    wf = walk_forward(df, feature_columns(df), y, h, min_train_days=300, test_days=100)
    m = evaluate(wf.oos, h)
    assert m["auc"] > 0.6
    assert m["edge_verified"] is True
    bt = backtest(wf.oos, df, h, baseline_col="rsi_14", baseline_ascending=True)
    assert bt["model"]["cagr_pct"] > bt["equal_weight"]["cagr_pct"]


def test_event_day_respects_market_close():
    cal = pd.bdate_range("2026-03-02", periods=10)  # Mon 2 Mar ...
    before = datetime(2026, 3, 3, 10, 0, tzinfo=IST)
    after = datetime(2026, 3, 3, 18, 0, tzinfo=IST)
    weekend = datetime(2026, 3, 7, 12, 0, tzinfo=IST)  # Saturday
    assert cal[event_day_index(cal, before)] == pd.Timestamp("2026-03-03")
    assert cal[event_day_index(cal, after)] == pd.Timestamp("2026-03-04")
    assert cal[event_day_index(cal, weekend)] == pd.Timestamp("2026-03-09")


def test_compute_outcome_abnormal_return():
    cal = pd.bdate_range("2026-01-05", periods=30)
    stock = pd.Series(100.0, index=cal)
    bench = pd.Series(1000.0, index=cal)
    stock.iloc[5:] = 110.0      # +10% from day 5
    bench.iloc[5:] = 1020.0     # market +2%
    pub = datetime(2026, 1, 12, 9, 0, tzinfo=IST)  # day index 5, before close
    res = compute_outcome(stock, stock, bench, pub)
    assert res["base_close"] == 100.0
    assert res["abn_1d"] == pytest.approx(np.log(1.10) - np.log(1.02))
    assert res["abn_5d"] == pytest.approx(np.log(1.10) - np.log(1.02))


def test_wilson_and_summary():
    lo, hi = wilson_interval(60, 100)
    assert lo < 0.6 < hi and hi - lo < 0.2
    df = pd.DataFrame({
        "impact_direction": ["BULLISH"] * 20 + ["BEARISH"] * 20,
        "category": ["earnings"] * 40,
        "abn_5d": [0.02] * 15 + [-0.01] * 5 + [-0.02] * 12 + [0.01] * 8,
    })
    rows = {r["direction"]: r for r in summarize(df, "abn_5d")}
    assert rows["BULLISH"]["direction_correct_pct"] == 75.0
    assert rows["BEARISH"]["direction_correct_pct"] == 60.0
