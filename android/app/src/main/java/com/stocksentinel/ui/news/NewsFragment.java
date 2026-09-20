package com.stocksentinel.ui.news;

import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.HorizontalScrollView;
import android.widget.LinearLayout;
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

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;

/**
 * News Fragment — ML-powered market news with 1-10 impact rating,
 * daily top 10 rankings, stock impact, and catalyst detection.
 */
public class NewsFragment extends Fragment {

    private SwipeRefreshLayout swipeRefresh;
    private RecyclerView recyclerView;
    private NewsAdapter adapter;
    
    // Filters
    private boolean isDailyTopMode = true; // Default to Daily Top 10 Ranked
    private String currentSentiment = null;
    private Boolean currentDividendOnly = null;
    private Float currentMinImpact = null;
    
    // Filter Chips
    private TextView chipDailyTop, chipAll, chipBullish, chipBearish, chipDividend, chipHighImpact;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        return inflater.inflate(R.layout.fragment_news, container, false);
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        super.onViewCreated(view, savedInstanceState);

        swipeRefresh = view.findViewById(R.id.swipe_refresh);
        recyclerView = view.findViewById(R.id.news_recycler);
        
        chipDailyTop = view.findViewById(R.id.chip_daily_top);
        chipAll = view.findViewById(R.id.chip_all);
        chipBullish = view.findViewById(R.id.chip_bullish);
        chipBearish = view.findViewById(R.id.chip_bearish);
        chipDividend = view.findViewById(R.id.chip_dividend);
        chipHighImpact = view.findViewById(R.id.chip_high_impact);

        adapter = new NewsAdapter(url -> {
            if (url != null && !url.isEmpty()) {
                Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
                startActivity(intent);
            }
        });
        recyclerView.setLayoutManager(new LinearLayoutManager(requireContext()));
        recyclerView.setAdapter(adapter);

        swipeRefresh.setOnRefreshListener(this::loadNews);
        
