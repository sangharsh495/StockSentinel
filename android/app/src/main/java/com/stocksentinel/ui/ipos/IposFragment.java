package com.stocksentinel.ui.ipos;

import android.content.Intent;
import android.graphics.Color;
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
import java.util.Locale;

import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;

/**
 * IPOs Fragment — upcoming, open, and recently listed IPOs with AI Deep-Dive Reports.
 */
public class IposFragment extends Fragment {

    private SwipeRefreshLayout swipeRefresh;
    private RecyclerView recyclerView;
    private TextView emptyStateText;
    private IpoAdapter adapter;

    private List<JsonObject> allIpos = new ArrayList<>();
    private String currentFilter = "ALL"; // ALL, OPEN, UPCOMING, HIGH_GMP

    private TextView chipAll, chipOpen, chipUpcoming, chipHighGmp;

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
        emptyStateText = view.findViewById(R.id.empty_state_text);

        chipAll = view.findViewById(R.id.chip_ipo_all);
        chipOpen = view.findViewById(R.id.chip_ipo_open);
        chipUpcoming = view.findViewById(R.id.chip_ipo_upcoming);
        chipHighGmp = view.findViewById(R.id.chip_ipo_high_gmp);

        setupFilterChips();

        adapter = new IpoAdapter(ipo -> {
            int ipoId = ipo.has("id") ? ipo.get("id").getAsInt() : 0;
            String name = ipo.has("company_name") ? ipo.get("company_name").getAsString() : "IPO Report";

            Intent intent = new Intent(requireContext(), IpoDetailActivity.class);
            intent.putExtra(IpoDetailActivity.EXTRA_IPO_ID, ipoId);
            intent.putExtra(IpoDetailActivity.EXTRA_COMPANY_NAME, name);
            startActivity(intent);
        });

        recyclerView.setLayoutManager(new LinearLayoutManager(requireContext()));
        recyclerView.setAdapter(adapter);

        swipeRefresh.setOnRefreshListener(this::loadIpos);
        loadIpos();
    }

    private void setupFilterChips() {
        View.OnClickListener listener = v -> {
            resetChips();
            ((TextView) v).setTextColor(Color.WHITE);

            if (v == chipAll) {
                currentFilter = "ALL";
            } else if (v == chipOpen) {
                currentFilter = "OPEN";
            } else if (v == chipUpcoming) {
                currentFilter = "UPCOMING";
            } else if (v == chipHighGmp) {
                currentFilter = "HIGH_GMP";
            }

            applyFilter();
        };

        chipAll.setOnClickListener(listener);
        chipOpen.setOnClickListener(listener);
        chipUpcoming.setOnClickListener(listener);
        chipHighGmp.setOnClickListener(listener);
    }

    private void resetChips() {
        int defaultColor = getResources().getColor(R.color.text_secondary, null);
        chipAll.setTextColor(defaultColor);
        chipOpen.setTextColor(defaultColor);
        chipUpcoming.setTextColor(defaultColor);
        chipHighGmp.setTextColor(defaultColor);
    }

    private void applyFilter() {
        List<JsonObject> filtered = new ArrayList<>();
        for (JsonObject ipo : allIpos) {
            String status = ipo.has("status") && !ipo.get("status").isJsonNull()
                    ? ipo.get("status").getAsString().toLowerCase() : "";
            double gmp = ipo.has("gmp") && !ipo.get("gmp").isJsonNull()
                    ? ipo.get("gmp").getAsDouble() : 0.0;

            if ("ALL".equals(currentFilter)) {
                filtered.add(ipo);
            } else if ("OPEN".equals(currentFilter) && "open".equals(status)) {
                filtered.add(ipo);
            } else if ("UPCOMING".equals(currentFilter) && "upcoming".equals(status)) {
                filtered.add(ipo);
            } else if ("HIGH_GMP".equals(currentFilter) && gmp >= 50.0) {
                filtered.add(ipo);
            }
        }

        adapter.setItems(filtered);
        if (emptyStateText != null) {
            emptyStateText.setVisibility(filtered.isEmpty() ? View.VISIBLE : View.GONE);
        }
    }

    private void loadIpos() {
        swipeRefresh.setRefreshing(true);

        ApiClient.getApi().getIpos(null, null, 100, 0).enqueue(new Callback<JsonObject>() {
            @Override
            public void onResponse(@NonNull Call<JsonObject> call, @NonNull Response<JsonObject> response) {
                if (response.isSuccessful() && response.body() != null && isAdded()) {
                    JsonArray ipos = response.body().getAsJsonArray("ipos");
                    allIpos.clear();
                    if (ipos != null) {
                        for (JsonElement el : ipos) {
                            if (el.isJsonObject()) allIpos.add(el.getAsJsonObject());
                        }
                    }
                    applyFilter();
                }
                if (isAdded()) swipeRefresh.setRefreshing(false);
            }

            @Override
            public void onFailure(@NonNull Call<JsonObject> call, @NonNull Throwable t) {
                if (isAdded()) swipeRefresh.setRefreshing(false);
            }
        });
    }

    interface OnIpoClickListener {
        void onIpoClick(JsonObject ipo);
    }

    static class IpoAdapter extends RecyclerView.Adapter<IpoAdapter.VH> {
        private final List<JsonObject> items = new ArrayList<>();
        private final OnIpoClickListener listener;

        IpoAdapter(OnIpoClickListener listener) {
            this.listener = listener;
        }

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
                    ? ipo.get("market").getAsString() : "IN";
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
            Double gmp = ipo.has("gmp") && !ipo.get("gmp").isJsonNull()
                    ? ipo.get("gmp").getAsDouble() : null;

            holder.nameText.setText(name);
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

            // GMP Badge
            if (gmp != null && gmp > 0) {
                holder.gmpText.setVisibility(View.VISIBLE);
                holder.gmpText.setText(String.format(Locale.US, "GMP: +₹%.0f", gmp));
                holder.gmpText.setTextColor(Color.parseColor("#FFFFD740"));
            } else {
                holder.gmpText.setVisibility(View.GONE);
            }

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

            holder.itemView.setOnClickListener(v -> {
                if (listener != null) listener.onIpoClick(ipo);
            });
            holder.btnReport.setOnClickListener(v -> {
                if (listener != null) listener.onIpoClick(ipo);
            });
        }

        static class VH extends RecyclerView.ViewHolder {
            TextView nameText, statusText, dateText, priceText, lotText, gmpText, btnReport;

            VH(View v) {
                super(v);
                nameText = v.findViewById(R.id.ipo_name);
                statusText = v.findViewById(R.id.ipo_status);
                dateText = v.findViewById(R.id.ipo_dates);
                priceText = v.findViewById(R.id.ipo_price);
                lotText = v.findViewById(R.id.ipo_lot);
                gmpText = v.findViewById(R.id.ipo_gmp);
                btnReport = v.findViewById(R.id.ipo_btn_report);
            }
        }
    }
}
