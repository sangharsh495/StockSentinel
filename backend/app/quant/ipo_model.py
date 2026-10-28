"""
IPO listing-gain model.

Question: "If I get an allotment, what will the listing-day open be
versus the issue price?" Uses only facts known before listing:
final GMP and its trend, total subscription, issue size and structure
(fresh issue vs OFS, anchor and retail quotas), valuation and financials,
promoter dilution, market mood, and how the last 10 IPOs listed.

Walk-forward tested by listing date. The benchmark it must beat is the
simplest rule everyone uses: "listing gain = GMP / issue price".
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from sklearn.ensemble import (
    HistGradientBoostingClassifier, HistGradientBoostingRegressor,
    RandomForestClassifier, RandomForestRegressor,
)
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import mean_absolute_error, roc_auc_score

from app.quant.validation import _r

logger = logging.getLogger(__name__)

FEATURES = [
    "gmp_pct", "gmp_first_pct", "gmp_change_pct", "gmp_range_pct", "gmp_pos_sessions_pct",
    "gmp_slope_pct", "log_sub", "log_size", "log_mcap", "ofs_share", "fresh_share",
    "pe_ratio", "post_pe_ratio", "price_to_book", "roe", "roce", "debt_equity", "pat_margin",
    "promoter_dilution", "promoter_post", "anchor_share", "retail_share", "company_age",
    "mkt_ret_20", "mkt_ret_60", "vix", "ipo_heat_10", "ipo_heat_10_sub", "gmp_vs_heat",
]


def _f(x):
    return pd.to_numeric(x, errors="coerce")


def build_frame(rows: List[Dict], prices: Optional[Dict[str, pd.DataFrame]] = None,
                history: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """
    rows: IPO dicts from the scraper. history: past listed IPOs used for
    the 'IPO heat' features (defaults to rows themselves).
    """
    df = pd.DataFrame(rows).copy()
    if df.empty:
        return df

    def col(name):  # a missing column reads as all-blank, never crashes
        return _f(df[name]) if name in df else pd.Series(np.nan, index=df.index)

    price = _f(df["issue_price"])
    gmp = col("gmp").fillna(col("gmp_latest"))  # live/final GMP first if "gmp_latest" in df else col("gmp")
    df["gmp_pct"] = gmp / price * 100
    df["gmp_first_pct"] = col("gmp_first") / price * 100
    df["gmp_change_pct"] = (gmp - col("gmp_first")) / price * 100
    df["gmp_range_pct"] = col("gmp_range") / price * 100
    df["gmp_pos_sessions_pct"] = col("gmp_pos_sessions_pct")
    df["gmp_slope_pct"] = col("gmp_slope") / price * 100
    df["log_sub"] = np.log1p(col("subscription_x"))
    df["log_size"] = np.log1p(col("issue_size_cr"))
    df["log_mcap"] = np.log1p(col("market_cap_cr"))
    tot = col("total_issue_amt")
    df["ofs_share"] = col("ofs_amt") / tot
    df["fresh_share"] = col("fresh_issue_amt") / tot
    for c in ("pe_ratio", "post_pe_ratio", "price_to_book", "roe", "roce", "debt_equity", "pat_margin", "promoter_post"):
        df[c] = col(c)
    df["promoter_dilution"] = col("promoter_pre") - col("promoter_post")
    shares = col("total_shares")
    df["anchor_share"] = col("anchor_shares") / (shares + col("anchor_shares").fillna(0))
    df["retail_share"] = col("retail_shares") / shares
    df["listing_date"] = pd.to_datetime(df["listing_date"]) if "listing_date" in df else pd.NaT
    close = pd.to_datetime(df["issue_close_date"]) if "issue_close_date" in df else pd.Series(pd.NaT, index=df.index)
    df["decision_date"] = close.fillna(df["listing_date"] - pd.Timedelta(days=3))
    df["company_age"] = df["listing_date"].dt.year - col("incorporated")

    # Market mood at the decision date (subscription close), from the Nifty
    if prices is not None:
        n = prices["nifty"]["Close"].dropna()
        vix = prices["vix"].ffill()
        pos = n.index.searchsorted(df["decision_date"].values, side="right") - 1
        ok = pos >= 60
        r20 = np.full(len(df), np.nan)
        r60 = np.full(len(df), np.nan)
        vv = np.full(len(df), np.nan)
        r20[ok] = np.log(n.values[pos[ok]] / n.values[pos[ok] - 20]) * 100
        r60[ok] = np.log(n.values[pos[ok]] / n.values[pos[ok] - 60]) * 100
        vv[ok] = vix.reindex(n.index).values[pos[ok]]
        df["mkt_ret_20"], df["mkt_ret_60"], df["vix"] = r20, r60, vv

    # IPO heat: average listing gain / subscription of the last 10 IPOs that
    # LISTED BEFORE this one's subscription closed (strictly past).
    h = (history if history is not None else df)
    h = pd.DataFrame({"ld": pd.to_datetime(h["listing_date"]), "g": _f(h["listing_gain_pct"]),
                      "s": np.log1p(_f(h["subscription_x"]))}).dropna(subset=["ld", "g"]).sort_values("ld")
    heat, heat_s = [], []
    for d in df["decision_date"]:
        past = h[h["ld"] < d].tail(10)
        heat.append(past["g"].mean() if len(past) >= 5 else np.nan)
        heat_s.append(past["s"].mean() if len(past) >= 5 else np.nan)
    df["ipo_heat_10"], df["ipo_heat_10_sub"] = heat, heat_s
    df["gmp_vs_heat"] = df["gmp_pct"] - df["ipo_heat_10"]
    for c in FEATURES:
        if c not in df:
            df[c] = np.nan
        df[c] = _f(df[c]).replace([np.inf, -np.inf], np.nan)
    df["listing_gain_pct"] = _f(df["listing_gain_pct"]) if "listing_gain_pct" in df else np.nan
    return df


def _reg():
    # Learns only the CORRECTION to the GMP-implied gain (target = actual - GMP%),
    # so with weak evidence it stays close to GMP instead of relearning it.
    return HistGradientBoostingRegressor(loss="absolute_error", max_iter=120, learning_rate=0.03,
                                         max_leaf_nodes=6, min_samples_leaf=25, l2_regularization=5.0,
                                         random_state=7)


PROB_FEATURES = ["gmp_pct", "log_sub", "gmp_vs_heat", "mkt_ret_20"]
AVERAGE = "average"


class _ZeroCorrection:
    """'GMP alone' as a candidate: predicts no correction to the GMP-implied gain."""

    def fit(self, X, y):
        return self

    def predict(self, X):
        return np.zeros(len(X))


def _pipe(model):
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), model)


# Candidate algorithms: (factory, feature list)
REG_CANDIDATES = {
    "gradient_boosting": (_reg, FEATURES),
    "random_forest": (lambda: _pipe(RandomForestRegressor(
        n_estimators=300, min_samples_leaf=15, max_features=0.4, random_state=7, n_jobs=-1)), FEATURES),
    "ridge_linear": (lambda: _pipe(Ridge(alpha=30.0)), FEATURES),
    "gmp_only": (_ZeroCorrection, FEATURES),
}
CLF_CANDIDATES = {
    "logistic": (lambda: _pipe(LogisticRegression(C=0.5, max_iter=500)), PROB_FEATURES),
    "gradient_boosting": (lambda: HistGradientBoostingClassifier(
        max_iter=150, learning_rate=0.04, max_leaf_nodes=6, min_samples_leaf=20,
        l2_regularization=3.0, random_state=7), FEATURES),
    "random_forest": (lambda: _pipe(RandomForestClassifier(
        n_estimators=300, min_samples_leaf=10, max_features=0.4, random_state=7, n_jobs=-1)), FEATURES),
}


def _clf():
    return CLF_CANDIDATES["logistic"][0]()


def _usable(train: pd.DataFrame, cols: List[str]) -> List[str]:
    """Skip inputs that are completely blank in the training data (e.g. no market data)."""
    return [c for c in cols if train[c].notna().any()]


def _all_predictions(train: pd.DataFrame, test: pd.DataFrame) -> Dict[str, np.ndarray]:
    """Every candidate's prediction for `test`, trained on `train`, plus the averages."""
    out = {}
    target = (train["listing_gain_pct"] - train["gmp_pct"]).values
    up = (train["listing_gain_pct"] > 0).astype(int).values
    for n, (f, cols) in REG_CANDIDATES.items():
        c = _usable(train, cols)
        out[f"gain_{n}"] = test["gmp_pct"].values + f().fit(train[c].values, target).predict(test[c].values)
    for n, (f, cols) in CLF_CANDIDATES.items():
        c = _usable(train, cols)
        out[f"prob_{n}"] = f().fit(train[c].values, up).predict_proba(test[c].values)[:, 1]
    out[f"gain_{AVERAGE}"] = np.mean([out[f"gain_{n}"] for n in REG_CANDIDATES], axis=0)
    out[f"prob_{AVERAGE}"] = np.mean([out[f"prob_{n}"] for n in CLF_CANDIDATES], axis=0)
    return out


