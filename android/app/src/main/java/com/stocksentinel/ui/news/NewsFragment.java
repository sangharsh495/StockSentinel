package com.stocksentinel.ui.news;

import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
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
import com.stocksentinel.util.FormatUtils;

import java.util.ArrayList;
import java.util.List;

import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;

/**
 * News Fragment — ML-powered news with stock impact, dividend detection, and filter chips.
 */
public class NewsFragment extends Fragment {

    private SwipeRefreshLayout swipeRefresh;
    private RecyclerView recyclerView;
    private NewsAdapter adapter;
    
    // Filters
    private String currentSentiment = null;
    private Boolean currentDividendOnly = null;
    private Float currentMinImpact = null;
    
    // Filter Chips
    private TextView chipAll, chipBullish, chipBearish, chipDividend, chipHighImpact;

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
        
        chipAll = view.findViewById(R.id.chip_all);
        chipBullish = view.findViewById(R.id.chip_bullish);
        chipBearish = view.findViewById(R.id.chip_bearish);
        chipDividend = view.findViewById(R.id.chip_dividend);
        chipHighImpact = view.findViewById(R.id.chip_high_impact);

        adapter = new NewsAdapter(url -> {
            Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
            startActivity(intent);
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

            if (v == chipBullish) currentSentiment = "BULLISH";
            else if (v == chipBearish) currentSentiment = "BEARISH";
            else if (v == chipDividend) currentDividendOnly = true;
            else if (v == chipHighImpact) currentMinImpact = 0.5f;

            loadNews();
        };

        chipAll.setOnClickListener(listener);
        chipBullish.setOnClickListener(listener);
        chipBearish.setOnClickListener(listener);
        chipDividend.setOnClickListener(listener);
        chipHighImpact.setOnClickListener(listener);
    }

    private void resetChips() {
        int secondary = getResources().getColor(R.color.text_secondary, requireContext().getTheme());
        chipAll.setTextColor(secondary);
        chipBullish.setTextColor(secondary);
        chipBearish.setTextColor(secondary);
        chipDividend.setTextColor(secondary);
        chipHighImpact.setTextColor(secondary);
    }

    private void loadNews() {
        swipeRefresh.setRefreshing(true);

        ApiClient.getApi().getNews(currentSentiment, null, currentDividendOnly, currentMinImpact, 50, 0)
                .enqueue(new Callback<JsonObject>() {
            @Override
            public void onResponse(@NonNull Call<JsonObject> call, @NonNull Response<JsonObject> response) {
                if (response.isSuccessful() && response.body() != null && isAdded()) {
                    JsonArray news = response.body().getAsJsonArray("news");
                    List<JsonObject> items = new ArrayList<>();
                    for (JsonElement el : news) {
                        items.add(el.getAsJsonObject());
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
        void onClick(String url);
    }

    class NewsAdapter extends RecyclerView.Adapter<NewsAdapter.VH> {
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
            JsonObject news = items.get(position);

            String title = news.has("title") ? news.get("title").getAsString() : "";
            String source = news.has("source") && !news.get("source").isJsonNull()
                    ? news.get("source").getAsString() : "";
            String sentiment = news.has("sentiment") && !news.get("sentiment").isJsonNull()
                    ? news.get("sentiment").getAsString() : "";
            String published = news.has("published_at") && !news.get("published_at").isJsonNull()
                    ? news.get("published_at").getAsString() : "";
            String url = news.has("url") && !news.get("url").isJsonNull()
                    ? news.get("url").getAsString() : "";

            holder.titleText.setText(title);
            holder.sourceText.setText(source);
            holder.timeText.setText(FormatUtils.timeAgo(published));

            // Sentiment badge
            String badge;
            int badgeColor;
            switch (sentiment.toUpperCase()) {
                case "BULLISH":
                    badge = "🟢 BULLISH";
                    badgeColor = 0xFF00E676;
                    break;
                case "BEARISH":
                    badge = "🔴 BEARISH";
                    badgeColor = 0xFFFF5252;
                    break;
                default:
                    badge = "⚪ NEUTRAL";
                    badgeColor = 0xFF9E9E9E;
            }
            holder.sentimentText.setText(badge);
            holder.sentimentText.setTextColor(badgeColor);

            // Impact Score
            if (news.has("impact_score") && !news.get("impact_score").isJsonNull()) {
                float impact = news.get("impact_score").getAsFloat();
                holder.impactText.setVisibility(View.VISIBLE);
                holder.impactText.setText(String.format("⚡ %.1f", impact));
                if (impact > 0.6) holder.impactText.setTextColor(0xFFFFC107); // Amber for high impact
                else holder.impactText.setTextColor(getResources().getColor(R.color.text_secondary, requireContext().getTheme()));
            } else {
                holder.impactText.setVisibility(View.GONE);
            }

            // Dividend Badge
            if (news.has("dividend_detected") && news.get("dividend_detected").getAsBoolean()) {
                holder.dividendBadge.setVisibility(View.VISIBLE);
            } else {
                holder.dividendBadge.setVisibility(View.GONE);
            }

            // Affected Stocks
            holder.affectedStocksContainer.removeAllViews();
            if (news.has("affected_stocks") && !news.get("affected_stocks").isJsonNull()) {
                JsonArray stocks = news.get("affected_stocks").getAsJsonArray();
                if (stocks.size() > 0) {
                    holder.affectedStocksScroll.setVisibility(View.VISIBLE);
                    for (JsonElement el : stocks) {
                        JsonObject s = el.getAsJsonObject();
                        String sym = s.has("symbol") ? s.get("symbol").getAsString() : "";
                        String dir = s.has("direction") ? s.get("direction").getAsString() : "";
                        
                        TextView chip = new TextView(requireContext());
                        chip.setText(sym + (dir.equals("BULLISH") ? " ↗" : dir.equals("BEARISH") ? " ↘" : ""));
                        chip.setTextColor(Color.WHITE);
                        chip.setTextSize(11);
                        chip.setPadding(16, 8, 16, 8);
                        chip.setBackgroundResource(R.drawable.badge_bg);
                        
                        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
                        params.setMarginEnd(16);
                        chip.setLayoutParams(params);
                        
                        holder.affectedStocksContainer.addView(chip);
                    }
                } else {
                    holder.affectedStocksScroll.setVisibility(View.GONE);
                }
            } else {
                holder.affectedStocksScroll.setVisibility(View.GONE);
            }

            holder.itemView.setOnClickListener(v -> {
                if (!url.isEmpty() && listener != null) {
                    listener.onClick(url);
                }
            });
        }

        class VH extends RecyclerView.ViewHolder {
            TextView titleText, sourceText, sentimentText, timeText;
            TextView impactText, dividendBadge;
            View affectedStocksScroll;
            LinearLayout affectedStocksContainer;

            VH(View v) {
                super(v);
                titleText = v.findViewById(R.id.news_title);
                sourceText = v.findViewById(R.id.news_source);
                sentimentText = v.findViewById(R.id.news_sentiment);
                timeText = v.findViewById(R.id.news_time);
                impactText = v.findViewById(R.id.news_impact);
                dividendBadge = v.findViewById(R.id.news_dividend_badge);
                affectedStocksScroll = v.findViewById(R.id.affected_stocks_scroll);
                affectedStocksContainer = v.findViewById(R.id.affected_stocks_container);
            }
        }
    }
}
