"""
Quant API — tested model predictions, validation reports and news outcomes.

Every response carries `edge_verified` and the model's out-of-sample
accuracy, so the app can show how much to trust each number.
"""

import json
import re
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.database import fetch, fetchrow

router = APIRouter(prefix="/quant")

STRATEGIES = {"trader": "stock_trader", "swing": "stock_swing", "investor": "stock_investor",
              "investor_factor": "stock_investor_factor"}


def _j(v):
    return json.loads(v) if isinstance(v, str) else v


def _trust(run: dict) -> dict:
    """Compact 'how much can I trust this' block for the app."""
    m = _j(run.get("metrics")) or {}
    bt = _j(run.get("backtest")) or {}
    edge = bool(run.get("edge_verified"))
    return {
        "edge_verified": edge,
        "verdict": _verdict(edge, m, bt),
        "ranking_skill_verified": m.get("ranking_skill_verified"),
        "backtest_equal_weight_cagr_pct": (bt.get("equal_weight") or {}).get("cagr_pct"),
        "oos_period": [m.get("oos_start"), m.get("oos_end")],
        "auc": m.get("auc"),
        "accuracy": m.get("accuracy"),
        "accuracy_always_majority": m.get("accuracy_always_majority"),
        "rank_ic_tstat": m.get("rank_ic_tstat"),
        "backtest_cagr_pct": (bt.get("model") or {}).get("cagr_pct"),
        "nifty_cagr_pct": (bt.get("nifty") or {}).get("cagr_pct"),
        "trained_at": run["trained_at"].isoformat() if run.get("trained_at") else None,
        "data_end": str(run["data_end"]) if run.get("data_end") else None,
    }


def _verdict(edge: bool, m: dict, bt: dict) -> str:
    track = m.get("coverage_track_record")
    if track:
        c5 = (track.get("5d") or {}).get("p80", {}).get("coverage")
        return (f"Coverage promise held: the 80% ranges contained the real closing price "
                f"{c5 * 100:.1f}% of the time on years of unseen days (5-day horizon)."
                if edge and c5 else "Coverage promise not met on recent history; ranges shown for context.")
    if edge:
        return "Tested edge: beat chance and the hold-everything basket after costs on years of unseen data."
    if m.get("ranking_skill_verified"):
        return ("Ranks stocks better than chance, but after trading costs its picks did not beat "
                "simply holding all stocks. Use as context, not a buy signal.")
    if "gmp_rule_mae_pct" in m:
        return "Did not beat the simple GMP rule on past IPOs; the expected gain shown is GMP-based."
    return ("No proven edge yet: on unseen data this was close to a coin flip. "
            "Treat its probabilities as near 50/50 context, not a signal.")


async def _latest_run(model_key: str) -> Optional[dict]:
    return await fetchrow(
        "SELECT * FROM quant_model_runs WHERE model_key = $1 ORDER BY trained_at DESC LIMIT 1",
        model_key,
    )


@router.get("/picks")
async def picks(
    strategy: str = Query("swing", description="trader (5d), swing (20d), investor (60d) or investor_factor"),
    limit: int = Query(20, ge=1, le=100),
    min_probability: float = Query(0.0, ge=0, le=1),
):
    """Stocks ranked by tested probability of beating their peers for the chosen strategy."""
    key = STRATEGIES.get(strategy.lower())
    if not key:
        raise HTTPException(400, f"strategy must be one of {list(STRATEGIES)}")
    run = await _latest_run(key)
    if not run:
        return {"strategy": strategy, "status": "not_trained", "picks": []}
    rows = await fetch(
        """
        SELECT p.payload, s.name, s.sector, s.current_price, s.change_pct
        FROM quant_predictions p
        LEFT JOIN stocks s ON UPPER(s.symbol) = p.symbol AND s.exchange = 'NSE'
        WHERE p.model_key = $1 AND p.probability >= $2
        ORDER BY p.rank ASC LIMIT $3
        """,
        key, min_probability, limit,
    )
    out = []
    for r in rows:
        p = _j(r["payload"])
        p.update({"name": r["name"], "sector": r["sector"],
                  "current_price": float(r["current_price"]) if r["current_price"] is not None else None,
                  "change_pct": float(r["change_pct"]) if r["change_pct"] is not None else None})
        out.append(p)
    return {"strategy": strategy, "horizon_days": run["horizon_days"],
            "description": run["description"], "trust": _trust(run), "picks": out}


