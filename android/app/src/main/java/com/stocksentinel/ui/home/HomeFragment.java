package com.stocksentinel.ui.home;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.LinearLayout;
import android.widget.TextView;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.stocksentinel.R;
import com.stocksentinel.data.api.ApiClient;
import com.stocksentinel.util.FormatUtils;

import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;

/**
 * Home Fragment — Market summary, indices, top gainers/losers, sentiment gauge.
 */
public class HomeFragment extends Fragment {

    private SwipeRefreshLayout swipeRefresh;
    private LinearLayout indicesContainer;
    private LinearLayout gainersContainer;
    private LinearLayout losersContainer;
    private TextView sentimentBullish;
    private TextView sentimentBearish;
    private TextView sentimentNeutral;
    private TextView stockCountText;

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

        swipeRefresh = view.findViewById(R.id.swipe_refresh);
        indicesContainer = view.findViewById(R.id.indices_container);
        gainersContainer = view.findViewById(R.id.gainers_container);
        losersContainer = view.findViewById(R.id.losers_container);
        sentimentBullish = view.findViewById(R.id.sentiment_bullish);
        sentimentBearish = view.findViewById(R.id.sentiment_bearish);
        sentimentNeutral = view.findViewById(R.id.sentiment_neutral);
        stockCountText = view.findViewById(R.id.stock_count);

        swipeRefresh.setOnRefreshListener(this::loadAllData);
        swipeRefresh.setColorSchemeResources(R.color.green_accent, R.color.red_accent, R.color.blue_accent);

        loadAllData();
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