def _fit_predict(train: pd.DataFrame, test: pd.DataFrame, reg_name: str = "gradient_boosting",
                 clf_name: str = "logistic"):
    preds = _all_predictions(train, test)
    return preds[f"gain_{reg_name}"], preds[f"prob_{clf_name}"], None, None


def walk_forward_ipo(df: pd.DataFrame, min_train: int = 120, step: int = 30) -> pd.DataFrame:
    """
    Train on IPOs listed before each block, predict the next block — for
    every candidate. Then, block by block, use the candidate that had the
    lowest error (gain) / best Brier score (probability) on EARLIER blocks.
    Columns pred_gain / prob_gain hold that honest selection; the report
    is in .attrs["multi_model"].
    """
    d = df.dropna(subset=["listing_gain_pct", "gmp_pct"]).sort_values("listing_date").reset_index(drop=True)
    out = []
    for start in range(min_train, len(d), step):
        test = d.iloc[start:start + step]
        # train only on IPOs that had already listed when the test IPOs' books closed
        train = d[d["listing_date"] < test["decision_date"].min()]
        if len(train) < min_train:
            continue
        part = test[["name", "listing_date", "listing_gain_pct", "gmp_pct"]].copy()
        for k, v in _all_predictions(train, test).items():
            part[k] = v
        part["fold"] = len(out)
        out.append(part)
    if not out:
        return pd.DataFrame()
    oos = pd.concat(out)
    y, up = oos["listing_gain_pct"], (oos["listing_gain_pct"] > 0).astype(int)
    regs = list(REG_CANDIDATES) + [AVERAGE]
    clfs = list(CLF_CANDIDATES) + [AVERAGE]
    mae = pd.DataFrame({n: (oos[f"gain_{n}"] - y).abs().groupby(oos["fold"]).mean() for n in regs})
    brier = pd.DataFrame({n: ((oos[f"prob_{n}"] - up) ** 2).groupby(oos["fold"]).mean() for n in clfs})

    oos["pred_gain"], oos["prob_gain"] = np.nan, np.nan
    picks = []
    for k in sorted(oos["fold"].unique()):
        rn = mae[mae.index < k].mean().idxmin() if k > 0 else AVERAGE
        cn = brier[brier.index < k].mean().idxmin() if k > 0 else AVERAGE
        m = oos["fold"] == k
        oos.loc[m, "pred_gain"] = oos.loc[m, f"gain_{rn}"]
        oos.loc[m, "prob_gain"] = oos.loc[m, f"prob_{cn}"]
        picks.append((rn, cn))

    def board(table, lower_better, metric):
        overall = {n: float(((oos[f"{'gain' if metric == 'mae' else 'prob'}_{n}"] -
                              (y if metric == 'mae' else up)).abs() if metric == "mae" else
                             (oos[f"prob_{n}"] - up) ** 2).mean()) for n in table.columns}
        wins = (table.idxmin(axis=1) if lower_better else table.idxmax(axis=1)).value_counts()
        rows = [{"model": n, metric: _r(v, 4), "folds_won": int(wins.get(n, 0))} for n, v in overall.items()]
        return sorted(rows, key=lambda r: r[metric]), min(overall, key=overall.get)

    gain_board, gain_live = board(mae, True, "mae")
    prob_board, prob_live = board(brier, True, "brier")
    oos.attrs["multi_model"] = {
        "gain_leaderboard": gain_board, "probability_leaderboard": prob_board,
        "gain_chosen_live": gain_live, "probability_chosen_live": prob_live,
        "selection_rule": "lowest error on earlier IPO blocks only",
        "times_selected": {"gain": pd.Series([p[0] for p in picks]).value_counts().to_dict(),
                           "probability": pd.Series([p[1] for p in picks]).value_counts().to_dict()},
    }
    return oos


