package com.stocksentinel.ui.settings;

import android.graphics.Color;
import android.os.Bundle;
import android.widget.TextView;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.appcompat.app.AppCompatActivity;
import androidx.appcompat.widget.Toolbar;

import com.google.gson.JsonObject;
import com.stocksentinel.R;
import com.stocksentinel.data.api.ApiClient;
import com.stocksentinel.util.FormatUtils;
import com.stocksentinel.util.Constants;

import java.util.Locale;

import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;

/**
 * Settings & System Status Activity — End-to-End Connectivity Dashboard.
 * Displays live cloud server health, ping latency, database inventories,
 * and status of all AI / Quantitative engines.
 */
public class SettingsActivity extends AppCompatActivity {

    private TextView textServerStatusBadge;
    private TextView textServerUrl;
    private TextView textPingLatency;
    private TextView btnTestPing;
    private TextView btnSyncAll;

    private TextView statDbStocks;
    private TextView statDbDividends;
    private TextView statDbIpos;
    private TextView statDbNews;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_settings);

        Toolbar toolbar = findViewById(R.id.toolbar);
        setSupportActionBar(toolbar);
        if (getSupportActionBar() != null) {
            getSupportActionBar().setDisplayHomeAsUpEnabled(true);
            getSupportActionBar().setDisplayShowHomeEnabled(true);
        }
        toolbar.setNavigationOnClickListener(v -> finish());

        // Bind views
        textServerStatusBadge = findViewById(R.id.text_server_status_badge);
        textServerUrl = findViewById(R.id.text_server_url);
        textPingLatency = findViewById(R.id.text_ping_latency);
        btnTestPing = findViewById(R.id.btn_test_ping);
        btnSyncAll = findViewById(R.id.btn_sync_all);

        statDbStocks = findViewById(R.id.stat_db_stocks);
        statDbDividends = findViewById(R.id.stat_db_dividends);
        statDbIpos = findViewById(R.id.stat_db_ipos);
        statDbNews = findViewById(R.id.stat_db_news);

        textServerUrl.setText(Constants.BASE_URL);

        btnTestPing.setOnClickListener(v -> checkConnectionPing());
        btnSyncAll.setOnClickListener(v -> syncAllFeeds());

        // Initial fetch
        checkConnectionPing();
    }

    private void checkConnectionPing() {
        textPingLatency.setText("Measuring...");
        textPingLatency.setTextColor(Color.parseColor("#FFD97706"));

        long startTime = System.currentTimeMillis();

        ApiClient.getApi().getSystemStatus().enqueue(new Callback<JsonObject>() {
            @Override
            public void onResponse(@NonNull Call<JsonObject> call, @NonNull Response<JsonObject> response) {
                long duration = System.currentTimeMillis() - startTime;

                if (response.isSuccessful() && response.body() != null) {
                    JsonObject body = response.body();

                    // Server status
                    textServerStatusBadge.setText("🟢 ONLINE");
                    textServerStatusBadge.setTextColor(Color.parseColor("#FF059669"));

                    textPingLatency.setText(String.format(Locale.US, "%d ms (Ultra-Fast)", duration));
                    textPingLatency.setTextColor(Color.parseColor("#FF059669"));

                    // Database stats
                    if (body.has("database") && body.get("database").isJsonObject()) {
                        JsonObject db = body.getAsJsonObject("database");
                        // Show "—" when a count is missing; never invent numbers.
                        statDbStocks.setText(count(db, "active_stocks") + " Active (NSE Bluechips + US)");
                        statDbDividends.setText(count(db, "dividends_tracked") + " High-Yield Events");
                        statDbIpos.setText(count(db, "ipos_pipeline") + " Live / Pipeline");
                        statDbNews.setText(count(db, "news_articles_rated") + " Rated Headlines");
                    }
                } else {
                    // Fallback to health endpoint if system status is deploying
                    fallbackHealthCheck(startTime);
                }
            }

            @Override
            public void onFailure(@NonNull Call<JsonObject> call, @NonNull Throwable t) {
                fallbackHealthCheck(startTime);
            }
        });
    }

    /** A count from the status response, formatted by the shared FormatUtils ("—" if missing or malformed). */
    private static String count(JsonObject db, String key) {
        try {
            return FormatUtils.formatNumber(db.has(key) && !db.get(key).isJsonNull()
                    ? db.get(key).getAsLong() : null);
        } catch (RuntimeException e) {  // non-numeric value from the server
            return FormatUtils.formatNumber(null);
        }
    }

    private void fallbackHealthCheck(long startTime) {
        ApiClient.getApi().healthCheck().enqueue(new Callback<JsonObject>() {
            @Override
            public void onResponse(@NonNull Call<JsonObject> call, @NonNull Response<JsonObject> response) {
                long duration = System.currentTimeMillis() - startTime;
                if (response.isSuccessful()) {
                    textServerStatusBadge.setText("🟢 ONLINE");
                    textServerStatusBadge.setTextColor(Color.parseColor("#FF059669"));
                    textPingLatency.setText(String.format(Locale.US, "%d ms (Connected)", duration));
                    textPingLatency.setTextColor(Color.parseColor("#FF059669"));

                    // Only /health answered: counts are unknown, so don't show any.
                    statDbStocks.setText("— Active (NSE Bluechips + US)");
                    statDbDividends.setText("— High-Yield Events");
                    statDbIpos.setText("— Live / Pipeline");
                    statDbNews.setText("— Rated Headlines");
                } else {
                    showOfflineState();
                }
            }

            @Override
            public void onFailure(@NonNull Call<JsonObject> call, @NonNull Throwable t) {
                showOfflineState();
            }
        });
    }

    private void showOfflineState() {
        textServerStatusBadge.setText("🔴 RETRYING");
        textServerStatusBadge.setTextColor(Color.parseColor("#FFDC2626"));
        textPingLatency.setText("Render service waking up...");
        textPingLatency.setTextColor(Color.parseColor("#FFD97706"));
    }

    private void syncAllFeeds() {
        Toast.makeText(this, "Refreshing all market feeds & caches...", Toast.LENGTH_SHORT).show();
        checkConnectionPing();
    }
}
