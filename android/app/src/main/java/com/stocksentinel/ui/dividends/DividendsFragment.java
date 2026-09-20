package com.stocksentinel.ui.dividends;

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
import com.stocksentinel.ui.stockdetail.StockDetailActivity;
import com.stocksentinel.util.FormatUtils;

import java.text.DateFormatSymbols;
import java.util.ArrayList;
import java.util.Calendar;
import java.util.List;
import java.util.Locale;

import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;

/**
 * Dividends Fragment — Monthly dividend calendar, yield analysis,
 * consistency rating (1-5 stars), and institutional dividend data sheet.
 */
public class DividendsFragment extends Fragment {

    private SwipeRefreshLayout swipeRefresh;
    private RecyclerView recyclerView;
    private DividendAdapter adapter;

    // Month Navigation
    private TextView btnPrevMonth, btnNextMonth, textCurrentMonth;
    private int selectedYear;
    private int selectedMonth; // 1-12

    // Monthly Stats Views
    private TextView statTotalPayouts, statAvgYield, statHighYieldCount;

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

        btnPrevMonth = view.findViewById(R.id.btn_prev_month);
        btnNextMonth = view.findViewById(R.id.btn_next_month);
        textCurrentMonth = view.findViewById(R.id.text_current_month);

        statTotalPayouts = view.findViewById(R.id.stat_total_payouts);
        statAvgYield = view.findViewById(R.id.stat_avg_yield);
        statHighYieldCount = view.findViewById(R.id.stat_high_yield_count);

        // Initialize to current month & year
        Calendar cal = Calendar.getInstance();
        selectedYear = cal.get(Calendar.YEAR);
        selectedMonth = cal.get(Calendar.MONTH) + 1; // Calendar.MONTH is 0-based

        updateMonthHeader();

        btnPrevMonth.setOnClickListener(v -> {
            selectedMonth--;
            if (selectedMonth < 1) {
                selectedMonth = 12;
                selectedYear--;
            }
            updateMonthHeader();
            loadDividendCalendar();
        });

        btnNextMonth.setOnClickListener(v -> {
            selectedMonth++;
            if (selectedMonth > 12) {
                selectedMonth = 1;
                selectedYear++;
            }
            updateMonthHeader();
            loadDividendCalendar();
        });

        adapter = new DividendAdapter(div -> {
            String sym = div.has("symbol") ? div.get("symbol").getAsString() : "";
            String ex = div.has("exchange") ? div.get("exchange").getAsString() : "NSE";
            String name = div.has("company_name") ? div.get("company_name").getAsString() : sym;

            Intent intent = new Intent(requireContext(), StockDetailActivity.class);
            intent.putExtra(StockDetailActivity.EXTRA_SYMBOL, sym);
            intent.putExtra(StockDetailActivity.EXTRA_EXCHANGE, ex);
            intent.putExtra(StockDetailActivity.EXTRA_NAME, name);
            startActivity(intent);
        });

        recyclerView.setLayoutManager(new LinearLayoutManager(requireContext()));
        recyclerView.setAdapter(adapter);

