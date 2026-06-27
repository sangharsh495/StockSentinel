package com.stocksentinel.ui.home;

import android.animation.ValueAnimator;
import android.content.Context;
import android.content.SharedPreferences;
import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.view.animation.DecelerateInterpolator;
import android.widget.LinearLayout;
import android.widget.TextView;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout;

import com.google.android.material.button.MaterialButton;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.stocksentinel.R;
import com.stocksentinel.data.api.ApiClient;
import com.stocksentinel.util.FormatUtils;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;

/**
 * Home Fragment — Upgraded INDmoney-style Wealth Dashboard with interactive settings,
 * canvas-based trend charts, and original market stats.
 */
public class HomeFragment extends Fragment implements WealthSettingsBottomSheet.OnWealthSavedListener {

    private SwipeRefreshLayout swipeRefresh;
    private LinearLayout indicesContainer;
    private LinearLayout gainersContainer;
    private LinearLayout losersContainer;
    private TextView sentimentBullish;
    private TextView sentimentBearish;
    private TextView sentimentNeutral;
    private TextView stockCountText;

    // Wealth UI components
    private View wealthCard;
    private TextView txtNetWorth;
    private TextView txtWealthChange;
    private MaterialButton btnAdjustBalances;
    private LineChartView wealthTrendChart;
    private View chartTraceContainer;
    private TextView txtTraceDate;
    private TextView txtTraceValue;

    private TextView txtValIndian;
    private TextView txtValUs;
    private TextView txtValMf;
    private TextView txtValCash;

    // Wealth state
    private float valIndian;
    private float valUs;
    private float valMf;
    private float valCash;
    private float totalNetWorth;

    private SharedPreferences prefs;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        return inflater.inflate(R.layout.fragment_home, container, false);
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        super.onViewCreated(view, savedInstanceState);

        prefs = requireContext().getSharedPreferences("stocksentinel_wealth", Context.MODE_PRIVATE);

        // Core bindings
        swipeRefresh = view.findViewById(R.id.swipe_refresh);
        indicesContainer = view.findViewById(R.id.indices_container);
        gainersContainer = view.findViewById(R.id.gainers_container);
        losersContainer = view.findViewById(R.id.losers_container);
        sentimentBullish = view.findViewById(R.id.sentiment_bullish);
        sentimentBearish = view.findViewById(R.id.sentiment_bearish);
        sentimentNeutral = view.findViewById(R.id.sentiment_neutral);
        stockCountText = view.findViewById(R.id.stock_count);

        // Wealth bindings
        wealthCard = view.findViewById(R.id.wealth_card);
        txtNetWorth = view.findViewById(R.id.txt_net_worth);
        txtWealthChange = view.findViewById(R.id.txt_wealth_change);
        btnAdjustBalances = view.findViewById(R.id.btn_adjust_balances);
        wealthTrendChart = view.findViewById(R.id.wealth_trend_chart);
        chartTraceContainer = view.findViewById(R.id.chart_trace_container);
        txtTraceDate = view.findViewById(R.id.txt_trace_date);
        txtTraceValue = view.findViewById(R.id.txt_trace_value);

        txtValIndian = view.findViewById(R.id.txt_val_indian);
        txtValUs = view.findViewById(R.id.txt_val_us);
        txtValMf = view.findViewById(R.id.txt_val_mf);
        txtValCash = view.findViewById(R.id.txt_val_cash);

        // Set SwipeRefresh Layout setup
        swipeRefresh.setOnRefreshListener(this::loadAllData);
        swipeRefresh.setColorSchemeResources(R.color.green_accent, R.color.red_accent, R.color.blue_accent);

        // Load wealth data first
        loadWealthData();

        // Dynamic adjust buttons
        btnAdjustBalances.setOnClickListener(v -> showWealthSettings());

        // Dynamic interactive line chart touch trace listener
        wealthTrendChart.setOnSelectedPointListener(new LineChartView.OnSelectedPointListener() {
            @Override
            public void onPointSelected(int index, float value, String label) {
                chartTraceContainer.setVisibility(View.VISIBLE);
                txtTraceDate.setText(label);
                txtTraceValue.setText(FormatUtils.formatPrice((double) value, "INR"));
            }

            @Override
            public void onSelectionCleared() {
                chartTraceContainer.setVisibility(View.GONE);
            }
        });

        // Trigger entrance animations
        wealthCard.setAlpha(0f);
        wealthCard.setTranslationY(100f);
        wealthCard.animate()
                .alpha(1f)
                .translationY(0f)
                .setDuration(600)
                .setInterpolator(new DecelerateInterpolator())
                .start();

