"""Multibagger Radar: state-space tools, statistics, point-in-time fundamentals and the zoo on noise."""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.quant import multibagger as mb  # noqa: E402
from app.quant.fundamentals import point_in_time  # noqa: E402
from app.quant.state_space import GaussianHMM, kalman_trend  # noqa: E402


def test_kalman_finds_real_trend_and_ignores_noise():
    rng = np.random.default_rng(0)
    days = pd.bdate_range("2021-01-01", periods=600)
    noise = rng.normal(0, 0.02, (600, 100))
    drift = np.r_[np.full(50, 0.6 / 250), np.zeros(50)]       # 50 stocks +60%/yr, 50 flat
    close = pd.DataFrame(100 * np.exp(np.cumsum(noise + drift, 0)), index=days)
    k = kalman_trend(close)
    v = k["velocity"].iloc[-1]
    assert v[:50].mean() > v[50:].mean() + 0.3
    assert abs(v[50:].mean()) < 0.2
    assert k["snr"].iloc[-1][:50].mean() > k["snr"].iloc[-1][50:].mean()


def test_kalman_is_forward_only():
    rng = np.random.default_rng(1)
    days = pd.bdate_range("2021-01-01", periods=300)
    close = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, 0.02, (300, 3)), 0)), index=days)
    a = kalman_trend(close)["velocity"].iloc[:200]
    c2 = close.copy()
    c2.iloc[200:] *= 3
    b = kalman_trend(c2)["velocity"].iloc[:200]
    pd.testing.assert_frame_equal(a, b)


def test_hmm_separates_two_regimes():
    rng = np.random.default_rng(2)
    X = np.r_[rng.normal(-1, 0.3, (100, 2)), rng.normal(1.5, 0.3, (100, 2)), rng.normal(-1, 0.3, (100, 2))]
    h = GaussianHMM(2, n_iter=50).fit(X)
    s = h.filtered(X).argmax(1)
    assert (s[:100] == s[0]).mean() > 0.95 and (s[100:200] != s[0]).mean() > 0.95


def test_statistics():
    assert mb.bh_fdr({"a": 0.001, "b": 0.02, "c": 0.5, "d": 0.9}, 0.1) == ["a", "b"]
    assert mb.newey_west_t(np.r_[np.ones(20), np.ones(20) * 1.2], 3) > 10
    assert abs(mb.newey_west_t(np.random.default_rng(3).normal(0, 1, 2000), 5)) < 3.5


def test_fundamentals_are_point_in_time():
    fund = pd.DataFrame([
        {"symbol": "A", "kind": "A", "period_end": pd.Timestamp("2022-03-31"),
         "available": pd.Timestamp("2022-06-14"), "revenue": 100.0, "net_income": 10.0, "shares": 10.0},
        {"symbol": "A", "kind": "A", "period_end": pd.Timestamp("2023-03-31"),
         "available": pd.Timestamp("2023-06-14"), "revenue": 200.0, "net_income": 30.0, "shares": 10.0},
    ])
    for c in ["op_income", "debt", "equity", "ocf", "fcf"]:
        fund[c] = np.nan
    days = pd.bdate_range("2023-01-02", "2023-12-29")
    close = pd.DataFrame({"A": 50.0}, index=days)
    pit = point_in_time(fund, days, close)
    g = pit["rev_growth"]["A"]
    assert g.loc[:"2023-06-13"].isna().all()                  # not known before filing deadline
    assert abs(g.loc["2023-06-14"] - np.log(2)) < 1e-9
    assert abs(pit["earnings_yield"]["A"].loc["2023-07-03"] - 30 / 500) < 1e-9


def _market(n_days=900, n=150, seed=4):
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2021-01-01", periods=n_days)
    lr = rng.standard_t(4, (n_days, n)) * rng.uniform(0.01, 0.04, n) / np.sqrt(2)
    close = pd.DataFrame(100 * np.exp(np.cumsum(lr, 0)), index=days, columns=[f"S{i:03d}" for i in range(n)])
    W = {"Close": close, "Open": close.shift(1).fillna(close.iloc[0]), "High": close * 1.01, "Low": close * 0.99,
         "TurnoverLacs": close * 0 + 500.0, "DelivPct": close * 0 + 40.0 + rng.normal(0, 5, close.shape)}
    return W


def test_zoo_on_pure_noise_finds_no_edge():
    W = _market()
    cfgs = mb.all_configs(families=["logistic", "rank_sum"], targets=["double_1y", "x15_6m"],
                          views=["momentum", "flow"])
    res = mb.run_multibagger(W, None, n_bags=1, configs=cfgs, top_n=10)
    m = res["metrics"]
    assert res["model_key"] == "multibagger_radar" and len(res["predictions"]) == 10
    assert m["honest_stack"]["months"] >= 6
    assert not res["edge_verified"]
    p = res["predictions"][0]
    assert p["stage"] in {"discovery", "confirmation", "momentum", "exit_risk"} and p["rank"] == 1
