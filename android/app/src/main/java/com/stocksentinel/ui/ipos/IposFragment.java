package com.stocksentinel.ui.ipos;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
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
import com.stocksentinel.util.FormatUtils;

import java.util.ArrayList;
import java.util.List;

import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;

/**
 * IPOs Fragment — upcoming, open, and recently listed IPOs.
 */
public class IposFragment extends Fragment {

    private SwipeRefreshLayout swipeRefresh;
    private RecyclerView recyclerView;
    private IpoAdapter adapter;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        return inflater.inflate(R.layout.fragment_ipos, container, false);
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        super.onViewCreated(view, savedInstanceState);

        swipeRefresh = view.findViewById(R.id.swipe_refresh);
        recyclerView = view.findViewById(R.id.ipos_recycler);

        adapter = new IpoAdapter();
        recyclerView.setLayoutManager(new LinearLayoutManager(requireContext()));
        recyclerView.setAdapter(adapter);

        swipeRefresh.setOnRefreshListener(this::loadIpos);
        loadIpos();
    }

    private void loadIpos() {
        swipeRefresh.setRefreshing(true);

        ApiClient.getApi().getIpos(null, null, 100, 0).enqueue(new Callback<JsonObject>() {
            @Override
            public void onResponse(@NonNull Call<JsonObject> call, @NonNull Response<JsonObject> response) {
                if (response.isSuccessful() && response.body() != null && isAdded()) {
                    JsonArray ipos = response.body().getAsJsonArray("ipos");
                    List<JsonObject> items = new ArrayList<>();
                    for (JsonElement el : ipos) {
                        items.add(el.getAsJsonObject());
                    }
                    adapter.setItems(items);
                }
                if (isAdded()) swipeRefresh.setRefreshing(false);
            }

            @Override
            public void onFailure(@NonNull Call<JsonObject> call, @NonNull Throwable t) {
                if (isAdded()) swipeRefresh.setRefreshing(false);
            }
        });
    }

    static class IpoAdapter extends RecyclerView.Adapter<IpoAdapter.VH> {
        private final List<JsonObject> items = new ArrayList<>();

        void setItems(List<JsonObject> newItems) {
            items.clear();
            items.addAll(newItems);
            notifyDataSetChanged();
        }

        @Override
        public int getItemCount() { return items.size(); }

        @NonNull
        @Override
        public VH onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
            View v = LayoutInflater.from(parent.getContext())
                    .inflate(R.layout.item_ipo, parent, false);
            return new VH(v);
        }

        @Override
        public void onBindViewHolder(@NonNull VH holder, int position) {
            JsonObject ipo = items.get(position);

            String name = ipo.has("company_name") ? ipo.get("company_name").getAsString() : "";
            String market = ipo.has("market") && !ipo.get("market").isJsonNull()
                    ? ipo.get("market").getAsString() : "";
            String status = ipo.has("status") && !ipo.get("status").isJsonNull()
                    ? ipo.get("status").getAsString() : "";
            String openDate = ipo.has("open_date") && !ipo.get("open_date").isJsonNull()
                    ? ipo.get("open_date").getAsString() : "";
            String closeDate = ipo.has("close_date") && !ipo.get("close_date").isJsonNull()
                    ? ipo.get("close_date").getAsString() : "";
            Double priceLow = ipo.has("price_band_low") && !ipo.get("price_band_low").isJsonNull()
                    ? ipo.get("price_band_low").getAsDouble() : null;
            Double priceHigh = ipo.has("price_band_high") && !ipo.get("price_band_high").isJsonNull()
                    ? ipo.get("price_band_high").getAsDouble() : null;
            String lotSize = ipo.has("lot_size") && !ipo.get("lot_size").isJsonNull()
                    ? ipo.get("lot_size").getAsString() : "";

            holder.nameText.setText(name);
            holder.marketText.setText(market);
            holder.statusText.setText(status.toUpperCase());
            holder.dateText.setText(FormatUtils.formatDate(openDate) +
                    (closeDate.isEmpty() ? "" : " – " + FormatUtils.formatDate(closeDate)));

            String currency = "IN".equals(market) ? "₹" : "$";
            if (priceLow != null && priceHigh != null) {
                holder.priceText.setText(String.format("%s%.0f – %s%.0f", currency, priceLow, currency, priceHigh));
            } else {
                holder.priceText.setText("TBD");
            }

            holder.lotText.setText(lotSize.isEmpty() ? "" : "Lot: " + lotSize);

            // Color status
            int statusColor;
            switch (status.toLowerCase()) {
                case "open": statusColor = 0xFF00E676; break;
                case "upcoming": statusColor = 0xFF448AFF; break;
                case "closed": statusColor = 0xFFFFD740; break;
                case "listed": statusColor = 0xFF9E9E9E; break;
                default: statusColor = 0xFF9E9E9E;
            }
            holder.statusText.setTextColor(statusColor);
        }

        static class VH extends RecyclerView.ViewHolder {
            TextView nameText, marketText, statusText, dateText, priceText, lotText;

            VH(View v) {
                super(v);
                nameText = v.findViewById(R.id.ipo_name);
                marketText = v.findViewById(R.id.ipo_market);
                statusText = v.findViewById(R.id.ipo_status);
                dateText = v.findViewById(R.id.ipo_dates);
                priceText = v.findViewById(R.id.ipo_price);
                lotText = v.findViewById(R.id.ipo_lot);
            }
        }
    }
}