@router.get("/stock/{symbol}")
async def stock_view(symbol: str):
    """All strategy probabilities for one stock plus its measured news reactions."""
    sym = symbol.upper().strip()
    if not re.match(r"^[A-Z0-9&_.-]{1,20}$", sym):
        raise HTTPException(400, "Invalid symbol")
    rows = await fetch(
        """
        SELECT p.model_key, p.payload, r.horizon_days, r.description, r.edge_verified,
               r.metrics, r.backtest, r.trained_at, r.data_end
        FROM quant_predictions p JOIN quant_model_runs r ON r.id = p.run_id
        WHERE p.symbol = $1 AND p.model_key LIKE 'stock_%'
        """,
        sym,
    )
    strategies = {
        r["model_key"].replace("stock_", ""): {
            **_j(r["payload"]), "horizon_days": r["horizon_days"],
            "description": r["description"], "trust": _trust(r),
        }
        for r in rows
    }
    ranges = await fetchrow(
        """
        SELECT p.payload, r.metrics FROM quant_predictions p JOIN quant_model_runs r ON r.id = p.run_id
        WHERE p.model_key = 'price_ranges' AND p.symbol = $1
        """,
        sym,
    )
    news = await fetch(
        """
        SELECT n.title, n.source, n.published_at, nsi.impact_direction, nsi.impact_score,
               o.abn_1d, o.abn_5d, o.abn_20d
        FROM news_stock_impact nsi
        JOIN news n ON n.id = nsi.news_id
        LEFT JOIN news_outcomes o ON o.news_id = nsi.news_id AND o.symbol = nsi.symbol
        WHERE nsi.symbol = $1
        ORDER BY n.published_at DESC NULLS LAST LIMIT 15
        """,
        sym,
    )
    for n in news:
        for k in ("abn_1d", "abn_5d", "abn_20d"):
            v = n.pop(k, None)
            n[k + "_pct"] = round(v * 100, 2) if v is not None else None
        n["impact_score"] = float(n["impact_score"]) if n.get("impact_score") is not None else None
    price_ranges = None
    if ranges:
        track = (_j(ranges["metrics"]) or {}).get("coverage_track_record", {})
        price_ranges = {**_j(ranges["payload"]),
                        "track_record": {h: {lv: {"promised": int(lv[1:]) / 100, "achieved": v.get("coverage"),
                                                  "worst_quarter": v.get("worst_quarter_coverage")}
                                             for lv, v in d.items()} for h, d in track.items()}}
    return {"symbol": sym, "strategies": strategies, "price_ranges": price_ranges, "news_reactions": news}


@router.get("/market-outlook")
async def market_outlook():
    """Chance the Nifty is higher in 5 / 20 trading days, with the model's tested accuracy."""
    out = {}
    for h in (5, 20):
        key = f"market_{h}d"
        run = await _latest_run(key)
        if not run:
            continue
        p = await fetchrow("SELECT payload FROM quant_predictions WHERE model_key = $1", key)
        out[f"{h}d"] = {**(_j(p["payload"]) if p else {}), "trust": _trust(run)}
    return {"status": "ok" if out else "not_trained", "outlook": out}


@router.get("/models")
async def models_report():
    """Full validation report for every model: metrics, calibration, deciles, backtest, folds."""
    rows = await fetch(
        """
        SELECT DISTINCT ON (model_key) * FROM quant_model_runs
        ORDER BY model_key, trained_at DESC
        """
    )
    return {"models": [
        {k: (_j(v) if k in ("metrics", "backtest", "folds") else
             (v.isoformat() if hasattr(v, "isoformat") else v)) for k, v in r.items()}
        for r in rows
    ]}


