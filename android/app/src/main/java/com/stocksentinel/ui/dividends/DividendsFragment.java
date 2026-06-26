package com.stocksentinel.ui.dividends;

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
 * Dividends Fragment — upcoming and past dividends.
 */
public class DividendsFragment extends Fragment {

    private SwipeRefreshLayout swipeRefresh;
    private RecyclerView recyclerView;
    private DividendAdapter adapter;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        return inflater.inflate(R.layout.fragment_dividends, container, false);
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        super.onViewCreated(view, savedInstanceState);

        swipeRefresh = view.findViewById(R.id.swipe_refresh);
        recyclerView = view.findViewById(R.id.dividends_recycler);

        adapter = new DividendAdapter();
        recyclerView.setLayoutManager(new LinearLayoutManager(requireContext()));
        recyclerView.setAdapter(adapter);

        swipeRefresh.setOnRefreshListener(this::loadDividends);
        loadDividends();
    }

    private void loadDividends() {
        swipeRefresh.setRefreshing(true);

        ApiClient.getApi().getUpcomingDividends(60, 100).enqueue(new Callback<JsonObject>() {
            @Override
            public void onResponse(@NonNull Call<JsonObject> call, @NonNull Response<JsonObject> response) {
                if (response.isSuccessful() && response.body() != null && isAdded()) {
                    JsonArray divs = response.body().getAsJsonArray("dividends");
                    List<JsonObject> items = new ArrayList<>();
                    for (JsonElement el : divs) {
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

    static class DividendAdapter extends RecyclerView.Adapter<DividendAdapter.VH> {
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
                    .inflate(R.layout.item_dividend, parent, false);
            return new VH(v);
        }

        @Override
        public void onBindViewHolder(@NonNull VH holder, int position) {
            JsonObject div = items.get(position);

            String symbol = div.has("symbol") ? div.get("symbol").getAsString() : "";
            String company = div.has("company_name") && !div.get("company_name").isJsonNull()
                    ? div.get("company_name").getAsString() : symbol;
            String exDate = div.has("ex_date") && !div.get("ex_date").isJsonNull()
                    ? div.get("ex_date").getAsString() : "";
            String status = div.has("status") && !div.get("status").isJsonNull()
                    ? div.get("status").getAsString() : "";
            Double amount = div.has("amount") && !div.get("amount").isJsonNull()
                    ? div.get("amount").getAsDouble() : null;
            String type = div.has("dividend_type") && !div.get("dividend_type").isJsonNull()
                    ? div.get("dividend_type").getAsString() : "";

            holder.symbolText.setText(symbol);
            holder.companyText.setText(company.length() > 35 ? company.substring(0, 35) + "…" : company);
            holder.exDateText.setText("Ex: " + FormatUtils.formatDate(exDate));
            holder.amountText.setText(amount != null ? "₹" + String.format("%.2f", amount) : "TBD");
            holder.statusText.setText(status.toUpperCase());
            holder.typeText.setText(type);

            // Color status
            int statusColor;
            switch (status.toLowerCase()) {
                case "upcoming": statusColor = 0xFF448AFF; break;
                case "pending": statusColor = 0xFFFFD740; break;
                case "paid": statusColor = 0xFF00E676; break;
                default: statusColor = 0xFF9E9E9E;
            }
            holder.statusText.setTextColor(statusColor);
        }

        static class VH extends RecyclerView.ViewHolder {
            TextView symbolText, companyText, exDateText, amountText, statusText, typeText;

            VH(View v) {
                super(v);
                symbolText = v.findViewById(R.id.div_symbol);
                companyText = v.findViewById(R.id.div_company);
                exDateText = v.findViewById(R.id.div_ex_date);
                amountText = v.findViewById(R.id.div_amount);
                statusText = v.findViewById(R.id.div_status);
                typeText = v.findViewById(R.id.div_type);
            }
        }
    }
}
