"""Today's rating (open-to-close day model) and the BSE / US price feeds."""

import os
import sys
from datetime import date

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.quant.features import forward_labels  # noqa: E402


def _prices():
    idx = pd.bdate_range("2026-01-05", periods=4)
    o = pd.DataFrame({"A": [100, 110, 120, 130], "B": [50, 50, 50, 50]}, index=idx, dtype=float)
    c = pd.DataFrame({"A": [105, 121, 120, 130], "B": [50, 55, 50, 50]}, index=idx, dtype=float)
    nifty = pd.DataFrame({"Open": [1000, 1000, 1000, 1000], "Close": [1000, 1010, 1000, 1000]}, index=idx, dtype=float)
    return {"Open": o, "Close": c, "nifty": nifty}


def test_intraday_label_is_next_session_open_to_close_vs_nifty():
    lab = forward_labels(_prices(), 1, intraday=True)
    d0 = pd.Timestamp("2026-01-05")
    # Rated on day 0's close; traded on day 1: A opens 110, closes 121 (+10%); Nifty +1%.
    assert np.isclose(lab.loc[(d0, "A"), "fwd_ret"], np.log(121 / 110))
    assert np.isclose(lab.loc[(d0, "A"), "fwd_excess"], np.log(121 / 110) - np.log(1010 / 1000))
    assert np.isclose(lab.loc[(d0, "B"), "fwd_ret"], np.log(55 / 50))
    # The last day has no next session: no label (it is "today").
    assert lab.xs(pd.Timestamp("2026-01-08"), level="date")["fwd_ret"].isna().all()


def test_intraday_backtest_pays_full_costs_every_day():
    from app.quant.validation import COST_PER_SIDE_INTRADAY, backtest
    dates = pd.bdate_range("2025-01-01", periods=30)
    syms = [f"S{i}" for i in range(20)]
    idx = pd.MultiIndex.from_product([dates, syms], names=["date", "symbol"])
    oos = pd.DataFrame({"prob_raw": np.tile(np.arange(20), 30), "fwd_ret": 0.0, "fwd_excess": 0.0}, index=idx)
    bt = backtest(oos, oos, 1, intraday=True)
    # Same picks every day, zero returns: an intraday book still pays two sides daily.
    assert bt["settings"]["intraday"] is True
    assert bt["model"]["total_return_pct"] < 0
    expected = ((1 - 2 * COST_PER_SIDE_INTRADAY) ** 30 - 1) * 100
    assert abs(bt["model"]["total_return_pct"] - expected) < 0.2
    bt_hold = backtest(oos, oos, 1, intraday=False)
    assert bt_hold["model"]["total_return_pct"] > bt["model"]["total_return_pct"]


def test_session_after_skips_weekends():
    from app.api.quant import _session_after
    assert _session_after(date(2026, 11, 5)) == date(2026, 11, 6)    # Thu -> Fri
    assert _session_after(date(2026, 11, 6)) == date(2026, 11, 9)    # Fri -> Mon


def test_intraday_rows_use_only_todays_bars():
    from app.scrapers.nse_prices import IST, intraday_rows
    idx = pd.DatetimeIndex(["2026-11-04 15:25", "2026-11-05 09:15", "2026-11-05 09:20"]).tz_localize(IST)
    cols = pd.MultiIndex.from_product([["Open", "High", "Low", "Close"], ["TCS.NS"]])
    data = pd.DataFrame([[1, 9, 0.5, 2], [100, 105, 99, 103], [103, 107, 102, 106]], index=idx, columns=cols)
    rows = intraday_rows(data, ["TCS", "MISSING"], date(2026, 11, 5))
    assert rows == [("TCS", 106.0, 100.0, 107.0, 99.0)]


def test_bse_daily_file_keeps_company_shares_only():
    from app.scrapers.bse_scraper import parse_bse_bhav
    head = ("TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,FininstrmActlXpryDt,"
            "StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,UndrlygPric,"
            "SttlmPric,OpnIntrst,ChngInOpnIntrst,TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,"
            "Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4\n")
    row = "2026-11-04,2026-11-04,CM,BSE,{tp},1,INE1,{sym},{ser},,,,,{sym} LTD,10,12,9,11,11,10,,11,,,500,5500,9,F1,1,,,,,\n"
    text = head + row.format(tp="STK", sym="SMALLCO", ser="X") + row.format(tp="STK", sym="BOND1", ser="F") \
        + row.format(tp="STK", sym="ZEROCO", ser="B").replace(",11,11,10,", ",,,10,")
    rows = parse_bse_bhav(text)
    assert [r["symbol"] for r in rows] == ["SMALLCO"]
    assert rows[0]["change_pct"] == 10.0 and rows[0]["volume"] == 500


def test_us_prices_from_one_batched_daily_frame():
    from app.scrapers.us_scraper import rows_from_daily
    idx = pd.DatetimeIndex(["2026-11-04", "2026-11-05"])
    cols = pd.MultiIndex.from_product([["Open", "High", "Low", "Close", "Volume"], ["AAPL", "BRK-B"]])
    vals = [[1, 1, 2, 2, 0.5, 0.5, 100, 200, 10, 20], [101, 201, 105, 205, 99, 199, 104, 202, 30, 40]]
    data = pd.DataFrame(vals, index=idx, columns=cols, dtype=float)
    data.loc[idx[1], ("Close", "BRK-B")] = np.nan     # no trade today -> previous row becomes "today"
    rows = {r[0]: r for r in rows_from_daily(data, ["AAPL", "BRK-B", "NOPE"])}
    assert rows["AAPL"][1:3] == (104.0, 100.0) and rows["AAPL"][-1] == 4.0
    assert "BRK-B" not in rows and "NOPE" not in rows


def test_saved_prices_must_include_the_latest_session():
    from datetime import datetime, timedelta, timezone
    from app.quant.data import _cache_is_current, last_finished_session
    ist = timezone(timedelta(hours=5, minutes=30))
    fri_night = datetime(2026, 11, 6, 21, 0, tzinfo=ist)
    sun = datetime(2026, 11, 8, 13, 0, tzinfo=ist)
    mon_morning = datetime(2026, 11, 9, 8, 0, tzinfo=ist)
    assert last_finished_session(fri_night).isoformat() == "2026-11-06"
    assert last_finished_session(sun).isoformat() == "2026-11-06"
    assert last_finished_session(mon_morning).isoformat() == "2026-11-06"
    idx = pd.bdate_range("2026-11-02", "2026-11-05")
    thu = {"nifty": pd.DataFrame({"Close": range(len(idx))}, index=idx)}
    assert not _cache_is_current(thu, fri_night)
    idx2 = pd.bdate_range("2026-11-02", "2026-11-06")
    fri = {"nifty": pd.DataFrame({"Close": range(len(idx2))}, index=idx2)}
    assert _cache_is_current(fri, sun)
