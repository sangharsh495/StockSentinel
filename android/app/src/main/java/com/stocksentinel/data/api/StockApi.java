package com.stocksentinel.data.api;

import com.google.gson.JsonObject;

import retrofit2.Call;
import retrofit2.http.*;

/**
 * Retrofit API interface — all backend endpoints.
 */
public interface StockApi {

    // ---- Stocks ----
    @GET("api/stocks")
    Call<JsonObject> getStocks(
            @Query("market") String market,
            @Query("exchange") String exchange,
            @Query("limit") int limit,
            @Query("offset") int offset
    );

    @GET("api/stocks/search")
    Call<JsonObject> searchStocks(
            @Query("q") String query,
            @Query("limit") int limit
    );

    @GET("api/stocks/top-gainers")
    Call<JsonObject> getTopGainers(
            @Query("market") String market,
            @Query("limit") int limit
    );

    @GET("api/stocks/top-losers")
    Call<JsonObject> getTopLosers(
            @Query("market") String market,
            @Query("limit") int limit
    );

    @GET("api/stocks/indices")
    Call<JsonObject> getMarketIndices();

    @GET("api/stocks/{symbol}")
    Call<JsonObject> getStock(
            @Path("symbol") String symbol,
            @Query("exchange") String exchange
    );

    @GET("api/stocks/count/summary")
    Call<JsonObject> getStockCount();

    // ---- Dividends ----
    @GET("api/dividends")
    Call<JsonObject> getDividends(
            @Query("status") String status,
            @Query("limit") int limit,
            @Query("offset") int offset
    );

    @GET("api/dividends/upcoming")
    Call<JsonObject> getUpcomingDividends(
            @Query("days") int days,
            @Query("limit") int limit
    );

    // ---- IPOs ----
    @GET("api/ipos")
    Call<JsonObject> getIpos(
            @Query("market") String market,
            @Query("status") String status,
            @Query("limit") int limit,
            @Query("offset") int offset
    );

    @GET("api/ipos/upcoming")
    Call<JsonObject> getUpcomingIpos(
            @Query("days") int days,
            @Query("limit") int limit
    );

    // ---- News ----
    @GET("api/news")
    Call<JsonObject> getNews(
            @Query("sentiment") String sentiment,
            @Query("source") String source,
            @Query("dividend_only") Boolean dividendOnly,
            @Query("min_impact") Float minImpact,
            @Query("limit") int limit,
            @Query("offset") int offset
    );

    @GET("api/news/sentiment-summary")
    Call<JsonObject> getSentimentSummary(@Query("hours") int hours);

    @GET("api/news/stock-impact")
    Call<JsonObject> getStockImpactNews(
            @Query("symbol") String symbol,
            @Query("direction") String direction,
            @Query("limit") int limit
    );

    @GET("api/news/dividend-alerts")
    Call<JsonObject> getDividendAlerts(@Query("limit") int limit);

    @GET("api/stocks/{symbol}/news")
    Call<JsonObject> getStockNews(
            @Path("symbol") String symbol,
            @Query("limit") int limit
    );

    // ---- Watchlist ----
    @GET("api/watchlist/{device_id}")
    Call<JsonObject> getWatchlist(@Path("device_id") String deviceId);

    @POST("api/watchlist")
    Call<JsonObject> addToWatchlist(@Body JsonObject body);

    @DELETE("api/watchlist/stock/{device_id}/{stock_id}")
    Call<JsonObject> removeStockFromWatchlist(
            @Path("device_id") String deviceId,
            @Path("stock_id") int stockId
    );

    // ---- Notifications ----
    @POST("api/register-device")
    Call<JsonObject> registerDevice(@Body JsonObject body);

    // ---- Analyst & Intelligence ----
    @GET("api/analyst/weekly-movers")
    Call<JsonObject> getWeeklyMovers(@Query("limit") int limit);

    @GET("api/analyst/extreme-news")
    Call<JsonObject> getExtremeNews(
            @Query("catalyst") String catalyst,
            @Query("limit") int limit
    );

    @GET("api/stocks/{symbol}/dossier")
    Call<JsonObject> getStockDossier(@Path("symbol") String symbol);

    @GET("api/stocks/{symbol}/chart")
    Call<JsonObject> getStockChart(
            @Path("symbol") String symbol,
            @Query("exchange") String exchange,
            @Query("range") String range
    );

