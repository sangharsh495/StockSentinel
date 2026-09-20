package com.stocksentinel.ui.stocks;

import android.content.Intent;
import android.graphics.Color;
import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.TextView;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout;

import com.google.android.material.chip.Chip;
import com.google.android.material.chip.ChipGroup;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.stocksentinel.R;
import com.stocksentinel.data.api.ApiClient;
import com.stocksentinel.ui.search.SearchActivity;
import com.stocksentinel.ui.stockdetail.StockDetailActivity;
import com.stocksentinel.util.DeviceUtils;
import com.stocksentinel.util.FormatUtils;

import java.util.ArrayList;
import java.util.List;

import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;

/**
 * Stocks Fragment — AI-powered research screener and institutional stock directory.
 */
public class StocksFragment extends Fragment {

    private SwipeRefreshLayout swipeRefresh;
    private RecyclerView recyclerView;
    private StockListAdapter adapter;

    // Filters
    private String currentMarket = null;
    private String currentResearchMode = "ALL"; // ALL, TOP_AI, CATALYST, DIVIDEND
    private int currentOffset = 0;
    private boolean isLoading = false;

    // Research Filter Chips
    private TextView chipAll, chipTopAi, chipCatalysts, chipDividends;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        return inflater.inflate(R.layout.fragment_stocks, container, false);
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        super.onViewCreated(view, savedInstanceState);

        swipeRefresh = view.findViewById(R.id.swipe_refresh);
        recyclerView = view.findViewById(R.id.stocks_recycler);

        // Market filter chips
        ChipGroup chipGroup = view.findViewById(R.id.market_chips);
        setupMarketChips(chipGroup);

        // Research filter chips
        chipAll = view.findViewById(R.id.chip_filter_all);
        chipTopAi = view.findViewById(R.id.chip_filter_top_ai);
        chipCatalysts = view.findViewById(R.id.chip_filter_catalysts);
        chipDividends = view.findViewById(R.id.chip_filter_dividends);
        setupResearchChips();

        // Search bar (opens SearchActivity)
        view.findViewById(R.id.search_bar).setOnClickListener(v ->
                startActivity(new Intent(requireContext(), SearchActivity.class)));

        // RecyclerView & Adapter
        adapter = new StockListAdapter(stock -> {
            String sym = stock.has("symbol") ? stock.get("symbol").getAsString() : "";
            String ex = stock.has("exchange") ? stock.get("exchange").getAsString() : "NSE";
            String name = stock.has("name") ? stock.get("name").getAsString() : sym;

            Intent intent = new Intent(requireContext(), StockDetailActivity.class);
            intent.putExtra(StockDetailActivity.EXTRA_SYMBOL, sym);
            intent.putExtra(StockDetailActivity.EXTRA_EXCHANGE, ex);
            intent.putExtra(StockDetailActivity.EXTRA_NAME, name);
            startActivity(intent);
        });
        recyclerView.setLayoutManager(new LinearLayoutManager(requireContext()));
        recyclerView.setAdapter(adapter);

        // Infinite scroll for standard stock list
        recyclerView.addOnScrollListener(new RecyclerView.OnScrollListener() {
            @Override
            public void onScrolled(@NonNull RecyclerView rv, int dx, int dy) {
                LinearLayoutManager lm = (LinearLayoutManager) rv.getLayoutManager();
                if (lm != null && !isLoading && "ALL".equals(currentResearchMode)) {
                    int lastVisible = lm.findLastVisibleItemPosition();
                    if (lastVisible >= adapter.getItemCount() - 5) {
                        loadMore();
                    }
                }
            }
        });

        swipeRefresh.setOnRefreshListener(() -> {
            currentOffset = 0;
            refreshData();
        });