        loadAllData();
    }

    private void loadWealthData() {
        // Load default values (10L, 5L, 8L, 1.5L) if not set
        valIndian = prefs.getFloat("val_indian", 1000000f);
        valUs = prefs.getFloat("val_us", 500000f);
        valMf = prefs.getFloat("val_mf", 800000f);
        valCash = prefs.getFloat("val_cash", 150000f);

        float oldTotal = totalNetWorth;
        totalNetWorth = valIndian + valUs + valMf + valCash;

        // Dynamic counter rolling animation
        animateNetWorthCounter(oldTotal, totalNetWorth);

        // Update static asset distribution texts
        txtValIndian.setText(FormatUtils.formatPrice((double) valIndian, "INR"));
        txtValUs.setText(FormatUtils.formatPrice((double) valUs, "INR"));
        txtValMf.setText(FormatUtils.formatPrice((double) valMf, "INR"));
        txtValCash.setText(FormatUtils.formatPrice((double) valCash, "INR"));

        // Build premium line chart dataset (historical 7 days based on current assets + random variations)
        updateWealthChart();
    }

    private void animateNetWorthCounter(float fromValue, float toValue) {
        ValueAnimator animator = ValueAnimator.ofFloat(fromValue, toValue);
        animator.setDuration(1000);
        animator.setInterpolator(new DecelerateInterpolator());
        animator.addUpdateListener(animation -> {
            float val = (float) animation.getAnimatedValue();
            txtNetWorth.setText(FormatUtils.formatPrice((double) val, "INR"));
        });
        animator.start();

        // Calculate and format daily percentage change (randomized mockup change)
        double simulatedChangePct = 0.68;
        double simulatedChangeVal = toValue * (simulatedChangePct / 100.0);
        txtWealthChange.setText(String.format(Locale.getDefault(), 
                "+%s (+%.2f%%) Today", 
                FormatUtils.formatPrice(simulatedChangeVal, "INR"), 
                simulatedChangePct
        ));
    }

    private void updateWealthChart() {
        List<Float> points = new ArrayList<>();
        List<String> labels = new ArrayList<>();

        // Generate 7 days of simulated history ending in the current net worth
        float baseNetWorth = totalNetWorth;
        float[] factors = { 0.962f, 0.978f, 0.971f, 0.985f, 0.981f, 0.994f, 1.0f };
        String[] days = { "21 Jun", "22 Jun", "23 Jun", "24 Jun", "25 Jun", "26 Jun", "Today" };

        for (int i = 0; i < 7; i++) {
            points.add(baseNetWorth * factors[i]);
            labels.add(days[i]);
        }

        wealthTrendChart.setData(points, labels);
    }

    private void showWealthSettings() {
        WealthSettingsBottomSheet bottomSheet = WealthSettingsBottomSheet.newInstance(
                valIndian, valUs, valMf, valCash
        );
        bottomSheet.setOnWealthSavedListener(this);
        bottomSheet.show(getParentFragmentManager(), "wealth_settings");
    }

    @Override
    public void onWealthSaved(float indian, float us, float mf, float cash) {
        // Save back to preferences
        prefs.edit()
                .putFloat("val_indian", indian)
                .putFloat("val_us", us)
                .putFloat("val_mf", mf)
                .putFloat("val_cash", cash)
                .apply();

        // Reload wealth layout and values
        loadWealthData();
    }

    private void loadAllData() {
        swipeRefresh.setRefreshing(true);
        loadIndices();
        loadGainers();
        loadLosers();
        loadSentiment();
        loadStockCount();
    }

    private void loadIndices() {
        ApiClient.getApi().getMarketIndices().enqueue(new Callback<JsonObject>() {
            @Override
            public void onResponse(@NonNull Call<JsonObject> call, @NonNull Response<JsonObject> response) {
                if (response.isSuccessful() && response.body() != null && isAdded()) {
                    JsonArray indices = response.body().getAsJsonArray("indices");
                    indicesContainer.removeAllViews();
                    for (JsonElement el : indices) {
                        JsonObject idx = el.getAsJsonObject();
                        addIndexCard(idx);
                    }
                }
                if (isAdded()) swipeRefresh.setRefreshing(false);
            }

            @Override
            public void onFailure(@NonNull Call<JsonObject> call, @NonNull Throwable t) {
                if (isAdded()) swipeRefresh.setRefreshing(false);
            }
        });
    }

    private void addIndexCard(JsonObject index) {
        View card = LayoutInflater.from(requireContext())
                .inflate(R.layout.item_index_card, indicesContainer, false);

        TextView nameText = card.findViewById(R.id.index_name);
        TextView priceText = card.findViewById(R.id.index_price);
        TextView changeText = card.findViewById(R.id.index_change);

        String name = index.has("name") && !index.get("name").isJsonNull()
                ? index.get("name").getAsString() : "—";
        Double price = index.has("current_price") && !index.get("current_price").isJsonNull()
                ? index.get("current_price").getAsDouble() : null;
        Double pct = index.has("change_pct") && !index.get("change_pct").isJsonNull()
                ? index.get("change_pct").getAsDouble() : null;
        String market = index.has("market") && !index.get("market").isJsonNull()
                ? index.get("market").getAsString() : "IN";

        nameText.setText(name);
        priceText.setText(FormatUtils.formatPrice(price, "IN".equals(market) ? "INR" : "USD"));
        changeText.setText(FormatUtils.formatChangePercent(pct));
        changeText.setTextColor(FormatUtils.getChangeColor(pct));

        indicesContainer.addView(card);
    }

    private void loadGainers() {
        ApiClient.getApi().getTopGainers(null, 5).enqueue(new Callback<JsonObject>() {
            @Override
            public void onResponse(@NonNull Call<JsonObject> call, @NonNull Response<JsonObject> response) {
                if (response.isSuccessful() && response.body() != null && isAdded()) {
                    JsonArray stocks = response.body().getAsJsonArray("stocks");
                    gainersContainer.removeAllViews();
                    for (JsonElement el : stocks) {
                        addStockRow(gainersContainer, el.getAsJsonObject());
                    }
                }
            }

            @Override
            public void onFailure(@NonNull Call<JsonObject> call, @NonNull Throwable t) { }
        });
    }

    private void loadLosers() {
        ApiClient.getApi().getTopLosers(null, 5).enqueue(new Callback<JsonObject>() {
            @Override
            public void onResponse(@NonNull Call<JsonObject> call, @NonNull Response<JsonObject> response) {
                if (response.isSuccessful() && response.body() != null && isAdded()) {
                    JsonArray stocks = response.body().getAsJsonArray("stocks");
                    losersContainer.removeAllViews();
                    for (JsonElement el : stocks) {
                        addStockRow(losersContainer, el.getAsJsonObject());
                    }
                }
            }

            @Override
            public void onFailure(@NonNull Call<JsonObject> call, @NonNull Throwable t) { }
        });
    }

    private void addStockRow(LinearLayout container, JsonObject stock) {
        View row = LayoutInflater.from(requireContext())
                .inflate(R.layout.item_stock_row, container, false);

        TextView symbol = row.findViewById(R.id.stock_symbol);
        TextView price = row.findViewById(R.id.stock_price);
        TextView change = row.findViewById(R.id.stock_change);

        String sym = stock.has("symbol") ? stock.get("symbol").getAsString() : "";
        Double p = stock.has("current_price") && !stock.get("current_price").isJsonNull()
                ? stock.get("current_price").getAsDouble() : null;
        Double pct = stock.has("change_pct") && !stock.get("change_pct").isJsonNull()
                ? stock.get("change_pct").getAsDouble() : null;
        String currency = stock.has("currency") && !stock.get("currency").isJsonNull()
                ? stock.get("currency").getAsString() : "INR";

        symbol.setText(sym);
        price.setText(FormatUtils.formatPrice(p, currency));
        change.setText(FormatUtils.formatChangePercent(pct));
        change.setTextColor(FormatUtils.getChangeColor(pct));

        container.addView(row);
    }

    private void loadSentiment() {
        ApiClient.getApi().getSentimentSummary(24).enqueue(new Callback<JsonObject>() {
            @Override
            public void onResponse(@NonNull Call<JsonObject> call, @NonNull Response<JsonObject> response) {
                if (response.isSuccessful() && response.body() != null && isAdded()) {
                    JsonObject data = response.body();
                    double bullish = data.has("bullish_pct") ? data.get("bullish_pct").getAsDouble() : 0;
                    double bearish = data.has("bearish_pct") ? data.get("bearish_pct").getAsDouble() : 0;
                    double neutral = data.has("neutral_pct") ? data.get("neutral_pct").getAsDouble() : 0;

                    sentimentBullish.setText(String.format("🟢 %.0f%% Bullish", bullish));
                    sentimentBearish.setText(String.format("🔴 %.0f%% Bearish", bearish));
                    sentimentNeutral.setText(String.format("⚪ %.0f%% Neutral", neutral));
                }
            }

            @Override
            public void onFailure(@NonNull Call<JsonObject> call, @NonNull Throwable t) { }
        });
    }

    private void loadStockCount() {
        ApiClient.getApi().getStockCount().enqueue(new Callback<JsonObject>() {
            @Override
            public void onResponse(@NonNull Call<JsonObject> call, @NonNull Response<JsonObject> response) {
                if (response.isSuccessful() && response.body() != null && isAdded()) {
                    int total = response.body().has("total") ? response.body().get("total").getAsInt() : 0;
                    stockCountText.setText(String.format("Tracking %,d stocks", total));
                }
            }

            @Override
            public void onFailure(@NonNull Call<JsonObject> call, @NonNull Throwable t) { }
        });
    }
}
