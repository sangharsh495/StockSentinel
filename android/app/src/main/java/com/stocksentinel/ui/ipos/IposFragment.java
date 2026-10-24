package com.stocksentinel.ui.ipos;

import android.content.Intent;
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
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

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
    private String currentFilter = "ALL"; // ALL, OPEN, UPCOMING, HIGH_GMP, BEST_ODDS

    private TextView chipAll, chipOpen, chipUpcoming, chipHighGmp, chipBestOdds;

    // Tested listing odds from the quant engine, keyed by normalised company name
    private final Map<String, JsonObject> oddsByName = new HashMap<>();
    private final List<JsonObject> oddsList = new ArrayList<>();

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
        chipBestOdds = view.findViewById(R.id.chip_ipo_best_odds);

        setupFilterChips();

        adapter = new IpoAdapter(ipo -> {
            if (!ipo.has("id")) return; // scored by the model but not in our IPO list yet
            int ipoId = ipo.get("id").getAsInt();
            String name = ipo.has("company_name") ? ipo.get("company_name").getAsString() : "IPO Report";

            Intent intent = new Intent(requireContext(), IpoDetailActivity.class);
            intent.putExtra(IpoDetailActivity.EXTRA_IPO_ID, ipoId);
            intent.putExtra(IpoDetailActivity.EXTRA_COMPANY_NAME, name);
            startActivity(intent);
        });

        recyclerView.setLayoutManager(new LinearLayoutManager(requireContext()));
        recyclerView.setAdapter(adapter);
        adapter.setOdds(oddsByName);

        swipeRefresh.setOnRefreshListener(() -> {
            loadIpos();
            loadOdds();
        });
        loadIpos();
        loadOdds();
    }

    private void setupFilterChips() {
        View.OnClickListener listener = v -> {
            resetChips();
            ((TextView) v).setTextColor(getResources().getColor(R.color.blue_accent, null));

            if (v == chipAll) {
                currentFilter = "ALL";
            } else if (v == chipOpen) {
                currentFilter = "OPEN";
            } else if (v == chipUpcoming) {
                currentFilter = "UPCOMING";
            } else if (v == chipHighGmp) {
                currentFilter = "HIGH_GMP";
            } else if (v == chipBestOdds) {
                currentFilter = "BEST_ODDS";
            }

            applyFilter();
        };

        chipAll.setOnClickListener(listener);
        chipOpen.setOnClickListener(listener);
        chipUpcoming.setOnClickListener(listener);
        chipHighGmp.setOnClickListener(listener);
        chipBestOdds.setOnClickListener(listener);
    }

    private void resetChips() {
        int defaultColor = getResources().getColor(R.color.text_secondary, null);
        chipAll.setTextColor(defaultColor);
        chipOpen.setTextColor(defaultColor);
        chipUpcoming.setTextColor(defaultColor);
        chipHighGmp.setTextColor(defaultColor);
        chipBestOdds.setTextColor(defaultColor);
    }

    private void applyFilter() {
        List<JsonObject> filtered = new ArrayList<>();
        if ("BEST_ODDS".equals(currentFilter)) {
            // Every IPO the model scored, best expected listing first (already ranked by the API)
            Set<String> shown = new HashSet<>();
            for (JsonObject odds : oddsList) {
                JsonObject match = null;
                for (JsonObject ipo : allIpos) {
                    if (normalise(str(ipo, "company_name")).equals(normalise(str(odds, "name")))) {
                        match = ipo;
                        break;
                    }
                }
                JsonObject row = match != null ? match : ipoFromOdds(odds);
                String key = normalise(str(row, "company_name"));
                if (shown.add(key)) filtered.add(row);
            }
            adapter.setItems(filtered);
            if (emptyStateText != null) {
                emptyStateText.setVisibility(filtered.isEmpty() ? View.VISIBLE : View.GONE);
            }
            return;
        }
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

    private void loadOdds() {
        ApiClient.getApi().getIpoOdds().enqueue(new Callback<JsonObject>() {
            @Override
            public void onResponse(@NonNull Call<JsonObject> call, @NonNull Response<JsonObject> response) {
                if (!response.isSuccessful() || response.body() == null || !isAdded()) return;
                JsonArray ipos = response.body().has("ipos") ? response.body().getAsJsonArray("ipos") : null;
                oddsByName.clear();
                oddsList.clear();
                if (ipos != null) {
                    for (JsonElement el : ipos) {
                        if (!el.isJsonObject()) continue;
                        JsonObject o = el.getAsJsonObject();
                        oddsList.add(o);
                        oddsByName.put(normalise(str(o, "name")), o);
                    }
                }
                applyFilter();
            }

            @Override
            public void onFailure(@NonNull Call<JsonObject> call, @NonNull Throwable t) { }
        });
    }

    /** A row for a scored IPO our IPO list doesn't have yet. */
    private static JsonObject ipoFromOdds(JsonObject odds) {
        JsonObject row = new JsonObject();
        row.addProperty("company_name", str(odds, "name"));
        row.addProperty("market", "IN");
        row.addProperty("status", "upcoming");
        if (odds.has("issue_price") && !odds.get("issue_price").isJsonNull()) {
            row.add("price_band_low", odds.get("issue_price"));
            row.add("price_band_high", odds.get("issue_price"));
        }
        if (odds.has("gmp") && !odds.get("gmp").isJsonNull()) row.add("gmp", odds.get("gmp"));
        if (odds.has("issue_close_date") && !odds.get("issue_close_date").isJsonNull()) {
            row.add("close_date", odds.get("issue_close_date"));
        }
        return row;
    }

    static String normalise(String name) {
        String n = name.toLowerCase(Locale.US)
                .replaceAll("\\b(limited|ltd|ipo|india|private|pvt)\\b", "")
                .replaceAll("[^a-z0-9]", "");
        return n.length() > 14 ? n.substring(0, 14) : n;
    }

    private static String str(JsonObject o, String k) {
        return o != null && o.has(k) && !o.get(k).isJsonNull() ? o.get(k).getAsString() : "";
    }

    interface OnIpoClickListener {
        void onIpoClick(JsonObject ipo);
    }

    static class IpoAdapter extends RecyclerView.Adapter<IpoAdapter.VH> {
        private final List<JsonObject> items = new ArrayList<>();
        private final OnIpoClickListener listener;
        private Map<String, JsonObject> odds = new HashMap<>();

        IpoAdapter(OnIpoClickListener listener) {
            this.listener = listener;
        }

        void setOdds(Map<String, JsonObject> odds) {
            this.odds = odds;
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
                holder.gmpText.setTextColor(holder.itemView.getResources().getColor(R.color.yellow_accent, null));
            } else {
                holder.gmpText.setVisibility(View.GONE);
            }

            // Color status
            int statusColor;
            switch (status.toLowerCase()) {
                case "open": statusColor = R.color.bullish; break;
                case "upcoming": statusColor = R.color.blue_accent; break;
                case "closed": statusColor = R.color.yellow_accent; break;
                default: statusColor = R.color.neutral;
            }
            holder.statusText.setTextColor(holder.itemView.getResources().getColor(statusColor, null));

            // Tested listing odds
            JsonObject o = odds.get(normalise(name));
            if (o != null && o.has("probability") && !o.get("probability").isJsonNull()) {
                double p = o.get("probability").getAsDouble();
                Double exp = o.has("expected_gain_pct") && !o.get("expected_gain_pct").isJsonNull()
                        ? o.get("expected_gain_pct").getAsDouble() : null;
                holder.oddsText.setVisibility(View.VISIBLE);
                holder.oddsText.setText(String.format(Locale.US, "🎯 Listing %s · %.0f%% up · %s",
                        exp == null ? "—" : String.format(Locale.US, "%+.0f%%", exp), p * 100,
                        str(o, "verdict").replaceAll(" \\(.*\\)", "")));
                int oddsColor = p >= 0.6 ? R.color.bullish : (p >= 0.45 ? R.color.yellow_accent : R.color.bearish);
                holder.oddsText.setTextColor(holder.itemView.getResources().getColor(oddsColor, null));
            } else {
                holder.oddsText.setVisibility(View.GONE);
            }

            holder.itemView.setOnClickListener(v -> {
                if (listener != null) listener.onIpoClick(ipo);
            });
            holder.btnReport.setOnClickListener(v -> {
                if (listener != null) listener.onIpoClick(ipo);
            });
        }

        static class VH extends RecyclerView.ViewHolder {
            TextView nameText, statusText, dateText, priceText, lotText, gmpText, btnReport, oddsText;

            VH(View v) {
                super(v);
                nameText = v.findViewById(R.id.ipo_name);
                statusText = v.findViewById(R.id.ipo_status);
                dateText = v.findViewById(R.id.ipo_dates);
                priceText = v.findViewById(R.id.ipo_price);
                lotText = v.findViewById(R.id.ipo_lot);
                gmpText = v.findViewById(R.id.ipo_gmp);
                btnReport = v.findViewById(R.id.ipo_btn_report);
                oddsText = v.findViewById(R.id.ipo_odds);
            }
        }
    }
}
