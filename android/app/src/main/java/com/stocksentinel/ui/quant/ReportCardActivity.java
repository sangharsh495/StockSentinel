package com.stocksentinel.ui.quant;

import static com.stocksentinel.ui.quant.QuantPicksActivity.arr;
import static com.stocksentinel.ui.quant.QuantPicksActivity.bool;
import static com.stocksentinel.ui.quant.QuantPicksActivity.dbl;
import static com.stocksentinel.ui.quant.QuantPicksActivity.obj;
import static com.stocksentinel.ui.quant.QuantPicksActivity.str;

import android.graphics.Typeface;
import android.os.Bundle;
import android.text.SpannableStringBuilder;
import android.text.Spanned;
import android.text.style.StyleSpan;
import android.view.View;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.appcompat.app.AppCompatActivity;
import androidx.appcompat.widget.Toolbar;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.stocksentinel.R;
import com.stocksentinel.data.api.ApiClient;

import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;

import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;

/**
 * ReportCardActivity — one stock's 57-check report card: Buy / Hold / Sell
 * for four holding periods, stage, governance, dividends, and every check
 * with how it did when tested on history.
 */
public class ReportCardActivity extends AppCompatActivity {

    public static final String EXTRA_SYMBOL = "extra_symbol";

    private static final Map<String, String> CATEGORY_TITLES = new LinkedHashMap<>();

    static {
        CATEGORY_TITLES.put("trend", "Trend");
        CATEGORY_TITLES.put("momentum", "Momentum");
        CATEGORY_TITLES.put("risk", "Risk");
        CATEGORY_TITLES.put("flow", "Trading flow");
        CATEGORY_TITLES.put("growth", "Growth");
        CATEGORY_TITLES.put("quality", "Quality");
        CATEGORY_TITLES.put("balance_sheet", "Balance sheet");
        CATEGORY_TITLES.put("governance", "Governance");
        CATEGORY_TITLES.put("valuation", "Valuation");
        CATEGORY_TITLES.put("dividend", "Dividends");
    }

    private String symbol;
    private ProgressBar loadingBar;
    private TextView symbolText, stageBadge, summaryText, testsText, governanceText, dividendText, checksText;
    private TextView v1w, v1m, v3m, v1y;

    @Override
    protected void onCreate(@Nullable Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_report_card);

        symbol = getIntent().getStringExtra(EXTRA_SYMBOL);
        if (symbol == null || symbol.isEmpty()) {
            Toast.makeText(this, "Stock symbol missing", Toast.LENGTH_SHORT).show();
            finish();
            return;
        }

        Toolbar toolbar = findViewById(R.id.card_toolbar);
        setSupportActionBar(toolbar);
        if (getSupportActionBar() != null) {
            getSupportActionBar().setDisplayHomeAsUpEnabled(true);
            getSupportActionBar().setDisplayShowTitleEnabled(false);
        }
        toolbar.setNavigationOnClickListener(v -> finish());

        loadingBar = findViewById(R.id.card_loading_bar);
        symbolText = findViewById(R.id.card_symbol);
        stageBadge = findViewById(R.id.card_stage_badge);
        summaryText = findViewById(R.id.card_summary);
        testsText = findViewById(R.id.card_tests);
        governanceText = findViewById(R.id.card_governance);
        dividendText = findViewById(R.id.card_dividend);
        checksText = findViewById(R.id.card_checks);
        v1w = findViewById(R.id.verdict_1w);
        v1m = findViewById(R.id.verdict_1m);
        v3m = findViewById(R.id.verdict_3m);
        v1y = findViewById(R.id.verdict_1y);
        symbolText.setText(symbol);

