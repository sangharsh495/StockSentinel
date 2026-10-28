"""
Multi-model engine: several algorithms per task, one honest winner.

For every task we walk-forward test each candidate algorithm on the same
unseen periods, plus an "average" of all of them. Then a selection rule
picks, for each test period, the candidate that had done best on the
EARLIER periods only. The track record of that rule (not of the luckiest
candidate in hindsight) is what the app reports, so picking the best model
does not quietly inflate the accuracy.
"""

import logging
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import (
    HistGradientBoostingClassifier, HistGradientBoostingRegressor,
    RandomForestClassifier, RandomForestRegressor,
)
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from app.quant.validation import (
    WalkForwardResult, _r, _sequential_calibration, predict_score, walk_forward,
)

logger = logging.getLogger(__name__)

AVERAGE = "average"


# ---------------------------------------------------------------------------
# Candidate algorithms
# ---------------------------------------------------------------------------
def stock_candidates() -> Dict[str, Callable]:
    """Rank-regression candidates for the cross-sectional stock models."""
    return {
        "gradient_boosting": lambda: HistGradientBoostingRegressor(
            max_iter=200, learning_rate=0.03, max_leaf_nodes=15, min_samples_leaf=2000,
            l2_regularization=5.0, max_features=0.7, random_state=7),
        "random_forest": lambda: make_pipeline(
            SimpleImputer(strategy="median"),
            RandomForestRegressor(n_estimators=80, max_samples=0.15, min_samples_leaf=400,
                                  max_features=0.3, n_jobs=-1, random_state=7)),
        "ridge_linear": lambda: make_pipeline(
            SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=300.0)),
    }


def market_candidates() -> Dict[str, Callable]:
    """Classifiers for the single-series market direction model (small data)."""
    return {
        "logistic": lambda: make_pipeline(
            SimpleImputer(strategy="median"), StandardScaler(), LogisticRegression(C=0.1, max_iter=500)),
        "gradient_boosting": lambda: HistGradientBoostingClassifier(
            max_iter=100, learning_rate=0.03, max_leaf_nodes=7, min_samples_leaf=100,
            l2_regularization=5.0, random_state=7),
        "random_forest": lambda: make_pipeline(
            SimpleImputer(strategy="median"),
            RandomForestClassifier(n_estimators=200, min_samples_leaf=40, max_features=0.5,
                                   n_jobs=-1, random_state=7)),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _normalise(oos: pd.DataFrame, cross_sectional: bool) -> pd.Series:
    """
    Put every candidate's scores on one scale so they can be averaged:
    stock models -> rank within the day; single-series classifiers already
    output probabilities, which are averaged as they are.
    """
    if not cross_sectional:
        return oos["prob_raw"]
    return oos["prob_raw"].groupby(oos.index.get_level_values("date")).rank(pct=True)


def _fold_auc(oos: pd.DataFrame, col: str) -> pd.Series:
    def auc(g):
        return roc_auc_score(g["y"], g[col]) if g["y"].nunique() == 2 else np.nan
    return oos.groupby("fold").apply(auc)


# ---------------------------------------------------------------------------
# Multi-model walk-forward
# ---------------------------------------------------------------------------
def multi_walk_forward(
    df: pd.DataFrame,
    feature_cols: List[str],
    target: pd.Series,
    horizon: int,
    candidates: Dict[str, Callable],
    cross_sectional: bool = True,
    **wf_kwargs,
) -> Tuple[WalkForwardResult, Dict]:
    """
    Returns (result of the honest selection rule, report). The report holds
    a leaderboard of every candidate and how often each one was chosen.
    """
    runs: Dict[str, WalkForwardResult] = {}
    for name, factory in candidates.items():
        logger.info(f"Walk-forward candidate: {name}")
        runs[name] = walk_forward(df, feature_cols, target, horizon, model_factory=factory,
                                  cross_sectional=cross_sectional, **wf_kwargs)
    names = list(runs)
    base = runs[names[0]].oos
    if base.empty:
        return runs[names[0]], {"leaderboard": [], "chosen_live": names[0]}

    # Same rows, same folds for every candidate (same data and splits).
    table = base[["fwd_ret", "fwd_excess", "y", "fold"]].copy()
    for n in names:
        o = runs[n].oos
        table[n] = _normalise(o, cross_sectional).reindex(table.index).values
    table[AVERAGE] = table[names].mean(axis=1)
    options = names + [AVERAGE]

    # Periods where the outcome never varied (e.g. market up every day) have
    # no AUC; they are skipped when comparing models.
    fold_auc = pd.DataFrame({n: _fold_auc(table, n) for n in options}).dropna(how="all")

    # Honest selection: fold k uses whichever option had the best mean AUC
    # on folds < k. The first fold has no history, so it uses the average.
    chosen_per_fold = {}
    for k in sorted(table["fold"].unique()):
        past = fold_auc.loc[fold_auc.index < k].mean()
        chosen_per_fold[k] = past.idxmax() if past.notna().any() else AVERAGE
    sel = pd.Series(np.nan, index=table.index)
    for k, n in chosen_per_fold.items():
        m = table["fold"] == k
        sel[m] = table.loc[m, n]

    oos = table[["fwd_ret", "fwd_excess", "y", "fold"]].copy()
    oos["prob_raw"] = sel.values
    oos["score"] = (oos.groupby(level="date")["prob_raw"].rank(pct=True)
                    if cross_sectional else oos["prob_raw"])
    oos["prob"] = _sequential_calibration(oos)

    overall = {n: roc_auc_score(table["y"], table[n]) for n in options}
    sel_auc = roc_auc_score(oos["y"], oos["prob_raw"])
    # For live predictions use the option with the best record on ALL folds.
    chosen_live = max(overall, key=overall.get)
    counts = pd.Series(list(chosen_per_fold.values())).value_counts().to_dict()
    leaderboard = sorted(
        [{"model": n, "auc": _r(overall[n]), "folds_won": int((fold_auc.idxmax(axis=1) == n).sum()),
          "times_selected": int(counts.get(n, 0))} for n in options],
        key=lambda r: -(r["auc"] or 0))
    report = {
        "leaderboard": leaderboard,
        "selection_rule": "best average AUC on earlier test periods only",
        "selected_auc": _r(sel_auc),
        "chosen_live": chosen_live,
        "candidates": options,
    }
    logger.info(f"Leaderboard: {[(r['model'], r['auc']) for r in leaderboard]} -> live: {chosen_live}")
    return WalkForwardResult(oos=oos, folds=runs[names[0]].folds), report


class LiveEnsemble:
    """Fits the chosen option (one model, or all of them averaged) for today's scores."""

    def __init__(self, candidates: Dict[str, Callable], chosen: str):
        self.candidates, self.chosen = candidates, chosen
        self.models = {}

    def fit(self, X, y):
        names = list(self.candidates) if self.chosen == AVERAGE else [self.chosen]
        for n in names:
            self.models[n] = self.candidates[n]().fit(X, y)
        return self

    def score(self, X, group: Optional[np.ndarray] = None) -> np.ndarray:
        """Average of per-model 0..1 ranks (within `group` if given) — same scale as testing."""
        cols = []
        for m in self.models.values():
            s = pd.Series(predict_score(m, X))
            cols.append(s.groupby(group).rank(pct=True).values if group is not None else s.rank(pct=True).values)
        return np.mean(cols, axis=0)

    def raw(self, X) -> np.ndarray:
        """Unscaled score (single-series tasks: calibrator expects the raw scale)."""
        return np.mean([predict_score(m, X) for m in self.models.values()], axis=0)