def evaluate_ipo(oos: pd.DataFrame) -> Dict:
    y = oos["listing_gain_pct"].values
    up = (y > 0).astype(int)
    gmp = oos["gmp_pct"].values
    m = {
        "oos_ipos": int(len(oos)),
        "oos_start": str(pd.Timestamp(oos["listing_date"].min()).date()),
        "oos_end": str(pd.Timestamp(oos["listing_date"].max()).date()),
        "share_listed_positive": _r(up.mean()),
        "model_mae_pct": _r(mean_absolute_error(y, oos["pred_gain"]), 2),
        "gmp_rule_mae_pct": _r(mean_absolute_error(y, gmp), 2),
        "model_auc_positive_listing": _r(roc_auc_score(up, oos["prob_gain"])) if up.min() != up.max() else None,
        "gmp_rule_auc_positive_listing": _r(roc_auc_score(up, gmp)) if up.min() != up.max() else None,
        "model_direction_accuracy": _r(((oos["prob_gain"] >= 0.5) == up).mean()),
        "gmp_rule_direction_accuracy": _r(((gmp > 0) == up).mean()),
        "model_corr": _r(np.corrcoef(oos["pred_gain"], y)[0, 1]),
        "gmp_rule_corr": _r(np.corrcoef(np.nan_to_num(gmp), y)[0, 1]),
    }
    # Bootstrap: how often does the model's error beat the GMP rule's error?
    rng = np.random.default_rng(0)
    e_m, e_g = np.abs(y - oos["pred_gain"].values), np.abs(y - gmp)
    wins = [(e_g[s].mean() - e_m[s].mean()) > 0 for s in (rng.integers(0, len(y), len(y)) for _ in range(1000))]
    m["model_beats_gmp_mae_bootstrap_pct"] = _r(np.mean(wins) * 100, 1)

    # Applying strategy: apply only when the model says P(gain) >= 0.6
    for name, sel in (("model_p60", oos["prob_gain"] >= 0.6), ("gmp_positive", gmp > 0), ("all", np.ones(len(y), bool))):
        g = y[np.asarray(sel)]
        m[f"apply_{name}"] = {"ipos": int(len(g)), "avg_gain_pct": _r(g.mean(), 2) if len(g) else None,
                              "win_rate_pct": _r((g > 0).mean() * 100, 1) if len(g) else None}

    # Calibration of P(gain>0)
    b = np.clip((oos["prob_gain"].values * 5).astype(int), 0, 4)
    cal = pd.DataFrame({"b": b, "p": oos["prob_gain"].values, "y": up}).groupby("b").agg(
        predicted=("p", "mean"), actual=("y", "mean"), n=("y", "size"))
    m["calibration"] = [{"predicted": _r(r.predicted, 3), "actual": _r(r.actual, 3), "n": int(r.n)}
                        for r in cal.itertuples() if r.n >= 10]
    m["edge_verified"] = bool(
        m["model_mae_pct"] < m["gmp_rule_mae_pct"] and m["model_beats_gmp_mae_bootstrap_pct"] >= 90
    )
    return m


