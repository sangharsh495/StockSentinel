package com.stocksentinel.ui.stocks;

import android.content.Intent;
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

import com.google.android.material.chip.Chip;
import com.google.android.material.chip.ChipGroup;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.stocksentinel.R;
import com.stocksentinel.data.api.ApiClient;
import com.stocksentinel.ui.search.SearchActivity;
import com.stocksentinel.util.FormatUtils;

import java.util.ArrayList;
import java.util.List;

import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;

/**
 * Stocks Fragment — scrollable list of stocks with market filter chips.
 */
public class StocksFragment extends Fragment {

    private SwipeRefreshLayout swipeRefresh;
    private RecyclerView recyclerView;
    private StockListAdapter adapter;
    private String currentMarket = null;
    private int currentOffset = 0;
    private boolean isLoading = false;

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
        setupChips(chipGroup);

        // Search bar (opens SearchActivity)
        view.findViewById(R.id.search_bar).setOnClickListener(v ->
                startActivity(new Intent(requireContext(), SearchActivity.class)));

        // RecyclerView
        adapter = new StockListAdapter();
        recyclerView.setLayoutManager(new LinearLayoutManager(requireContext()));
        recyclerView.setAdapter(adapter);

        // Infinite scroll
        recyclerView.addOnScrollListener(new RecyclerView.OnScrollListener() {
            @Override
            public void onScrolled(@NonNull RecyclerView rv, int dx, int dy) {
                LinearLayoutManager lm = (LinearLayoutManager) rv.getLayoutManager();
                if (lm != null && !isLoading) {
                    int lastVisible = lm.findLastVisibleItemPosition();
                    if (lastVisible >= adapter.getItemCount() - 5) {
                        loadMore();
                    }
                }
            }
        });

        swipeRefresh.setOnRefreshListener(() -> {
            currentOffset = 0;
            loadStocks(true);
        });

        loadStocks(true);
    }

    private void setupChips(ChipGroup chipGroup) {
        String[] markets = {"All", "India", "US"};
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
                    loadStocks(true);
                }
            });
            chipGroup.addView(chip);
        }
    }

    private void loadStocks(boolean clear) {
        isLoading = true;
        swipeRefresh.setRefreshing(true);

        ApiClient.getApi().getStocks(currentMarket, null, 50, currentOffset)
                .enqueue(new Callback<JsonObject>() {
                    @Override
                    public void onResponse(@NonNull Call<JsonObject> call,
                                           @NonNull Response<JsonObject> response) {
                        if (response.isSuccessful() && response.body() != null && isAdded()) {
                            JsonArray stocks = response.body().getAsJsonArray("stocks");
                            List<JsonObject> items = new ArrayList<>();
                            for (JsonElement el : stocks) {
                                items.add(el.getAsJsonObject());
                            }
                            if (clear) {
                                adapter.setItems(items);
                            } else {
                                adapter.addItems(items);
                            }
                        }
                        isLoading = false;
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
        loadStocks(false);
    }

    /**
     * Simple RecyclerView adapter for stock list.
     */
    static class StockListAdapter extends RecyclerView.Adapter<StockListAdapter.VH> {
        private final List<JsonObject> items = new ArrayList<>();

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
                    ? stock.get("exchange").getAsString() : "";
            String currency = stock.has("currency") && !stock.get("currency").isJsonNull()
                    ? stock.get("currency").getAsString() : "INR";

            holder.symbolText.setText(symbol);
            holder.nameText.setText(name.length() > 30 ? name.substring(0, 30) + "…" : name);
            holder.exchangeText.setText(exchange);
            holder.priceText.setText(FormatUtils.formatPrice(price, currency));
            holder.changeText.setText(FormatUtils.formatChangePercent(pct));
            holder.changeText.setTextColor(FormatUtils.getChangeColor(pct));
        }

        static class VH extends RecyclerView.ViewHolder {
            TextView symbolText, nameText, exchangeText, priceText, changeText;

            VH(View v) {
                super(v);
                symbolText = v.findViewById(R.id.stock_symbol);
                nameText = v.findViewById(R.id.stock_name);
                exchangeText = v.findViewById(R.id.stock_exchange);
                priceText = v.findViewById(R.id.stock_price);
                changeText = v.findViewById(R.id.stock_change);
            }
        }
    }
}
