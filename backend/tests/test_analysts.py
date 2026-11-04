"""Analyst panel: structure, honest grading on noise, and voting."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.quant import analysts as A  # noqa: E402
from app.quant.multibagger import month_ends  # noqa: E402
from app.quant.report_card import build_card_panel, check_matrix  # noqa: E402
from tests.test_multibagger import _market  # noqa: E402


def test_full_panel_size():
    names = {a.key for a in A.all_analysts()}
    assert len(names) == 4 * 4 * 12 * 9 == 1728


def test_grade_and_vote_on_noise(monkeypatch):
    monkeypatch.setattr(A, "SEGMENTS", ["all", "large"])
    monkeypatch.setattr(A, "SPECIALITIES", ["trend", "momentum", "all_checks", "raw_numbers"])
    monkeypatch.setattr(A, "FAMILIES", ["logistic_weak", "rank_sum", "boost_shallow"])
    monkeypatch.setattr(A, "HORIZONS", {"1w": 5, "1m": 21})
    W = _market(n_days=900, n=120, seed=11)
    dates = month_ends(W["Close"].index)
    panel = build_card_panel(W, None, dates + [W["Close"].index[-1]])
    M = check_matrix(panel)
    g = A.grade(panel, M, first="2022-07-01")
    m = g["metrics"]
    assert m["analysts"] == 2 * 4 * 3 * 2 and m["fits"] > 0
    assert set(m["weights"]) == {a.key for a in A.all_analysts()}
    # pure noise: the consensus must not claim a tested edge
    assert not any(t.get("verified") for t in m["consensus_tests"].values())
    v = A.vote(panel, M, g)
    assert v["model_key"] == "analyst_consensus"
    for p in v["predictions"][:5]:
        for h, c in p["consensus"].items():
            assert c["verdict"] == "hold" or c["verified"]
