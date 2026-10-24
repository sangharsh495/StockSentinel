package com.stocksentinel.ui.quant;

import android.content.Context;
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
import com.stocksentinel.ui.stockdetail.StockDetailActivity;
import com.stocksentinel.util.FormatUtils;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;

/**
 * QuantPicksActivity — stocks ranked by walk-forward tested models, per
 * strategy, with the model's track record shown above the list.
 */
public class QuantPicksActivity extends AppCompatActivity {

    public static final String EXTRA_STRATEGY = "extra_strategy";

    /** Investor tab uses the transparent factor score (the investor ML model has no proven edge). */
    public static final String STRATEGY_INVESTOR = "investor_factor";
    public static final String STRATEGY_SWING = "swing";
    public static final String STRATEGY_TRADER = "trader";

    private SwipeRefreshLayout swipeRefresh;
    private TextView emptyStateText, trustBadge, trustVerdict, trustStats, subtitle;
    private TextView chipInvestor, chipSwing, chipTrader;
    private PicksAdapter adapter;
    private String strategy = STRATEGY_INVESTOR;

    @Override
    protected void onCreate(@Nullable Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_quant_picks);

        String s = getIntent().getStringExtra(EXTRA_STRATEGY);
        if (s != null) strategy = s;

        setupToolbar();
        swipeRefresh = findViewById(R.id.swipe_refresh);
        emptyStateText = findViewById(R.id.empty_state_text);
        trustBadge = findViewById(R.id.trust_badge);
        trustVerdict = findViewById(R.id.trust_verdict);
        trustStats = findViewById(R.id.trust_stats);
        subtitle = findViewById(R.id.quant_subtitle);
        chipInvestor = findViewById(R.id.chip_investor);
        chipSwing = findViewById(R.id.chip_swing);
        chipTrader = findViewById(R.id.chip_trader);
        setupChips();

        RecyclerView recycler = findViewById(R.id.quant_recycler);
        recycler.setLayoutManager(new LinearLayoutManager(this));
        adapter = new PicksAdapter(pick -> openStock(this, pick));
        recycler.setAdapter(adapter);