def train_ipo_model(history_rows: List[Dict], current_rows: List[Dict],
                    prices: Optional[Dict[str, pd.DataFrame]] = None) -> Dict:
    hist = build_frame(history_rows, prices)
    hist = hist.dropna(subset=["listing_gain_pct", "gmp_pct"])
    if len(hist) < 150:
        return {"model_key": "ipo_listing", "status": "collecting_data", "samples": int(len(hist)),
                "edge_verified": False}
    oos = walk_forward_ipo(hist)
    mm = dict(oos.attrs.get("multi_model", {}))
    metrics = evaluate_ipo(oos)

    # Confidence tiers: how past IPOs at each confidence level really listed
    tiers = []
    for lo_p, hi_p, label in ((0.95, 1.01, "95%+"), (0.9, 0.95, "90-95%"), (0.8, 0.9, "80-90%"),
                              (0.6, 0.8, "60-80%"), (0.3, 0.6, "30-60%"), (0.0, 0.3, "under 30%")):
        t = oos[(oos["prob_gain"] >= lo_p) & (oos["prob_gain"] < hi_p)]
        tiers.append({"tier": label, "lo": lo_p, "hi": hi_p, "ipos": int(len(t)),
                      "listed_positive_pct": _r((t["listing_gain_pct"] > 0).mean() * 100, 1) if len(t) else None,
                      "avg_listing_gain_pct": _r(t["listing_gain_pct"].mean(), 1) if len(t) else None})
    metrics["confidence_tiers"] = tiers

    # Residual spread per predicted-gain band -> honest range for new IPOs
    oos = oos.assign(resid=oos["listing_gain_pct"] - oos["pred_gain"])
    lo_q, hi_q = np.percentile(oos["resid"], [10, 90])

    preds = []
    if current_rows:
        cur = build_frame(current_rows, prices, history=hist)
        cur = cur.dropna(subset=["gmp_pct"])
        if not cur.empty:
            pg, pp, _, _ = _fit_predict(hist, cur, mm.get("gain_chosen_live", "gradient_boosting"),
                                        mm.get("probability_chosen_live", "logistic"))
            for (_, r), g, p in zip(cur.iterrows(), pg, pp):
                use_model = metrics["edge_verified"]
                exp = float(g) if use_model else float(r["gmp_pct"])
                preds.append({
                    "symbol": f"IPO{int(r['ig_id'])}", "ig_id": int(r["ig_id"]), "name": r["name"],
                    "as_of": str(datetime.now(timezone.utc).date()),
                    "issue_price": _r(r.get("issue_price"), 2), "gmp": _r(r.get("gmp"), 2),
                    "gmp_implied_gain_pct": _r(r["gmp_pct"], 2),
                    "model_expected_gain_pct": _r(g, 2),
                    "expected_gain_pct": _r(exp, 2),
                    "expected_range_pct": [_r(exp + lo_q, 1), _r(exp + hi_q, 1)],
                    "probability": _r(p, 4),
                    "source": "model" if use_model else "gmp_rule",
                    "subscription_x": _r(r.get("subscription_x"), 2),
                    "subscription_known": bool(pd.notna(r.get("subscription_x"))),
                    "note": None if pd.notna(r.get("subscription_x")) else
                    "Bidding not started: estimate uses GMP only and is less reliable.",
                    "issue_close_date": str(r["decision_date"].date()) if pd.notna(r.get("decision_date")) else None,
                    "listing_date": str(r["listing_date"].date()) if pd.notna(r.get("listing_date")) else None,
                    "verdict": _verdict(p, exp),
                    "gmp_check": r.get("gmp_check"),
                    "gmp_sources": r.get("gmp_sources") if isinstance(r.get("gmp_sources"), dict) else None,
                    "gmp_gap_pct_points": _r(r.get("gmp_gap_pct_points"), 2),
                    "track_record_at_this_confidence": next(
                        ({k: t[k] for k in ("tier", "ipos", "listed_positive_pct", "avg_listing_gain_pct")}
                         for t in tiers if t["lo"] <= p < t["hi"]), None),
                })
                if r.get("gmp_check") == "disagree":
                    preds[-1]["note"] = r.get("gmp_warning")
                    if preds[-1]["verdict"].startswith("Strong apply"):
                        preds[-1]["verdict"] = "Apply (GMP sources disagree)"
    preds.sort(key=lambda x: -(x["expected_gain_pct"] or -999))
    for i, p in enumerate(preds, 1):
        p["rank"] = i
    imp = _importance(hist)
    return {
        "model_key": "ipo_listing", "strategy": "ipo", "horizon_days": 0,
        "description": "Listing-day open vs issue price for mainboard IPOs. Benchmark: GMP-implied gain.",
        "model_type": f"multi_model:{mm.get('gain_chosen_live')}+{mm.get('probability_chosen_live')}",
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "data_end": str(pd.Timestamp(hist["listing_date"].max()).date()),
        "edge_verified": metrics["edge_verified"], "metrics": {**metrics, "top_drivers": imp, "multi_model": mm},
        "backtest": None, "folds": None, "predictions": preds, "samples": int(len(hist)),
    }