        setupFilterChips();
        loadNews();
    }

    private void setupFilterChips() {
        View.OnClickListener listener = v -> {
            resetChips();
            ((TextView) v).setTextColor(Color.WHITE);
            
            currentSentiment = null;
            currentDividendOnly = null;
            currentMinImpact = null;
            isDailyTopMode = false;

            if (v == chipDailyTop) {
                isDailyTopMode = true;
                chipDailyTop.setTextColor(Color.parseColor("#FFFFD740"));
            } else if (v == chipBullish) {
                currentSentiment = "BULLISH";
            } else if (v == chipBearish) {
                currentSentiment = "BEARISH";
            } else if (v == chipDividend) {
                currentDividendOnly = true;
            } else if (v == chipHighImpact) {
                currentMinImpact = 0.5f;
            }

            loadNews();
        };

        chipDailyTop.setOnClickListener(listener);
        chipAll.setOnClickListener(listener);
        chipBullish.setOnClickListener(listener);
        chipBearish.setOnClickListener(listener);
        chipDividend.setOnClickListener(listener);
        chipHighImpact.setOnClickListener(listener);

        // Highlight Daily Top initially
        resetChips();
        chipDailyTop.setTextColor(Color.parseColor("#FFFFD740"));
    }

    private void resetChips() {
        int defaultColor = getResources().getColor(R.color.text_secondary, null);
        chipDailyTop.setTextColor(defaultColor);
        chipAll.setTextColor(defaultColor);
        chipBullish.setTextColor(defaultColor);
        chipBearish.setTextColor(defaultColor);
        chipDividend.setTextColor(defaultColor);
        chipHighImpact.setTextColor(defaultColor);
    }

    private void loadNews() {
        swipeRefresh.setRefreshing(true);

        if (isDailyTopMode) {
            loadDailyTopNews();
        } else {
            loadStreamNews();
        }
    }

    private void loadDailyTopNews() {
        ApiClient.getApi().getDailyNewsRanked(null).enqueue(new Callback<JsonObject>() {
            @Override
            public void onResponse(@NonNull Call<JsonObject> call, @NonNull Response<JsonObject> response) {
                if (response.isSuccessful() && response.body() != null && isAdded()) {
                    JsonArray news = null;
                    if (response.body().has("ranked_news") && response.body().get("ranked_news").isJsonArray()) {
                        news = response.body().getAsJsonArray("ranked_news");
                    } else if (response.body().has("top_10") && response.body().get("top_10").isJsonArray()) {
                        news = response.body().getAsJsonArray("top_10");
                    }

                    if (news != null && news.size() > 0) {
                        List<JsonObject> items = new ArrayList<>();
                        for (JsonElement el : news) {
                            if (el.isJsonObject()) items.add(el.getAsJsonObject());
                        }
                        adapter.setItems(items);
                        if (isAdded()) swipeRefresh.setRefreshing(false);
                        return;
                    }
                }
                // Fallback to latest news stream if top 10 ranked is empty
                loadStreamNews();
            }

            @Override
            public void onFailure(@NonNull Call<JsonObject> call, @NonNull Throwable t) {
                loadStreamNews();
            }
        });
    }

    private void loadStreamNews() {
        ApiClient.getApi().getNews(
                currentSentiment, 
                null, 
                currentDividendOnly, 
                currentMinImpact, 
                50, 
                0
        ).enqueue(new Callback<JsonObject>() {
            @Override
            public void onResponse(@NonNull Call<JsonObject> call, @NonNull Response<JsonObject> response) {
                if (response.isSuccessful() && response.body() != null && isAdded()) {
                    JsonArray news = response.body().getAsJsonArray("news");
                    List<JsonObject> items = new ArrayList<>();
                    if (news != null) {
                        for (JsonElement el : news) {
                            if (el.isJsonObject()) items.add(el.getAsJsonObject());
                        }
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

    interface OnNewsClickListener {
        void onNewsClick(String url);
    }

    static class NewsAdapter extends RecyclerView.Adapter<NewsAdapter.VH> {
        private final List<JsonObject> items = new ArrayList<>();
        private final OnNewsClickListener listener;

        NewsAdapter(OnNewsClickListener listener) {
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
                    .inflate(R.layout.item_news, parent, false);
            return new VH(v);
        }

        @Override
        public void onBindViewHolder(@NonNull VH holder, int position) {
            JsonObject item = items.get(position);

            String title = item.has("title") ? item.get("title").getAsString() : "";
            String source = item.has("source") ? item.get("source").getAsString() : "";
            String date = item.has("published_at") && !item.get("published_at").isJsonNull()
                    ? item.get("published_at").getAsString() : "";
            String url = item.has("url") && !item.get("url").isJsonNull()
                    ? item.get("url").getAsString() : "";
            String sentiment = item.has("sentiment") && !item.get("sentiment").isJsonNull()
                    ? item.get("sentiment").getAsString() : "";

            holder.titleText.setText(title);
            holder.sourceText.setText(source);
            holder.timeText.setText(FormatUtils.formatRelativeTime(date));

            // Rating badge (1–10 scale)
            double rating = 0;
            if (item.has("rating") && !item.get("rating").isJsonNull()) {
                rating = item.get("rating").getAsDouble();
            } else if (item.has("impact_score") && !item.get("impact_score").isJsonNull()) {
                rating = item.get("impact_score").getAsDouble();
                if (rating <= 1.0 && rating > 0) rating = rating * 10.0;
            }

            if (rating > 0) {
                String impactLevel = item.has("impact_level") ? item.get("impact_level").getAsString() : 
                        (rating >= 8.5 ? "EXTREME" : (rating >= 7.0 ? "HIGH" : "MODERATE"));
                String reason = item.has("rating_reason") && !item.get("rating_reason").isJsonNull()
                        ? item.get("rating_reason").getAsString() : (item.has("impact_reason") && !item.get("impact_reason").isJsonNull() ? item.get("impact_reason").getAsString() : "");

                holder.ratingRow.setVisibility(View.VISIBLE);
                holder.ratingBadge.setText(String.format(Locale.US, "⭐ %.1f / 10", rating));
                holder.verdictBadge.setText(impactLevel + " IMPACT");

                if (rating >= 8.5) {
                    holder.ratingBadge.setTextColor(Color.parseColor("#FFFFD740"));
                    holder.verdictBadge.setTextColor(Color.parseColor("#FFFF5252"));
                } else if (rating >= 7.0) {
                    holder.ratingBadge.setTextColor(Color.parseColor("#FF00E676"));
                    holder.verdictBadge.setTextColor(Color.parseColor("#FF00E676"));
                } else {
                    holder.ratingBadge.setTextColor(Color.parseColor("#FF448AFF"));
                    holder.verdictBadge.setTextColor(Color.parseColor("#FF448AFF"));
                }

                if (!reason.isEmpty()) {
                    holder.impactReason.setText(reason);
                    holder.impactReason.setVisibility(View.VISIBLE);
                } else {
                    holder.impactReason.setVisibility(View.GONE);
                }
            } else {
                holder.ratingRow.setVisibility(View.GONE);
                holder.impactReason.setVisibility(View.GONE);
            }

            // Sentiment Badge
            if (!sentiment.isEmpty()) {
                holder.sentimentText.setVisibility(View.VISIBLE);
                if ("BULLISH".equalsIgnoreCase(sentiment)) {
                    holder.sentimentText.setText("🟢 BULLISH");
                    holder.sentimentText.setTextColor(Color.parseColor("#FF00E676"));
                } else if ("BEARISH".equalsIgnoreCase(sentiment)) {
                    holder.sentimentText.setText("🔴 BEARISH");
                    holder.sentimentText.setTextColor(Color.parseColor("#FFFF5252"));
                } else {
                    holder.sentimentText.setText("⚪ NEUTRAL");
                    holder.sentimentText.setTextColor(Color.parseColor("#FF9E9E9E"));
                }
            } else {
                holder.sentimentText.setVisibility(View.GONE);
            }

            // Dividend Badge
            boolean isDiv = (item.has("dividend_detected") && !item.get("dividend_detected").isJsonNull() 
                    && item.get("dividend_detected").getAsBoolean())
                    || title.toLowerCase().contains("dividend") || title.toLowerCase().contains("bonus");
            holder.dividendBadge.setVisibility(isDiv ? View.VISIBLE : View.GONE);

            // Affected Stocks Pills
            holder.stocksContainer.removeAllViews();
            JsonArray arr = null;
            if (item.has("affected_stocks") && !item.get("affected_stocks").isJsonNull()) {
                try {
                    if (item.get("affected_stocks").isJsonArray()) {
                        arr = item.getAsJsonArray("affected_stocks");
                    } else if (item.get("affected_stocks").isJsonPrimitive()) {
                        com.google.gson.JsonElement parsed = com.google.gson.JsonParser.parseString(item.get("affected_stocks").getAsString());
                        if (parsed.isJsonArray()) arr = parsed.getAsJsonArray();
                    }
                } catch (Exception ignored) {}
            }

            if (arr != null && arr.size() > 0) {
                holder.stocksScroll.setVisibility(View.VISIBLE);
                for (JsonElement el : arr) {
                    if (!el.isJsonObject()) continue;
                    JsonObject st = el.getAsJsonObject();
                    String sym = st.has("symbol") ? st.get("symbol").getAsString() : "";
                    String dir = st.has("direction") ? st.get("direction").getAsString() : 
                            (st.has("impact") ? st.get("impact").getAsString() : "");

                    TextView pill = new TextView(holder.itemView.getContext());
                    pill.setBackgroundResource(R.drawable.badge_bg);
                    pill.setText(sym);
                    pill.setTextSize(10f);
                    pill.setPadding(12, 4, 12, 4);
                    LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                            ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
                    lp.setMargins(0, 0, 8, 0);
                    pill.setLayoutParams(lp);

                    if ("BULLISH".equalsIgnoreCase(dir)) pill.setTextColor(Color.parseColor("#FF00E676"));
                    else if ("BEARISH".equalsIgnoreCase(dir)) pill.setTextColor(Color.parseColor("#FFFF5252"));
                    else pill.setTextColor(Color.parseColor("#FF448AFF"));

                    // Click on ticker pill opens stock details
                    pill.setOnClickListener(v -> {
                        Intent intent = new Intent(holder.itemView.getContext(), StockDetailActivity.class);
                        intent.putExtra(StockDetailActivity.EXTRA_SYMBOL, sym);
                        intent.putExtra(StockDetailActivity.EXTRA_EXCHANGE, "NSE");
                        intent.putExtra(StockDetailActivity.EXTRA_NAME, sym);
                        holder.itemView.getContext().startActivity(intent);
                    });

                    holder.stocksContainer.addView(pill);
                }
            } else {
                holder.stocksScroll.setVisibility(View.GONE);
            }

            holder.itemView.setOnClickListener(v -> {
                if (listener != null) listener.onNewsClick(url);
            });
        }

        static class VH extends RecyclerView.ViewHolder {
            View ratingRow;
            TextView ratingBadge, verdictBadge, impactReason;
            TextView titleText, sourceText, timeText, sentimentText, dividendBadge;
            HorizontalScrollView stocksScroll;
            LinearLayout stocksContainer;

            VH(View v) {
                super(v);
                ratingRow = v.findViewById(R.id.news_rating_row);
                ratingBadge = v.findViewById(R.id.news_rating_badge);
                verdictBadge = v.findViewById(R.id.news_verdict_badge);
                impactReason = v.findViewById(R.id.news_impact_reason);
                titleText = v.findViewById(R.id.news_title);
                sourceText = v.findViewById(R.id.news_source);
                timeText = v.findViewById(R.id.news_time);
                sentimentText = v.findViewById(R.id.news_sentiment);
                dividendBadge = v.findViewById(R.id.news_dividend_badge);
                stocksScroll = v.findViewById(R.id.affected_stocks_scroll);
                stocksContainer = v.findViewById(R.id.affected_stocks_container);
            }
        }
    }
}