@router.get("/news-impact")
async def news_impact(
    days: int = Query(180, ge=7, le=730),
    horizon: str = Query("5d", description="1d, 5d or 20d"),
    min_samples: int = Query(10, ge=3, le=500),
):
    """
    Measured outcome of news tags: for each (direction, category), how often
    the stock really moved that way vs the market, with 95% intervals.
    """
    from app.quant.news_events import load_outcomes_frame, summarize, MIN_SAMPLES_FOR_MODEL

    if horizon not in ("1d", "5d", "20d"):
        raise HTTPException(400, "horizon must be 1d, 5d or 20d")
    df = await load_outcomes_frame(days)
    col = f"abn_{horizon}"
    total = int(df[col].notna().sum()) if not df.empty else 0
    news_run = await _latest_run("news_5d")
    return {
        "horizon": horizon, "days": days, "measured_pairs": total,
        "model": {
            "samples_needed": MIN_SAMPLES_FOR_MODEL,
            "status": "trained" if news_run else "collecting_data",
            "trust": _trust(news_run) if news_run else None,
        },
        "groups": summarize(df, col, min_samples) if total else [],
    }


@router.get("/ipo-odds")
async def ipo_odds():
    """Open/upcoming IPOs with expected listing gain, chance of a positive listing and the model's track record."""
    run = await _latest_run("ipo_listing")
    if not run:
        return {"status": "not_trained", "ipos": []}
    rows = await fetch(
        "SELECT payload FROM quant_predictions WHERE model_key = 'ipo_listing' ORDER BY rank ASC"
    )
    m = _j(run.get("metrics")) or {}
    return {
        "status": "ok", "trust": _trust(run),
        "track_record": {k: m.get(k) for k in (
            "oos_ipos", "oos_start", "oos_end", "model_mae_pct", "gmp_rule_mae_pct",
            "model_auc_positive_listing", "gmp_rule_auc_positive_listing",
            "model_direction_accuracy", "gmp_rule_direction_accuracy",
            "apply_model_p60", "apply_gmp_positive", "apply_all", "top_drivers", "confidence_tiers")},
        "ipos": [_j(r["payload"]) for r in rows],
    }


@router.get("/data-quality")
async def data_quality():
    """Latest cross-source checks: Yahoo vs NSE prices, investorgain vs ipowatch GMP."""
    run = await _latest_run("data_quality")
    if not run:
        return {"status": "not_checked_yet"}
    return {"status": "ok", "checked_at": run["trained_at"].isoformat() if run.get("trained_at") else None,
            **(_j(run.get("metrics")) or {})}


@router.get("/ranges")
async def ranges_all(limit: int = Query(200, ge=1, le=2000)):
    """Guaranteed-coverage price ranges (80% / 95%) for every tracked stock, plus the method's track record."""
    run = await _latest_run("price_ranges")
    if not run:
        return {"status": "not_trained", "stocks": []}
    rows = await fetch(
        "SELECT payload FROM quant_predictions WHERE model_key = 'price_ranges' ORDER BY symbol LIMIT $1", limit)
    return {"status": "ok", "trust": _trust(run),
            "track_record": (_j(run.get("metrics")) or {}).get("coverage_track_record"),
            "stocks": [_j(r["payload"]) for r in rows]}


@router.get("/scanner")
async def scanner():
    """
    Tonight's 20-stock watchlist from the whole-market scan, by setup, each
    with its historical track record, guaranteed-coverage ranges, live
    market-hours status, and the live scorecard of earlier picks.
    """
    run = await _latest_run("market_scanner")
    if not run:
        return {"status": "not_scanned_yet", "picks": []}
    rows = await fetch(
        """
        SELECT p.payload, l.price, l.change_pct, l.status AS live_status, l.updated_at
        FROM quant_predictions p LEFT JOIN live_watch l ON l.symbol = p.symbol
        WHERE p.model_key = 'market_scanner' ORDER BY p.rank
        """
    )
    picks = []
    for r in rows:
        p = _j(r["payload"])
        if r.get("price") is not None:
            p["live"] = {"price": float(r["price"]), "change_pct": r["change_pct"],
                         "status": r["live_status"],
                         "updated_at": r["updated_at"].isoformat() if r.get("updated_at") else None}
        picks.append(p)
    card_run = await _latest_run("scanner_scorecard")
    m = _j(run.get("metrics")) or {}
    return {
        "status": "ok", "as_of": str(run["data_end"]) if run.get("data_end") else None,
        "description": run.get("description"),
        "category_track_record": m.get("category_track_record"),
        "watchlist_categories": m.get("watchlist_categories"),
        "today_counts": m.get("today_counts"),
        "live_scorecard": (_j(card_run.get("metrics")) if card_run else {"status": "collecting"}),
        "picks": picks,
    }


