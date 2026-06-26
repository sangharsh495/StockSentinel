package com.stocksentinel.ui.watchlist;

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
import com.stocksentinel.util.DeviceUtils;
import com.stocksentinel.util.FormatUtils;

import java.util.ArrayList;
import java.util.List;

import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;

/**
 * Watchlist Fragment — shows user's saved stocks with live prices.
 * Pull-to-refresh, swipe-to-remove, empty state.
 */
public class WatchlistFragment extends Fragment {

    private SwipeRefreshLayout swipeRefresh;
    private RecyclerView recyclerView;
    private WatchlistAdapter adapter;
    private LinearLayout emptyState;
    private TextView countText;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        return inflater.inflate(R.layout.fragment_watchlist, container, false);
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        super.onViewCreated(view, savedInstanceState);

        swipeRefresh = view.findViewById(R.id.swipe_refresh);
        recyclerView = view.findViewById(R.id.watchlist_recycler);
        emptyState = view.findViewById(R.id.empty_state);
        countText = view.findViewById(R.id.watchlist_count);

        adapter = new WatchlistAdapter();
        recyclerView.setLayoutManager(new LinearLayoutManager(requireContext()));
        recyclerView.setAdapter(adapter);

        swipeRefresh.setOnRefreshListener(this::loadWatchlist);

        loadWatchlist();
    }

    @Override
    public void onResume() {
        super.onResume();
        loadWatchlist();
    }

    private void loadWatchlist() {
        String deviceId = DeviceUtils.getDeviceId(requireContext());
        swipeRefresh.setRefreshing(true);

        ApiClient.getApi().getWatchlist(deviceId)
                .enqueue(new Callback<JsonObject>() {
                    @Override
                    public void onResponse(@NonNull Call<JsonObject> call,
                                           @NonNull Response<JsonObject> response) {
                        if (response.isSuccessful() && response.body() != null && isAdded()) {
                            JsonArray stocks = response.body().getAsJsonArray("stocks");
                            int count = stocks != null ? stocks.size() : 0;
                            List<WatchlistItem> items = new ArrayList<>();

                            if (stocks != null) {
                                for (JsonElement el : stocks) {
                                    items.add(WatchlistItem.fromJson(el.getAsJsonObject()));
                                }
                            }

                            adapter.setItems(items);
                            countText.setText(count + " stock" + (count != 1 ? "s" : "") + " tracked");
                            emptyState.setVisibility(count == 0 ? View.VISIBLE : View.GONE);
                        }
                        if (isAdded()) swipeRefresh.setRefreshing(false);
                    }

                    @Override
                    public void onFailure(@NonNull Call<JsonObject> call, @NonNull Throwable t) {
                        if (isAdded()) swipeRefresh.setRefreshing(false);
                    }
                });
    }

    /**
     * Simple data holder for watchlist items.
     */
    static class WatchlistItem {
        int watchlistId;
        int stockId;
        String symbol;
        String name;
        String exchange;
        String market;
        Double currentPrice;
        Double changePct;
        String currency;
        String addedAt;

        static WatchlistItem fromJson(JsonObject obj) {
            WatchlistItem item = new WatchlistItem();
            item.watchlistId = obj.has("watchlist_id") ? obj.get("watchlist_id").getAsInt() : 0;
            item.stockId = obj.has("stock_id") && !obj.get("stock_id").isJsonNull()
                    ? obj.get("stock_id").getAsInt() : 0;
            item.symbol = obj.has("symbol") ? obj.get("symbol").getAsString() : "";
            item.name = obj.has("name") && !obj.get("name").isJsonNull()
                    ? obj.get("name").getAsString() : item.symbol;
            item.exchange = obj.has("exchange") ? obj.get("exchange").getAsString() : "";
            item.market = obj.has("market") ? obj.get("market").getAsString() : "";
            item.currentPrice = obj.has("current_price") && !obj.get("current_price").isJsonNull()
                    ? obj.get("current_price").getAsDouble() : null;
            item.changePct = obj.has("change_pct") && !obj.get("change_pct").isJsonNull()
                    ? obj.get("change_pct").getAsDouble() : null;
            item.currency = obj.has("currency") && !obj.get("currency").isJsonNull()
                    ? obj.get("currency").getAsString() : "INR";
            item.addedAt = obj.has("added_at") && !obj.get("added_at").isJsonNull()
                    ? obj.get("added_at").getAsString() : "";
            return item;
        }
    }

    /**
     * RecyclerView adapter for watchlist stock items.
     */
    static class WatchlistAdapter extends RecyclerView.Adapter<WatchlistAdapter.VH> {
        private final List<WatchlistItem> items = new ArrayList<>();

        void setItems(List<WatchlistItem> newItems) {
            items.clear();
            items.addAll(newItems);
            notifyDataSetChanged();
        }

        void removeItem(int position) {
            items.remove(position);
            notifyItemRemoved(position);
        }

        @Override
        public int getItemCount() { return items.size(); }

        @NonNull
        @Override
        public VH onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
            View v = LayoutInflater.from(parent.getContext())
                    .inflate(R.layout.item_stock_row, parent, false);
            return new VH(v);
        }

        @Override
        public void onBindViewHolder(@NonNull VH holder, int position) {
            WatchlistItem item = items.get(position);

            holder.symbolText.setText(item.symbol);
            String name = item.name != null && item.name.length() > 28
                    ? item.name.substring(0, 28) + "…" : item.name;
            holder.nameText.setText(name);
            holder.exchangeText.setText(item.exchange);
            holder.priceText.setText(FormatUtils.formatPrice(item.currentPrice, item.currency));
            holder.changeText.setText(FormatUtils.formatChangePercent(item.changePct));
            holder.changeText.setTextColor(FormatUtils.getChangeColor(item.changePct));

            // Remove button
            holder.removeBtn.setOnClickListener(v -> removeFromWatchlist(holder.getAdapterPosition()));
        }

        private void removeFromWatchlist(int position) {
            if (position < 0 || position >= items.size()) return;
            WatchlistItem item = items.get(position);

            String deviceId = DeviceUtils.getDeviceId(
                    com.stocksentinel.StockSentinelApp.getAppContext());

            ApiClient.getApi().removeStockFromWatchlist(deviceId, item.stockId)
                    .enqueue(new Callback<JsonObject>() {
                        @Override
                        public void onResponse(@NonNull Call<JsonObject> call,
                                               @NonNull Response<JsonObject> response) {
                            // Item removed server-side
                        }

                        @Override
                        public void onFailure(@NonNull Call<JsonObject> call,
                                              @NonNull Throwable t) { }
                    });

            removeItem(position);
        }

        static class VH extends RecyclerView.ViewHolder {
            TextView symbolText, nameText, exchangeText, priceText, changeText;
            View removeBtn;

            VH(View v) {
                super(v);
                symbolText = v.findViewById(R.id.stock_symbol);
                nameText = v.findViewById(R.id.stock_name);
                exchangeText = v.findViewById(R.id.stock_exchange);
                priceText = v.findViewById(R.id.stock_price);
                changeText = v.findViewById(R.id.stock_change);
                removeBtn = v.findViewById(R.id.remove_btn);
            }
        }
    }
}