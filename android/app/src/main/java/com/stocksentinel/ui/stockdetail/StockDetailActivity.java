package com.stocksentinel.ui.stockdetail;

import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ImageButton;
import android.widget.TextView;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.appcompat.app.AppCompatActivity;
import androidx.appcompat.widget.Toolbar;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.stocksentinel.R;
import com.stocksentinel.data.api.ApiClient;
import com.stocksentinel.ui.home.LineChartView;
import com.stocksentinel.util.DeviceUtils;
import com.stocksentinel.util.FormatUtils;

import java.util.ArrayList;
import java.util.List;

import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;

/**
 * StockDetailActivity — institutional-grade personal market analyst terminal.
 */
public class StockDetailActivity extends AppCompatActivity {

    public static final String EXTRA_SYMBOL = "extra_symbol";
    public static final String EXTRA_EXCHANGE = "extra_exchange";
    public static final String EXTRA_NAME = "extra_name";

    private String symbol = "";
    private String exchange = "NSE";
    private String currentRange = "1M";
    private int stockId = 0;
    private boolean isWatchlisted = false;

    // Header views
    private TextView toolbarSymbol, toolbarExchange, companyName, livePrice, priceChange, scrubberInfo;
    private ImageButton btnWatchlist;
    private LineChartView chartView;

    // Timeframe selector
    private TextView tf1d, tf1w, tf1m, tf1y, tf5y;

    // Buffett Valuation views
    private TextView valVerdictBadge, valFairValue, valMarginOfSafety;
    private TextView valModelDcf, valModelGraham, valModelPeg, valBuffettScore;

    // Buffett Moat & Quality views
    private TextView qualityGradeBadge, qualityVerdictText;
    private TextView qualityPiotroskiScore, qualityPiotroskiVerdict;
    private TextView qualityAltmanScore, qualityAltmanZone;
    private TextView qualityMoatRating, qualityMoatSpread;

    // Technical Signals views
    private TextView techVerdictBadge, techRsi, techSma50, techSma200, techCrossSignal;

    // AI Dossier views
    private TextView aiVerdictBadge, aiTrendForecast, aiEmergingCatalysts, aiUpcomingEvents, aiBullCase, aiBearRisk;

    // Equity Research Report views
    private TextView reportGradeBadge, reportActionBadge, reportScoreBadge, reportSummaryText;
    private TextView reportStatPe, reportStatRoe, reportStatMargin, reportStatDebt;
    private TextView reportThesisMoat, reportThesisDrivers, reportTargetUpside, reportTargetDownside;
    private TextView reportSharePromoters, reportShareFii, reportShareDii, reportSharePublic;

    // Stats views
    private TextView statOpen, statPrevClose, statDayRange, statVolume, statMarketCap, statSector;

    // News views
    private RecyclerView newsRecycler;
    private TextView newsEmpty;
    private DetailNewsAdapter newsAdapter;

    @Override
    protected void onCreate(@Nullable Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_stock_detail);

        // Parse Intent
        symbol = getIntent().getStringExtra(EXTRA_SYMBOL);
        if (symbol == null || symbol.trim().isEmpty()) {
            Toast.makeText(this, "Stock symbol missing", Toast.LENGTH_SHORT).show();
            finish();
            return;
        }
        symbol = symbol.trim().toUpperCase();
        String ex = getIntent().getStringExtra(EXTRA_EXCHANGE);
        if (ex != null && !ex.isEmpty()) exchange = ex;

        initViews();
        setupToolbar();
        setupTimeframeTabs();
        setupChartScrubber();

