"""
Whole-market scanner: every liquid NSE stock, every night.

1. Universe: all EQ stocks whose 20-day median turnover is at least ₹5 Cr
   and price at least ₹20 (about 800–1,200 stocks), from NSE's official files.
2. Categories (setups traders and investors actually use):
   - breakout              near 52-week high on a volume surge
   - momentum_leader       top 10% 12-month momentum, above 200-day average
   - oversold_in_uptrend   RSI-14 under 35 while above the 200-day average
   - delivery_accumulation delivery % jumps 15+ points above its 60-day norm, price up
   - unusual_move          today's move is outside its own 80% range, on 2x volume
   - falling_knife (avoid) below 200-day average and down 20%+ in 3 months
3. Every category gets a measured track record over all stocks since 2021:
   when the setup fired, how often did the stock beat the median liquid
   stock over the next 5 and 20 days (entry at the next day's open)?
4. Tonight's watchlist: up to 20 stocks, best category track records get
   the most slots, each with guaranteed-coverage price ranges.
Stocks with an unexplained 35%+ one-day move in the last year (possible
unadjusted demerger/bonus) are flagged and left out of the watchlist.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List

import numpy as np
import pandas as pd

from app.quant.ranges import todays_ranges
from app.quant.validation import _r

logger = logging.getLogger(__name__)

MIN_TURNOVER_CR = 5.0
MIN_PRICE = 20.0
WATCHLIST_SIZE = 20
CATEGORIES = {
    "breakout": "Within 2% of the 52-week high on 1.5x+ normal volume",
    "momentum_leader": "Top 10% 12-month momentum (skipping the last month), above the 200-day average",
    "oversold_in_uptrend": "RSI-14 below 35 while still above the 200-day average",
    "delivery_accumulation": "Delivery % 15+ points above its 60-day norm with the price rising",
    "unusual_move": "Today's move broke outside its own 80% range, on 2x+ volume",
    "falling_knife": "AVOID: below the 200-day average and down 20%+ in 3 months",
}
AVOID = {"falling_knife"}


def _rsi(close: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def compute_signals(W: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    """Point-in-time features and category flags, all as (date x symbol) frames."""
    c, o, v = W["Close"], W["Open"], W["Volume"]
    turnover_cr = W["TurnoverLacs"].astype(float) / 100
    lr = np.log(c).diff()
    f: Dict[str, pd.DataFrame] = {}
    f["liquid"] = (turnover_cr.rolling(20, min_periods=15).median() >= MIN_TURNOVER_CR) & (c >= MIN_PRICE)
    f["suspect"] = (lr.abs() > np.log(1.35)).rolling(250, min_periods=1).max().astype(bool)
    f["ret_1"] = lr
    f["ret_5"] = np.log(c / c.shift(5))
    f["ret_20"] = np.log(c / c.shift(20))
    f["ret_60"] = np.log(c / c.shift(60))
    f["mom_12_1"] = np.log(c.shift(20) / c.shift(250))
    f["vol_20"] = lr.rolling(20, min_periods=15).std()
    f["sma200"] = c.rolling(200, min_periods=150).mean()
    f["dist_52w_high"] = c / c.rolling(250, min_periods=200).max() - 1
    f["rsi_14"] = _rsi(c)
    f["vol_surge"] = v / v.rolling(20, min_periods=15).mean().shift(1)
    dp = W["DelivPct"].astype(float)
    f["deliv_jump"] = dp.rolling(5, min_periods=3).mean() - dp.rolling(60, min_periods=30).mean().shift(5)
    above200 = c > f["sma200"]
    liq = f["liquid"] & ~f["suspect"]
    mom_rank = f["mom_12_1"].where(liq).rank(axis=1, pct=True)
    # 1-day 80% band from recent volatility (same scale the range engine uses)
    sig1 = (0.6 * f["vol_20"] + 0.4 * lr.rolling(60, min_periods=40).std())
    f["move_z"] = lr.abs() / sig1

    cats = {
        "breakout": liq & (f["dist_52w_high"] >= -0.02) & (f["vol_surge"] >= 1.5) & (f["ret_5"] > 0),
        "momentum_leader": liq & (mom_rank >= 0.9) & above200 & (f["ret_20"] > 0),
        "oversold_in_uptrend": liq & (f["rsi_14"] < 35) & above200,
        "delivery_accumulation": liq & (f["deliv_jump"] >= 15) & (f["ret_5"] > 0),
        "unusual_move": liq & (f["move_z"] > 1.28) & (f["vol_surge"] >= 2),
        "falling_knife": liq & ~above200 & (f["ret_60"] < np.log(0.8)),
    }
    strength = {
        "breakout": f["vol_surge"], "momentum_leader": mom_rank,
        "oversold_in_uptrend": 35 - f["rsi_14"], "delivery_accumulation": f["deliv_jump"],
        "unusual_move": f["move_z"], "falling_knife": -f["ret_60"],
    }
    f["cats"], f["strength"] = cats, strength
    return f


def category_track_record(W: Dict[str, pd.DataFrame], f: Dict, horizons=(5, 20)) -> Dict:
    """How each setup did historically vs the median liquid stock (entry at next open)."""
    c, o = W["Close"], W["Open"]
    liq = f["liquid"] & ~f["suspect"]
    out = {}
    for h in horizons:
        fwd = np.log(c.shift(-h) / o.shift(-1)).where(liq)
        med = fwd.median(axis=1)
        excess = fwd.sub(med, axis=0)
        valid_dates = c.index[250:-h - 1]
        for name, flag in f["cats"].items():
            ev = flag.loc[valid_dates] & excess.loc[valid_dates].notna()
            x = excess.loc[valid_dates].where(ev)
            n = int(ev.values.sum())
            rec = out.setdefault(name, {"description": CATEGORIES[name]})
            if n < 30:
                rec[f"{h}d"] = {"events": n, "status": "too_few_events"}
                continue
            # one number per date (avg excess of that day's events), every h-th date -> no overlap
            per_day = x.mean(axis=1).dropna()
            no = per_day.iloc[::h]
            t = no.mean() / (no.std(ddof=1) / np.sqrt(len(no))) if len(no) > 5 and no.std() > 0 else np.nan
            hit = float((x.values[ev.values] > 0).mean())
            beat = hit if name not in AVOID else 1 - hit
            rec[f"{h}d"] = {
                "events": n, "event_days": int(len(per_day)),
                "avg_excess_return_pct": _r(np.nanmean(x.values) * 100, 3),
                "beat_median_stock_pct": _r(hit * 100, 1),
                "success_pct": _r(beat * 100, 1),     # for 'avoid' = underperformed
                "t_stat": _r(t, 2),
                "significant": bool(np.isfinite(t) and abs(t) > 2),
            }
    return out


def build_watchlist(W: Dict[str, pd.DataFrame], f: Dict, track: Dict) -> List[Dict]:
    last = W["Close"].index[-1]
    c = W["Close"]
    # Only setups that beat the median stock historically get watchlist slots,
    # more slots for better records. Others are still counted and reported.
    def quality(name):
        r = track.get(name, {}).get("5d", {})
        return r.get("success_pct") or 0
    eligible = [k for k in f["cats"] if k not in AVOID and quality(k) > 50
                and (track[k]["5d"].get("avg_excess_return_pct") or 0) > 0]
    cats = sorted(eligible, key=quality, reverse=True)
    weights = np.array([quality(k) - 50 for k in cats]) if cats else np.array([])
    alloc = np.floor(weights / weights.sum() * WATCHLIST_SIZE).astype(int) if cats else []
    slots = {k: max(2, int(a)) for k, a in zip(cats, alloc)}
    picks, used = [], set()
    candidates = {}
    for name in set(list(slots) + list(AVOID)):
        flag = f["cats"][name].loc[last]
        st = f["strength"][name].loc[last].where(flag).dropna().sort_values(ascending=False)
        candidates[name] = list(st.index)
    for name, n in slots.items():
        for sym in candidates[name]:
            if len([p for p in picks if p["category"] == name]) >= n or len(picks) >= WATCHLIST_SIZE:
                break
            if sym in used:
                continue
            used.add(sym)
            picks.append({"symbol": sym, "category": name})
    # fill any empty slots from the best categories
    for name in cats:
        for sym in candidates[name]:
            if len(picks) >= WATCHLIST_SIZE:
                break
            if sym not in used:
                used.add(sym)
                picks.append({"symbol": sym, "category": name})
    avoid = [{"symbol": s, "category": "falling_knife"} for s in candidates["falling_knife"][:5]]

    syms = [p["symbol"] for p in picks + avoid]
    liquid_cols = f["liquid"].loc[last][f["liquid"].loc[last]].index
    ranges = todays_ranges(c[liquid_cols.union(syms)].iloc[-400:], syms)
    out = []
    for rank, p in enumerate(picks + avoid, 1):
        s, name = p["symbol"], p["category"]
        rec = track.get(name, {})
        out.append({
            "symbol": s, "as_of": str(last.date()), "rank": rank, "category": name,
            "category_description": CATEGORIES[name], "avoid": name in AVOID,
            "category_track_record": {h: {k: rec.get(h, {}).get(k) for k in
                                          ("success_pct", "avg_excess_return_pct", "events", "significant")}
                                      for h in ("5d", "20d")},
            "last_close": _r(c[s].iloc[-1], 2),
            "signals": {
                "ret_1d_pct": _r(f["ret_1"][s].iloc[-1] * 100, 2), "ret_20d_pct": _r(f["ret_20"][s].iloc[-1] * 100, 2),
                "rsi_14": _r(f["rsi_14"][s].iloc[-1], 1), "volume_vs_avg": _r(f["vol_surge"][s].iloc[-1], 2),
                "dist_52w_high_pct": _r(f["dist_52w_high"][s].iloc[-1] * 100, 1),
                "delivery_jump_pts": _r(f["deliv_jump"][s].iloc[-1], 1),
            },
            "ranges": ranges.get(s, {}),
        })
    return out


def run_scanner(W: Dict[str, pd.DataFrame]) -> Dict:
    f = compute_signals(W)
    track = category_track_record(W, f)
    picks = build_watchlist(W, f, track)
    last = W["Close"].index[-1]
    liq = f["liquid"].loc[last]
    counts = {k: int(v.loc[last].sum()) for k, v in f["cats"].items()}
    any_edge = any((v.get("5d") or {}).get("significant") and (v.get("5d") or {}).get("avg_excess_return_pct", 0) > 0
                   for k, v in track.items() if k not in AVOID)
    return {
        "model_key": "market_scanner", "strategy": "scanner", "horizon_days": 5,
        "description": (f"Nightly scan of {int(liq.sum())} liquid NSE stocks (of {int(W['Close'].iloc[-1].notna().sum())} listed): "
                        "20-stock watchlist by setup, each setup with its measured track record."),
        "model_type": "rule_scan_with_event_study",
        "trained_at": datetime.now(timezone.utc).isoformat(), "data_end": str(last.date()),
        "edge_verified": bool(any_edge),
        "metrics": {"category_track_record": track, "today_counts": counts,
                    "watchlist_categories": [k for k in f["cats"] if k not in AVOID
                                             and (track.get(k, {}).get("5d", {}).get("success_pct") or 0) > 50
                                             and (track.get(k, {}).get("5d", {}).get("avg_excess_return_pct") or 0) > 0],
                    "liquid_universe": int(liq.sum()), "listed": int(W["Close"].iloc[-1].notna().sum())},
        "backtest": None, "folds": None, "predictions": picks,
    }


def score_past_picks(W: Dict[str, pd.DataFrame], log: List[Dict], h: int = 5) -> Dict:
    """
    Live scorecard: for every watchlist pick saved on an earlier night, did
    it beat the median liquid stock over the next h days (entry next open)?
    Only picks whose h days have fully passed are scored.
    """
    c, o = W["Close"], W["Open"]
    liq = (W["TurnoverLacs"].astype(float) / 100).rolling(20, min_periods=15).median() >= MIN_TURNOVER_CR
    idx = {d: i for i, d in enumerate(c.index)}
    rows = []
    for r in log:
        d = pd.Timestamp(r["date"])
        if d not in idx or r["symbol"] not in c.columns:
            continue
        i = idx[d]
        if i + h >= len(c) or i + 1 >= len(c):
            continue
        entry, exit_ = o.iloc[i + 1], c.iloc[i + h]
        fwd = np.log(exit_ / entry).where(liq.iloc[i])
        med = fwd.median()
        x = fwd.get(r["symbol"])
        if x is None or not np.isfinite(x):
            continue
        avoid = r["category"] in AVOID
        rows.append({"date": d, "category": r["category"], "excess": float(x - med),
                     "right": bool((x < med) if avoid else (x > med))})
    if not rows:
        return {"status": "collecting", "scored_picks": 0,
                "note": f"Picks are scored {h} trading days after they are made."}
    df = pd.DataFrame(rows)
    recent = df[df["date"] >= df["date"].max() - pd.Timedelta(days=90)]
    by_cat = df.groupby("category").agg(n=("right", "size"), right=("right", "mean"), excess=("excess", "mean"))
    return {
        "status": "ok", "horizon_days": h, "scored_picks": int(len(df)),
        "right_pct_all": _r(df["right"].mean() * 100, 1),
        "right_pct_last_90d": _r(recent["right"].mean() * 100, 1),
        "avg_excess_pct": _r(df["excess"].mean() * 100, 3),
        "by_category": {k: {"picks": int(v.n), "right_pct": _r(v.right * 100, 1),
                            "avg_excess_pct": _r(v.excess * 100, 3)} for k, v in by_cat.iterrows()},
        "first_pick": str(df["date"].min().date()), "last_scored": str(df["date"].max().date()),
    }
