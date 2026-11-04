package com.stocksentinel.ui.quant;

import static com.stocksentinel.ui.quant.QuantPicksActivity.arr;
import static com.stocksentinel.ui.quant.QuantPicksActivity.bool;
import static com.stocksentinel.ui.quant.QuantPicksActivity.dbl;
import static com.stocksentinel.ui.quant.QuantPicksActivity.obj;
import static com.stocksentinel.ui.quant.QuantPicksActivity.str;

import android.os.Bundle;
import android.view.View;
import android.view.inputmethod.EditorInfo;
import android.widget.EditText;
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
import com.stocksentinel.util.FormatUtils;

import java.util.Locale;

import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;

/**
 * ResearchActivity — one NSE stock through every tested model: verdicts per
 * holding period, how much to invest (risk budget, quarter-Kelly and evidence
 * caps), tested price ranges, valuation against the whole market, news with
 * measured impact, the checks that matter most, governance and dividends.
 */
public class ResearchActivity extends AppCompatActivity {

    public static final String EXTRA_SYMBOL = "extra_symbol";
    private static final String[][] PERIODS = {{"1w", "1 week"}, {"1m", "1 month"}, {"3m", "3 months"}, {"1y", "1 year"}};

    private EditText symbolInput, capitalInput;
    private ProgressBar loadingBar;
    private TextView nameText, stageBadge, summaryText, priceText, changeText, verdictText, chanceText;
    private TextView analystsText, positionText, rangesText, valuationText, newsText, checksText, governanceText, dividendText, trustText;
    private TextView chip1w, chip1m, chip3m, chip1y, chipR05, chipR1, chipR2;
    private String horizon = null;      // null: the server picks the longest tested period
    private double riskPct = 1.0;
    private String lastKey = "";

    @Override
    protected void onCreate(@Nullable Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_research);

        Toolbar toolbar = findViewById(R.id.research_toolbar);
        setSupportActionBar(toolbar);
        if (getSupportActionBar() != null) {
            getSupportActionBar().setDisplayHomeAsUpEnabled(true);
            getSupportActionBar().setDisplayShowTitleEnabled(false);
        }
        toolbar.setNavigationOnClickListener(v -> finish());

        symbolInput = findViewById(R.id.research_symbol);
        capitalInput = findViewById(R.id.research_capital);
        loadingBar = findViewById(R.id.research_loading_bar);
        nameText = findViewById(R.id.research_name);
        stageBadge = findViewById(R.id.research_stage_badge);
        summaryText = findViewById(R.id.research_summary);
        priceText = findViewById(R.id.research_price);
        changeText = findViewById(R.id.research_change);
        verdictText = findViewById(R.id.research_verdict);
        chanceText = findViewById(R.id.research_chance);
        analystsText = findViewById(R.id.research_analysts);
        positionText = findViewById(R.id.research_position);
        rangesText = findViewById(R.id.research_ranges);
        valuationText = findViewById(R.id.research_valuation);
        newsText = findViewById(R.id.research_news);
        checksText = findViewById(R.id.research_checks);
        governanceText = findViewById(R.id.research_governance);
        dividendText = findViewById(R.id.research_dividend);
        trustText = findViewById(R.id.research_trust);
        setupChips();

        findViewById(R.id.btn_research_go).setOnClickListener(v -> load());
        TextView.OnEditorActionListener go = (v, actionId, e) -> {
            if (actionId == EditorInfo.IME_ACTION_SEARCH) {
                load();
                return true;
            }
            return false;
        };
        symbolInput.setOnEditorActionListener(go);
        capitalInput.setOnEditorActionListener(go);

