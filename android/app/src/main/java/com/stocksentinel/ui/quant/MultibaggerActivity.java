package com.stocksentinel.ui.quant;

import static com.stocksentinel.ui.quant.QuantPicksActivity.arr;
import static com.stocksentinel.ui.quant.QuantPicksActivity.bool;
import static com.stocksentinel.ui.quant.QuantPicksActivity.dbl;
import static com.stocksentinel.ui.quant.QuantPicksActivity.obj;
import static com.stocksentinel.ui.quant.QuantPicksActivity.str;

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
 * MultibaggerActivity — stocks with the best tested odds of doubling in a
 * year, from the weekly model zoo, with the zoo's honest track record and
 * the market regime above the list.
 */
public class MultibaggerActivity extends AppCompatActivity {

    private SwipeRefreshLayout swipeRefresh;
    private TextView emptyStateText, trustBadge, trustVerdict, trustStats, regimeText, subtitle;
    private RadarAdapter adapter;

    @Override
    protected void onCreate(@Nullable Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_multibagger);

        Toolbar toolbar = findViewById(R.id.radar_toolbar);
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
        regimeText = findViewById(R.id.regime_text);
        subtitle = findViewById(R.id.radar_subtitle);

        RecyclerView recycler = findViewById(R.id.radar_recycler);
        recycler.setLayoutManager(new LinearLayoutManager(this));
        adapter = new RadarAdapter(pick -> QuantPicksActivity.openStock(this, pick));
        recycler.setAdapter(adapter);