@router.get("/multibagger")
async def multibagger():
    """
    Multibagger Radar: stocks with the best tested odds of doubling within a
    year, each with its stage, evidence ledger and red flags, plus the
    model zoo's honest test results, market regime and live scorecard.
    """
    run = await _latest_run("multibagger_radar")
    if not run:
        return {"status": "not_trained", "picks": []}
    rows = await fetch(
        """
        SELECT p.payload, s.name, s.sector, s.current_price, s.change_pct
        FROM quant_predictions p
        LEFT JOIN stocks s ON UPPER(s.symbol) = p.symbol AND s.exchange = 'NSE'
        WHERE p.model_key = 'multibagger_radar' ORDER BY p.rank
        """
    )
    picks = []
    for r in rows:
        p = _j(r["payload"])
        p.update({"name": r["name"], "sector": r["sector"],
                  "current_price": float(r["current_price"]) if r["current_price"] is not None else None,
                  "change_pct": float(r["change_pct"]) if r["change_pct"] is not None else None})
        picks.append(p)
    m = _j(run.get("metrics")) or {}
    card_run = await _latest_run("multibagger_scorecard")
    stack = m.get("honest_stack") or {}
    if run.get("edge_verified"):
        verdict = (f"Tested edge: on {stack.get('months')} unseen months the top 10% of this ranking doubled "
                   f"{stack.get('top_decile_hit_pct')}% of the time vs {stack.get('avg_base_rate_pct')}% for an "
                   f"average liquid stock ({stack.get('lift_top_decile')}x). Most picks still won't double.")
    else:
        verdict = "No proven edge yet on unseen data: treat this list as research leads, not buy signals."
    mom = m.get("momentum_12m_alone") or {}
    if mom and not m.get("beats_momentum_baseline", True):
        verdict += (f" Honest note: simple 12-month momentum alone did better in the same test "
                    f"({mom.get('top_decile_hit_pct')}% doubled), so the zoo does not yet beat the classic factor.")
    return {
        "status": "ok", "as_of": str(run["data_end"]) if run.get("data_end") else None,
        "edge_verified": bool(run.get("edge_verified")), "verdict": verdict,
        "description": run.get("description"),
        "zoo": {k: m.get(k) for k in ("model_configurations", "fitted_models", "bags_per_configuration",
                                      "families", "targets", "views", "fdr_q")},
        "fdr_survivors": len(m.get("fdr_survivors") or []),
        "honest_test": {k: v for k, v in stack.items() if k != "by_month"},
        "beats_momentum_baseline": m.get("beats_momentum_baseline"),
        "baselines": {"momentum_12m_alone": {k: v for k, v in (m.get("momentum_12m_alone") or {}).items()
                                             if k != "by_month"},
                      "zoo_average": {k: v for k, v in (m.get("zoo_average") or {}).items() if k != "by_month"},
                      "price_and_flow_only": {k: v for k, v in (m.get("price_and_flow_only") or {}).items()
                                              if k != "by_month"}},
        "lift_by_score_bucket": m.get("lift_by_score_bucket"),
        "stage_track_record": m.get("stage_track_record"),
        "red_flag_study": m.get("red_flag_study"),
        "regime": m.get("regime"),
        "live_scorecard": (_j(card_run.get("metrics")) if card_run else {"status": "collecting"}),
        "picks": picks,
    }


CARD_HORIZONS = ("1w", "1m", "3m", "1y")
SYMBOL_RE = re.compile(r"^[A-Z0-9&\-]{1,30}$")


def _card_context(run: dict) -> dict:
    m = _j(run.get("metrics")) or {}
    return {
        "as_of": str(run["data_end"]) if run.get("data_end") else None,
        "horizon_tests": {h: {k: v for k, v in (t or {}).items() if k != "calibration"}
                          for h, t in (m.get("horizon_tests") or {}).items()},
        "dividend_backtest": m.get("dividend_backtest"),
        "check_count": m.get("check_count"),
        "how_to_read": ("Buy = likely to beat the median stock over that period, Sell = likely to lag it, "
                        "Hold = no clear edge. A period marked unverified did not prove itself on unseen "
                        "history, so every stock is Hold there."),
    }