        swipeRefresh.setOnRefreshListener(this::loadPicks);
        loadPicks();
    }

    private void setupToolbar() {
        Toolbar toolbar = findViewById(R.id.quant_toolbar);
        setSupportActionBar(toolbar);
        if (getSupportActionBar() != null) {
            getSupportActionBar().setDisplayHomeAsUpEnabled(true);
            getSupportActionBar().setDisplayShowTitleEnabled(false);
        }
        toolbar.setNavigationOnClickListener(v -> finish());
    }

    private void setupChips() {
        View.OnClickListener listener = v -> {
            if (v == chipInvestor) strategy = STRATEGY_INVESTOR;
            else if (v == chipSwing) strategy = STRATEGY_SWING;
            else if (v == chipTrader) strategy = STRATEGY_TRADER;
            highlightChips();
            loadPicks();
        };
        chipInvestor.setOnClickListener(listener);
        chipSwing.setOnClickListener(listener);
        chipTrader.setOnClickListener(listener);
        highlightChips();
    }

    private void highlightChips() {
        int on = getResources().getColor(R.color.blue_accent, null);
        int off = getResources().getColor(R.color.text_secondary, null);
        chipInvestor.setTextColor(STRATEGY_INVESTOR.equals(strategy) ? on : off);
        chipSwing.setTextColor(STRATEGY_SWING.equals(strategy) ? on : off);
        chipTrader.setTextColor(STRATEGY_TRADER.equals(strategy) ? on : off);
    }

    private void loadPicks() {
        swipeRefresh.setRefreshing(true);
        final String requested = strategy;
        ApiClient.getApi().getQuantPicks(requested, 50).enqueue(new Callback<JsonObject>() {
            @Override
            public void onResponse(@NonNull Call<JsonObject> call, @NonNull Response<JsonObject> response) {
                if (isFinishing() || !requested.equals(strategy)) return;
                List<JsonObject> items = new ArrayList<>();
                if (response.isSuccessful() && response.body() != null) {
                    JsonObject body = response.body();
                    JsonArray picks = body.has("picks") ? body.getAsJsonArray("picks") : null;
                    if (picks != null) {
                        for (JsonElement el : picks) {
                            if (el.isJsonObject()) items.add(el.getAsJsonObject());
                        }
                    }
                    bindTrust(body);
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

    private void bindTrust(JsonObject body) {
        String desc = str(body, "description");
        if (!desc.isEmpty()) subtitle.setText(desc);
        JsonObject trust = body.has("trust") && body.get("trust").isJsonObject()
                ? body.getAsJsonObject("trust") : null;
        if (trust == null) {
            trustBadge.setText("NOT TRAINED YET");
            trustBadge.setTextColor(getResources().getColor(R.color.text_secondary, null));
            trustVerdict.setText("Models update every weekday after market close.");
            trustStats.setText("");
            return;
        }
        boolean edge = trust.has("edge_verified") && trust.get("edge_verified").getAsBoolean();
        boolean skill = trust.has("ranking_skill_verified") && !trust.get("ranking_skill_verified").isJsonNull()
                && trust.get("ranking_skill_verified").getAsBoolean();
        trustBadge.setText(edge ? "✓ TESTED EDGE" : (skill ? "RANKING SKILL ONLY" : "NO PROVEN EDGE"));
        trustBadge.setTextColor(getResources().getColor(
                edge ? R.color.bullish : (skill ? R.color.yellow_accent : R.color.neutral), null));
        trustVerdict.setText(str(trust, "verdict"));
        trustStats.setText(String.format(Locale.US,
                "Backtest %s/yr vs Nifty %s · all stocks %s · AUC %s",
                pct(trust, "backtest_cagr_pct"), pct(trust, "nifty_cagr_pct"),
                pct(trust, "backtest_equal_weight_cagr_pct"), num(trust, "auc")));
    }

    // ---- helpers shared with HomeFragment ----

    public static String str(JsonObject o, String k) {
        return o != null && o.has(k) && !o.get(k).isJsonNull() ? o.get(k).getAsString() : "";
    }

    public static Double dbl(JsonObject o, String k) {
        return o != null && o.has(k) && !o.get(k).isJsonNull() ? o.get(k).getAsDouble() : null;
    }

    private static String pct(JsonObject o, String k) {
        Double v = dbl(o, k);
        return v == null ? "—" : String.format(Locale.US, "%.1f%%", v);
    }

    private static String num(JsonObject o, String k) {
        Double v = dbl(o, k);
        return v == null ? "—" : String.format(Locale.US, "%.3f", v);
    }

    public static void openStock(Context ctx, JsonObject pick) {
        String sym = str(pick, "symbol");
        String name = str(pick, "name");
        Intent intent = new Intent(ctx, StockDetailActivity.class);
        intent.putExtra(StockDetailActivity.EXTRA_SYMBOL, sym);
        intent.putExtra(StockDetailActivity.EXTRA_EXCHANGE, "NSE");
        intent.putExtra(StockDetailActivity.EXTRA_NAME, name.isEmpty() ? sym : name);
        ctx.startActivity(intent);
    }

    public interface OnPickClickListener {
        void onPickClick(JsonObject pick);
    }

    /** Rows for tested picks, drawn with the shared item_research_pick layout. */
    public static class PicksAdapter extends RecyclerView.Adapter<PicksAdapter.VH> {
        private final List<JsonObject> items = new ArrayList<>();
        private final OnPickClickListener listener;

        public PicksAdapter(OnPickClickListener listener) {
            this.listener = listener;
        }

        public void setItems(List<JsonObject> newItems) {
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
                    .inflate(R.layout.item_research_pick, parent, false);
            return new VH(v);
        }

        @Override
        public void onBindViewHolder(@NonNull VH holder, int position) {
            JsonObject p = items.get(position);
            Double prob = dbl(p, "probability");
            Double exp = dbl(p, "expected_excess_pct");
            Double hit = dbl(p, "historical_hit_rate_pct");
            JsonArray range = p.has("typical_range_pct") && p.get("typical_range_pct").isJsonArray()
                    ? p.getAsJsonArray("typical_range_pct") : null;

            holder.gradeText.setText(prob == null ? "—" : String.format(Locale.US, "%.0f%%", prob * 100));
            holder.symbolText.setText(str(p, "symbol"));
            holder.actionText.setText("#" + str(p, "rank"));

            String rangeText = "";
            if (range != null && range.size() == 2 && !range.get(0).isJsonNull() && !range.get(1).isJsonNull()) {
                rangeText = String.format(Locale.US, " (range %+.1f%% to %+.1f%%)",
                        range.get(0).getAsDouble(), range.get(1).getAsDouble());
            }
            holder.reasonText.setText(exp == null ? "No history for this score yet"
                    : String.format(Locale.US, "Avg vs market %+.2f%%%s", exp, rangeText));
            holder.scoreText.setText(hit == null ? ""
                    : String.format(Locale.US, "Similar scores beat peers %.0f%% of the time", hit));

            Double price = dbl(p, "current_price");
            Double change = dbl(p, "change_pct");
            holder.priceText.setText(FormatUtils.formatPrice(price, "INR"));
            holder.changeText.setText(FormatUtils.formatChangePercent(change));
            holder.changeText.setTextColor(FormatUtils.getChangeColor(change));

            int color = prob == null ? R.color.neutral
                    : (prob >= 0.55 ? R.color.bullish : (prob <= 0.45 ? R.color.bearish : R.color.neutral));
            holder.gradeText.setTextColor(holder.itemView.getResources().getColor(color, null));
            holder.actionText.setTextColor(holder.itemView.getResources().getColor(R.color.blue_accent, null));

            holder.itemView.setOnClickListener(v -> {
                if (listener != null) listener.onPickClick(p);
            });
        }

        static class VH extends RecyclerView.ViewHolder {
            TextView gradeText, symbolText, actionText, reasonText, scoreText, priceText, changeText;

            VH(View v) {
                super(v);
                gradeText = v.findViewById(R.id.pick_grade);
                symbolText = v.findViewById(R.id.pick_symbol);
                actionText = v.findViewById(R.id.pick_action);
                reasonText = v.findViewById(R.id.pick_reason);
                scoreText = v.findViewById(R.id.pick_score);
                priceText = v.findViewById(R.id.pick_price);
                changeText = v.findViewById(R.id.pick_change);
            }
        }
    }
}