        swipeRefresh.setOnRefreshListener(this::loadRadar);
        loadRadar();
    }

    private void loadRadar() {
        swipeRefresh.setRefreshing(true);
        ApiClient.getApi().getMultibaggerRadar().enqueue(new Callback<JsonObject>() {
            @Override
            public void onResponse(@NonNull Call<JsonObject> call, @NonNull Response<JsonObject> response) {
                if (isFinishing()) return;
                List<JsonObject> items = new ArrayList<>();
                if (response.isSuccessful() && response.body() != null) {
                    JsonObject body = response.body();
                    JsonArray picks = arr(body, "picks");
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
        if (!"ok".equals(str(body, "status"))) {
            trustBadge.setText("NOT TRAINED YET");
            trustBadge.setTextColor(getResources().getColor(R.color.text_secondary, null));
            trustVerdict.setText("The model zoo retrains every Saturday.");
            trustStats.setText("");
            regimeText.setText("");
            return;
        }
        boolean edge = bool(body, "edge_verified");
        trustBadge.setText(edge ? "✓ TESTED EDGE" : "NO PROVEN EDGE");
        trustBadge.setTextColor(getResources().getColor(edge ? R.color.bullish : R.color.neutral, null));
        trustVerdict.setText(str(body, "verdict"));

        JsonObject zoo = obj(body, "zoo");
        JsonObject test = obj(body, "honest_test");
        Double fitted = dbl(zoo, "fitted_models");
        Double configs = dbl(zoo, "model_configurations");
        Double survivors = dbl(body, "fdr_survivors");
        Double months = dbl(test, "months");
        Double t = dbl(test, "newey_west_t");
        String asOf = str(body, "as_of");
        subtitle.setText(String.format(Locale.US, "%s models%s",
                fitted == null ? "—" : String.format(Locale.US, "%,.0f", fitted),
                asOf.isEmpty() ? "" : " · as of " + asOf));
        trustStats.setText(String.format(Locale.US,
                "%s configurations · %s passed the luck filter · %s unseen months · t = %s",
                configs == null ? "—" : String.format(Locale.US, "%.0f", configs),
                survivors == null ? "—" : String.format(Locale.US, "%.0f", survivors),
                months == null ? "—" : String.format(Locale.US, "%.0f", months),
                t == null ? "—" : String.format(Locale.US, "%.1f", t)));

        JsonObject regime = obj(body, "regime");
        String current = str(regime, "current");
        Double typical = dbl(regime, "typical_doubling_rate_pct");
        regimeText.setText(current.isEmpty() ? "" : String.format(Locale.US,
                "Market regime: %s · a typical year sees %s of liquid stocks double",
                current, typical == null ? "—" : String.format(Locale.US, "%.1f%%", typical)));
    }

    /** Stage label shown in the row's badge. */
    static String stageLabel(String stage) {
        switch (stage) {
            case "discovery": return "Discovery";
            case "confirmation": return "Confirmation";
            case "momentum": return "Momentum";
            case "exit_risk": return "Exit risk";
            default: return stage;
        }
    }

    /** Rows for radar picks, drawn with the shared item_research_pick layout. */
    static class RadarAdapter extends RecyclerView.Adapter<QuantPicksActivity.PicksAdapter.VH> {
        private final List<JsonObject> items = new ArrayList<>();
        private final QuantPicksActivity.OnPickClickListener listener;

        RadarAdapter(QuantPicksActivity.OnPickClickListener listener) {
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
        public QuantPicksActivity.PicksAdapter.VH onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
            View v = LayoutInflater.from(parent.getContext())
                    .inflate(R.layout.item_research_pick, parent, false);
            return new QuantPicksActivity.PicksAdapter.VH(v);
        }

        @Override
        public void onBindViewHolder(@NonNull QuantPicksActivity.PicksAdapter.VH h, int position) {
            JsonObject p = items.get(position);
            Double odds = dbl(p, "odds_vs_average_stock");
            JsonObject chance = obj(p, "chance_double_1y_pct");
            Double weak = dbl(chance, "weak_year");
            Double typical = dbl(chance, "typical_year");
            Double strong = dbl(chance, "strong_year");
            String stage = str(p, "stage");

            h.gradeText.setText(odds == null ? "—" : String.format(Locale.US, "%.1fx", odds));
            h.symbolText.setText(str(p, "symbol"));
            h.actionText.setText(stageLabel(stage));

            // Two strongest pieces of evidence, e.g. "revenue growth ×1.3 · margin expansion ×1.2"
            StringBuilder why = new StringBuilder();
            JsonArray ev = arr(p, "evidence");
            if (ev != null) {
                int shown = 0;
                for (JsonElement el : ev) {
                    if (!el.isJsonObject() || shown == 2) continue;
                    JsonObject e = el.getAsJsonObject();
                    Double m = dbl(e, "odds_multiplier");
                    if (m == null || m <= 1) continue;
                    if (why.length() > 0) why.append(" · ");
                    why.append(str(e, "label")).append(String.format(Locale.US, " ×%.2f", m));
                    shown++;
                }
            }
            h.reasonText.setText(why.length() == 0 ? "No single factor stands out" : why.toString());

            JsonArray flags = arr(p, "red_flags");
            String chanceText = typical == null ? "" : String.format(Locale.US,
                    "Chance to double in 1y: %.0f%% (weak year %.0f%%, strong %.0f%%)",
                    typical, weak == null ? 0 : weak, strong == null ? 0 : strong);
            if (flags != null && flags.size() > 0) {
                chanceText += String.format(Locale.US, " · ⚠ %d flag%s", flags.size(), flags.size() == 1 ? "" : "s");
            }
            h.scoreText.setText(chanceText);

            Double price = dbl(p, "current_price");
            Double change = dbl(p, "change_pct");
            h.priceText.setText(FormatUtils.formatPrice(price, "INR"));
            h.changeText.setText(FormatUtils.formatChangePercent(change));
            h.changeText.setTextColor(FormatUtils.getChangeColor(change));

            int oddsColor = odds == null ? R.color.neutral : (odds >= 1.2 ? R.color.bullish : R.color.neutral);
            h.gradeText.setTextColor(h.itemView.getResources().getColor(oddsColor, null));
            int stageColor = "exit_risk".equals(stage) ? R.color.bearish
                    : ("momentum".equals(stage) ? R.color.bullish : R.color.blue_accent);
            h.actionText.setTextColor(h.itemView.getResources().getColor(stageColor, null));

            h.itemView.setOnClickListener(v -> {
                if (listener != null) listener.onPickClick(p);
            });
        }
    }
}
