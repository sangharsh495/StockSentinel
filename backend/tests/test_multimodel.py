"""
Multi-model selection and cross-source data checks.
"""

import os
import sys

import numpy as np
import pandas as pd
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import HistGradientBoostingRegressor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.quant import data_checks  # noqa: E402
from app.quant.ensemble import AVERAGE, LiveEnsemble, multi_walk_forward  # noqa: E402
from app.quant.features import build_dataset, feature_columns  # noqa: E402
from app.quant.validation import evaluate  # noqa: E402
from tests.test_quant import synthetic_prices  # noqa: E402


def _planted():
    p = synthetic_prices(seed=2)
    df = build_dataset(p, 5, extras=False)
    rng = np.random.default_rng(5)
    df["signal"] = df["fwd_excess"].fillna(0) + rng.normal(0, df["fwd_excess"].std(), len(df))
    y = (df["fwd_excess"] > 0).where(df["fwd_excess"].notna())
    rank = df.groupby(level="date")["fwd_excess"].rank(pct=True) - 0.5
    return df, y, rank


def test_selection_prefers_the_model_that_learns_and_stays_honest():
    df, y, rank = _planted()
    cands = {
        "learner": lambda: HistGradientBoostingRegressor(max_iter=60, random_state=0),
        "constant": lambda: DummyRegressor(strategy="mean"),
    }
    wf, rep = multi_walk_forward(df, feature_columns(df), y, 5, cands, fit_target=rank,
                                 min_train_days=300, test_days=100)
    board = {r["model"]: r["auc"] for r in rep["leaderboard"]}
    assert board["learner"] > 0.6 and board["learner"] > board["constant"]
    assert rep["chosen_live"] in ("learner", AVERAGE)
    # The selected track record can't beat the best model in hindsight.
    assert rep["selected_auc"] <= max(board.values()) + 1e-9
    assert evaluate(wf.oos, 5)["edge_verified"] is True


def test_live_ensemble_average_scores_are_ranks():
    df, y, rank = _planted()
    fc = feature_columns(df)
    lab = rank.notna()
    cands = {"a": lambda: DummyRegressor(), "b": lambda: HistGradientBoostingRegressor(max_iter=20)}
    live = LiveEnsemble(cands, AVERAGE).fit(df.loc[lab, fc].values[:2000], rank[lab].values[:2000])
    s = live.score(df[fc].values[:50])
    assert len(s) == 50 and s.min() > 0 and s.max() <= 1


IPOWATCH_HTML = """
<table><tr><th>Company</th><th>GMP*</th><th>Trend</th><th>Price Band</th><th>Est. Gain</th></tr>
<tr><td>BLS Polymers Open</td><td>₹44</td><td>🟢</td><td>₹150</td><td>₹194 (29.33%)</td></tr>
<tr><td>SFC Environmental Technologies</td><td>₹18</td><td>🔴</td><td>₹330</td><td>₹348</td></tr>
</table>
<table><tr><td>Unrelated</td><td>table</td></tr></table>
"""


def test_parse_second_gmp_source():
    rows = data_checks.parse_ipowatch(IPOWATCH_HTML)
    assert [(r["key"], r["gmp"], r["price"]) for r in rows] == [
        ("blspolymers", 44.0, 150.0), ("sfcenvironmentaltechnologies", 18.0, 330.0)]


def test_gmp_consensus_flags_big_relative_gaps():
    assert data_checks.gmp_consensus(50, 150, {"gmp": 44})["gmp_check"] == "agree"
    r = data_checks.gmp_consensus(32, 330, {"gmp": 18})
    assert r["gmp_check"] == "disagree" and r["gmp_consensus"] == 25.0 and "disagree" in r["gmp_warning"]
    assert data_checks.gmp_consensus(50, 150, None)["gmp_check"] == "single_source"


def test_attach_gmp_checks_matches_names(monkeypatch):
    monkeypatch.setattr(data_checks, "fetch_ipowatch",
                        lambda: data_checks.parse_ipowatch(IPOWATCH_HTML))
    rows = [{"name": "BLS Polymers", "gmp": 50.0, "issue_price": 150.0},
            {"name": "SFC Environmental Technologies", "gmp": 32.0, "issue_price": 330.0},
            {"name": "Nobody Else", "gmp": 5.0, "issue_price": 100.0}]
    summary = data_checks.attach_gmp_checks(rows)
    assert [r["gmp_check"] for r in rows] == ["agree", "disagree", "single_source"]
    assert summary["agree"] == 1 and summary["disagree"] == 1 and summary["single_source"] == 1


def test_price_check_flags_mismatches(monkeypatch):
    days = pd.bdate_range("2026-10-20", periods=3)
    close = pd.DataFrame({"AAA": [100, 101, 102.0], "BBB": [50, 50, 50.0]}, index=days)
    nse = pd.Series({"AAA": 102.0, "BBB": 52.0})
    monkeypatch.setattr(data_checks, "fetch_nse_close", lambda day: nse if day == days[-1] else None)
    rep = data_checks.price_check({"Close": close})
    assert rep["compared"] == 2 and rep["agree"] == 1
    assert list(rep["disagree"]) == ["BBB"] and rep["status"] == "warnings"