        loadCard();
    }

    private void loadCard() {
        loadingBar.setVisibility(View.VISIBLE);
        ApiClient.getApi().getReportCard(symbol, "1y").enqueue(new Callback<JsonObject>() {
            @Override
            public void onResponse(@NonNull Call<JsonObject> call, @NonNull Response<JsonObject> response) {
                if (isFinishing()) return;
                loadingBar.setVisibility(View.GONE);
                if (response.isSuccessful() && response.body() != null) {
                    populate(response.body());
                } else {
                    Toast.makeText(ReportCardActivity.this, "Unable to load report card", Toast.LENGTH_SHORT).show();
                }
            }

            @Override
            public void onFailure(@NonNull Call<JsonObject> call, @NonNull Throwable t) {
                if (isFinishing()) return;
                loadingBar.setVisibility(View.GONE);
                Toast.makeText(ReportCardActivity.this, "Failed to load report card", Toast.LENGTH_SHORT).show();
            }
        });
    }

    private void populate(JsonObject body) {
        String status = str(body, "status");
        if (!"ok".equals(status)) {
            summaryText.setText("not_covered".equals(status) ? str(body, "note")
                    : "Report cards update every weekday after market close.");
            testsText.setText("—");
            governanceText.setText("—");
            dividendText.setText("—");
            checksText.setText("—");
            return;
        }
        JsonObject card = obj(body, "card");
        stageBadge.setText(MultibaggerActivity.stageLabel(str(card, "stage")));
        Double passed = dbl(card, "checks_passed");
        Double failed = dbl(card, "checks_failed");
        Double unknown = dbl(card, "checks_unknown");
        summaryText.setText(String.format(Locale.US,
                "%s checks pass, %s fail, %s have no data · as of %s.\n%s",
                n(passed), n(failed), n(unknown), str(body, "as_of"), str(body, "how_to_read")));

        JsonObject verdicts = obj(card, "verdicts");
        bindVerdict(v1w, obj(verdicts, "1w"));
        bindVerdict(v1m, obj(verdicts, "1m"));
        bindVerdict(v3m, obj(verdicts, "3m"));
        bindVerdict(v1y, obj(verdicts, "1y"));

        // How each holding period did on unseen history
        JsonObject tests = obj(body, "horizon_tests");
        StringBuilder t = new StringBuilder();
        String[][] periods = {{"1w", "1 week"}, {"1m", "1 month"}, {"3m", "3 months"}, {"1y", "1 year"}};
        for (String[] p : periods) {
            JsonObject h = obj(tests, p[0]);
            if (h == null) continue;
            if (t.length() > 0) t.append("\n");
            t.append(String.format(Locale.US, "%s %s: Buy picks beat the market %s of the time, Sell picks %s (t = %s)",
                    bool(h, "verified") ? "✓" : "✗", p[1], pct(h, "buy_beat_market_pct"),
                    pct(h, "sell_beat_market_pct"), num(h, "buy_minus_sell_t")));
        }
        testsText.setText(t.length() == 0 ? "No test results yet." : t.toString());

        // Governance
        JsonObject gov = obj(card, "governance");
        StringBuilder g = new StringBuilder(String.format(Locale.US, "Grade %s · %s of %s governance checks passed",
                str(gov, "grade"), n(dbl(gov, "passed")), n(dbl(gov, "checked"))));
        JsonArray flags = arr(card, "red_flags");
        if (flags != null && flags.size() > 0) {
            g.append("\n⚠ Red flags: ");
            for (int i = 0; i < flags.size(); i++) {
                if (i > 0) g.append(", ");
                g.append(flags.get(i).isJsonNull() ? "" : flags.get(i).getAsString().replace('_', ' '));
            }
        }
        JsonArray missing = arr(gov, "not_covered");
        if (missing != null && missing.size() > 0) {
            g.append("\nNot checked yet (no free data source): ");
            for (int i = 0; i < missing.size(); i++) {
                if (i > 0) g.append(", ");
                g.append(missing.get(i).isJsonNull() ? "" : missing.get(i).getAsString());
            }
        }
        governanceText.setText(g.toString());

        // Dividends
        JsonObject div = obj(card, "dividend");
        Double y = dbl(div, "yield_pct");
        dividendText.setText(y == null || y == 0 ? "No dividend in the last 12 months."
                : String.format(Locale.US, "Yield %.2f%% · ₹%s per share in 12 months · paid in %s of the last 5 years · payout %s",
                y, num(div, "dps_ttm"), n(dbl(div, "years_paid_of_5")), pct(div, "payout_pct")));

        bindChecks(arr(card, "checks"));
    }

    private void bindVerdict(TextView view, JsonObject v) {
        String verdict = str(v, "verdict");
        Double chance = dbl(v, "chance_beat_market_pct");
        view.setText(String.format(Locale.US, "%s %s", BestStocksActivity.verdictLabel(verdict),
                chance == null ? "" : String.format(Locale.US, "%.0f%%", chance)));
        view.setTextColor(getResources().getColor(BestStocksActivity.verdictColor(verdict), null));
    }

    /** All checks grouped by category: ✓ / ✗ / – and how each one did when tested over 1 year. */
    private void bindChecks(JsonArray checks) {
        if (checks == null) {
            checksText.setText("No checks available.");
            return;
        }
        SpannableStringBuilder sb = new SpannableStringBuilder();
        for (Map.Entry<String, String> cat : CATEGORY_TITLES.entrySet()) {
            boolean header = false;
            for (JsonElement el : checks) {
                if (!el.isJsonObject()) continue;
                JsonObject c = el.getAsJsonObject();
                if (!cat.getKey().equals(str(c, "category"))) continue;
                if (!header) {
                    if (sb.length() > 0) sb.append("\n");
                    int start = sb.length();
                    sb.append(cat.getValue().toUpperCase(Locale.US)).append("\n");
                    sb.setSpan(new StyleSpan(Typeface.BOLD), start, sb.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
                    header = true;
                }
                String result = str(c, "result");
                String mark = "pass".equals(result) ? "✓" : ("fail".equals(result) ? "✗" : "–");
                sb.append(mark).append(" ").append(str(c, "label"));
                JsonObject tested = obj(c, "tested");
                Double diff = dbl(tested, "pass_minus_fail_pct");
                if (diff != null) {
                    sb.append(String.format(Locale.US, "  (%s %+.1f%%/yr)",
                            bool(tested, "verified") ? "proven" : "unproven", diff));
                }
                sb.append("\n");
            }
        }
        checksText.setText(sb);
    }

    private static String n(Double v) {
        return v == null ? "—" : String.format(Locale.US, "%.0f", v);
    }

    private static String pct(JsonObject o, String k) {
        Double v = dbl(o, k);
        return v == null ? "—" : String.format(Locale.US, "%.1f%%", v);
    }

    private static String num(JsonObject o, String k) {
        Double v = dbl(o, k);
        return v == null ? "—" : String.format(Locale.US, "%.2f", v);
    }
}
