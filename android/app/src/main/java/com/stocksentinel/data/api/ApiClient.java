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
                    .addInterceptor(chain -> {
                        okhttp3.Request.Builder b = chain.request().newBuilder();
                        // Only send a key that HTTP headers can carry (printable ASCII). A key with
                        // any other character would make every request fail before it is sent.
                        if (isValidHeaderValue(API_KEY)) b.header("X-API-Key", API_KEY);
                        return chain.proceed(b.build());
                    })
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

    private static final String API_KEY = BuildConfig.API_KEY == null ? "" : BuildConfig.API_KEY.trim();

    /** True when the key is non-empty and made only of printable ASCII characters. */
    static boolean isValidHeaderValue(String v) {
        if (v == null || v.isEmpty()) return false;
        for (int i = 0; i < v.length(); i++) {
            char c = v.charAt(i);
            if (c < 0x21 || c > 0x7e) return false;
        }
        return true;
    }
}