        // Load data
        loadStockDetails();
        loadChartData(currentRange);
        loadAiDossier();
        loadFullResearchReport();
        loadStockNews();
        loadBuffettValuation();
        loadQualityScorecard();
        loadTechnicals();
    }

    private void initViews() {
        toolbarSymbol = findViewById(R.id.toolbar_symbol);
        toolbarExchange = findViewById(R.id.toolbar_exchange);
        companyName = findViewById(R.id.stock_company_name);
        livePrice = findViewById(R.id.stock_live_price);
        priceChange = findViewById(R.id.stock_price_change);
        scrubberInfo = findViewById(R.id.scrubber_info);
        btnWatchlist = findViewById(R.id.btn_watchlist_toggle);
        chartView = findViewById(R.id.stock_chart_view);

        tf1d = findViewById(R.id.tf_1d);
        tf1w = findViewById(R.id.tf_1w);
        tf1m = findViewById(R.id.tf_1m);
        tf1y = findViewById(R.id.tf_1y);
        tf5y = findViewById(R.id.tf_5y);

        // Buffett Valuation bindings
        valVerdictBadge = findViewById(R.id.val_verdict_badge);
        valFairValue = findViewById(R.id.val_fair_value);
        valMarginOfSafety = findViewById(R.id.val_margin_of_safety);
        valModelDcf = findViewById(R.id.val_model_dcf);
        valModelGraham = findViewById(R.id.val_model_graham);
        valModelPeg = findViewById(R.id.val_model_peg);
        valBuffettScore = findViewById(R.id.val_buffett_score);

        // Buffett Quality & Moat bindings
        qualityGradeBadge = findViewById(R.id.quality_grade_badge);
        qualityVerdictText = findViewById(R.id.quality_verdict_text);
        qualityPiotroskiScore = findViewById(R.id.quality_piotroski_score);
        qualityPiotroskiVerdict = findViewById(R.id.quality_piotroski_verdict);
        qualityAltmanScore = findViewById(R.id.quality_altman_score);
        qualityAltmanZone = findViewById(R.id.quality_altman_zone);
        qualityMoatRating = findViewById(R.id.quality_moat_rating);
        qualityMoatSpread = findViewById(R.id.quality_moat_spread);

        // Technicals bindings
        techVerdictBadge = findViewById(R.id.tech_verdict_badge);
        techRsi = findViewById(R.id.tech_rsi);
        techSma50 = findViewById(R.id.tech_sma_50);
        techSma200 = findViewById(R.id.tech_sma_200);
        techCrossSignal = findViewById(R.id.tech_cross_signal);

        aiVerdictBadge = findViewById(R.id.ai_verdict_badge);
        aiTrendForecast = findViewById(R.id.ai_trend_forecast);
        aiEmergingCatalysts = findViewById(R.id.ai_emerging_catalysts);
        aiUpcomingEvents = findViewById(R.id.ai_upcoming_events);
        aiBullCase = findViewById(R.id.ai_bull_case);
        aiBearRisk = findViewById(R.id.ai_bear_risk);

        // Research Report views
        reportGradeBadge = findViewById(R.id.report_grade_badge);
        reportActionBadge = findViewById(R.id.report_action_badge);
        reportScoreBadge = findViewById(R.id.report_score_badge);
        reportSummaryText = findViewById(R.id.report_summary_text);
        reportStatPe = findViewById(R.id.report_stat_pe);
        reportStatRoe = findViewById(R.id.report_stat_roe);
        reportStatMargin = findViewById(R.id.report_stat_margin);
        reportStatDebt = findViewById(R.id.report_stat_debt);
        reportThesisMoat = findViewById(R.id.report_thesis_moat);
        reportThesisDrivers = findViewById(R.id.report_thesis_drivers);
        reportTargetUpside = findViewById(R.id.report_target_upside);
        reportTargetDownside = findViewById(R.id.report_target_downside);
        reportSharePromoters = findViewById(R.id.report_share_promoters);
        reportShareFii = findViewById(R.id.report_share_fii);
        reportShareDii = findViewById(R.id.report_share_dii);
        reportSharePublic = findViewById(R.id.report_share_public);

        statOpen = findViewById(R.id.stat_open);
        statPrevClose = findViewById(R.id.stat_prev_close);
        statDayRange = findViewById(R.id.stat_day_range);
        statVolume = findViewById(R.id.stat_volume);
        statMarketCap = findViewById(R.id.stat_market_cap);
        statSector = findViewById(R.id.stat_sector);

        newsRecycler = findViewById(R.id.stock_news_recycler);
        newsEmpty = findViewById(R.id.stock_news_empty);

        toolbarSymbol.setText(symbol);
        toolbarExchange.setText(exchange);

        String preName = getIntent().getStringExtra(EXTRA_NAME);
        if (preName != null && !preName.isEmpty()) {
            companyName.setText(preName);
        }

        newsAdapter = new DetailNewsAdapter(url -> {
            Intent browserIntent = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
            startActivity(browserIntent);
        });
        newsRecycler.setLayoutManager(new LinearLayoutManager(this));
        newsRecycler.setAdapter(newsAdapter);
    }

    private void setupToolbar() {
        Toolbar toolbar = findViewById(R.id.toolbar);
        toolbar.setNavigationOnClickListener(v -> finish());

        btnWatchlist.setOnClickListener(v -> toggleWatchlist());
    }

    private void setupTimeframeTabs() {
        View.OnClickListener listener = v -> {
            tf1d.setTextColor(getColor(R.color.text_secondary));
            tf1w.setTextColor(getColor(R.color.text_secondary));
            tf1m.setTextColor(getColor(R.color.text_secondary));
            tf1y.setTextColor(getColor(R.color.text_secondary));
            if (tf5y != null) tf5y.setTextColor(getColor(R.color.text_secondary));

            ((TextView) v).setTextColor(getColor(R.color.text_primary));

            if (v == tf1d) currentRange = "1D";
            else if (v == tf1w) currentRange = "1W";
            else if (v == tf1m) currentRange = "1M";
            else if (v == tf1y) currentRange = "1Y";
            else if (v == tf5y) currentRange = "5Y";

            loadChartData(currentRange);
        };

        tf1d.setOnClickListener(listener);
        tf1w.setOnClickListener(listener);
        tf1m.setOnClickListener(listener);
        tf1y.setOnClickListener(listener);
        if (tf5y != null) tf5y.setOnClickListener(listener);
    }

    private void setupChartScrubber() {
        chartView.setOnSelectedPointListener(new LineChartView.OnSelectedPointListener() {
            @Override
            public void onPointSelected(int index, float value, String label) {
                scrubberInfo.setText(String.format("₹%.2f on %s", value, label));
                scrubberInfo.setTextColor(getColor(R.color.green_accent));
            }

            @Override
            public void onSelectionCleared() {
                scrubberInfo.setText("Touch chart to inspect points");
                scrubberInfo.setTextColor(getColor(R.color.text_tertiary));
            }
        });
    }

    private void loadStockDetails() {
        ApiClient.getApi().getStock(symbol, exchange).enqueue(new Callback<JsonObject>() {
            @Override
            public void onResponse(@NonNull Call<JsonObject> call, @NonNull Response<JsonObject> response) {
                if (!response.isSuccessful() || response.body() == null) return;
                JsonObject body = response.body();
                if (!body.has("stock") || body.get("stock").isJsonNull()) return;

                JsonObject stock = body.getAsJsonObject("stock");
                stockId = stock.has("id") && !stock.get("id").isJsonNull() ? stock.get("id").getAsInt() : 0;

                String name = stock.has("name") && !stock.get("name").isJsonNull() ? stock.get("name").getAsString() : symbol;
                companyName.setText(name);

                Double price = stock.has("current_price") && !stock.get("current_price").isJsonNull() ? stock.get("current_price").getAsDouble() : null;
                Double changePct = stock.has("change_pct") && !stock.get("change_pct").isJsonNull() ? stock.get("change_pct").getAsDouble() : null;
                String currency = stock.has("currency") && !stock.get("currency").isJsonNull() ? stock.get("currency").getAsString() : "INR";

                livePrice.setText(FormatUtils.formatPrice(price, currency));
                priceChange.setText(FormatUtils.formatChangePercent(changePct));
                priceChange.setTextColor(FormatUtils.getChangeColor(changePct));

                // Stats
                Double open = stock.has("open_price") && !stock.get("open_price").isJsonNull() ? stock.get("open_price").getAsDouble() : null;
                Double prevClose = stock.has("prev_close") && !stock.get("prev_close").isJsonNull() ? stock.get("prev_close").getAsDouble() : null;
                Double dayHigh = stock.has("day_high") && !stock.get("day_high").isJsonNull() ? stock.get("day_high").getAsDouble() : null;
                Double dayLow = stock.has("day_low") && !stock.get("day_low").isJsonNull() ? stock.get("day_low").getAsDouble() : null;
                Long volume = stock.has("volume") && !stock.get("volume").isJsonNull() ? stock.get("volume").getAsLong() : null;
                Long marketCap = stock.has("market_cap") && !stock.get("market_cap").isJsonNull() ? stock.get("market_cap").getAsLong() : null;
                String sector = stock.has("sector") && !stock.get("sector").isJsonNull() ? stock.get("sector").getAsString() : "--";

                statOpen.setText(FormatUtils.formatPrice(open, currency));
                statPrevClose.setText(FormatUtils.formatPrice(prevClose, currency));
                if (dayLow != null && dayHigh != null) {
                    statDayRange.setText(String.format("%.1f / %.1f", dayLow, dayHigh));
                }
                statVolume.setText(volume != null ? FormatUtils.formatNumber(volume) : "--");
                statMarketCap.setText(marketCap != null ? FormatUtils.formatNumber(marketCap) : "--");
                statSector.setText(sector);
            }

            @Override
            public void onFailure(@NonNull Call<JsonObject> call, @NonNull Throwable t) { }
        });
    }

    private void loadChartData(String rangeKey) {
        scrubberInfo.setText("Loading chart...");
        ApiClient.getApi().getStockChart(symbol, exchange, rangeKey).enqueue(new Callback<JsonObject>() {
            @Override
            public void onResponse(@NonNull Call<JsonObject> call, @NonNull Response<JsonObject> response) {
                scrubberInfo.setText("Touch chart to inspect points");
                if (!response.isSuccessful() || response.body() == null) return;
                JsonObject data = response.body();

                if (!data.has("points") || data.get("points").isJsonNull()) return;
                JsonArray ptArr = data.getAsJsonArray("points");
                JsonArray lbArr = data.has("labels") ? data.getAsJsonArray("labels") : new JsonArray();

                if (ptArr.size() < 2) return;

                List<Float> points = new ArrayList<>();
                List<String> labels = new ArrayList<>();
                for (int i = 0; i < ptArr.size(); i++) {
                    points.add(ptArr.get(i).getAsFloat());
                    labels.add(i < lbArr.size() ? lbArr.get(i).getAsString() : "");
                }

                double pct = data.has("change_pct") ? data.get("change_pct").getAsDouble() : 0.0;
                int themeColor = pct >= 0 ? Color.parseColor("#FF00E676") : Color.parseColor("#FFFF5252");
                chartView.setThemeColor(themeColor);
                chartView.setData(points, labels);
            }

            @Override
            public void onFailure(@NonNull Call<JsonObject> call, @NonNull Throwable t) {
                scrubberInfo.setText("Chart data unavailable offline");
            }
        });
    }

    private void loadAiDossier() {
        ApiClient.getApi().getStockDossier(symbol).enqueue(new Callback<JsonObject>() {
            @Override
            public void onResponse(@NonNull Call<JsonObject> call, @NonNull Response<JsonObject> response) {
                if (!response.isSuccessful() || response.body() == null) {
                    aiTrendForecast.setText("AI analysis temporarily unavailable.");
                    return;
                }
                JsonObject dossier = response.body();

                String verdict = dossier.has("verdict") ? dossier.get("verdict").getAsString() : "NEUTRAL";
                aiVerdictBadge.setText(verdict.replace("_", " "));

                if (verdict.contains("BUY") || verdict.contains("BULLISH")) {
                    aiVerdictBadge.setTextColor(Color.parseColor("#FF00E676"));
                } else if (verdict.contains("RISK") || verdict.contains("BEARISH")) {
                    aiVerdictBadge.setTextColor(Color.parseColor("#FFFF5252"));
                } else {
                    aiVerdictBadge.setTextColor(Color.parseColor("#FFFFD740"));
                }

                if (dossier.has("trend_forecast") && !dossier.get("trend_forecast").isJsonNull()) {
                    aiTrendForecast.setText(dossier.get("trend_forecast").getAsString());
                }

                if (dossier.has("emerging_catalysts") && dossier.get("emerging_catalysts").isJsonArray()) {
                    JsonArray cats = dossier.getAsJsonArray("emerging_catalysts");
                    StringBuilder sb = new StringBuilder();
                    for (JsonElement el : cats) {
                        sb.append("• ").append(el.getAsString()).append("\n");
                    }
                    aiEmergingCatalysts.setText(sb.toString().trim());
                }

                if (dossier.has("upcoming_events") && !dossier.get("upcoming_events").isJsonNull()) {
                    aiUpcomingEvents.setText(dossier.get("upcoming_events").getAsString());
                }

                if (dossier.has("bull_case") && !dossier.get("bull_case").isJsonNull()) {
                    aiBullCase.setText(dossier.get("bull_case").getAsString());
                }

                if (dossier.has("bear_risk") && !dossier.get("bear_risk").isJsonNull()) {
                    aiBearRisk.setText(dossier.get("bear_risk").getAsString());
                }
            }

            @Override
            public void onFailure(@NonNull Call<JsonObject> call, @NonNull Throwable t) {
                aiTrendForecast.setText("Offline: Rule-based Sentinel tracking active.");
            }
        });
    }

    private void loadFullResearchReport() {
        ApiClient.getApi().getFullResearchReport(symbol).enqueue(new Callback<JsonObject>() {
            @Override
            public void onResponse(@NonNull Call<JsonObject> call, @NonNull Response<JsonObject> response) {
                if (!response.isSuccessful() || response.body() == null) return;
                JsonObject report = response.body();

                // Grade & Action
                String grade = report.has("research_grade") ? report.get("research_grade").getAsString() : "A";
                reportGradeBadge.setText("GRADE " + grade);
                if (grade.startsWith("A")) {
                    reportGradeBadge.setTextColor(Color.parseColor("#FF00E676"));
                } else if (grade.startsWith("B")) {
                    reportGradeBadge.setTextColor(Color.parseColor("#FF2979FF"));
                } else {
                    reportGradeBadge.setTextColor(Color.parseColor("#FFFFD740"));
                }

                String action = report.has("action") ? report.get("action").getAsString() : "ACCUMULATE";
                reportActionBadge.setText(action.replace("_", " "));
                if (action.contains("BUY") || action.contains("ACCUMULATE")) {
                    reportActionBadge.setTextColor(Color.parseColor("#FF00E676"));
                } else if (action.contains("SELL") || action.contains("AVOID")) {
                    reportActionBadge.setTextColor(Color.parseColor("#FFFF5252"));
                } else {
                    reportActionBadge.setTextColor(Color.parseColor("#FFFFD740"));
                }

                if (report.has("composite_score")) {
                    double score = report.get("composite_score").getAsDouble();
                    reportScoreBadge.setText(String.format(java.util.Locale.US, "AI Score: %.1f/100", score));
                }

                // Summary / Thesis
                if (report.has("company_profile")) {
                    reportSummaryText.setText(report.get("company_profile").getAsString());
                } else if (report.has("investment_thesis")) {
                    reportSummaryText.setText(report.get("investment_thesis").getAsString());
                }

                // Financial Scorecard
                if (report.has("financial_scorecard") && report.get("financial_scorecard").isJsonObject()) {
                    JsonObject fin = report.getAsJsonObject("financial_scorecard");
                    if (fin.has("revenue_growth")) {
                        reportStatPe.setText("Rev: " + fin.get("revenue_growth").getAsString());
                    }
                    if (fin.has("profit_margins")) {
                        reportStatRoe.setText("Margins: " + fin.get("profit_margins").getAsString());
                    }
                    if (fin.has("cash_flow")) {
                        reportStatMargin.setText("Cash: " + fin.get("cash_flow").getAsString());
                    }
                    if (fin.has("debt_health")) {
                        reportStatDebt.setText("Debt: " + fin.get("debt_health").getAsString());
                    }
                }

                // Investment Thesis & Drivers
                if (report.has("investment_thesis")) {
                    reportThesisMoat.setText(report.get("investment_thesis").getAsString());
                }
                if (report.has("technical_summary")) {
                    reportThesisDrivers.setText("Technical: " + report.get("technical_summary").getAsString());
                }

                // Shareholding Pattern
                if (report.has("shareholding_pattern") && report.get("shareholding_pattern").isJsonObject()) {
                    JsonObject sh = report.getAsJsonObject("shareholding_pattern");
                    if (sh.has("promoter_pct")) {
                        reportSharePromoters.setText(String.format(java.util.Locale.US, "Prom: %.1f%%", sh.get("promoter_pct").getAsDouble()));
                    }
                    if (sh.has("fii_pct")) {
                        reportShareFii.setText(String.format(java.util.Locale.US, "FII: %.1f%%", sh.get("fii_pct").getAsDouble()));
                    }
                    if (sh.has("dii_pct")) {
                        reportShareDii.setText(String.format(java.util.Locale.US, "DII: %.1f%%", sh.get("dii_pct").getAsDouble()));
                    }
                    if (sh.has("public_pct")) {
                        reportSharePublic.setText(String.format(java.util.Locale.US, "Pub: %.1f%%", sh.get("public_pct").getAsDouble()));
                    }
                }
            }

            @Override
            public void onFailure(@NonNull Call<JsonObject> call, @NonNull Throwable t) {
                reportSummaryText.setText("Full institutional equity research report is being calculated.");
            }
        });
    }

    private void loadStockNews() {
        ApiClient.getApi().getStockNews(symbol, 10).enqueue(new Callback<JsonObject>() {
            @Override
            public void onResponse(@NonNull Call<JsonObject> call, @NonNull Response<JsonObject> response) {
                if (!response.isSuccessful() || response.body() == null) {
                    newsEmpty.setVisibility(View.VISIBLE);
                    return;
                }
                JsonObject body = response.body();
                if (!body.has("news") || body.get("news").isJsonNull()) {
                    newsEmpty.setVisibility(View.VISIBLE);
                    return;
                }

                JsonArray newsArr = body.getAsJsonArray("news");
                if (newsArr.size() == 0) {
                    newsEmpty.setVisibility(View.VISIBLE);
                } else {
                    newsEmpty.setVisibility(View.GONE);
                    newsAdapter.setItems(newsArr);
                }
            }

            @Override
            public void onFailure(@NonNull Call<JsonObject> call, @NonNull Throwable t) {
                newsEmpty.setVisibility(View.VISIBLE);
            }
        });
    }

    private void toggleWatchlist() {
        if (stockId <= 0) return;
        String deviceId = DeviceUtils.getDeviceId(this);

        if (!isWatchlisted) {
            JsonObject body = new JsonObject();
            body.addProperty("device_id", deviceId);
            body.addProperty("stock_id", stockId);

            ApiClient.getApi().addToWatchlist(body).enqueue(new Callback<JsonObject>() {
                @Override
                public void onResponse(@NonNull Call<JsonObject> call, @NonNull Response<JsonObject> response) {
                    isWatchlisted = true;
                    btnWatchlist.setColorFilter(Color.parseColor("#FF00E676"));
                    Toast.makeText(StockDetailActivity.this, "Added to Watchlist", Toast.LENGTH_SHORT).show();
                }

                @Override
                public void onFailure(@NonNull Call<JsonObject> call, @NonNull Throwable t) { }
            });
        } else {
            ApiClient.getApi().removeStockFromWatchlist(deviceId, stockId).enqueue(new Callback<JsonObject>() {
                @Override
                public void onResponse(@NonNull Call<JsonObject> call, @NonNull Response<JsonObject> response) {
                    isWatchlisted = false;
                    btnWatchlist.setColorFilter(getColor(R.color.text_secondary));
                    Toast.makeText(StockDetailActivity.this, "Removed from Watchlist", Toast.LENGTH_SHORT).show();
                }

                @Override
                public void onFailure(@NonNull Call<JsonObject> call, @NonNull Throwable t) { }
            });
        }
    }

    // ---------------------------------------------------------------------------
    // Phase 1 & 2: Buffett Valuation, Quality Scorecard & Technicals Loaders
    // ---------------------------------------------------------------------------
    private void loadBuffettValuation() {
        ApiClient.getApi().getValuation(symbol, exchange).enqueue(new Callback<JsonObject>() {
            @Override
            public void onResponse(@NonNull Call<JsonObject> call, @NonNull Response<JsonObject> response) {
                if (!response.isSuccessful() || response.body() == null) return;
                JsonObject val = response.body();

                String verdict = val.has("consensus_verdict") && !val.get("consensus_verdict").isJsonNull()
                        ? val.get("consensus_verdict").getAsString() : "ANALYZED";
                if (valVerdictBadge != null) {
                    valVerdictBadge.setText(verdict);
                    if ("UNDERVALUED".equalsIgnoreCase(verdict) || verdict.contains("BUY")) {
                        valVerdictBadge.setTextColor(getColor(R.color.green_accent));
                    } else if ("OVERVALUED".equalsIgnoreCase(verdict) || verdict.contains("SELL")) {
                        valVerdictBadge.setTextColor(getColor(R.color.red_accent));
                    } else {
                        valVerdictBadge.setTextColor(getColor(R.color.yellow_accent));
                    }
                }

                if (valFairValue != null && val.has("consensus_fair_value") && !val.get("consensus_fair_value").isJsonNull()) {
                    valFairValue.setText(String.format("₹%.2f", val.get("consensus_fair_value").getAsDouble()));
                }

                if (valMarginOfSafety != null && val.has("margin_of_safety_pct") && !val.get("margin_of_safety_pct").isJsonNull()) {
                    double mos = val.get("margin_of_safety_pct").getAsDouble();
                    valMarginOfSafety.setText(String.format("%+.1f%%", mos));
                    valMarginOfSafety.setTextColor(mos >= 0 ? getColor(R.color.green_accent) : getColor(R.color.red_accent));
                }

                if (valBuffettScore != null && val.has("buffett_score") && !val.get("buffett_score").isJsonNull()) {
                    valBuffettScore.setText(String.format("%d/100", val.get("buffett_score").getAsInt()));
                }

                if (val.has("models") && val.get("models").isJsonObject()) {
                    JsonObject models = val.getAsJsonObject("models");
                    if (valModelDcf != null && models.has("dcf") && models.get("dcf").isJsonObject()) {
                        JsonObject dcf = models.getAsJsonObject("dcf");
                        if (dcf.has("fair_value") && !dcf.get("fair_value").isJsonNull()) {
                            valModelDcf.setText(String.format("₹%.0f", dcf.get("fair_value").getAsDouble()));
                        }
                    }
                    if (valModelGraham != null && models.has("graham_number") && models.get("graham_number").isJsonObject()) {
                        JsonObject graham = models.getAsJsonObject("graham_number");
                        if (graham.has("fair_value") && !graham.get("fair_value").isJsonNull()) {
                            valModelGraham.setText(String.format("₹%.0f", graham.get("fair_value").getAsDouble()));
                        }
                    }
                    if (valModelPeg != null && models.has("peg_valuation") && models.get("peg_valuation").isJsonObject()) {
                        JsonObject peg = models.getAsJsonObject("peg_valuation");
                        if (peg.has("fair_value") && !peg.get("fair_value").isJsonNull()) {
                            valModelPeg.setText(String.format("₹%.0f", peg.get("fair_value").getAsDouble()));
                        }
                    }
                }
            }

            @Override
            public void onFailure(@NonNull Call<JsonObject> call, @NonNull Throwable t) { }
        });
    }

    private void loadQualityScorecard() {
        ApiClient.getApi().getQualityScorecard(symbol, exchange).enqueue(new Callback<JsonObject>() {
            @Override
            public void onResponse(@NonNull Call<JsonObject> call, @NonNull Response<JsonObject> response) {
                if (!response.isSuccessful() || response.body() == null) return;
                JsonObject q = response.body();

                if (qualityGradeBadge != null && q.has("quality_grade") && !q.get("quality_grade").isJsonNull()) {
                    qualityGradeBadge.setText("GRADE " + q.get("quality_grade").getAsString());
                }

                if (qualityVerdictText != null && q.has("quality_verdict") && !q.get("quality_verdict").isJsonNull()) {
                    qualityVerdictText.setText(q.get("quality_verdict").getAsString());
                }

                if (q.has("piotroski_f_score") && q.get("piotroski_f_score").isJsonObject()) {
                    JsonObject p = q.getAsJsonObject("piotroski_f_score");
                    if (qualityPiotroskiScore != null && p.has("score")) {
                        int score = p.get("score").getAsInt();
                        qualityPiotroskiScore.setText(score + "/9");
                        qualityPiotroskiScore.setTextColor(score >= 7 ? getColor(R.color.green_accent) : getColor(R.color.yellow_accent));
                    }
                    if (qualityPiotroskiVerdict != null && p.has("verdict")) {
                        qualityPiotroskiVerdict.setText(p.get("verdict").getAsString());
                    }
                }

                if (q.has("altman_z_score") && q.get("altman_z_score").isJsonObject()) {
                    JsonObject a = q.getAsJsonObject("altman_z_score");
                    if (qualityAltmanScore != null && a.has("z_score") && !a.get("z_score").isJsonNull()) {
                        qualityAltmanScore.setText(String.format("%.2f", a.get("z_score").getAsDouble()));
                    }
                    if (qualityAltmanZone != null && a.has("zone") && !a.get("zone").isJsonNull()) {
                        qualityAltmanZone.setText(a.get("zone").getAsString());
                    }
                }

                if (q.has("economic_moat") && q.get("economic_moat").isJsonObject()) {
                    JsonObject m = q.getAsJsonObject("economic_moat");
                    if (qualityMoatRating != null && m.has("moat_rating")) {
                        qualityMoatRating.setText(m.get("moat_rating").getAsString());
                    }
                    if (qualityMoatSpread != null && m.has("roic_pct") && !m.get("roic_pct").isJsonNull()) {
                        qualityMoatSpread.setText(String.format("ROIC %.1f%%", m.get("roic_pct").getAsDouble()));
                    }
                }
            }

            @Override
            public void onFailure(@NonNull Call<JsonObject> call, @NonNull Throwable t) { }
        });
    }

    private void loadTechnicals() {
        ApiClient.getApi().getTechnicals(symbol, exchange).enqueue(new Callback<JsonObject>() {
            @Override
            public void onResponse(@NonNull Call<JsonObject> call, @NonNull Response<JsonObject> response) {
                if (!response.isSuccessful() || response.body() == null) return;
                JsonObject t = response.body();

                if (techVerdictBadge != null && t.has("overall_verdict") && !t.get("overall_verdict").isJsonNull()) {
                    String v = t.get("overall_verdict").getAsString();
                    techVerdictBadge.setText(v);
                    if (v.contains("BUY")) {
                        techVerdictBadge.setTextColor(getColor(R.color.green_accent));
                    } else if (v.contains("SELL")) {
                        techVerdictBadge.setTextColor(getColor(R.color.red_accent));
                    } else {
                        techVerdictBadge.setTextColor(getColor(R.color.yellow_accent));
                    }
                }

                if (t.has("indicators") && t.get("indicators").isJsonObject()) {
                    JsonObject ind = t.getAsJsonObject("indicators");
                    if (techRsi != null && ind.has("rsi_14") && !ind.get("rsi_14").isJsonNull()) {
                        double rsi = ind.get("rsi_14").getAsDouble();
                        techRsi.setText(String.format("%.1f", rsi));
                        if (rsi <= 30) {
                            techRsi.setTextColor(getColor(R.color.green_accent)); // Oversold
                        } else if (rsi >= 70) {
                            techRsi.setTextColor(getColor(R.color.red_accent)); // Overbought
                        } else {
                            techRsi.setTextColor(getColor(R.color.text_primary));
                        }
                    }

                    if (techSma50 != null && ind.has("sma_50") && !ind.get("sma_50").isJsonNull()) {
                        techSma50.setText(String.format("₹%.0f", ind.get("sma_50").getAsDouble()));
                    }

                    if (techSma200 != null && ind.has("sma_200") && !ind.get("sma_200").isJsonNull()) {
                        techSma200.setText(String.format("₹%.0f", ind.get("sma_200").getAsDouble()));
                    }
                }

                if (t.has("signals") && t.get("signals").isJsonObject()) {
                    JsonObject sig = t.getAsJsonObject("signals");
                    if (techCrossSignal != null && sig.has("ma_cross") && !sig.get("ma_cross").isJsonNull()) {
                        String cross = sig.get("ma_cross").getAsString();
                        techCrossSignal.setText(cross);
                        techCrossSignal.setTextColor("GOLDEN_CROSS".equalsIgnoreCase(cross) ? getColor(R.color.green_accent) : getColor(R.color.text_secondary));
                    }
                }
            }

            @Override
            public void onFailure(@NonNull Call<JsonObject> call, @NonNull Throwable t) { }
        });
    }

    // ---------------------------------------------------------------------------
    // Recycler Adapter for Stock News
    // ---------------------------------------------------------------------------
    private static class DetailNewsAdapter extends RecyclerView.Adapter<DetailNewsAdapter.VH> {
        private final List<JsonObject> items = new ArrayList<>();
        private final OnNewsClickListener listener;

        interface OnNewsClickListener {
            void onNewsClick(String url);
        }

        DetailNewsAdapter(OnNewsClickListener listener) {
            this.listener = listener;
        }

        void setItems(JsonArray array) {
            items.clear();
            for (JsonElement el : array) {
                items.add(el.getAsJsonObject());
            }
            notifyDataSetChanged();
        }

        @NonNull
        @Override
        public VH onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
            View v = LayoutInflater.from(parent.getContext()).inflate(R.layout.item_news, parent, false);
            return new VH(v);
        }

        @Override
        public void onBindViewHolder(@NonNull VH holder, int position) {
            JsonObject item = items.get(position);
            String title = item.has("title") ? item.get("title").getAsString() : "";
            String source = item.has("source") ? item.get("source").getAsString() : "";
            String sentiment = item.has("sentiment") && !item.get("sentiment").isJsonNull() ? item.get("sentiment").getAsString() : "NEUTRAL";
            String url = item.has("url") ? item.get("url").getAsString() : "";

            holder.titleText.setText(title);
            holder.sourceText.setText(source);
            holder.sentimentBadge.setText(sentiment);

            if ("BULLISH".equalsIgnoreCase(sentiment)) {
                holder.sentimentBadge.setTextColor(Color.parseColor("#FF00E676"));
            } else if ("BEARISH".equalsIgnoreCase(sentiment)) {
                holder.sentimentBadge.setTextColor(Color.parseColor("#FFFF5252"));
            } else {
                holder.sentimentBadge.setTextColor(Color.parseColor("#FF9E9E9E"));
            }

            holder.itemView.setOnClickListener(v -> {
                if (listener != null && url != null && !url.isEmpty()) {
                    listener.onNewsClick(url);
                }
            });
        }

        @Override
        public int getItemCount() {
            return items.size();
        }

        static class VH extends RecyclerView.ViewHolder {
            TextView titleText, sourceText, sentimentBadge;

            VH(View v) {
                super(v);
                titleText = v.findViewById(R.id.news_title);
                sourceText = v.findViewById(R.id.news_source);
                sentimentBadge = v.findViewById(R.id.news_sentiment);
            }
        }
    }
}
