"""
Stock Report Card: 57 checks per stock, each one tested on history, rolled
into a Buy / Hold / Sell verdict for four holding periods.

How it stays honest
1. Every check is a plain pass / fail rule (e.g. "debt below half of equity").
2. Each check is TESTED: on every month-end since 2021, do the stocks that
   pass it go on to beat the median liquid stock (total return, dividends
   included) over 1 week, 1 month, 3 months and 1 year? Newey-West t-stats
   and a Benjamini-Hochberg false-discovery filter decide which checks
   really mattered, so lucky ones are not trusted.
3. A verdict model per holding period weighs the checks (logistic
   regression), trained walk-forward: only on months whose outcome was
   known at the time, then scored on the months after.
4. Buy needs a predicted chance of beating the market of at least 55%,
   Sell at most 45%. A holding period counts as "verified" only if, on
   unseen months, Buy picks beat Sell picks after 0.4% trading costs with
   t > 2. Where it is not verified, every verdict there is Hold.
5. Governance and dividend checks are shown for every stock; the best
   dividend list is backtested the same way.
"""

import logging
import math
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.quant.fundamentals import point_in_time
from app.quant.multibagger import (MIN_PRICE, MIN_TURNOVER_LACS, bh_fdr, clean_json, daily_features,
                                   month_ends, newey_west_t, red_flags, stage_of, _norm_sf)

logger = logging.getLogger(__name__)

HORIZONS = {"1w": 5, "1m": 21, "3m": 63, "1y": 250}
CAL_GAP = {5: 12, 21: 35, 63: 100, 250: 380}       # calendar days until an outcome is surely known
COST = 0.004                                       # round-trip trading cost
BUY_P, SELL_P = 0.55, 0.45


# --------------------------------------------------------------------- features

def dividend_frames(fund: Optional[pd.DataFrame], index: pd.DatetimeIndex, columns) -> Dict[str, pd.DataFrame]:
    """Daily dividend-per-share by ex-date, trailing-12-month DPS, and years paid in the last five."""
    dps = pd.DataFrame(0.0, index=index, columns=columns)
    if fund is not None and len(fund) and "dividend" in fund:
        d = fund[(fund["kind"] == "D") & fund["symbol"].isin(columns)].dropna(subset=["dividend"])
        if len(d):
            pos = index.searchsorted(pd.DatetimeIndex(d["period_end"]))
            ok = pos < len(index)
            d = d[ok].assign(day=index[pos[ok]])
            agg = d.groupby(["day", "symbol"])["dividend"].sum().unstack()
            dps = dps.add(agg.reindex(index=index, columns=columns).fillna(0.0), fill_value=0.0)
    ttm = dps.rolling(250, min_periods=1).sum()
    years = sum((ttm.shift(250 * k) > 0).astype(float) for k in range(5))
    return {"dps": dps, "dps_ttm": ttm, "dps_prev": ttm.shift(250), "div_years": years}


