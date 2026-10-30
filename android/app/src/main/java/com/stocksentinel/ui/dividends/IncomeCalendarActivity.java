package com.stocksentinel.ui.dividends;

import static com.stocksentinel.ui.quant.QuantPicksActivity.arr;
import static com.stocksentinel.ui.quant.QuantPicksActivity.dbl;
import static com.stocksentinel.ui.quant.QuantPicksActivity.obj;
import static com.stocksentinel.ui.quant.QuantPicksActivity.str;

import android.content.Intent;
import android.os.Bundle;
import android.view.View;
import android.widget.TextView;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.appcompat.app.AppCompatActivity;
import androidx.appcompat.widget.Toolbar;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.stocksentinel.R;
import com.stocksentinel.data.api.ApiClient;
import com.stocksentinel.ui.stockdetail.StockDetailActivity;

import java.text.DateFormatSymbols;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;

/**
 * IncomeCalendarActivity — dividend payers by the month they usually pay,
 * with filters for yield, regularity, cuts, frequency and governance, and
 * the tested Income Score ("paying power") of each company.
 */
public class IncomeCalendarActivity extends AppCompatActivity {

    private static final String[] SORTS = {"score", "yield", "next"};
    private static final String[] SORT_LABELS = {"Sort: Score", "Sort: Yield", "Sort: Next date"};
    private static final String[] SHORT_MONTHS = new DateFormatSymbols(Locale.US).getShortMonths();

    private SwipeRefreshLayout swipeRefresh;
    private DividendsFragment.DividendAdapter adapter;
    private TextView textCurrentMonth, statTotal, statAvgYield, statHighYield, backtestNote, emptyStateText;
    private TextView chipYield2, chipYield4, chipRegular, chipNoCuts, chipQuarterly, chipHalf, chipGov, chipStrong, chipSort;

    private int month = 0;            // 0 = all months, 1-12
    private int sortIndex = 0;
    private boolean yield2, yield4, regular, noCuts, quarterly, half, gov, strong;
    private JsonObject monthCounts;

    @Override
    protected void onCreate(@Nullable Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_income_calendar);

        Toolbar toolbar = findViewById(R.id.income_toolbar);
        setSupportActionBar(toolbar);
        if (getSupportActionBar() != null) {
            getSupportActionBar().setDisplayHomeAsUpEnabled(true);
            getSupportActionBar().setDisplayShowTitleEnabled(false);
        }
        toolbar.setNavigationOnClickListener(v -> finish());

        swipeRefresh = findViewById(R.id.swipe_refresh);
        textCurrentMonth = findViewById(R.id.text_current_month);
        statTotal = findViewById(R.id.stat_total_payouts);
        statAvgYield = findViewById(R.id.stat_avg_yield);
        statHighYield = findViewById(R.id.stat_high_yield_count);
        backtestNote = findViewById(R.id.income_backtest_note);
        emptyStateText = findViewById(R.id.empty_state_text);

        findViewById(R.id.btn_prev_month).setOnClickListener(v -> {
            month = month == 0 ? 12 : month - 1;
            updateMonthHeader();
            load();
        });
        findViewById(R.id.btn_next_month).setOnClickListener(v -> {
            month = month == 12 ? 0 : month + 1;
            updateMonthHeader();
            load();
        });

        setupChips();

        RecyclerView recycler = findViewById(R.id.income_recycler);
        recycler.setLayoutManager(new LinearLayoutManager(this));
        adapter = new DividendsFragment.DividendAdapter(div -> {
            String sym = str(div, "symbol");
            Intent intent = new Intent(this, StockDetailActivity.class);
            intent.putExtra(StockDetailActivity.EXTRA_SYMBOL, sym);
            intent.putExtra(StockDetailActivity.EXTRA_EXCHANGE, "NSE");
            intent.putExtra(StockDetailActivity.EXTRA_NAME, sym);
            startActivity(intent);
        });
        recycler.setAdapter(adapter);

