package com.stocksentinel.ui.search;

import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.Editable;
import android.text.TextWatcher;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.EditText;
import android.widget.TextView;

import androidx.annotation.NonNull;
import androidx.appcompat.app.AppCompatActivity;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.stocksentinel.R;
import com.stocksentinel.data.api.ApiClient;
import com.stocksentinel.util.Constants;
import com.stocksentinel.util.FormatUtils;

import java.util.ArrayList;
import java.util.List;

import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;

/**
 * Search Activity — instant search across 13,000+ stocks.
 */
public class SearchActivity extends AppCompatActivity {

    private EditText searchInput;
    private RecyclerView resultsRecycler;
    private TextView emptyText;
    private SearchAdapter adapter;
    private Handler handler = new Handler(Looper.getMainLooper());
    private Runnable searchRunnable;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_search);

        searchInput = findViewById(R.id.search_input);
        resultsRecycler = findViewById(R.id.search_results);
        emptyText = findViewById(R.id.empty_text);

        adapter = new SearchAdapter();
        resultsRecycler.setLayoutManager(new LinearLayoutManager(this));
        resultsRecycler.setAdapter(adapter);

        // Back button
        findViewById(R.id.btn_back).setOnClickListener(v -> finish());

        // Debounced search
        searchInput.addTextChangedListener(new TextWatcher() {
            @Override
            public void beforeTextChanged(CharSequence s, int start, int count, int after) { }

            @Override
            public void onTextChanged(CharSequence s, int start, int before, int count) {
                if (searchRunnable != null) handler.removeCallbacks(searchRunnable);
                searchRunnable = () -> performSearch(s.toString().trim());
                handler.postDelayed(searchRunnable, Constants.SEARCH_DEBOUNCE_MS);
            }

            @Override
            public void afterTextChanged(Editable s) { }
        });

        searchInput.requestFocus();
    }

    private void performSearch(String query) {
        if (query.length() < 1) {
            adapter.clear();
            emptyText.setVisibility(View.VISIBLE);
            emptyText.setText("Search 13,000+ stocks…");
            return;
        }

        ApiClient.getApi().searchStocks(query, 20).enqueue(new Callback<JsonObject>() {
            @Override
            public void onResponse(@NonNull Call<JsonObject> call, @NonNull Response<JsonObject> response) {
                if (response.isSuccessful() && response.body() != null) {
                    JsonArray stocks = response.body().getAsJsonArray("stocks");
                    List<JsonObject> items = new ArrayList<>();
                    for (JsonElement el : stocks) {
                        items.add(el.getAsJsonObject());
                    }
                    adapter.setItems(items);
                    emptyText.setVisibility(items.isEmpty() ? View.VISIBLE : View.GONE);
                    if (items.isEmpty()) emptyText.setText("No stocks found for \"" + query + "\"");
                }
            }

            @Override
            public void onFailure(@NonNull Call<JsonObject> call, @NonNull Throwable t) {
                emptyText.setVisibility(View.VISIBLE);
                emptyText.setText("Search failed — check connection");
            }
        });
    }

    static class SearchAdapter extends RecyclerView.Adapter<SearchAdapter.VH> {
        private final List<JsonObject> items = new ArrayList<>();

        void setItems(List<JsonObject> newItems) {
            items.clear();
            items.addAll(newItems);
            notifyDataSetChanged();
        }

        void clear() {
            items.clear();
            notifyDataSetChanged();
        }

        @Override
        public int getItemCount() { return items.size(); }

        @NonNull
        @Override
        public VH onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
            View v = LayoutInflater.from(parent.getContext())
                    .inflate(R.layout.item_stock_list, parent, false);
            return new VH(v);
        }

        @Override
        public void onBindViewHolder(@NonNull VH holder, int position) {
            JsonObject stock = items.get(position);

            String symbol = stock.has("symbol") ? stock.get("symbol").getAsString() : "";
            String name = stock.has("name") && !stock.get("name").isJsonNull()
                    ? stock.get("name").getAsString() : symbol;
            Double price = stock.has("current_price") && !stock.get("current_price").isJsonNull()
                    ? stock.get("current_price").getAsDouble() : null;
            Double pct = stock.has("change_pct") && !stock.get("change_pct").isJsonNull()
                    ? stock.get("change_pct").getAsDouble() : null;
            String exchange = stock.has("exchange") && !stock.get("exchange").isJsonNull()
                    ? stock.get("exchange").getAsString() : "";
            String currency = stock.has("currency") && !stock.get("currency").isJsonNull()
                    ? stock.get("currency").getAsString() : "INR";

            holder.symbolText.setText(symbol);
            holder.nameText.setText(name.length() > 30 ? name.substring(0, 30) + "…" : name);
            holder.exchangeText.setText(exchange);
            holder.priceText.setText(FormatUtils.formatPrice(price, currency));
            holder.changeText.setText(FormatUtils.formatChangePercent(pct));
            holder.changeText.setTextColor(FormatUtils.getChangeColor(pct));
        }

        static class VH extends RecyclerView.ViewHolder {
            TextView symbolText, nameText, exchangeText, priceText, changeText;

            VH(View v) {
                super(v);
                symbolText = v.findViewById(R.id.stock_symbol);
                nameText = v.findViewById(R.id.stock_name);
                exchangeText = v.findViewById(R.id.stock_exchange);
                priceText = v.findViewById(R.id.stock_price);
                changeText = v.findViewById(R.id.stock_change);
            }
        }
    }
}
