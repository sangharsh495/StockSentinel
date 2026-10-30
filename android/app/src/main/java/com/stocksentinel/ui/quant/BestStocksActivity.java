package com.stocksentinel.ui.quant;

import static com.stocksentinel.ui.quant.QuantPicksActivity.arr;
import static com.stocksentinel.ui.quant.QuantPicksActivity.bool;
import static com.stocksentinel.ui.quant.QuantPicksActivity.dbl;
import static com.stocksentinel.ui.quant.QuantPicksActivity.obj;
import static com.stocksentinel.ui.quant.QuantPicksActivity.str;

import android.content.Intent;
import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
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
import com.stocksentinel.util.FormatUtils;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;

/**
 * BestStocksActivity — best stocks for a holding period (Buy verdicts from
 * the 57-check report card, clean governance only) or best dividend stocks,
 * with that period's tested track record above the list.
 */
public class BestStocksActivity extends AppCompatActivity {

    private static final String KIND_STOCKS = "stocks";
    private static final String KIND_DIVIDEND = "dividend";

    private SwipeRefreshLayout swipeRefresh;
    private TextView emptyStateText, trustBadge, trustVerdict, trustStats;
    private TextView chip1w, chip1m, chip3m, chip1y, chipDividend;
    private BestAdapter adapter;
    private String horizon = "1y";
    private String kind = KIND_STOCKS;

    @Override
    protected void onCreate(@Nullable Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_best_stocks);

        Toolbar toolbar = findViewById(R.id.best_toolbar);
        setSupportActionBar(toolbar);
        if (getSupportActionBar() != null) {
            getSupportActionBar().setDisplayHomeAsUpEnabled(true);
            getSupportActionBar().setDisplayShowTitleEnabled(false);
        }
        toolbar.setNavigationOnClickListener(v -> finish());

        swipeRefresh = findViewById(R.id.swipe_refresh);
        emptyStateText = findViewById(R.id.empty_state_text);
        trustBadge = findViewById(R.id.trust_badge);
        trustVerdict = findViewById(R.id.trust_verdict);
        trustStats = findViewById(R.id.trust_stats);
        chip1w = findViewById(R.id.chip_1w);
        chip1m = findViewById(R.id.chip_1m);
        chip3m = findViewById(R.id.chip_3m);
        chip1y = findViewById(R.id.chip_1y);
        chipDividend = findViewById(R.id.chip_dividend);
        setupChips();

        RecyclerView recycler = findViewById(R.id.best_recycler);
        recycler.setLayoutManager(new LinearLayoutManager(this));
        adapter = new BestAdapter(pick -> {
            Intent intent = new Intent(this, ReportCardActivity.class);
            intent.putExtra(ReportCardActivity.EXTRA_SYMBOL, str(pick, "symbol"));
            startActivity(intent);
        });
        recycler.setAdapter(adapter);