@router.get("/report-card/{symbol}")
async def report_card(symbol: str, horizon: str = Query("1y")):
    """One stock's 57-check report card: verdict per holding period, stage, governance, dividends and every check with its tested track record."""
    sym = symbol.upper().strip()
    if not SYMBOL_RE.match(sym):
        raise HTTPException(400, "invalid symbol")
    if horizon not in CARD_HORIZONS:
        raise HTTPException(400, f"horizon must be one of {list(CARD_HORIZONS)}")
    run = await _latest_run("stock_report_card")
    if not run:
        return {"status": "not_trained"}
    row = await fetchrow(
        "SELECT payload FROM quant_predictions WHERE model_key = 'stock_report_card' AND symbol = $1", sym)
    if not row:
        return {"status": "not_covered", "symbol": sym,
                "note": "Only liquid NSE companies (median turnover above Rs 50 lakh a day) get a report card."}
    card = _j(row["payload"])
    m = _j(run.get("metrics")) or {}
    checks = []
    for c in m.get("checks") or []:
        t = (c.get("tests") or {}).get(horizon) or {}
        checks.append({"id": c["id"], "category": c["category"], "label": c["label"],
                       "result": {1: "pass", -1: "fail"}.get((card.get("checks") or {}).get(c["id"]), "no data"),
                       "tested": {k: t.get(k) for k in ("pass_minus_fail_pct", "pass_beat_market_pct", "t", "verified",
                                                         "direction", "months")}})
    card["checks"] = checks
    inc = await fetchrow("SELECT payload FROM quant_predictions WHERE model_key = 'dividend_income' AND symbol = $1", sym)
    if inc:
        p = _j(inc["payload"])
        card["income"] = {k: p.get(k) for k in ("income_score", "rating_badge", "frequency", "usual_months",
                                                 "years_paid_of_10", "streak_years", "cuts_last_5y",
                                                 "dps_5y_growth_pct", "next_expected", "income_per_lakh_rs")}
    return {"status": "ok", "horizon": horizon, **_card_context(run), "card": card}


@router.get("/best")
async def best_stocks(kind: str = Query("stocks", description="stocks or dividend"),
                      horizon: str = Query("1y"), limit: int = Query(25, ge=1, le=50)):
    """Best stocks for a holding period (Buy verdicts with clean governance) or best dividend stocks."""
    if kind not in ("stocks", "dividend"):
        raise HTTPException(400, "kind must be stocks or dividend")
    if horizon not in CARD_HORIZONS:
        raise HTTPException(400, f"horizon must be one of {list(CARD_HORIZONS)}")
    run = await _latest_run("stock_report_card")
    if not run:
        return {"status": "not_trained", "stocks": []}
    m = _j(run.get("metrics")) or {}
    symbols = ((m.get("best") or {}).get("dividend" if kind == "dividend" else horizon) or [])[:limit]
    rows = await fetch(
        """
        SELECT p.symbol, p.payload, s.name, s.current_price, s.change_pct
        FROM quant_predictions p
        LEFT JOIN stocks s ON UPPER(s.symbol) = p.symbol AND s.exchange = 'NSE'
        WHERE p.model_key = 'stock_report_card' AND p.symbol = ANY($1::text[])
        """,
        symbols,
    )
    by_sym = {r["symbol"]: r for r in rows}
    out = []
    for sym in symbols:
        r = by_sym.get(sym)
        if not r:
            continue
        c = _j(r["payload"])
        out.append({"symbol": sym, "name": r["name"],
                    "current_price": float(r["current_price"]) if r["current_price"] is not None else None,
                    "change_pct": float(r["change_pct"]) if r["change_pct"] is not None else None,
                    "verdict": (c.get("verdicts") or {}).get(horizon), "stage": c.get("stage"),
                    "governance": (c.get("governance") or {}).get("grade"),
                    "checks_passed": c.get("checks_passed"), "checks_failed": c.get("checks_failed"),
                    "dividend": c.get("dividend")})
    ht = ((m.get("horizon_tests") or {}).get(horizon) or {})
    live_run = await _latest_run("report_card_scorecard")
    live = (_j(live_run.get("metrics")) or {}) if live_run else {"status": "collecting"}
    return {"status": "ok", "kind": kind, "horizon": horizon, **_card_context(run),
            "verified": (m.get("dividend_backtest") or {}).get("verified") if kind == "dividend" else ht.get("verified"),
            "live_scorecard": {"status": live.get("status"), "logged_calls": live.get("logged_calls"),
                               "this_period": live.get(horizon)},
            "stocks": out}


