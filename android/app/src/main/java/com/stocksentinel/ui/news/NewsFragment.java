package com.stocksentinel.ui.news;

import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
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
 * News Fragment — sentiment-tagged news with filter chips.
 */
public class NewsFragment extends Fragment {

    private SwipeRefreshLayout swipeRefresh;
    private RecyclerView recyclerView;
    private NewsAdapter adapter;
    private String currentSentiment = null;

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

        adapter = new NewsAdapter(url -> {
            Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
            startActivity(intent);
        });
        recyclerView.setLayoutManager(new LinearLayoutManager(requireContext()));
        recyclerView.setAdapter(adapter);

        swipeRefresh.setOnRefreshListener(this::loadNews);
        loadNews();
    }

    private void loadNews() {
        swipeRefresh.setRefreshing(true);

        ApiClient.getApi().getNews(currentSentiment, null, 50, 0).enqueue(new Callback<JsonObject>() {
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

            holder.itemView.setOnClickListener(v -> {
                if (!url.isEmpty() && listener != null) {
                    listener.onClick(url);
                }
            });
        }

        static class VH extends RecyclerView.ViewHolder {
            TextView titleText, sourceText, sentimentText, timeText;

            VH(View v) {
                super(v);
                titleText = v.findViewById(R.id.news_title);
                sourceText = v.findViewById(R.id.news_source);
                sentimentText = v.findViewById(R.id.news_sentiment);
                timeText = v.findViewById(R.id.news_time);
            }
        }
    }
}