        refreshData();
    }

    private void setupMarketChips(ChipGroup chipGroup) {
        String[] markets = {"All Markets", "India", "US"};
        String[] values = {null, "IN", "US"};

        for (int i = 0; i < markets.length; i++) {
            Chip chip = new Chip(requireContext());
            chip.setText(markets[i]);
            chip.setCheckable(true);
            chip.setChecked(i == 0);
            chip.setChipBackgroundColorResource(R.color.card_dark);
            chip.setTextColor(getResources().getColor(R.color.text_primary, null));

            final String market = values[i];
            chip.setOnCheckedChangeListener((button, checked) -> {
                if (checked) {
                    currentMarket = market;
                    currentOffset = 0;
                    refreshData();
                }
            });
            chipGroup.addView(chip);
        }
    }

    private void setupResearchChips() {
        View.OnClickListener listener = v -> {
            chipAll.setTextColor(getResources().getColor(R.color.text_secondary, null));
            chipTopAi.setTextColor(getResources().getColor(R.color.text_secondary, null));
            chipCatalysts.setTextColor(getResources().getColor(R.color.text_secondary, null));
            chipDividends.setTextColor(getResources().getColor(R.color.text_secondary, null));

            ((TextView) v).setTextColor(getResources().getColor(R.color.blue_accent, null));

            if (v == chipAll) currentResearchMode = "ALL";
            else if (v == chipTopAi) currentResearchMode = "TOP_AI";
            else if (v == chipCatalysts) currentResearchMode = "CATALYST";
            else if (v == chipDividends) currentResearchMode = "DIVIDEND";

            currentOffset = 0;
            refreshData();
        };

        chipAll.setOnClickListener(listener);
        chipTopAi.setOnClickListener(listener);
        chipCatalysts.setOnClickListener(listener);
        chipDividends.setOnClickListener(listener);
    }

    private void refreshData() {
        if ("ALL".equals(currentResearchMode)) {
            loadAllStocks(true);
        } else {
            loadScreenerStocks();
        }
    }

    private void loadAllStocks(boolean refresh) {
        isLoading = true;
        swipeRefresh.setRefreshing(true);

        ApiClient.getApi().getStocks(currentMarket, null, 50, currentOffset)
                .enqueue(new Callback<JsonObject>() {
                    @Override
                    public void onResponse(@NonNull Call<JsonObject> call, @NonNull Response<JsonObject> response) {
                        isLoading = false;
                        if (response.isSuccessful() && response.body() != null && isAdded()) {
                            JsonArray stocks = response.body().getAsJsonArray("stocks");
                            List<JsonObject> items = new ArrayList<>();
                            if (stocks != null) {
                                for (JsonElement el : stocks) {
                                    if (el.isJsonObject()) items.add(el.getAsJsonObject());
                                }
                            }
                            if (refresh) {
                                adapter.setItems(items);
                            } else {
                                adapter.addItems(items);
                            }
                        }
                        if (isAdded()) swipeRefresh.setRefreshing(false);
                    }

                    @Override
                    public void onFailure(@NonNull Call<JsonObject> call, @NonNull Throwable t) {
                        isLoading = false;
                        if (isAdded()) swipeRefresh.setRefreshing(false);
                    }
                });
    }

    private void loadScreenerStocks() {
        isLoading = true;
        swipeRefresh.setRefreshing(true);

        Float minScore = null;
        Boolean hasCatalyst = false;
        Boolean hasDividend = false;

        if ("TOP_AI".equals(currentResearchMode)) {
            minScore = 70.0f;
        } else if ("CATALYST".equals(currentResearchMode)) {
            hasCatalyst = true;
        } else if ("DIVIDEND".equals(currentResearchMode)) {
            hasDividend = true;
        }

        ApiClient.getApi().getScreenerResults(null, currentMarket, null, minScore, hasCatalyst, hasDividend, 50)
                .enqueue(new Callback<JsonObject>() {
                    @Override
                    public void onResponse(@NonNull Call<JsonObject> call, @NonNull Response<JsonObject> response) {
                        isLoading = false;
                        if (response.isSuccessful() && response.body() != null && isAdded()) {
                            JsonArray stocks = response.body().getAsJsonArray("stocks");
                            List<JsonObject> items = new ArrayList<>();
                            if (stocks != null) {
                                for (JsonElement el : stocks) {
                                    if (el.isJsonObject()) items.add(el.getAsJsonObject());
                                }
                            }
                            adapter.setItems(items);
                        }
                        if (isAdded()) swipeRefresh.setRefreshing(false);
                    }

                    @Override
                    public void onFailure(@NonNull Call<JsonObject> call, @NonNull Throwable t) {
                        isLoading = false;
                        if (isAdded()) swipeRefresh.setRefreshing(false);
                    }
                });
    }

    private void loadMore() {
        currentOffset += 50;
        loadAllStocks(false);
    }

    interface OnStockClickListener {
        void onStockClick(JsonObject stock);
    }

    /**
     * RecyclerView adapter for stock list with AI Screener badges.
     */
    static class StockListAdapter extends RecyclerView.Adapter<StockListAdapter.VH> {
        private final List<JsonObject> items = new ArrayList<>();
        private final OnStockClickListener listener;

        StockListAdapter(OnStockClickListener listener) {
            this.listener = listener;
        }

        void setItems(List<JsonObject> newItems) {
            items.clear();
            items.addAll(newItems);
            notifyDataSetChanged();
        }

        void addItems(List<JsonObject> newItems) {
            int start = items.size();
            items.addAll(newItems);
            notifyItemRangeInserted(start, newItems.size());
        }

        @Override
        public int getItemCount() { return items.size(); }

        @NonNull
        @Override
        public VH onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
            View v = LayoutInflater.from(parent.getContext())
                    .inflate(R.layout.item_stock_list, parent, false);
            return new VH(v);
        }

        @Override
        public void onBindViewHolder(@NonNull VH holder, int position) {
            JsonObject stock = items.get(position);

            String symbol = stock.has("symbol") ? stock.get("symbol").getAsString() : "";
            String name = stock.has("name") && !stock.get("name").isJsonNull()
                    ? stock.get("name").getAsString() : symbol;
            Double price = stock.has("current_price") && !stock.get("current_price").isJsonNull()
                    ? stock.get("current_price").getAsDouble() : null;
            Double pct = stock.has("change_pct") && !stock.get("change_pct").isJsonNull()
                    ? stock.get("change_pct").getAsDouble() : null;
            String exchange = stock.has("exchange") && !stock.get("exchange").isJsonNull()
                    ? stock.get("exchange").getAsString() : "NSE";
            String currency = stock.has("currency") && !stock.get("currency").isJsonNull()
                    ? stock.get("currency").getAsString() : "INR";
            int stockId = stock.has("id") && !stock.get("id").isJsonNull()
                    ? stock.get("id").getAsInt() : 0;

            holder.symbolText.setText(symbol);
            holder.nameText.setText(name.length() > 30 ? name.substring(0, 30) + "…" : name);
            holder.exchangeText.setText(exchange);
            holder.priceText.setText(FormatUtils.formatPrice(price, currency));
            holder.changeText.setText(FormatUtils.formatChangePercent(pct));
            holder.changeText.setTextColor(FormatUtils.getChangeColor(pct));

            // AI Screener metadata (if present)
            if (stock.has("research_grade")) {
                String grade = stock.get("research_grade").getAsString();
                holder.gradeBadge.setText(grade);
                holder.gradeBadge.setVisibility(View.VISIBLE);
                if (grade.startsWith("A")) {
                    holder.gradeBadge.setTextColor(Color.parseColor("#FF059669"));
                } else if (grade.startsWith("B")) {
                    holder.gradeBadge.setTextColor(Color.parseColor("#FF2563EB"));
                } else {
                    holder.gradeBadge.setTextColor(Color.parseColor("#FFD97706"));
                }
            } else {
                holder.gradeBadge.setVisibility(View.GONE);
            }

            if (stock.has("action")) {
                String action = stock.get("action").getAsString();
                holder.actionBadge.setText(action.replace("_", " "));
                holder.actionBadge.setVisibility(View.VISIBLE);
                if (action.contains("BUY") || action.contains("ACCUMULATE")) {
                    holder.actionBadge.setTextColor(Color.parseColor("#FF059669"));
                } else if (action.contains("SELL") || action.contains("AVOID")) {
                    holder.actionBadge.setTextColor(Color.parseColor("#FFDC2626"));
                } else {
                    holder.actionBadge.setTextColor(Color.parseColor("#FFD97706"));
                }
            } else {
                holder.actionBadge.setVisibility(View.GONE);
            }

            if (stock.has("key_reason")) {
                String reason = stock.get("key_reason").getAsString();
                holder.reasonText.setText(reason);
                holder.reasonText.setVisibility(View.VISIBLE);
            } else {
                holder.reasonText.setVisibility(View.GONE);
            }

            // Click listener -> Open Stock Detail Research Report
            holder.itemView.setOnClickListener(v -> {
                if (listener != null) listener.onStockClick(stock);
            });

            // Add to Watchlist button
            final int fStockId = stockId;
            holder.addBtn.setVisibility(stockId > 0 ? View.VISIBLE : View.GONE);
            holder.addBtn.setOnClickListener(v -> {
                String deviceId = DeviceUtils.getDeviceId(holder.itemView.getContext());
                JsonObject body = new JsonObject();
                body.addProperty("device_id", deviceId);
                body.addProperty("stock_id", fStockId);
                ApiClient.getApi().addToWatchlist(body).enqueue(new Callback<JsonObject>() {
                    @Override
                    public void onResponse(@NonNull Call<JsonObject> call, @NonNull Response<JsonObject> response) {
                        Toast.makeText(holder.itemView.getContext(),
                                symbol + " added to watchlist", Toast.LENGTH_SHORT).show();
                    }

                    @Override
                    public void onFailure(@NonNull Call<JsonObject> call, @NonNull Throwable t) {
                        Toast.makeText(holder.itemView.getContext(),
                                "Failed to add", Toast.LENGTH_SHORT).show();
                    }
                });
            });
        }

        static class VH extends RecyclerView.ViewHolder {
            TextView symbolText, nameText, priceText, changeText, exchangeText, addBtn;
            TextView gradeBadge, actionBadge, reasonText;

            VH(View v) {
                super(v);
                symbolText = v.findViewById(R.id.stock_symbol);
                nameText = v.findViewById(R.id.stock_name);
                priceText = v.findViewById(R.id.stock_price);
                changeText = v.findViewById(R.id.stock_change);
                exchangeText = v.findViewById(R.id.stock_exchange);
                addBtn = v.findViewById(R.id.add_watchlist_btn);
                gradeBadge = v.findViewById(R.id.stock_grade_badge);
                actionBadge = v.findViewById(R.id.stock_action_badge);
                reasonText = v.findViewById(R.id.stock_screener_reason);
            }
        }
    }
}
