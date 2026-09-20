package com.stocksentinel.ui.home;

import android.content.Intent;
import android.graphics.Color;
import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.LinearLayout;
import android.widget.TextView;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.stocksentinel.R;
import com.stocksentinel.data.api.ApiClient;
import com.stocksentinel.ui.stockdetail.StockDetailActivity;
import com.stocksentinel.util.FormatUtils;

import java.util.ArrayList;
import java.util.List;

import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;

/**
 * Home Fragment — Institutional Market Intelligence Terminal
 * Displays Weekly Movers Radar, live indices, sentiment pulse, and top market movers.
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

    // Weekly Movers Radar
    private RecyclerView weeklyMoversRecycler;
    private WeeklyMoversAdapter weeklyMoversAdapter;

    // AI Research Picks (Top 10)
    private RecyclerView researchPicksRecycler;
    private ResearchPicksAdapter researchPicksAdapter;

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

        // Core bindings
        swipeRefresh = view.findViewById(R.id.swipe_refresh);
        indicesContainer = view.findViewById(R.id.indices_container);
        gainersContainer = view.findViewById(R.id.gainers_container);
        losersContainer = view.findViewById(R.id.losers_container);
        sentimentBullish = view.findViewById(R.id.sentiment_bullish);
        sentimentBearish = view.findViewById(R.id.sentiment_bearish);
        sentimentNeutral = view.findViewById(R.id.sentiment_neutral);
        stockCountText = view.findViewById(R.id.stock_count);

        // Weekly Movers Radar setup
        weeklyMoversRecycler = view.findViewById(R.id.weekly_movers_recycler);
        weeklyMoversRecycler.setLayoutManager(new LinearLayoutManager(requireContext(), LinearLayoutManager.HORIZONTAL, false));
        weeklyMoversAdapter = new WeeklyMoversAdapter(mover -> {
            String sym = mover.has("symbol") ? mover.get("symbol").getAsString() : "";
            String ex = mover.has("exchange") ? mover.get("exchange").getAsString() : "NSE";
            String name = mover.has("name") ? mover.get("name").getAsString() : sym;

            Intent intent = new Intent(requireContext(), StockDetailActivity.class);
            intent.putExtra(StockDetailActivity.EXTRA_SYMBOL, sym);
            intent.putExtra(StockDetailActivity.EXTRA_EXCHANGE, ex);
            intent.putExtra(StockDetailActivity.EXTRA_NAME, name);
            startActivity(intent);
        });
        weeklyMoversRecycler.setAdapter(weeklyMoversAdapter);

        // AI Research Picks setup
        researchPicksRecycler = view.findViewById(R.id.research_picks_recycler);
        researchPicksRecycler.setLayoutManager(new LinearLayoutManager(requireContext()));
        researchPicksRecycler.setNestedScrollingEnabled(false);
        researchPicksAdapter = new ResearchPicksAdapter(pick -> {
            String sym = pick.has("symbol") ? pick.get("symbol").getAsString() : "";
            String ex = pick.has("exchange") ? pick.get("exchange").getAsString() : "NSE";
            String name = pick.has("name") ? pick.get("name").getAsString() : sym;

            Intent intent = new Intent(requireContext(), StockDetailActivity.class);
            intent.putExtra(StockDetailActivity.EXTRA_SYMBOL, sym);
            intent.putExtra(StockDetailActivity.EXTRA_EXCHANGE, ex);
            intent.putExtra(StockDetailActivity.EXTRA_NAME, name);
            startActivity(intent);
        });
        researchPicksRecycler.setAdapter(researchPicksAdapter);

        // SwipeRefresh setup
        swipeRefresh.setOnRefreshListener(this::loadAllData);
        swipeRefresh.setColorSchemeResources(R.color.green_accent, R.color.red_accent, R.color.blue_accent);

        loadAllData();
    }

    private void loadAllData() {
        swipeRefresh.setRefreshing(true);
        loadWeeklyMovers();
        loadResearchPicks();
        loadIndices();
        loadGainers();
        loadLosers();
        loadSentiment();
        loadStockCount();
    }


    private void loadWeeklyMovers() {
        ApiClient.getApi().getWeeklyMovers(10).enqueue(new Callback<JsonObject>() {
            @Override
            public void onResponse(@NonNull Call<JsonObject> call, @NonNull Response<JsonObject> response) {
                if (response.isSuccessful() && response.body() != null && isAdded()) {
                    JsonArray movers = response.body().getAsJsonArray("movers");
                    if (movers != null && weeklyMoversAdapter != null) {
                        weeklyMoversAdapter.setItems(movers);
                    }
                }
            }

            @Override
            public void onFailure(@NonNull Call<JsonObject> call, @NonNull Throwable t) { }
        });
    }

    private void loadResearchPicks() {
        ApiClient.getApi().getScreenerResults(null, null, null, 50f, false, false, 10)
                .enqueue(new Callback<JsonObject>() {
            @Override
            public void onResponse(@NonNull Call<JsonObject> call, @NonNull Response<JsonObject> response) {
                if (response.isSuccessful() && response.body() != null && isAdded()) {
                    JsonArray stocks = response.body().getAsJsonArray("stocks");
                    if (stocks != null && researchPicksAdapter != null) {
                        researchPicksAdapter.setItems(stocks);
                    }
                }
            }

            @Override
            public void onFailure(@NonNull Call<JsonObject> call, @NonNull Throwable t) { }
        });
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

        final String finalSym = sym;
        final String finalEx = stock.has("exchange") ? stock.get("exchange").getAsString() : "NSE";
        final String finalName = stock.has("name") ? stock.get("name").getAsString() : sym;
        row.setOnClickListener(v -> {
            Intent intent = new Intent(requireContext(), StockDetailActivity.class);
            intent.putExtra(StockDetailActivity.EXTRA_SYMBOL, finalSym);
            intent.putExtra(StockDetailActivity.EXTRA_EXCHANGE, finalEx);
            intent.putExtra(StockDetailActivity.EXTRA_NAME, finalName);
            startActivity(intent);
        });

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

    // ---------------------------------------------------------------------------
    // Weekly Movers Adapter
    // ---------------------------------------------------------------------------
    private static class WeeklyMoversAdapter extends RecyclerView.Adapter<WeeklyMoversAdapter.VH> {
        private final List<JsonObject> items = new ArrayList<>();
        private final OnMoverClickListener listener;

        interface OnMoverClickListener {
            void onMoverClick(JsonObject mover);
        }

        WeeklyMoversAdapter(OnMoverClickListener listener) {
            this.listener = listener;
        }

        void setItems(JsonArray array) {
            items.clear();
            for (JsonElement el : array) {
                items.add(el.getAsJsonObject());
            }
            notifyDataSetChanged();
        }

        @NonNull
        @Override
        public VH onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
            View v = LayoutInflater.from(parent.getContext())
                    .inflate(R.layout.item_weekly_mover, parent, false);
            return new VH(v);
        }

        @Override
        public void onBindViewHolder(@NonNull VH holder, int position) {
            JsonObject item = items.get(position);
            String symbol = item.has("symbol") ? item.get("symbol").getAsString() : "";
            String name = item.has("name") ? item.get("name").getAsString() : symbol;
            String trend = item.has("expected_trend") ? item.get("expected_trend").getAsString() : "BULLISH";
            String badge = item.has("catalyst_badge") ? item.get("catalyst_badge").getAsString() : "Catalyst";
            String summary = item.has("catalyst_summary") ? item.get("catalyst_summary").getAsString() : "";
            Double price = item.has("current_price") && !item.get("current_price").isJsonNull()
                    ? item.get("current_price").getAsDouble() : null;
            Double pct = item.has("change_pct") && !item.get("change_pct").isJsonNull()
                    ? item.get("change_pct").getAsDouble() : null;
            String currency = item.has("currency") ? item.get("currency").getAsString() : "INR";

            holder.symbolText.setText(symbol);
            holder.nameText.setText(name);
            holder.trendBadge.setText(trend.replace("_", " "));
            holder.catalystBadge.setText(badge);
            holder.summaryText.setText(summary);
            holder.priceText.setText(FormatUtils.formatPrice(price, currency));
            holder.changeText.setText(FormatUtils.formatChangePercent(pct));
            holder.changeText.setTextColor(FormatUtils.getChangeColor(pct));

            if (trend.contains("BULLISH")) {
                holder.trendBadge.setTextColor(Color.parseColor("#FF00E676"));
            } else if (trend.contains("BEARISH")) {
                holder.trendBadge.setTextColor(Color.parseColor("#FFFF5252"));
            } else {
                holder.trendBadge.setTextColor(Color.parseColor("#FFFFD740"));
            }

            holder.itemView.setOnClickListener(v -> {
                if (listener != null) listener.onMoverClick(item);
            });
        }

        @Override
        public int getItemCount() {
            return items.size();
        }

        static class VH extends RecyclerView.ViewHolder {
            TextView symbolText, trendBadge, nameText, catalystBadge, summaryText, priceText, changeText;

            VH(View v) {
                super(v);
                symbolText = v.findViewById(R.id.mover_symbol);
                trendBadge = v.findViewById(R.id.mover_trend_badge);
                nameText = v.findViewById(R.id.mover_name);
                catalystBadge = v.findViewById(R.id.mover_catalyst_badge);
                summaryText = v.findViewById(R.id.mover_summary);
                priceText = v.findViewById(R.id.mover_price);
                changeText = v.findViewById(R.id.mover_change);
            }
        }
    }

    // -------------------------------------------------------------------------
    // AI Research Picks Adapter
    // -------------------------------------------------------------------------
    interface OnPickClickListener {
        void onPickClick(JsonObject pick);
    }

    static class ResearchPicksAdapter extends RecyclerView.Adapter<ResearchPicksAdapter.VH> {
        private final List<JsonObject> items = new ArrayList<>();
        private final OnPickClickListener listener;

        ResearchPicksAdapter(OnPickClickListener listener) {
            this.listener = listener;
        }

        public void setItems(JsonArray array) {
            items.clear();
            if (array != null) {
                for (JsonElement el : array) {
                    if (el.isJsonObject()) items.add(el.getAsJsonObject());
                }
            }
            notifyDataSetChanged();
        }

        @NonNull
        @Override
        public VH onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
            View v = LayoutInflater.from(parent.getContext())
                    .inflate(R.layout.item_research_pick, parent, false);
            return new VH(v);
        }

        @Override
        public void onBindViewHolder(@NonNull VH holder, int position) {
            JsonObject item = items.get(position);
            String symbol = item.has("symbol") ? item.get("symbol").getAsString() : "";
            String grade = item.has("research_grade") ? item.get("research_grade").getAsString() : "B";
            String action = item.has("action") ? item.get("action").getAsString() : "ACCUMULATE";
            String reason = item.has("key_reason") ? item.get("key_reason").getAsString() : "";
            double score = item.has("composite_score") ? item.get("composite_score").getAsDouble() : 0.0;
            Double price = item.has("current_price") && !item.get("current_price").isJsonNull()
                    ? item.get("current_price").getAsDouble() : null;
            Double pct = item.has("change_pct") && !item.get("change_pct").isJsonNull()
                    ? item.get("change_pct").getAsDouble() : null;
            String currency = item.has("currency") ? item.get("currency").getAsString() : "INR";

            holder.gradeText.setText(grade);
            holder.symbolText.setText(symbol);
            holder.actionText.setText(action.replace("_", " "));
            holder.reasonText.setText(reason.isEmpty() ? "Multi-factor ML screened" : reason);
            holder.scoreText.setText(String.format(java.util.Locale.US, "AI Score: %.1f/100", score));
            holder.priceText.setText(FormatUtils.formatPrice(price, currency));
            holder.changeText.setText(FormatUtils.formatChangePercent(pct));
            holder.changeText.setTextColor(FormatUtils.getChangeColor(pct));

            // Grade styling
            if (grade.startsWith("A")) {
                holder.gradeText.setTextColor(Color.parseColor("#FF00E676"));
            } else if (grade.startsWith("B")) {
                holder.gradeText.setTextColor(Color.parseColor("#FF2979FF"));
            } else if (grade.startsWith("C")) {
                holder.gradeText.setTextColor(Color.parseColor("#FFFFD740"));
            } else {
                holder.gradeText.setTextColor(Color.parseColor("#FFFF5252"));
            }

            // Action badge styling
            if (action.contains("BUY") || action.contains("ACCUMULATE")) {
                holder.actionText.setTextColor(Color.parseColor("#FF00E676"));
            } else if (action.contains("SELL") || action.contains("AVOID")) {
                holder.actionText.setTextColor(Color.parseColor("#FFFF5252"));
            } else {
                holder.actionText.setTextColor(Color.parseColor("#FFFFD740"));
            }

            holder.itemView.setOnClickListener(v -> {
                if (listener != null) listener.onPickClick(item);
            });
        }

        @Override
        public int getItemCount() {
            return items.size();
        }

        static class VH extends RecyclerView.ViewHolder {
            TextView gradeText, symbolText, actionText, reasonText, scoreText, priceText, changeText;

            VH(View v) {
                super(v);
                gradeText = v.findViewById(R.id.pick_grade);
                symbolText = v.findViewById(R.id.pick_symbol);
                actionText = v.findViewById(R.id.pick_action);
                reasonText = v.findViewById(R.id.pick_reason);
                scoreText = v.findViewById(R.id.pick_score);
                priceText = v.findViewById(R.id.pick_price);
                changeText = v.findViewById(R.id.pick_change);
            }
        }
    }
}
