package com.stocksentinel.ui.ipos;

import android.graphics.Color;
import android.os.Bundle;
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

import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;

/**
 * IpoDetailActivity — Institutional AI Deep-Dive Research Report for IPOs.
 * Displays company overview, business model, financial datasheet,
 * concrete reasons to buy/avoid, and AI subscribe/avoid verdict.
 */
public class IpoDetailActivity extends AppCompatActivity {

    public static final String EXTRA_IPO_ID = "extra_ipo_id";
    public static final String EXTRA_COMPANY_NAME = "extra_company_name";

    private int ipoId = 0;
    private String companyName = "";

    private ProgressBar loadingBar;
    private TextView companyNameText, verdictBadge, verdictRationale;
    private TextView statPrice, statGmp, statIssue;
    private TextView companyOverviewText, businessModelText, industryPositionText;
    private TextView finRevenue, finProfit, finDebt, finMetrics;
    private TextView reasonsBuyText, reasonsAvoidText;

    @Override
    protected void onCreate(@Nullable Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_ipo_detail);

        ipoId = getIntent().getIntExtra(EXTRA_IPO_ID, 0);
        companyName = getIntent().getStringExtra(EXTRA_COMPANY_NAME);
        if (companyName == null) companyName = "IPO Research";

        initViews();
        setupToolbar();
        loadIpoReport();
    }

    private void initViews() {
        loadingBar = findViewById(R.id.ipo_loading_bar);
        companyNameText = findViewById(R.id.ipo_company_name);
        verdictBadge = findViewById(R.id.ipo_verdict_badge);
        verdictRationale = findViewById(R.id.ipo_verdict_rationale);

        statPrice = findViewById(R.id.ipo_stat_price);
        statGmp = findViewById(R.id.ipo_stat_gmp);
        statIssue = findViewById(R.id.ipo_stat_issue);

        companyOverviewText = findViewById(R.id.ipo_company_overview);
        businessModelText = findViewById(R.id.ipo_business_model);
        industryPositionText = findViewById(R.id.ipo_industry_position);

        finRevenue = findViewById(R.id.ipo_fin_revenue);
        finProfit = findViewById(R.id.ipo_fin_profit);
        finDebt = findViewById(R.id.ipo_fin_debt);
        finMetrics = findViewById(R.id.ipo_fin_metrics);

        reasonsBuyText = findViewById(R.id.ipo_reasons_buy);
        reasonsAvoidText = findViewById(R.id.ipo_reasons_avoid);

        companyNameText.setText(companyName);
    }

    private void setupToolbar() {
        Toolbar toolbar = findViewById(R.id.ipo_toolbar);
        setSupportActionBar(toolbar);
        if (getSupportActionBar() != null) {
            getSupportActionBar().setDisplayHomeAsUpEnabled(true);
            getSupportActionBar().setDisplayShowTitleEnabled(false);
        }
        toolbar.setNavigationOnClickListener(v -> finish());
    }

    private void loadIpoReport() {
        loadingBar.setVisibility(View.VISIBLE);

        ApiClient.getApi().getIpoReport(ipoId).enqueue(new Callback<JsonObject>() {
            @Override
            public void onResponse(@NonNull Call<JsonObject> call, @NonNull Response<JsonObject> response) {
                loadingBar.setVisibility(View.GONE);
                if (response.isSuccessful() && response.body() != null) {
                    populateReport(response.body());
                } else {
                    Toast.makeText(IpoDetailActivity.this, "Unable to generate IPO report", Toast.LENGTH_SHORT).show();
                }
            }

            @Override
            public void onFailure(@NonNull Call<JsonObject> call, @NonNull Throwable t) {
                loadingBar.setVisibility(View.GONE);
                Toast.makeText(IpoDetailActivity.this, "Failed to load report: " + t.getMessage(), Toast.LENGTH_SHORT).show();
            }
        });
    }

    private void populateReport(JsonObject report) {
        String company = report.has("company_name") ? report.get("company_name").getAsString() : companyName;
        companyNameText.setText(company);

        // Verdict
        String verdict = report.has("verdict") ? report.get("verdict").getAsString() : "SUBSCRIBE";
        verdictBadge.setText(verdict.replace("_", " "));
        if (verdict.contains("SUBSCRIBE") || verdict.contains("BUY")) {
            verdictBadge.setTextColor(Color.parseColor("#FF00E676"));
        } else if (verdict.contains("AVOID")) {
            verdictBadge.setTextColor(Color.parseColor("#FFFF5252"));
        } else {
            verdictBadge.setTextColor(Color.parseColor("#FFFFD740"));
        }

        if (report.has("verdict_rationale")) {
            verdictRationale.setText(report.get("verdict_rationale").getAsString());
        }

        // Stats
        if (report.has("ipo_data") && report.get("ipo_data").isJsonObject()) {
            JsonObject data = report.getAsJsonObject("ipo_data");
            Double low = data.has("price_band_low") && !data.get("price_band_low").isJsonNull()
                    ? data.get("price_band_low").getAsDouble() : null;
            Double high = data.has("price_band_high") && !data.get("price_band_high").isJsonNull()
                    ? data.get("price_band_high").getAsDouble() : null;
            String issue = data.has("issue_size") && !data.get("issue_size").isJsonNull()
                    ? data.get("issue_size").getAsString() : "TBD";
            Double gmp = data.has("gmp") && !data.get("gmp").isJsonNull()
                    ? data.get("gmp").getAsDouble() : null;

            if (low != null && high != null) {
                statPrice.setText(String.format("₹%.0f - ₹%.0f", low, high));
            }
            statIssue.setText(issue);
            if (gmp != null) {
                statGmp.setText(String.format("+₹%.0f", gmp));
            }
        }

        // Detailed sections
        if (report.has("company_overview")) {
            companyOverviewText.setText(report.get("company_overview").getAsString());
        }
        if (report.has("business_model")) {
            businessModelText.setText(report.get("business_model").getAsString());
        }
        if (report.has("industry_position")) {
            industryPositionText.setText(report.get("industry_position").getAsString());
        }

        // Financial snapshot
        if (report.has("financial_snapshot") && report.get("financial_snapshot").isJsonObject()) {
            JsonObject fin = report.getAsJsonObject("financial_snapshot");
            if (fin.has("revenue_description")) {
                finRevenue.setText("• Revenue: " + fin.get("revenue_description").getAsString());
            }
            if (fin.has("profitability")) {
                finProfit.setText("• Profitability: " + fin.get("profitability").getAsString());
            }
            if (fin.has("debt_status")) {
                finDebt.setText("• Debt Profile: " + fin.get("debt_status").getAsString());
            }
            if (fin.has("key_metrics")) {
                finMetrics.setText("• Key Valuation: " + fin.get("key_metrics").getAsString());
            }
        }

        // Reasons to buy
        if (report.has("reasons_to_buy") && report.get("reasons_to_buy").isJsonArray()) {
            StringBuilder sb = new StringBuilder();
            JsonArray buyArr = report.getAsJsonArray("reasons_to_buy");
            for (JsonElement el : buyArr) {
                sb.append("• ").append(el.getAsString()).append("\n\n");
            }
            reasonsBuyText.setText(sb.toString().trim());
        }

        // Reasons not to buy
        if (report.has("reasons_not_to_buy") && report.get("reasons_not_to_buy").isJsonArray()) {
            StringBuilder sb = new StringBuilder();
            JsonArray avoidArr = report.getAsJsonArray("reasons_not_to_buy");
            for (JsonElement el : avoidArr) {
                sb.append("• ").append(el.getAsString()).append("\n\n");
            }
            reasonsAvoidText.setText(sb.toString().trim());
        }
    }
}