def _verdict(p: float, exp: float) -> str:
    if p >= 0.75 and exp >= 15:
        return "Strong apply (listing gain likely)"
    if p >= 0.6 and exp >= 5:
        return "Apply (moderate gain likely)"
    if p >= 0.45:
        return "Neutral (coin-flip listing)"
    return "Avoid (listing loss risk)"


def _importance(hist: pd.DataFrame) -> List[Dict]:
    """Which inputs matter most (permutation importance on a holdout of the latest 20%)."""
    from sklearn.inspection import permutation_importance
    h = hist.sort_values("listing_date")
    cut = int(len(h) * 0.8)
    tr, te = h.iloc[:cut], h.iloc[cut:]
    fc = _usable(tr, FEATURES)
    m = _reg().fit(tr[fc].values, (tr["listing_gain_pct"] - tr["gmp_pct"]).values)
    pi = permutation_importance(m, te[fc].values, (te["listing_gain_pct"] - te["gmp_pct"]).values,
                                n_repeats=10, random_state=0, scoring="neg_mean_absolute_error")
    order = np.argsort(-pi.importances_mean)[:8]
    # How much each input improves the correction to GMP (error increase when shuffled)
    return [{"feature": fc[i], "mae_increase_pct": _r(pi.importances_mean[i], 2)} for i in order]