        swipeRefresh.setOnRefreshListener(this::load);
        updateMonthHeader();
        load();
    }

    private void setupChips() {
        chipYield2 = findViewById(R.id.chip_yield2);
        chipYield4 = findViewById(R.id.chip_yield4);
        chipRegular = findViewById(R.id.chip_regular);
        chipNoCuts = findViewById(R.id.chip_no_cuts);
        chipQuarterly = findViewById(R.id.chip_quarterly);
        chipHalf = findViewById(R.id.chip_half);
        chipGov = findViewById(R.id.chip_gov);
        chipStrong = findViewById(R.id.chip_strong);
        chipSort = findViewById(R.id.chip_sort);

        View.OnClickListener toggle = v -> {
            if (v == chipYield2) { yield2 = !yield2; if (yield2) yield4 = false; }
            else if (v == chipYield4) { yield4 = !yield4; if (yield4) yield2 = false; }
            else if (v == chipRegular) regular = !regular;
            else if (v == chipNoCuts) noCuts = !noCuts;
            else if (v == chipQuarterly) { quarterly = !quarterly; if (quarterly) half = false; }
            else if (v == chipHalf) { half = !half; if (half) quarterly = false; }
            else if (v == chipGov) gov = !gov;
            else if (v == chipStrong) strong = !strong;
            else if (v == chipSort) {
                sortIndex = (sortIndex + 1) % SORTS.length;
                chipSort.setText(SORT_LABELS[sortIndex]);
            }
            highlightChips();
            load();
        };
        for (TextView c : new TextView[]{chipYield2, chipYield4, chipRegular, chipNoCuts, chipQuarterly, chipHalf,
                chipGov, chipStrong, chipSort}) {
            c.setOnClickListener(toggle);
        }
        highlightChips();
    }

    private void highlightChips() {
        int on = getResources().getColor(R.color.blue_accent, null);
        int off = getResources().getColor(R.color.text_secondary, null);
        chipYield2.setTextColor(yield2 ? on : off);
        chipYield4.setTextColor(yield4 ? on : off);
        chipRegular.setTextColor(regular ? on : off);
        chipNoCuts.setTextColor(noCuts ? on : off);
        chipQuarterly.setTextColor(quarterly ? on : off);
        chipHalf.setTextColor(half ? on : off);
        chipGov.setTextColor(gov ? on : off);
        chipStrong.setTextColor(strong ? on : off);
        chipSort.setTextColor(on);
    }

    private void updateMonthHeader() {
        if (month == 0) {
            textCurrentMonth.setText("All months");
            return;
        }
        String name = new DateFormatSymbols(Locale.US).getMonths()[month - 1];
        Double n = monthCounts == null ? null : dbl(monthCounts, SHORT_MONTHS[month - 1]);
        textCurrentMonth.setText(n == null ? name : String.format(Locale.US, "%s · %.0f usually pay", name, n));
    }

    private void load() {
        swipeRefresh.setRefreshing(true);
        final int reqMonth = month;
        final String reqKey = filterKey();
        ApiClient.getApi().getIncomeCalendar(month, yield4 ? 4 : (yield2 ? 2 : 0), 0, regular ? 10 : 0,
                quarterly ? "quarterly" : (half ? "half-yearly" : null), gov ? "AB" : null, noCuts, strong,
                SORTS[sortIndex], 200).enqueue(new Callback<JsonObject>() {
            @Override
            public void onResponse(@NonNull Call<JsonObject> call, @NonNull Response<JsonObject> response) {
                if (isFinishing() || reqMonth != month || !reqKey.equals(filterKey())) return;
                List<JsonObject> items = new ArrayList<>();
                if (response.isSuccessful() && response.body() != null) {
                    JsonObject body = response.body();
                    JsonObject counts = obj(body, "month_counts");
                    if (counts != null) {
                        monthCounts = counts;
                        updateMonthHeader();
                    }
                    bindStats(body);
                    JsonArray divs = arr(body, "dividends");
                    if (divs != null) {
                        for (JsonElement el : divs) {
                            if (el.isJsonObject()) items.add(withRecord(el.getAsJsonObject()));
                        }
                    }
                }
                adapter.setItems(items);
                emptyStateText.setVisibility(items.isEmpty() ? View.VISIBLE : View.GONE);
                swipeRefresh.setRefreshing(false);
            }

            @Override
            public void onFailure(@NonNull Call<JsonObject> call, @NonNull Throwable t) {
                if (!isFinishing()) swipeRefresh.setRefreshing(false);
            }
        });
    }

    private String filterKey() {
        return "" + yield2 + yield4 + regular + noCuts + quarterly + half + gov + strong + sortIndex;
    }

    private void bindStats(JsonObject body) {
        JsonObject stats = obj(body, "stats");
        Double total = dbl(stats, "total_payouts");
        Double avg = dbl(stats, "avg_yield_pct");
        Double high = dbl(stats, "high_yield_count");
        statTotal.setText(total == null ? "--" : String.format(Locale.US, "%.0f", total));
        statAvgYield.setText(avg == null ? "--%" : String.format(Locale.US, "%.2f%%", avg));
        statHighYield.setText(high == null ? "--" : String.format(Locale.US, "%.0f", high));

        JsonObject bt = obj(body, "paying_power_backtest");
        Double paid = dbl(bt, "top_bucket_paid_pct");
        Double noCut = dbl(bt, "top_bucket_no_cut_pct");
        Double cases = dbl(bt, "snapshots");
        backtestNote.setText(paid == null ? "Income Score is being tested on past payment records."
                : String.format(Locale.US,
                "Tested on %.0f past cases (%s): companies with the best payment record paid again the next year "
                        + "%.0f%% of the time and avoided a cut %.0f%% of the time.",
                cases == null ? 0 : cases, str(bt, "years"), paid, noCut == null ? 0 : noCut));
    }

    /** Puts the payment record into the row's name line: "Coal India · quarterly · Feb, Aug, Nov · 10/10 yrs". */
    private JsonObject withRecord(JsonObject p) {
        StringBuilder sb = new StringBuilder(str(p, "company_name"));
        String freq = str(p, "frequency");
        if (!freq.isEmpty()) sb.append(" · ").append(freq);
        JsonArray months = arr(p, "usual_months");
        if (months != null && months.size() > 0) {
            sb.append(" · ");
            for (int i = 0; i < months.size(); i++) {
                if (months.get(i).isJsonNull()) continue;
                int m = months.get(i).getAsInt();
                if (i > 0) sb.append(", ");
                if (m >= 1 && m <= 12) sb.append(SHORT_MONTHS[m - 1]);
            }
        }
        Double years = dbl(p, "years_paid_of_10");
        if (years != null) sb.append(String.format(Locale.US, " · %.0f/10 yrs", years));
        JsonObject copy = p.deepCopy();
        copy.addProperty("company_name", sb.toString());
        return copy;
    }
}