        swipeRefresh.setOnRefreshListener(this::loadDividendCalendar);
        loadDividendCalendar();
    }

    private void updateMonthHeader() {
        String monthName = new DateFormatSymbols().getMonths()[selectedMonth - 1];
        textCurrentMonth.setText(String.format(Locale.US, "%s %d", monthName, selectedYear));
    }

    private void loadDividendCalendar() {
        swipeRefresh.setRefreshing(true);

        ApiClient.getApi().getDividendCalendar(selectedMonth, selectedYear, 200)
                .enqueue(new Callback<JsonObject>() {
            @Override
            public void onResponse(@NonNull Call<JsonObject> call, @NonNull Response<JsonObject> response) {
                if (response.isSuccessful() && response.body() != null && isAdded()) {
                    JsonObject body = response.body();

                    // Parse statistics
                    if (body.has("stats") && body.get("stats").isJsonObject()) {
                        JsonObject stats = body.getAsJsonObject("stats");
                        int count = stats.has("total_payouts") ? stats.get("total_payouts").getAsInt() : 0;
                        double avgYield = stats.has("avg_yield_pct") ? stats.get("avg_yield_pct").getAsDouble() : 0.0;
                        int highYield = stats.has("high_yield_count") ? stats.get("high_yield_count").getAsInt() : 0;

                        statTotalPayouts.setText(String.valueOf(count));
                        statAvgYield.setText(String.format(Locale.US, "%.2f%%", avgYield));
                        statHighYieldCount.setText(String.valueOf(highYield));
                    } else if (body.has("total_payouts")) {
                        int count = body.get("total_payouts").getAsInt();
                        double avgYield = body.has("avg_yield_pct") ? body.get("avg_yield_pct").getAsDouble() : 0.0;
                        int highYield = body.has("high_yield_count") ? body.get("high_yield_count").getAsInt() : 0;

                        statTotalPayouts.setText(String.valueOf(count));
                        statAvgYield.setText(String.format(Locale.US, "%.2f%%", avgYield));
                        statHighYieldCount.setText(String.valueOf(highYield));
                    }

                    // Parse dividends list
                    JsonArray divs = body.getAsJsonArray("dividends");
                    List<JsonObject> items = new ArrayList<>();
                    if (divs != null) {
                        for (JsonElement el : divs) {
                            if (el.isJsonObject()) items.add(el.getAsJsonObject());
                        }
                    }
                    if (items.isEmpty()) {
                        loadUpcomingFallback();
                    } else {
                        adapter.setItems(items);
                    }
                } else if (isAdded()) {
                    loadUpcomingFallback();
                }
                if (isAdded()) swipeRefresh.setRefreshing(false);
            }

            @Override
            public void onFailure(@NonNull Call<JsonObject> call, @NonNull Throwable t) {
                if (isAdded()) {
                    swipeRefresh.setRefreshing(false);
                    loadUpcomingFallback();
                }
            }
        });
    }

    private void loadUpcomingFallback() {
        ApiClient.getApi().getDividends(null, 50, 0).enqueue(new Callback<JsonObject>() {
            @Override
            public void onResponse(@NonNull Call<JsonObject> call, @NonNull Response<JsonObject> response) {
                if (response.isSuccessful() && response.body() != null && isAdded()) {
                    JsonArray divs = response.body().getAsJsonArray("dividends");
                    if (divs != null && divs.size() > 0) {
                        List<JsonObject> fallbackItems = new ArrayList<>();
                        for (JsonElement el : divs) {
                            if (el.isJsonObject()) fallbackItems.add(el.getAsJsonObject());
                        }
                        adapter.setItems(fallbackItems);
                        statTotalPayouts.setText(String.valueOf(fallbackItems.size()));
                    }
                }
            }

            @Override
            public void onFailure(@NonNull Call<JsonObject> call, @NonNull Throwable t) {}
        });
    }

    interface OnDividendClickListener {
        void onDividendClick(JsonObject div);
    }

    static class DividendAdapter extends RecyclerView.Adapter<DividendAdapter.VH> {
        private final List<JsonObject> items = new ArrayList<>();
        private final OnDividendClickListener listener;

        DividendAdapter(OnDividendClickListener listener) {
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
                    .inflate(R.layout.item_dividend, parent, false);
            return new VH(v);
        }

        @Override
        public void onBindViewHolder(@NonNull VH holder, int position) {
            JsonObject div = items.get(position);

            String symbol = div.has("symbol") ? div.get("symbol").getAsString() : "";
            String company = div.has("company_name") && !div.get("company_name").isJsonNull()
                    ? div.get("company_name").getAsString() : symbol;
            Double amount = div.has("amount") && !div.get("amount").isJsonNull()
                    ? div.get("amount").getAsDouble() : null;
            String exDate = div.has("ex_date") && !div.get("ex_date").isJsonNull()
                    ? div.get("ex_date").getAsString() : "";
            String status = div.has("status") && !div.get("status").isJsonNull()
                    ? div.get("status").getAsString() : "upcoming";
            Double price = div.has("current_price") && !div.get("current_price").isJsonNull()
                    ? div.get("current_price").getAsDouble() : null;
            Double yield = div.has("dividend_yield_pct") && !div.get("dividend_yield_pct").isJsonNull()
                    ? div.get("dividend_yield_pct").getAsDouble() : null;
            String badge = div.has("rating_badge") && !div.get("rating_badge").isJsonNull()
                    ? div.get("rating_badge").getAsString() : "DIVIDEND";
            String stars = div.has("stars") && !div.get("stars").isJsonNull()
                    ? div.get("stars").getAsString() : "★★★☆☆";
            String currency = div.has("currency") ? div.get("currency").getAsString() : "INR";

            holder.symbolText.setText(symbol);
            holder.companyText.setText(company);
            holder.amountText.setText(FormatUtils.formatPrice(amount, currency));
            holder.exDateText.setText("Ex: " + FormatUtils.formatDate(exDate));
            holder.statusText.setText(status.toUpperCase());
            holder.ratingBadge.setText(badge);
            holder.ratingStars.setText(stars);

            if (price != null) {
                holder.stockPriceText.setText(FormatUtils.formatPrice(price, currency));
                holder.stockPriceText.setVisibility(View.VISIBLE);
            } else {
                holder.stockPriceText.setVisibility(View.GONE);
            }

            if (yield != null && yield > 0) {
                holder.yieldText.setText(String.format(Locale.US, "%.1f%% Yield", yield));
                holder.yieldText.setVisibility(View.VISIBLE);
            } else {
                holder.yieldText.setVisibility(View.GONE);
            }

            // Status & badge colors
            if ("paid".equalsIgnoreCase(status)) {
                holder.statusText.setTextColor(Color.parseColor("#FF64748B"));
            } else if ("pending".equalsIgnoreCase(status)) {
                holder.statusText.setTextColor(Color.parseColor("#FFD97706"));
            } else {
                holder.statusText.setTextColor(Color.parseColor("#FF2563EB"));
            }

            holder.itemView.setOnClickListener(v -> {
                if (listener != null) listener.onDividendClick(div);
            });
        }

        static class VH extends RecyclerView.ViewHolder {
            TextView symbolText, companyText, amountText, exDateText, statusText;
            TextView yieldText, ratingStars, ratingBadge, stockPriceText;

            VH(View v) {
                super(v);
                symbolText = v.findViewById(R.id.div_symbol);
                companyText = v.findViewById(R.id.div_company);
                amountText = v.findViewById(R.id.div_amount);
                exDateText = v.findViewById(R.id.div_ex_date);
                statusText = v.findViewById(R.id.div_status);
                yieldText = v.findViewById(R.id.div_yield);
                ratingStars = v.findViewById(R.id.div_rating_stars);
                ratingBadge = v.findViewById(R.id.div_rating_badge);
                stockPriceText = v.findViewById(R.id.div_stock_price);
            }
        }
    }
}