        String sym = getIntent().getStringExtra(EXTRA_SYMBOL);
        if (sym != null && !sym.isEmpty()) {
            symbolInput.setText(sym);
            load();
        }
    }

    private void setupChips() {
        chip1w = findViewById(R.id.chip_h_1w);
        chip1m = findViewById(R.id.chip_h_1m);
        chip3m = findViewById(R.id.chip_h_3m);
        chip1y = findViewById(R.id.chip_h_1y);
        chipR05 = findViewById(R.id.chip_r_05);
        chipR1 = findViewById(R.id.chip_r_1);
        chipR2 = findViewById(R.id.chip_r_2);
        View.OnClickListener l = v -> {
            if (v == chip1w) horizon = "1w";
            else if (v == chip1m) horizon = "1m";
            else if (v == chip3m) horizon = "3m";
            else if (v == chip1y) horizon = "1y";
            else if (v == chipR05) riskPct = 0.5;
            else if (v == chipR1) riskPct = 1.0;
            else if (v == chipR2) riskPct = 2.0;
            highlightChips();
            if (!symbolInput.getText().toString().trim().isEmpty()) load();
        };
        for (TextView c : new TextView[]{chip1w, chip1m, chip3m, chip1y, chipR05, chipR1, chipR2}) c.setOnClickListener(l);
        highlightChips();
    }

    private void highlightChips() {
        int on = getResources().getColor(R.color.blue_accent, null);
        int off = getResources().getColor(R.color.text_secondary, null);
        chip1w.setTextColor("1w".equals(horizon) ? on : off);
        chip1m.setTextColor("1m".equals(horizon) ? on : off);
        chip3m.setTextColor("3m".equals(horizon) ? on : off);
        chip1y.setTextColor("1y".equals(horizon) ? on : off);
        chipR05.setTextColor(riskPct == 0.5 ? on : off);
        chipR1.setTextColor(riskPct == 1.0 ? on : off);
        chipR2.setTextColor(riskPct == 2.0 ? on : off);
    }

    private void load() {
        String sym = symbolInput.getText().toString().trim().toUpperCase(Locale.US);
        if (sym.isEmpty()) {
            Toast.makeText(this, "Type an NSE symbol first", Toast.LENGTH_SHORT).show();
            return;
        }
        double capital = 100000;
        try {
            String c = capitalInput.getText().toString().trim();
            if (!c.isEmpty()) capital = Double.parseDouble(c);
        } catch (NumberFormatException ignored) {
            // keep the default
        }
        if (capital <= 0) capital = 100000;
        final String key = sym + "|" + capital + "|" + riskPct + "|" + horizon;
        lastKey = key;
        loadingBar.setVisibility(View.VISIBLE);
        ApiClient.getApi().getResearch(sym, capital, riskPct, horizon).enqueue(new Callback<JsonObject>() {
            @Override
            public void onResponse(@NonNull Call<JsonObject> call, @NonNull Response<JsonObject> response) {
                if (isFinishing() || !key.equals(lastKey)) return;
                loadingBar.setVisibility(View.GONE);
                if (response.isSuccessful() && response.body() != null) {
                    populate(response.body());
                } else {
                    Toast.makeText(ResearchActivity.this, "Unable to load research", Toast.LENGTH_SHORT).show();
                }
            }

            @Override
            public void onFailure(@NonNull Call<JsonObject> call, @NonNull Throwable t) {
                if (isFinishing() || !key.equals(lastKey)) return;
                loadingBar.setVisibility(View.GONE);
                Toast.makeText(ResearchActivity.this, "Failed to load research", Toast.LENGTH_SHORT).show();
            }
        });
    }

    private void populate(JsonObject b) {
        if (!"ok".equals(str(b, "status"))) {
            nameText.setText(str(b, "symbol"));
            summaryText.setText(str(b, "note"));
            clearSections();
            return;
        }
        String h = str(b, "horizon");
        if (horizon == null) {          // show which period the server chose
            horizon = h;
            highlightChips();
        }
        nameText.setText(str(b, "symbol"));
        String stage = str(b, "stage");
        stageBadge.setText(stage.isEmpty() ? "—" : MultibaggerActivity.stageLabel(stage));
        String note = str(b, "note");
        summaryText.setText(str(b, "name") + (note.isEmpty() ? "" : "\n" + note));

        JsonObject price = obj(b, "price");
        Double p = dbl(price, "current");
        Double ch = dbl(price, "change_pct");
        priceText.setText(FormatUtils.formatPrice(p, "INR"));
        changeText.setText(FormatUtils.formatChangePercent(ch));
        changeText.setTextColor(FormatUtils.getChangeColor(ch));

        JsonObject v = obj(obj(b, "verdicts"), h);
        String verdict = str(v, "verdict");
        verdictText.setText(v == null ? "—" : BestStocksActivity.verdictLabel(verdict)
                + (bool(v, "horizon_verified") ? "" : "*"));
        verdictText.setTextColor(getResources().getColor(BestStocksActivity.verdictColor(verdict), null));
        Double chance = dbl(v, "chance_beat_market_pct");
        chanceText.setText(chance == null ? "—" : String.format(Locale.US, "%.0f%%", chance));

        bindAnalysts(obj(b, "analysts"), h);
        bindPosition(obj(b, "position"));
        bindRanges(obj(b, "ranges"), obj(b, "ranges_track_record"));
        bindValuation(obj(b, "valuation"));
        bindNews(obj(b, "news"));
        bindChecks(arr(b, "key_checks"), obj(b, "checks"));
        bindGovernance(obj(b, "governance"), arr(b, "red_flags"), obj(b, "mentions"));
        bindDividend(obj(b, "dividend"));
        bindTrust(obj(b, "trust"), obj(b, "verdicts"));
    }

    private void clearSections() {
        for (TextView t : new TextView[]{analystsText, positionText, rangesText, valuationText, newsText, checksText,
                governanceText, dividendText, trustText}) t.setText("—");
        priceText.setText("—");
        changeText.setText("—");
        verdictText.setText("—");
        chanceText.setText("—");
        stageBadge.setText("—");
    }

    private void bindAnalysts(JsonObject a, String h) {
        JsonObject cons = obj(a, "consensus");
        if (cons == null) {
            analystsText.setText("The analyst panel hasn't voted on this stock yet.");
            return;
        }
        StringBuilder sb = new StringBuilder();
        for (String[] pp : PERIODS) {
            JsonObject c = obj(cons, pp[0]);
            if (c == null) continue;
            sb.append(String.format(Locale.US, "%s%s: %s of %s analysts bullish · %s%% chance to beat the market · %s%s\n",
                    pp[0].equals(h) ? "▶ " : "", pp[1], n0(dbl(c, "bullish_analysts")), n0(dbl(c, "analysts_voting")),
                    n0(dbl(c, "chance_beat_market_pct")), BestStocksActivity.verdictLabel(str(c, "verdict")),
                    bool(c, "verified") ? "" : " (unproven)"));
        }
        JsonArray top = arr(obj(cons, h), "top_analysts");
        if (top != null && top.size() > 0) {
            sb.append("Most trusted for this period:\n");
            for (JsonElement e : top) {
                if (!e.isJsonObject()) continue;
                JsonObject t = e.getAsJsonObject();
                sb.append(String.format(Locale.US, "• %s: %s%%\n", str(t, "name"), n0(dbl(t, "chance_pct"))));
            }
        }
        JsonObject test = obj(obj(a, "tests"), h);
        Double buy = dbl(test, "buy_beat_market_pct");
        if (buy != null) {
            sb.append(String.format(Locale.US, "Tested: the consensus's Buy picks beat the market %.1f%% of the time, Sell picks %s.",
                    buy, dbl(test, "sell_beat_market_pct") == null ? "—"
                            : String.format(Locale.US, "%.1f%%", dbl(test, "sell_beat_market_pct"))));
        }
        analystsText.setText(sb.toString().trim());
    }

    private void bindPosition(JsonObject pos) {
        if (pos == null) {
            positionText.setText("No report card for this stock yet, so no tested position size.");
            return;
        }
        StringBuilder sb = new StringBuilder();
        Double shares = dbl(pos, "shares");
        Double amount = dbl(pos, "amount");
        if (shares == null || shares <= 0) {
            sb.append("Suggested: don't buy now.\n");
        } else {
            sb.append(String.format(Locale.US, "Suggested: %s shares ≈ %s (%.1f%% of your portfolio)\n",
                    n0(shares), FormatUtils.formatPrice(amount, "INR"), dblOr(pos, "weight_pct")));
            sb.append(String.format(Locale.US, "Stop %s · target %s · loss if stopped %s · gain at target %s\n",
                    FormatUtils.formatPrice(dbl(pos, "stop"), "INR"), FormatUtils.formatPrice(dbl(pos, "target"), "INR"),
                    FormatUtils.formatPrice(dbl(pos, "loss_if_stopped"), "INR"),
                    FormatUtils.formatPrice(dbl(pos, "gain_if_target"), "INR")));
        }
        JsonArray notes = arr(pos, "notes");
        if (notes != null) {
            for (JsonElement e : notes) {
                if (e.isJsonPrimitive()) sb.append("• ").append(e.getAsString()).append("\n");
            }
        }
        sb.append("Not investment advice: the smallest of the three limits is used.");
        positionText.setText(sb.toString());
    }

    private void bindRanges(JsonObject ranges, JsonObject track) {
        if (ranges == null) {
            rangesText.setText("No tested price range for this stock yet.");
            return;
        }
        StringBuilder sb = new StringBuilder();
        String[][] hs = {{"1d", "Tomorrow"}, {"5d", "1 week"}, {"20d", "1 month"}};
        for (String[] hh : hs) {
            JsonObject r = obj(ranges, hh[0]);
            JsonArray p80 = arr(r, "p80");
            JsonArray p95 = arr(r, "p95");
            if (p80 == null || p80.size() < 2) continue;
            sb.append(String.format(Locale.US, "%s: 80%% between %s and %s", hh[1], px(p80, 0), px(p80, 1)));
            if (p95 != null && p95.size() == 2) {
                sb.append(String.format(Locale.US, " · 95%% %s – %s", px(p95, 0), px(p95, 1)));
            }
            sb.append("\n");
        }
        JsonObject t20 = obj(track, "20d");
        Double ach = dbl(t20, "achieved");
        if (ach != null) {
            sb.append(String.format(Locale.US, "On past days the 1-month 80%% range really held %.1f%% of the time.", ach * 100));
        }
        rangesText.setText(sb.length() == 0 ? "No tested price range for this stock yet." : sb.toString().trim());
    }

    private void bindValuation(JsonObject val) {
        if (val == null) {
            valuationText.setText("No valuation data for this stock yet.");
            return;
        }
        String[][] rows = {{"pe", "P/E", "x"}, {"ps", "Price/Sales", "x"}, {"roe", "ROE", "%"},
                {"rev_growth", "Revenue growth", "%"}, {"op_margin", "Operating margin", "%"},
                {"debt_to_equity", "Debt/Equity", "x"}, {"div_yield", "Dividend yield", "%"},
                {"ret_1y", "1-year return", "%"}, {"vol60", "Daily volatility", "%"}};
        StringBuilder sb = new StringBuilder();
        for (String[] r : rows) {
            JsonObject o = obj(val, r[0]);
            Double value = dbl(o, "value");
            Double pct = dbl(o, "market_percentile");
            String shown = value == null ? "—" : ("%".equals(r[2])
                    ? String.format(Locale.US, "%.1f%%", value * 100) : String.format(Locale.US, "%.2f", value));
            sb.append(r[1]).append(": ").append(shown);
            if (pct != null) {
                sb.append(String.format(Locale.US, " · higher than %.0f%% of NSE stocks (%s)", pct, str(o, "reading")));
            }
            sb.append("\n");
        }
        valuationText.setText(sb.toString().trim());
    }

    private void bindNews(JsonObject news) {
        if (news == null) {
            newsText.setText("No news linked to this stock yet.");
            return;
        }
        StringBuilder sb = new StringBuilder();
        sb.append(String.format(Locale.US, "Recent: %s bullish, %s bearish\n", n0(dbl(news, "bullish")), n0(dbl(news, "bearish"))));
        JsonArray items = arr(news, "items");
        if (items != null) {
            int shown = 0;
            for (JsonElement e : items) {
                if (!e.isJsonObject() || shown == 6) continue;
                JsonObject it = e.getAsJsonObject();
                String dir = str(it, "direction");
                sb.append("BULLISH".equals(dir) ? "▲ " : ("BEARISH".equals(dir) ? "▼ " : "• "));
                sb.append(str(it, "title"));
                Double a5 = dbl(it, "measured_abn_5d_pct");
                if (a5 != null) sb.append(String.format(Locale.US, " (measured: %+.1f%% vs market in 5 days)", a5));
                sb.append("\n");
                shown++;
            }
        }
        String note = str(obj(news, "model"), "note");
        if (!note.isEmpty()) sb.append(note);
        newsText.setText(sb.toString().trim());
    }

    private void bindChecks(JsonArray checks, JsonObject counts) {
        StringBuilder sb = new StringBuilder();
        if (counts != null) {
            sb.append(String.format(Locale.US, "%s of 57 checks pass, %s fail, %s no data\n",
                    n0(dbl(counts, "passed")), n0(dbl(counts, "failed")), n0(dbl(counts, "unknown"))));
        }
        if (checks != null) {
            for (JsonElement e : checks) {
                if (!e.isJsonObject()) continue;
                JsonObject c = e.getAsJsonObject();
                String res = str(c, "result");
                sb.append("pass".equals(res) ? "✓ " : ("fail".equals(res) ? "✗ " : "– "));
                sb.append(str(c, "label"));
                Double d = dbl(c, "pass_minus_fail_pct");
                if (d != null) sb.append(String.format(Locale.US, "  (passers did %+.1f%% better)", d));
                sb.append("\n");
            }
        }
        checksText.setText(sb.length() == 0 ? "No tested checks for this stock yet." : sb.toString().trim());
    }

    private void bindGovernance(JsonObject gov, JsonArray flags, JsonObject mentions) {
        StringBuilder sb = new StringBuilder();
        if (gov != null) {
            sb.append(String.format(Locale.US, "Grade %s (%s of %s governance checks passed)",
                    str(gov, "grade"), n0(dbl(gov, "passed")), n0(dbl(gov, "checked"))));
        }
        if (flags != null && flags.size() > 0) {
            sb.append("\n⚠ Red flags: ");
            for (int i = 0; i < flags.size(); i++) {
                if (i > 0) sb.append(", ");
                if (flags.get(i).isJsonPrimitive()) sb.append(flags.get(i).getAsString().replace('_', ' '));
            }
        }
        if (bool(mentions, "multibagger_radar")) sb.append("\n🚀 On this week's Multibagger Radar");
        if (bool(mentions, "market_scanner")) sb.append("\n📡 On tonight's market scanner watchlist");
        governanceText.setText(sb.length() == 0 ? "No governance data yet." : sb.toString());
    }

    private void bindDividend(JsonObject d) {
        if (d == null) {
            dividendText.setText("No regular dividend in the last 3 years.");
            return;
        }
        dividendText.setText(String.format(Locale.US,
                "%s · Income Score %s/100 · yield %s · pays %s · paid %s of the last 10 years · ₹%s a year per ₹1 lakh",
                str(d, "rating_badge"), n0(dbl(d, "income_score")),
                dbl(d, "yield_pct") == null ? "—" : String.format(Locale.US, "%.2f%%", dbl(d, "yield_pct")),
                str(d, "frequency"), n0(dbl(d, "years_paid_of_10")), n0(dbl(d, "income_per_lakh_rs"))));
    }

    private void bindTrust(JsonObject trust, JsonObject verdicts) {
        StringBuilder sb = new StringBuilder();
        for (String[] pp : PERIODS) {
            JsonObject v = obj(verdicts, pp[0]);
            if (v == null) continue;
            sb.append(String.format(Locale.US, "%s: %s%s, %s%% chance to beat the market\n", pp[1],
                    BestStocksActivity.verdictLabel(str(v, "verdict")), bool(v, "horizon_verified") ? "" : " (unproven)",
                    n0(dbl(v, "chance_beat_market_pct"))));
        }
        JsonObject t = obj(trust, "horizon_test");
        Double buy = dbl(t, "buy_beat_market_pct");
        if (buy != null) {
            sb.append(String.format(Locale.US, "Chosen period on unseen months: Buy picks beat the market %.1f%%, Sell picks %s.\n",
                    buy, dbl(t, "sell_beat_market_pct") == null ? "—"
                            : String.format(Locale.US, "%.1f%%", dbl(t, "sell_beat_market_pct"))));
        }
        sb.append(str(trust, "how_to_read"));
        sb.append("\n* = this holding period has not proved itself yet.");
        trustText.setText(sb.toString());
    }

    private static String px(JsonArray a, int i) {
        JsonElement e = a.get(i);
        if (!e.isJsonPrimitive() || !e.getAsJsonPrimitive().isNumber()) return "—";
        return FormatUtils.formatPrice(e.getAsDouble(), "INR");
    }

    private static String n0(Double v) {
        return v == null ? "—" : String.format(Locale.US, "%,.0f", v);
    }

    private static double dblOr(JsonObject o, String k) {
        Double v = dbl(o, k);
        return v == null ? 0 : v;
    }
}