        swipeRefresh.setOnRefreshListener(this::loadBest);
        loadBest();
    }

    private void setupChips() {
        View.OnClickListener listener = v -> {
            kind = v == chipDividend ? KIND_DIVIDEND : KIND_STOCKS;
            if (v == chip1w) horizon = "1w";
            else if (v == chip1m) horizon = "1m";
            else if (v == chip3m) horizon = "3m";
            else horizon = "1y";
            highlightChips();
            loadBest();
        };
        chip1w.setOnClickListener(listener);
        chip1m.setOnClickListener(listener);
        chip3m.setOnClickListener(listener);
        chip1y.setOnClickListener(listener);
        chipDividend.setOnClickListener(listener);
        highlightChips();
    }

    private void highlightChips() {
        int on = getResources().getColor(R.color.blue_accent, null);
        int off = getResources().getColor(R.color.text_secondary, null);
        boolean stocks = KIND_STOCKS.equals(kind);
        chip1w.setTextColor(stocks && "1w".equals(horizon) ? on : off);
        chip1m.setTextColor(stocks && "1m".equals(horizon) ? on : off);
        chip3m.setTextColor(stocks && "3m".equals(horizon) ? on : off);
        chip1y.setTextColor(stocks && "1y".equals(horizon) ? on : off);
        chipDividend.setTextColor(stocks ? off : on);
    }

    private void loadBest() {
        swipeRefresh.setRefreshing(true);
        final String reqKind = kind, reqHorizon = horizon;
        ApiClient.getApi().getBestStocks(reqKind, reqHorizon, 25).enqueue(new Callback<JsonObject>() {
            @Override
            public void onResponse(@NonNull Call<JsonObject> call, @NonNull Response<JsonObject> response) {
                if (isFinishing() || !reqKind.equals(kind) || !reqHorizon.equals(horizon)) return;
                List<JsonObject> items = new ArrayList<>();
                if (response.isSuccessful() && response.body() != null) {
                    JsonObject body = response.body();
                    JsonArray stocks = arr(body, "stocks");
                    if (stocks != null) {
                        for (JsonElement el : stocks) {
                            if (el.isJsonObject()) items.add(el.getAsJsonObject());
                        }
                    }
                    bindTrust(body);
                }
                adapter.setItems(items, KIND_DIVIDEND.equals(reqKind));
                emptyStateText.setVisibility(items.isEmpty() ? View.VISIBLE : View.GONE);
                swipeRefresh.setRefreshing(false);
            }

            @Override
            public void onFailure(@NonNull Call<JsonObject> call, @NonNull Throwable t) {
                if (!isFinishing()) swipeRefresh.setRefreshing(false);
            }
        });
    }

    private void bindTrust(JsonObject body) {
        if (!"ok".equals(str(body, "status"))) {
            trustBadge.setText("NOT TRAINED YET");
            trustBadge.setTextColor(getResources().getColor(R.color.text_secondary, null));
            trustVerdict.setText("Report cards update every weekday after market close.");
            trustStats.setText("");
            return;
        }
        boolean verified = bool(body, "verified");
        trustBadge.setText(verified ? "✓ TESTED EDGE" : "NO PROVEN EDGE");
        trustBadge.setTextColor(getResources().getColor(verified ? R.color.bullish : R.color.neutral, null));
        if (KIND_DIVIDEND.equals(kind)) {
            JsonObject d = obj(body, "dividend_backtest");
            trustVerdict.setText("Dividend payers with a 4-of-5-year streak, safe payout and clean governance, "
                    + "ranked by yield, growth and cash cover.");
            trustStats.setText(String.format(Locale.US,
                    "Past top 20: %s above the median stock per year (total return) · beat it %s of the time · %s months",
                    pct(d, "top20_avg_1y_excess_total_return_pct", true), pct(d, "top20_beat_market_pct", false),
                    num(d, "months")));
        } else {
            JsonObject t = obj(obj(body, "horizon_tests"), horizon);
            trustVerdict.setText(verified
                    ? "Buy = likely to beat the median stock over this period. Only stocks with governance A or B and no red flags are listed."
                    : "This holding period did not prove itself on unseen history, so every verdict here is Hold. Listed by score for research only.");
            JsonObject liveBuy = obj(obj(obj(body, "live_scorecard"), "this_period"), "buy");
            String live = liveBuy == null ? "Live record: collecting real calls"
                    : String.format(Locale.US, "Live: Buy calls beat the market %s of %s scored calls",
                    pct(liveBuy, "beat_market_pct", false), num(liveBuy, "scored").replace(".0", ""));
            trustStats.setText(String.format(Locale.US,
                    "On unseen months: Buy picks beat the market %s · Sell picks %s · t = %s\n%s",
                    pct(t, "buy_beat_market_pct", false), pct(t, "sell_beat_market_pct", false),
                    num(t, "buy_minus_sell_t"), live));
        }
    }

    private static String pct(JsonObject o, String k, boolean signed) {
        Double v = dbl(o, k);
        return v == null ? "—" : String.format(Locale.US, signed ? "%+.1f%%" : "%.1f%%", v);
    }

    private static String num(JsonObject o, String k) {
        Double v = dbl(o, k);
        return v == null ? "—" : String.format(Locale.US, "%.1f", v);
    }

    static String verdictLabel(String v) {
        switch (v) {
            case "buy": return "BUY";
            case "sell": return "SELL";
            default: return "HOLD";
        }
    }

    static int verdictColor(String v) {
        switch (v) {
            case "buy": return R.color.bullish;
            case "sell": return R.color.bearish;
            default: return R.color.neutral;
        }
    }

    /** Rows drawn with the shared item_research_pick layout. */
    static class BestAdapter extends RecyclerView.Adapter<QuantPicksActivity.PicksAdapter.VH> {
        private final List<JsonObject> items = new ArrayList<>();
        private final QuantPicksActivity.OnPickClickListener listener;
        private boolean dividend;

        BestAdapter(QuantPicksActivity.OnPickClickListener listener) {
            this.listener = listener;
        }

        void setItems(List<JsonObject> newItems, boolean dividendList) {
            items.clear();
            items.addAll(newItems);
            dividend = dividendList;
            notifyDataSetChanged();
        }

        @Override
        public int getItemCount() { return items.size(); }

        @NonNull
        @Override
        public QuantPicksActivity.PicksAdapter.VH onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
            View v = LayoutInflater.from(parent.getContext())
                    .inflate(R.layout.item_research_pick, parent, false);
            return new QuantPicksActivity.PicksAdapter.VH(v);
        }

        @Override
        public void onBindViewHolder(@NonNull QuantPicksActivity.PicksAdapter.VH h, int position) {
            JsonObject p = items.get(position);
            JsonObject verdict = obj(p, "verdict");
            JsonObject div = obj(p, "dividend");
            String v = str(verdict, "verdict");
            Double chance = dbl(verdict, "chance_beat_market_pct");
            Double passed = dbl(p, "checks_passed");
            Double failed = dbl(p, "checks_failed");

            h.gradeText.setText(verdictLabel(v));
            h.gradeText.setTextColor(h.itemView.getResources().getColor(verdictColor(v), null));
            h.symbolText.setText(str(p, "symbol"));
            h.actionText.setText(MultibaggerActivity.stageLabel(str(p, "stage")));
            h.actionText.setTextColor(h.itemView.getResources().getColor(R.color.blue_accent, null));

            h.reasonText.setText(String.format(Locale.US, "%s ✓ · %s ✗ of 57 checks · governance %s",
                    passed == null ? "—" : String.format(Locale.US, "%.0f", passed),
                    failed == null ? "—" : String.format(Locale.US, "%.0f", failed), str(p, "governance")));
            if (dividend) {
                Double y = dbl(div, "yield_pct");
                Double years = dbl(div, "years_paid_of_5");
                h.scoreText.setText(String.format(Locale.US, "Yield %s · paid %s of last 5 years",
                        y == null ? "—" : String.format(Locale.US, "%.2f%%", y),
                        years == null ? "—" : String.format(Locale.US, "%.0f", years)));
            } else {
                h.scoreText.setText(chance == null ? "" : String.format(Locale.US,
                        "Chance to beat the market: %.0f%%", chance));
            }

            Double price = dbl(p, "current_price");
            Double change = dbl(p, "change_pct");
            h.priceText.setText(FormatUtils.formatPrice(price, "INR"));
            h.changeText.setText(FormatUtils.formatChangePercent(change));
            h.changeText.setTextColor(FormatUtils.getChangeColor(change));

            h.itemView.setOnClickListener(x -> {
                if (listener != null) listener.onPickClick(p);
            });
        }
    }
}
