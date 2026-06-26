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
            @Query("limit") int limit,
            @Query("offset") int offset
    );

    @GET("api/news/sentiment-summary")
    Call<JsonObject> getSentimentSummary(@Query("hours") int hours);

    // ---- Watchlist ----
    @GET("api/watchlist/{device_id}")
    Call<JsonObject> getWatchlist(@Path("device_id") String deviceId);

    @POST("api/watchlist")
    Call<JsonObject> addToWatchlist(@Body JsonObject body);

    @DELETE("api/watchlist/{watchlist_id}")
    Call<JsonObject> removeFromWatchlist(@Path("watchlist_id") int watchlistId);

    @DELETE("api/watchlist/stock/{device_id}/{stock_id}")
    Call<JsonObject> removeStockFromWatchlist(
            @Path("device_id") String deviceId,
            @Path("stock_id") int stockId
    );

    // ---- Notifications ----
    @POST("api/register-device")
    Call<JsonObject> registerDevice(@Body JsonObject body);

    // ---- Health ----
    @GET("health")
    Call<JsonObject> healthCheck();
}