INCOME_SORTS = {"score": "income_score", "yield": "yield_pct", "next": "next"}


@router.get("/income/calendar")
async def income_calendar(
    month: int = Query(0, ge=0, le=12, description="1-12 for companies that usually pay that month; 0 = all"),
    min_yield: float = Query(0, ge=0, le=50, description="minimum dividend yield %"),
    min_score: float = Query(0, ge=0, le=100, description="minimum Income Score"),
    min_years: int = Query(0, ge=0, le=10, description="paid in at least this many of the last 10 years"),
    frequency: Optional[str] = Query(None, description="quarterly, half-yearly, yearly or irregular"),
    governance: Optional[str] = Query(None, description="A or AB"),
    no_cuts: bool = Query(False, description="no dividend cut in the last 5 years"),
    income_buy_only: bool = Query(False, description="only STRONG INCOME verdicts"),
    sort: str = Query("score", description="score, yield or next"),
    limit: int = Query(100, ge=1, le=500),
):
    """Dividend payers by usual pay month, with every filter for building a steady income list."""
    if sort not in INCOME_SORTS:
        raise HTTPException(400, f"sort must be one of {list(INCOME_SORTS)}")
    run = await _latest_run("dividend_income")
    if not run:
        return {"status": "not_trained", "stocks": []}
    rows = await fetch(
        """
        SELECT p.payload, s.name FROM quant_predictions p
        LEFT JOIN stocks s ON UPPER(s.symbol) = p.symbol AND s.exchange = 'NSE'
        WHERE p.model_key = 'dividend_income'
        """
    )
    out = []
    for r in rows:
        p = _j(r["payload"])
        if month and month not in (p.get("usual_months") or []):
            continue
        if (p.get("yield_pct") or 0) < min_yield or (p.get("income_score") or 0) < min_score:
            continue
        if (p.get("years_paid_of_10") or 0) < min_years:
            continue
        if frequency and p.get("frequency") != frequency:
            continue
        if governance and (p.get("governance") or "") not in governance.upper():
            continue
        if no_cuts and (p.get("cuts_last_5y") or 0) > 0:
            continue
        if income_buy_only and p.get("income_verdict") != "income_buy":
            continue
        nxt = p.get("next_expected") or []
        if month:
            nxt = [n for n in nxt if n.get("month") == month] or nxt
        first = nxt[0] if nxt else {}
        # field names shared with the app's dividend rows
        p.update({"company_name": r["name"] or p["symbol"], "amount": first.get("expected_amount"),
                  "ex_date": first.get("expected_date"), "status": "expected", "currency": "INR",
                  "current_price": p.get("price"), "dividend_yield_pct": p.get("yield_pct")})
        out.append(p)
    if sort == "next":
        out.sort(key=lambda p: p.get("ex_date") or "9999")
    else:
        out.sort(key=lambda p: -(p.get(INCOME_SORTS[sort]) or 0))
    m = _j(run.get("metrics")) or {}
    yields = [p["yield_pct"] for p in out if p.get("yield_pct") is not None]
    return {
        "status": "ok", "as_of": str(run["data_end"]) if run.get("data_end") else None,
        "month": month, "count": len(out), "month_counts": m.get("month_counts"),
        "stats": {"total_payouts": len(out), "avg_yield_pct": round(sum(yields) / len(yields), 2) if yields else 0.0,
                  "high_yield_count": sum(1 for y in yields if y > 3)},
        "paying_power_backtest": m.get("paying_power_backtest"), "verdict_rules": m.get("verdict_rules"),
        "dividends": out[:limit],
    }


@router.get("/income/{symbol}")
async def income_profile(symbol: str):
    """One company's dividend record: years paid, cuts, usual months, next expected dates and Income Score."""
    sym = symbol.upper().strip()
    if not SYMBOL_RE.match(sym):
        raise HTTPException(400, "invalid symbol")
    row = await fetchrow("SELECT payload FROM quant_predictions WHERE model_key = 'dividend_income' AND symbol = $1", sym)
    if not row:
        return {"status": "not_a_regular_payer", "symbol": sym,
                "note": "No dividend in the last 3 years, or not a liquid NSE company."}
    return {"status": "ok", "profile": _j(row["payload"])}