    // ---- NEW: Stock Screener (AI Research Picks) ----
    @GET("api/analyst/screener")
    Call<JsonObject> getScreenerResults(
            @Query("sector") String sector,
            @Query("market") String market,
            @Query("min_market_cap") Integer minMarketCap,
            @Query("min_score") Float minScore,
            @Query("has_catalyst") Boolean hasCatalyst,
            @Query("has_dividend") Boolean hasDividend,
            @Query("limit") int limit
    );

    // ---- NEW: Dividend Calendar & History ----
    @GET("api/analyst/dividend-calendar")
    Call<JsonObject> getDividendCalendar(
            @Query("month") int month,
            @Query("year") int year,
            @Query("limit") int limit
    );

    @GET("api/analyst/dividend-history/{symbol}")
    Call<JsonObject> getDividendHistory(@Path("symbol") String symbol);

    // ---- NEW: IPO Research Report ----
    @GET("api/analyst/ipo-report/{ipo_id}")
    Call<JsonObject> getIpoReport(@Path("ipo_id") int ipoId);

    // ---- NEW: Daily News Ranking ----
    @GET("api/analyst/daily-news-ranked")
    Call<JsonObject> getDailyNewsRanked(@Query("date") String date);

    @GET("api/analyst/daily-news-ranked/archive")
    Call<JsonObject> getNewsArchive(@Query("days") int days);

    // ---- NEW: Full Research Report ----
    @GET("api/stocks/{symbol}/research-report")
    Call<JsonObject> getFullResearchReport(@Path("symbol") String symbol);

    // ---- Phase 1 & 2: Buffett Deep Research & Fundamentals ----
    @GET("api/stocks/{symbol}/fundamentals")
    Call<JsonObject> getFundamentals(
            @Path("symbol") String symbol,
            @Query("exchange") String exchange
    );

    @GET("api/stocks/{symbol}/ratios")
    Call<JsonObject> getRatios(
            @Path("symbol") String symbol,
            @Query("exchange") String exchange
    );

    @GET("api/stocks/{symbol}/technicals")
    Call<JsonObject> getTechnicals(
            @Path("symbol") String symbol,
            @Query("exchange") String exchange
    );

    @GET("api/stocks/{symbol}/valuation")
    Call<JsonObject> getValuation(
            @Path("symbol") String symbol,
            @Query("exchange") String exchange
    );

    @GET("api/stocks/{symbol}/quality")
    Call<JsonObject> getQualityScorecard(
            @Path("symbol") String symbol,
            @Query("exchange") String exchange
    );

    @GET("api/stocks/{symbol}/shareholding")
    Call<JsonObject> getShareholding(
            @Path("symbol") String symbol,
            @Query("exchange") String exchange
    );

    @GET("api/stocks/{symbol}/compare")
    Call<JsonObject> compareStocks(
            @Path("symbol") String symbol,
            @Query("symbols") String compareSymbols
    );

    // ---- Quant engine: walk-forward tested models ----
    @GET("api/quant/picks")
    Call<JsonObject> getQuantPicks(
            @Query("strategy") String strategy,
            @Query("limit") int limit
    );

    @GET("api/quant/market-outlook")
    Call<JsonObject> getMarketOutlook();

    @GET("api/quant/ipo-odds")
    Call<JsonObject> getIpoOdds();

    @GET("api/quant/stock/{symbol}")
    Call<JsonObject> getQuantStock(@Path("symbol") String symbol);

    @GET("api/quant/multibagger")
    Call<JsonObject> getMultibaggerRadar();

    @GET("api/quant/report-card/{symbol}")
    Call<JsonObject> getReportCard(@Path("symbol") String symbol, @Query("horizon") String horizon);

    @GET("api/quant/income/calendar")
    Call<JsonObject> getIncomeCalendar(
            @Query("month") int month,
            @Query("min_yield") double minYield,
            @Query("min_score") double minScore,
            @Query("min_years") int minYears,
            @Query("frequency") String frequency,
            @Query("governance") String governance,
            @Query("no_cuts") boolean noCuts,
            @Query("income_buy_only") boolean incomeBuyOnly,
            @Query("sort") String sort,
            @Query("limit") int limit
    );

    @GET("api/quant/best")
    Call<JsonObject> getBestStocks(
            @Query("kind") String kind,
            @Query("horizon") String horizon,
            @Query("limit") int limit
    );

    // ---- Health & System Status ----
    @GET("health")
    Call<JsonObject> healthCheck();

    @GET("api/system/status")
    Call<JsonObject> getSystemStatus();
}

