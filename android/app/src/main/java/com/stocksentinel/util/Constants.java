package com.stocksentinel.util;

/**
 * App-wide constants.
 */
public class Constants {

    // ============================================================
    // 🔧 UPDATE THIS with your Render deployment URL
    // ============================================================
    public static final String BASE_URL = "https://stocksentinel-api.onrender.com/";

    // API paths
    public static final String API_PREFIX = "api/";

    // Auto-refresh interval (milliseconds)
    public static final long AUTO_REFRESH_INTERVAL = 60_000; // 60 seconds

    // Search debounce delay
    public static final long SEARCH_DEBOUNCE_MS = 300;
}