def extra_daily(W: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    C = W["Close"]
    r = C.pct_change(fill_method=None)
    ma50, ma200 = C.rolling(50, min_periods=40).mean(), C.rolling(200, min_periods=150).mean()
    gain = r.clip(lower=0).rolling(14).mean()
    loss = (-r.clip(upper=0)).rolling(14).mean()
    rsi = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    roll_max = C.rolling(250, min_periods=200).max()
    dd = C / C.rolling(250, min_periods=1).max() - 1
    return {
        "ret_5d": C / C.shift(5) - 1, "ret_63d": C / C.shift(63) - 1,
        "above_50dma": C / ma50, "ma50_over_200": ma50 / ma200, "rsi14": rsi,
        "dist_52w_low": C / C.rolling(250, min_periods=200).min(),
        "max_dd_1y": dd.rolling(250, min_periods=200).min(),
        "down_vol60": r.where(r < 0).rolling(60, min_periods=20).std(),
        "min_ret_20d": r.rolling(20).min(), "up_days_60": (r > 0).astype(float).where(r.notna()).rolling(60).mean(),
        "_roll_max": roll_max,
    }


# --------------------------------------------------------------------- checks

def _rule(col: str, good: Callable, bad: Optional[Callable] = None):
    """+1 when good(x), -1 when bad(x) (or not good, if bad is None), 0 when the value is missing."""
    def f(df: pd.DataFrame) -> np.ndarray:
        x = df[col].values.astype(float)
        with np.errstate(invalid="ignore"):
            g = good(x)
            b = bad(x) if bad is not None else ~g
        out = np.where(g, 1, np.where(b, -1, 0))
        return np.where(np.isnan(x), 0, out).astype(np.int8)
    return f


LOG = math.log
CHECKS: List[Tuple[str, str, str, Callable]] = [
    # --- trend
    ("above_200dma", "trend", "Price above its 200-day average", _rule("above_200dma", lambda x: x > 1)),
    ("above_50dma", "trend", "Price above its 50-day average", _rule("above_50dma", lambda x: x > 1)),
    ("golden_cross", "trend", "50-day average above 200-day average", _rule("ma50_over_200", lambda x: x > 1)),
    ("kalman_up", "trend", "Kalman trend pointing up", _rule("kalman_velocity", lambda x: x > 0)),
    ("kalman_certain", "trend", "Kalman trend clearly up (signal/noise > 2)",
     _rule("kalman_snr", lambda x: x > 2, lambda x: x < -2)),
    ("kalman_accel", "trend", "Trend speeding up", _rule("kalman_accel", lambda x: x > 0)),
    ("near_high", "trend", "Within 10% of its 52-week high", _rule("near_52w_high", lambda x: x >= 0.9, lambda x: x < 0.7)),
    ("off_lows", "trend", "At least 20% above its 52-week low", _rule("dist_52w_low", lambda x: x > 1.2, lambda x: x < 1.05)),
    # --- momentum
    ("mom12_positive", "momentum", "Up over the last 12 months (skipping last month)", _rule("mom12_1", lambda x: x > 0)),
    ("mom12_strong", "momentum", "Up more than 30% over 12 months", _rule("mom12_1", lambda x: x > 0.3, lambda x: x < 0)),
    ("mom6_positive", "momentum", "Up over 6 months", _rule("mom6", lambda x: x > 0)),
    ("mom3_positive", "momentum", "Up over 3 months", _rule("ret_63d", lambda x: x > 0)),
    ("month_calm", "momentum", "Last month's move not extreme (-10% to +15%)",
     _rule("mom1", lambda x: (x > -0.1) & (x < 0.15))),
    ("not_overbought", "momentum", "RSI below 75 (not overbought)", _rule("rsi14", lambda x: x < 75, lambda x: x >= 80)),
    ("not_oversold", "momentum", "RSI above 30 (not in free fall)", _rule("rsi14", lambda x: x > 30, lambda x: x < 25)),
    ("week_no_spike", "momentum", "No spike over the last week (< +10%)", _rule("ret_5d", lambda x: x < 0.1, lambda x: x > 0.15)),
    # --- risk
    ("low_volatility", "risk", "Daily volatility below 2.5%", _rule("vol60", lambda x: x < 0.025, lambda x: x > 0.04)),
    ("low_downside", "risk", "Down days are mild (downside volatility < 2%)",
     _rule("down_vol60", lambda x: x < 0.02, lambda x: x > 0.035)),
    ("small_drawdown", "risk", "Worst fall in the past year less than 30%",
     _rule("max_dd_1y", lambda x: x > -0.3, lambda x: x < -0.5)),
    ("no_crash_day", "risk", "No single-day fall worse than 8% this month", _rule("min_ret_20d", lambda x: x > -0.08)),
    ("no_jump_day", "risk", "No single-day jump above 12% this month", _rule("max_ret_20d", lambda x: x < 0.12)),
    ("not_already_5x", "risk", "Not already up 5x in a year", _rule("ret_1y", lambda x: x < 4)),
    # --- liquidity and flow
    ("liquid", "flow", "Trades more than Rs 5 crore a day", _rule("size_liq", lambda x: x > LOG(500), lambda x: x < LOG(100))),
    ("turnover_rising", "flow", "Trading activity rising (60d vs 1y, +20%)", _rule("turnover_growth", lambda x: x > 1.2)),
    ("delivery_rising", "flow", "Delivery % rising (genuine buying)", _rule("deliv_change", lambda x: x > 3)),
    ("high_delivery", "flow", "Delivery above 50% of volume", _rule("deliv_level", lambda x: x > 50, lambda x: x < 30)),
    ("steady_buying", "flow", "Up on more than 55% of days (60d)", _rule("up_days_60", lambda x: x > 0.55, lambda x: x < 0.45)),
    # --- growth
    ("revenue_growing", "growth", "Revenue grew last year", _rule("rev_growth", lambda x: x > 0)),
    ("revenue_fast", "growth", "Revenue grew more than 15%", _rule("rev_growth", lambda x: x > LOG(1.15), lambda x: x < 0)),
    ("revenue_accelerating", "growth", "Revenue growth speeding up", _rule("rev_accel", lambda x: x > 0)),
    ("profit_growing", "growth", "Profit grew last year", _rule("profit_growth", lambda x: x > 0)),
    ("turned_profitable", "growth", "Turned profitable this year", _rule("turned_profitable", lambda x: x > 0.5, lambda x: x < -1)),
    ("margin_expanding", "growth", "Operating margin expanding", _rule("margin_change", lambda x: x > 0)),
    # --- quality
    ("profitable", "quality", "Company is profitable", _rule("earnings_yield", lambda x: x > 0)),
    ("good_margin", "quality", "Operating margin above 15%", _rule("op_margin", lambda x: x > 0.15, lambda x: x < 0.05)),
    ("high_roe", "quality", "Return on equity above 15%", _rule("roe", lambda x: x > 0.15, lambda x: x < 0.05)),
    ("cash_backed_profit", "quality", "Profits backed by operating cash (OCF > 80% of profit)",
     _rule("cash_conversion", lambda x: x > 0.8, lambda x: x < 0)),
    ("fcf_positive", "quality", "Positive free cash flow", _rule("fcf_positive", lambda x: x > 0.5)),
    # --- balance sheet
    ("low_debt", "balance_sheet", "Debt below half of equity", _rule("debt_to_equity", lambda x: x < 0.5, lambda x: x > 2)),
    ("moderate_debt", "balance_sheet", "Debt below equity", _rule("debt_to_equity", lambda x: x < 1, lambda x: x > 1.5)),
    # --- governance
    ("no_dilution", "governance", "No meaningful new shares issued (< 2% a year)",
     _rule("dilution", lambda x: x < 0.02, lambda x: x > 0.1)),
    ("no_circuit_games", "governance", "Price rarely locked at circuit limits",
     _rule("locked_days", lambda x: x < 0.05, lambda x: x > 0.15)),
    ("no_big_profit_drop", "governance", "No big profit collapse (> 10% of sales)", _rule("profit_growth", lambda x: x > -0.1)),
    ("genuine_holders", "governance", "Delivery above 35% (not mostly intraday churn)", _rule("deliv_level", lambda x: x > 35, lambda x: x < 20)),
    ("no_pump_spikes", "governance", "No pump-like one-day spike above 20% this month", _rule("max_ret_20d", lambda x: x < 0.2)),
    ("not_micro_cap", "governance", "Market value above Rs 1,000 crore",
     _rule("log_mcap", lambda x: x > LOG(1e10), lambda x: x < LOG(2e9))),
    # --- valuation
    ("pe_reasonable", "valuation", "P/E below 25", _rule("earnings_yield", lambda x: x > 0.04, lambda x: x < 0.015)),
    ("pe_cheap", "valuation", "P/E below 14", _rule("earnings_yield", lambda x: x > 0.07)),
    ("ps_reasonable", "valuation", "Price/sales below 4", _rule("sales_yield", lambda x: x > 0.25, lambda x: x < 0.1)),
    ("growth_at_fair_price", "valuation", "Growing >10% at P/E below 33", _rule("garp", lambda x: x > 0.5)),
    # --- dividends
    ("pays_dividend", "dividend", "Paid a dividend in the last 12 months", _rule("dps_ttm", lambda x: x > 0)),
    ("yield_1pct", "dividend", "Dividend yield above 1%", _rule("div_yield", lambda x: x > 0.01)),
    ("yield_3pct", "dividend", "Dividend yield above 3%", _rule("div_yield", lambda x: x > 0.03)),
    ("dividend_streak", "dividend", "Paid dividends in at least 4 of the last 5 years", _rule("div_years", lambda x: x >= 4)),
    ("dividend_growing", "dividend", "Dividend higher than a year ago", _rule("div_growth", lambda x: x > 0, lambda x: x < 0)),
    ("payout_safe", "dividend", "Pays out less than 80% of profit", _rule("payout", lambda x: (x > 0) & (x < 0.8), lambda x: x > 1)),
    ("dividend_cash_covered", "dividend", "Free cash flow covers the dividend", _rule("div_cover", lambda x: x > 1, lambda x: x < 0.5)),
]
CHECK_IDS = [c[0] for c in CHECKS]
CHECK_META = {c[0]: {"category": c[1], "label": c[2]} for c in CHECKS}
GOVERNANCE_NOT_COVERED = ["promoter pledging", "auditor changes", "related-party transactions",
                          "SEBI actions"]


def build_card_panel(W: Dict[str, pd.DataFrame], fund: Optional[pd.DataFrame], dates: List[pd.Timestamp],
                     daily: Optional[Dict[str, pd.DataFrame]] = None) -> pd.DataFrame:
    C = W["Close"]
    daily = dict(daily or daily_features(W))
    daily.update(extra_daily(W))
    divs = dividend_frames(fund, C.index, C.columns)
    idx = pd.DatetimeIndex(dates)
    pit = point_in_time(fund, idx, C) if fund is not None and len(fund) else {}
    liq = W["TurnoverLacs"].rolling(60, min_periods=40).median()
    Cf = C.ffill(limit=5)
    cum_div = divs["dps"].cumsum()
    shares = None
    if fund is not None and len(fund):
        a = fund[fund["kind"] == "A"]
        for col in ("shares", "net_income", "fcf"):
            w = a.pivot_table(index="available", columns="symbol", values=col, aggfunc="last")
            w = w.reindex(w.index.union(idx)).sort_index().ffill().reindex(idx).reindex(columns=C.columns)
            pit["_" + col] = w
        shares = pit["_shares"]
    rows = []
    for d, i in zip(idx, C.index.get_indexer(idx)):
        p0 = C.iloc[i]
        elig = (liq.iloc[i] >= MIN_TURNOVER_LACS) & (p0 >= MIN_PRICE)
        syms = elig[elig].index
        if len(syms) < 50:
            continue
        df = pd.DataFrame(index=syms)
        for k, v in daily.items():
            if not k.startswith("_"):
                df[k] = v.iloc[i][syms].values
        for k in ("rev_growth", "rev_accel", "profit_growth", "op_margin", "margin_change", "roe", "debt_to_equity",
                  "cash_conversion", "dilution", "turned_profitable", "fcf_positive", "log_mcap", "earnings_yield",
                  "sales_yield"):
            df[k] = pit[k].loc[d, syms].values if k in pit else np.nan
        ttm = divs["dps_ttm"].iloc[i][syms].values
        prev = divs["dps_prev"].iloc[i][syms].values
        px = p0[syms].values
        df["dps_ttm"] = ttm
        df["div_yield"] = ttm / px
        df["div_years"] = divs["div_years"].iloc[i][syms].values
        with np.errstate(divide="ignore", invalid="ignore"):
            df["div_growth"] = np.where((ttm > 0) | (prev > 0), ttm - prev, np.nan)
            if shares is not None:
                sh = shares.loc[d, syms].values
                ni = pit["_net_income"].loc[d, syms].values
                fcf = pit["_fcf"].loc[d, syms].values
                paid = ttm * sh
                df["payout"] = np.where(ttm > 0, paid / np.where(ni > 0, ni, np.nan), np.nan)
                df["div_cover"] = np.where(ttm > 0, fcf / paid, np.nan)
            else:
                df["payout"] = df["div_cover"] = np.nan
        df["garp"] = np.where(df["earnings_yield"].isna() | df["rev_growth"].isna(), np.nan,
                              ((df["earnings_yield"] > 0.03) & (df["rev_growth"] > LOG(1.1))).astype(float))
        # forward total returns (price + cash dividends), excess over that day's median stock
        for name, h in HORIZONS.items():
            if i + h < len(C):
                p1 = Cf.iloc[i + h][syms].values
                dv = (cum_div.iloc[i + h][syms] - cum_div.iloc[i][syms]).values
                tr = (p1 + dv) / px - 1
                df[f"tr_{name}"] = tr
                df[f"ex_{name}"] = tr - np.nanmedian(tr)
            else:
                df[f"tr_{name}"] = df[f"ex_{name}"] = np.nan
        df["date"] = d
        rows.append(df.rename_axis("symbol").reset_index())
    return pd.concat(rows, ignore_index=True)


def check_matrix(panel: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({cid: fn(panel) for cid, _, _, fn in CHECKS}, index=panel.index)


# --------------------------------------------------------------------- testing

def test_checks(panel: pd.DataFrame, M: pd.DataFrame) -> Tuple[Dict, List[str]]:
    """Per check and horizon: excess return of passers vs failers, hit rate of passers, NW t, FDR."""
    stats, pvals = {}, {}
    dates = panel["date"].values
    for name, h in HORIZONS.items():
        ex = panel[f"ex_{name}"].values
        lab = ~np.isnan(ex)
        lags = max(1, math.ceil(h / 21))
        for cid in CHECK_IDS:
            v = M[cid].values
            diffs, hits = [], []
            for d in np.unique(dates[lab]):
                m = lab & (dates == d)
                p, f = m & (v == 1), m & (v == -1)
                if p.sum() >= 10 and f.sum() >= 10:
                    diffs.append(ex[p].mean() - ex[f].mean())
                    hits.append((ex[p] > 0).mean())
            if len(diffs) < 8:
                stats.setdefault(cid, {})[name] = {"months": len(diffs), "tested": False}
                continue
            t = newey_west_t(np.array(diffs), lags)
            key = f"{cid}|{name}"
            pvals[key] = 2 * _norm_sf(abs(t)) if not math.isnan(t) else float("nan")
            stats.setdefault(cid, {})[name] = {
                "months": len(diffs), "tested": True,
                "pass_minus_fail_pct": round(float(np.mean(diffs)) * 100, 2),
                "pass_beat_market_pct": round(float(np.mean(hits)) * 100, 1),
                "t": None if math.isnan(t) else round(t, 2),
            }
    survivors = set(bh_fdr(pvals, 0.10))
    for key in survivors:
        cid, name = key.split("|")
        s = stats[cid][name]
        s["verified"] = True
        s["direction"] = "helps" if s["pass_minus_fail_pct"] > 0 else "works in reverse"
    return stats, sorted(survivors)


def _fit_logit(X, y):
    from sklearn.linear_model import LogisticRegression

    return LogisticRegression(C=0.05, max_iter=400).fit(X, y)


def walk_forward_verdicts(panel: pd.DataFrame, M: pd.DataFrame, first: str = "2022-07-01",
                          refit_months: int = 6) -> Dict:
    """Out-of-sample Buy/Hold/Sell per horizon, and whether each horizon earns its verdicts."""
    X = M.values.astype(float)
    dates = panel["date"].values
    out = {}
    for name, h in HORIZONS.items():
        ex = panel[f"ex_{name}"].values
        lab = ~np.isnan(ex)
        y = (ex > 0).astype(int)
        test_dates = sorted(d for d in np.unique(dates[lab]) if d >= np.datetime64(first))
        if not test_dates:
            out[name] = {"verified": False, "months": 0}
            continue
        refits = pd.date_range(first, pd.Timestamp(test_dates[-1]) + pd.Timedelta(days=1), freq=f"{refit_months}MS")
        prob = np.full(len(panel), np.nan)
        for j, R0 in enumerate(refits):
            R1 = refits[j + 1] if j + 1 < len(refits) else pd.Timestamp.max
            train = lab & (dates <= np.datetime64(R0 - pd.Timedelta(days=CAL_GAP[h])))
            block = lab & (dates >= np.datetime64(R0)) & (dates < np.datetime64(R1))
            if train.sum() < 2000 or not block.any():
                continue
            prob[block] = _fit_logit(X[train], y[train]).predict_proba(X[block])[:, 1]
        ok = ~np.isnan(prob)
        rows = []
        for d in np.unique(dates[ok]):
            m = ok & (dates == d)
            b, s = m & (prob >= BUY_P), m & (prob <= SELL_P)
            rows.append({"date": d, "buy_n": int(b.sum()), "sell_n": int(s.sum()),
                         "buy_ex": ex[b].mean() if b.any() else np.nan, "sell_ex": ex[s].mean() if s.any() else np.nan,
                         "buy_hit": (ex[b] > 0).mean() if b.any() else np.nan,
                         "sell_hit": (ex[s] > 0).mean() if s.any() else np.nan,
                         "hold_hit": (ex[m & ~(prob >= BUY_P) & ~(prob <= SELL_P)] > 0).mean()})
        r = pd.DataFrame(rows)
        if r.empty:
            out[name] = {"horizon_days": h, "months": 0, "verified": False, "calibration": []}
            continue
        spread = (r["buy_ex"] - r["sell_ex"]).dropna().values
        t = newey_west_t(spread, max(1, math.ceil(h / 21))) if len(spread) >= 6 else float("nan")
        buy_net = float(r["buy_ex"].mean() - COST) if r["buy_ex"].notna().any() else float("nan")
        # calibration: predicted chance -> how often it really beat the market
        cal = []
        for lo, hi in ((0, 0.4), (0.4, 0.45), (0.45, 0.5), (0.5, 0.55), (0.55, 0.6), (0.6, 1.01)):
            m = ok & (prob >= lo) & (prob < hi)
            if m.sum() >= 100:
                cal.append({"from": lo, "to": min(hi, 1.0), "rows": int(m.sum()),
                            "beat_market_pct": round(float(y[m].mean()) * 100, 1),
                            "avg_excess_pct": round(float(ex[m].mean()) * 100, 2)})
        verified = bool(len(spread) >= 12 and not math.isnan(t) and t > 2 and buy_net > 0
                        and r["buy_hit"].mean() > 0.5)
        out[name] = {
            "horizon_days": h, "months": int(len(r)), "verified": verified,
            "buy_beat_market_pct": round(float(r["buy_hit"].mean()) * 100, 1) if r["buy_hit"].notna().any() else None,
            "sell_beat_market_pct": round(float(r["sell_hit"].mean()) * 100, 1) if r["sell_hit"].notna().any() else None,
            "hold_beat_market_pct": round(float(r["hold_hit"].mean()) * 100, 1),
            "buy_avg_excess_pct": round(float(r["buy_ex"].mean()) * 100, 2) if r["buy_ex"].notna().any() else None,
            "sell_avg_excess_pct": round(float(r["sell_ex"].mean()) * 100, 2) if r["sell_ex"].notna().any() else None,
            "buy_minus_sell_t": None if math.isnan(t) else round(t, 2),
            "avg_buy_picks_per_month": round(float(r["buy_n"].mean()), 1),
            "calibration": cal,
        }
    return out


def dividend_backtest(panel: pd.DataFrame, M: pd.DataFrame) -> Dict:
    """Monthly top-20 by the dividend score: 1-year total-return excess and hit rate."""
    score = dividend_score(panel, M)
    lab = panel["ex_1y"].notna().values & ~np.isnan(score)
    rows = []
    for d in np.unique(panel["date"].values[lab]):
        m = lab & (panel["date"].values == d)
        if m.sum() < 20:
            continue
        idx = np.where(m)[0]
        top = idx[np.argsort(-score[idx])[:20]]
        ex = panel["ex_1y"].values[top]
        rows.append((ex.mean(), (ex > 0).mean(), np.nanmedian(panel["div_yield"].values[top])))
    if not rows:
        return {"months": 0}
    a = np.array(rows)
    t = newey_west_t(a[:, 0], 12)
    return {"months": len(a), "top20_avg_1y_excess_total_return_pct": round(float(a[:, 0].mean()) * 100, 2),
            "top20_beat_market_pct": round(float(a[:, 1].mean()) * 100, 1),
            "top20_median_yield_pct": round(float(np.nanmean(a[:, 2])) * 100, 2),
            "t": None if math.isnan(t) else round(t, 2),
            "verified": bool(len(a) >= 12 and not math.isnan(t) and t > 2)}


def dividend_score(panel: pd.DataFrame, M: pd.DataFrame) -> np.ndarray:
    """Yield, streak, growth, safety and cash cover; only real dividend payers with clean governance score."""
    ok = (M["dividend_streak"] == 1) & (M["payout_safe"] >= 0) & (M["no_dilution"] >= 0) & \
         (M["no_circuit_games"] >= 0) & (M["pays_dividend"] == 1)
    y = panel["div_yield"].clip(upper=0.12)
    s = (y.groupby(panel["date"]).rank(pct=True) * 2 + (M["dividend_growing"] == 1) * 0.5
         + (M["dividend_cash_covered"] == 1) * 0.5 + (M["payout_safe"] == 1) * 0.5 + (M["low_debt"] == 1) * 0.3)
    return np.where(ok, s, np.nan)


def governance_grade(row: pd.Series) -> Tuple[str, int, int]:
    ids = [c for c in CHECK_IDS if CHECK_META[c]["category"] in ("governance", "balance_sheet")] + \
          ["cash_backed_profit"]
    vals = [int(row[c]) for c in ids if int(row[c]) != 0]
    if len(vals) < 3:
        return "not enough data", sum(v == 1 for v in vals), len(vals)
    share = sum(v == 1 for v in vals) / len(vals)
    grade = "A" if share >= 0.85 else "B" if share >= 0.65 else "C" if share >= 0.45 else "D"
    return grade, sum(v == 1 for v in vals), len(vals)


# --------------------------------------------------------------------- run

def run_report_cards(W: Dict[str, pd.DataFrame], fund: Optional[pd.DataFrame], top_n: int = 25) -> Dict:
    t0 = datetime.now(timezone.utc)
    from app.quant.market_data import equities_only

    W = equities_only(W)
    C = W["Close"]
    dates = month_ends(C.index)
    if dates[-1] != C.index[-1]:
        dates.append(C.index[-1])
    panel = build_card_panel(W, fund, dates)
    M = check_matrix(panel)
    logger.info(f"Report cards: {len(panel)} rows, {len(CHECKS)} checks")
    check_stats, survivors = test_checks(panel, M)
    horizon_tests = walk_forward_verdicts(panel, M)
    div_test = dividend_backtest(panel, M)

    today = panel["date"].max()
    live = panel["date"] == today
    X = M.values.astype(float)
    dates_arr = panel["date"].values
    probs = {}
    for name, h in HORIZONS.items():
        ex = panel[f"ex_{name}"].values
        train = ~np.isnan(ex) & (dates_arr <= np.datetime64(today - pd.Timedelta(days=CAL_GAP[h])))
        yt = (ex[train] > 0).astype(int)
        if train.sum() < 500 or len(set(yt)) < 2:
            probs[name] = np.full(int(live.sum()), 0.5)
        else:
            probs[name] = _fit_logit(X[train], yt).predict_proba(X[live.values])[:, 1]

    L = panel.loc[live].reset_index(drop=True)
    ML = M.loc[live].reset_index(drop=True)
    dscore = dividend_score(panel.loc[live].reset_index(drop=True), ML)
    cards = []
    for i, r in L.iterrows():
        mrow = ML.iloc[i]
        flags = red_flags(r)
        r2 = r.copy()
        r2["red_flag_count"] = len(flags)
        verdicts = {}
        for name in HORIZONS:
            p = float(probs[name][i])
            if not horizon_tests[name]["verified"]:
                v = "hold"
            else:
                v = "buy" if p >= BUY_P else ("sell" if p <= SELL_P else "hold")
            verdicts[name] = {"verdict": v, "chance_beat_market_pct": round(p * 100, 1),
                              "horizon_verified": horizon_tests[name]["verified"]}
        grade, g_pass, g_n = governance_grade(mrow)
        passed = int((mrow == 1).sum())
        failed = int((mrow == -1).sum())
        cards.append({
            "symbol": r["symbol"], "as_of": str(today.date()),
            "probability": round(float(probs["1y"][i]), 4),
            "verdicts": verdicts, "stage": stage_of(r2), "red_flags": flags,
            "governance": {"grade": grade, "passed": g_pass, "checked": g_n,
                           "not_covered": GOVERNANCE_NOT_COVERED},
            "checks_passed": passed, "checks_failed": failed, "checks_unknown": len(CHECKS) - passed - failed,
            "checks": {cid: int(mrow[cid]) for cid in CHECK_IDS},
            "dividend": {"yield_pct": None if pd.isna(r["div_yield"]) else round(float(r["div_yield"]) * 100, 2),
                         "dps_ttm": None if pd.isna(r["dps_ttm"]) else round(float(r["dps_ttm"]), 2),
                         "years_paid_of_5": None if pd.isna(r["div_years"]) else int(r["div_years"]),
                         "payout_pct": None if pd.isna(r["payout"]) else round(float(r["payout"]) * 100, 1),
                         "score": None if np.isnan(dscore[i]) else round(float(dscore[i]), 3)},
            "key_numbers": {k: (None if pd.isna(r[k]) else round(float(r[k]), 4)) for k in
                            ("ret_1y", "mom6", "vol60", "max_dd_1y", "rev_growth", "roe", "debt_to_equity",
                             "earnings_yield", "deliv_level", "kalman_snr")},
        })
    by_sym = {c["symbol"]: c for c in cards}

    def ok_gov(c):
        return c["governance"]["grade"] in ("A", "B") and not c["red_flags"]

    best = {}
    for name in HORIZONS:
        ranked = sorted((c for c in cards if ok_gov(c)), key=lambda c: -c["verdicts"][name]["chance_beat_market_pct"])
        best[name] = [c["symbol"] for c in ranked if (c["verdicts"][name]["verdict"] == "buy"
                                                      or not horizon_tests[name]["verified"])][:top_n]
    div_ranked = sorted((c for c in cards if c["dividend"]["score"] is not None and ok_gov(c)),
                        key=lambda c: -c["dividend"]["score"])
    best["dividend"] = [c["symbol"] for c in div_ranked[:top_n]]
    for rank, c in enumerate(sorted(cards, key=lambda c: -c["probability"]), 1):
        c["rank"] = rank

    return clean_json({
        "model_key": "stock_report_card", "strategy": "report_card", "horizon_days": 250,
        "description": f"{len(CHECKS)} tested checks per stock rolled into Buy / Hold / Sell for 1 week to 1 year.",
        "model_type": "checks_logistic", "trained_at": t0.isoformat(), "data_end": str(today.date()),
        "edge_verified": any(v["verified"] for v in horizon_tests.values()),
        "metrics": {
            "checks": [{"id": cid, **CHECK_META[cid], "tests": check_stats.get(cid, {})} for cid in CHECK_IDS],
            "check_count": len(CHECKS), "checks_verified": survivors,
            "horizon_tests": horizon_tests, "dividend_backtest": div_test,
            "best": best, "stocks_scored": len(cards), "panel_rows": int(len(panel)),
            "governance_not_covered": GOVERNANCE_NOT_COVERED,
            "minutes": round((datetime.now(timezone.utc) - t0).total_seconds() / 60, 1),
        },
        "backtest": None, "folds": None, "predictions": list(by_sym.values()),
    })


def nightly_report_cards(max_fetch: int = 400) -> Dict:
    """Nightly entry point: cached NSE data + fundamentals (refreshing up to max_fetch stale stocks)."""
    from app.quant.fundamentals import load_fundamentals
    from app.quant.market_data import update_market

    W = update_market(pd.DatetimeIndex([]))
    liq = W["TurnoverLacs"].rolling(60, min_periods=40).median()
    ever = liq.resample("ME").last().ge(MIN_TURNOVER_LACS).any()
    fund = load_fundamentals(list(ever[ever].index), max_fetch=max_fetch)
    return run_report_cards(W, fund)


def nightly_cards_and_income(max_fetch: int = 400) -> List[Dict]:
    """Report cards, then the dividend income calendar (which uses the cards' payout, governance and verdicts)."""
    from app.quant.fundamentals import load_fundamentals
    from app.quant.income import build_income
    from app.quant.market_data import equities_only, update_market

    W = update_market(pd.DatetimeIndex([]))
    liq = W["TurnoverLacs"].rolling(60, min_periods=40).median()
    ever = liq.resample("ME").last().ge(MIN_TURNOVER_LACS).any()
    fund = load_fundamentals(list(ever[ever].index), max_fetch=max_fetch)
    cards = run_report_cards(W, fund)
    income = build_income(fund, equities_only(W)["Close"], cards["predictions"])
    return [cards, income]


def verdicts_to_log(cards: Dict, per_side: int = 25) -> List[Tuple]:
    """Tonight's strongest Buy and Sell calls per verified holding period, for the live ledger."""
    rows = []
    preds = cards.get("predictions") or []
    tests = (cards.get("metrics") or {}).get("horizon_tests") or {}
    for name in HORIZONS:
        if not (tests.get(name) or {}).get("verified"):
            continue
        buys = sorted((p for p in preds if p["verdicts"][name]["verdict"] == "buy"),
                      key=lambda p: -p["verdicts"][name]["chance_beat_market_pct"])[:per_side]
        sells = sorted((p for p in preds if p["verdicts"][name]["verdict"] == "sell"),
                       key=lambda p: p["verdicts"][name]["chance_beat_market_pct"])[:per_side]
        for p in buys + sells:
            v = p["verdicts"][name]
            rows.append((p["as_of"], p["symbol"], name, v["verdict"], v["chance_beat_market_pct"]))
    return rows


def score_verdict_log(W: Dict[str, pd.DataFrame], rows: List[dict]) -> Dict:
    """Live scorecard: logged Buy / Sell calls whose holding period has passed, vs the median liquid stock."""
    C = W["Close"].ffill(limit=5)
    liq = W["TurnoverLacs"].rolling(60, min_periods=40).median() >= MIN_TURNOVER_LACS
    out: Dict[str, Dict[str, list]] = {}
    for r in rows:
        h = HORIZONS.get(r["horizon"])
        d = pd.Timestamp(r["date"])
        i = C.index.searchsorted(d, side="right") - 1
        if h is None or i < 0 or i + h >= len(C) or r["symbol"] not in C.columns:
            continue
        ret = C.iloc[i + h] / C.iloc[i] - 1
        rr = ret.get(r["symbol"])
        if pd.isna(rr):
            continue
        ex = float(rr - ret[liq.iloc[i]].median())
        out.setdefault(r["horizon"], {}).setdefault(r["verdict"], []).append(ex)
    card = {"status": "ok" if out else "waiting", "logged_calls": len(rows),
            "note": "Real calls saved each night, scored once their holding period has passed (price return vs the median liquid stock)."}
    for name, sides in out.items():
        card[name] = {side: {"scored": len(xs), "beat_market_pct": round(float(np.mean(np.array(xs) > 0)) * 100, 1),
                             "avg_excess_pct": round(float(np.mean(xs)) * 100, 2)} for side, xs in sides.items()}
    return card
