package com.stocksentinel.data.api;

import com.stocksentinel.BuildConfig;
import com.stocksentinel.util.Constants;

import java.util.concurrent.TimeUnit;

import okhttp3.OkHttpClient;
import okhttp3.logging.HttpLoggingInterceptor;
import retrofit2.Retrofit;
import retrofit2.converter.gson.GsonConverterFactory;

/**
 * Singleton Retrofit client for the StockSentinel API.
 */
public class ApiClient {

    private static Retrofit retrofit = null;
    private static StockApi api = null;

    public static StockApi getApi() {
        if (api == null) {
            api = getRetrofit().create(StockApi.class);
        }
        return api;
    }

    private static Retrofit getRetrofit() {
        if (retrofit == null) {
            HttpLoggingInterceptor logging = new HttpLoggingInterceptor();
            // No network logs in release builds; debug logs never print headers (API key).
            logging.setLevel(BuildConfig.DEBUG
                    ? HttpLoggingInterceptor.Level.BASIC : HttpLoggingInterceptor.Level.NONE);
            logging.redactHeader("X-API-Key");

            OkHttpClient client = new OkHttpClient.Builder()
                    .connectTimeout(30, TimeUnit.SECONDS)
                    .readTimeout(30, TimeUnit.SECONDS)
                    .writeTimeout(15, TimeUnit.SECONDS)
                    // Every request carries the app's API key (the backend rejects calls without it)
                    .addInterceptor(chain -> chain.proceed(chain.request().newBuilder()
                            .header("X-API-Key", BuildConfig.API_KEY)
                            .build()))
                    .addInterceptor(logging)
                    .build();

            retrofit = new Retrofit.Builder()
                    .baseUrl(Constants.BASE_URL)
                    .client(client)
                    .addConverterFactory(GsonConverterFactory.create())
                    .build();
        }
        return retrofit;
    }
}
