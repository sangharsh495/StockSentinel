package com.stocksentinel.util;

import java.text.DecimalFormat;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

/**
 * Formatting utilities for prices, percentages, dates.
 */
public class FormatUtils {

    private static final DecimalFormat PRICE_FORMAT_INR = new DecimalFormat("₹#,##,##0.00");
    private static final DecimalFormat PRICE_FORMAT_USD = new DecimalFormat("$#,##0.00");
    private static final DecimalFormat PCT_FORMAT = new DecimalFormat("+0.00;-0.00");
    private static final DecimalFormat VOLUME_FORMAT = new DecimalFormat("#,##0");

    public static String formatPrice(Double price, String currency) {
        if (price == null) return "—";
        if ("USD".equals(currency)) {
            return PRICE_FORMAT_USD.format(price);
        }
        return PRICE_FORMAT_INR.format(price);
    }

    public static String formatChangePercent(Double pct) {
        if (pct == null) return "—";
        return PCT_FORMAT.format(pct) + "%";
    }

    public static String formatVolume(Long volume) {
        if (volume == null) return "—";
        if (volume >= 10_000_000) {
            return String.format(Locale.US, "%.1fCr", volume / 10_000_000.0);
        } else if (volume >= 100_000) {
            return String.format(Locale.US, "%.1fL", volume / 100_000.0);
        } else if (volume >= 1000) {
            return String.format(Locale.US, "%.1fK", volume / 1000.0);
        }
        return VOLUME_FORMAT.format(volume);
    }

    public static String formatMarketCap(Long cap) {
        if (cap == null) return "—";
        if (cap >= 1_000_000_000_000L) {
            return String.format(Locale.US, "%.1fT", cap / 1_000_000_000_000.0);
        } else if (cap >= 1_000_000_000L) {
            return String.format(Locale.US, "%.1fB", cap / 1_000_000_000.0);
        } else if (cap >= 1_000_000L) {
            return String.format(Locale.US, "%.1fM", cap / 1_000_000.0);
        }
        return VOLUME_FORMAT.format(cap);
    }

    public static String formatDate(String dateStr) {
        if (dateStr == null || dateStr.isEmpty()) return "—";
        try {
            // Handle ISO format from backend
            SimpleDateFormat input = new SimpleDateFormat("yyyy-MM-dd", Locale.US);
            SimpleDateFormat output = new SimpleDateFormat("dd MMM yyyy", Locale.US);
            Date date = input.parse(dateStr);
            return date != null ? output.format(date) : dateStr;
        } catch (Exception e) {
            return dateStr;
        }
    }

    public static String timeAgo(String isoTimestamp) {
        if (isoTimestamp == null) return "";
        try {
            SimpleDateFormat sdf = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.US);
            Date date = sdf.parse(isoTimestamp.substring(0, 19));
            if (date == null) return "";

            long diff = System.currentTimeMillis() - date.getTime();
            long minutes = diff / 60_000;
            long hours = minutes / 60;
            long days = hours / 24;

            if (minutes < 1) return "Just now";
            if (minutes < 60) return minutes + "m ago";
            if (hours < 24) return hours + "h ago";
            if (days < 7) return days + "d ago";
            return new SimpleDateFormat("dd MMM", Locale.US).format(date);
        } catch (Exception e) {
            return "";
        }
    }

    public static int getChangeColor(Double pct) {
        if (pct == null || pct == 0) return 0xFF9E9E9E; // Gray
        return pct > 0 ? 0xFF00E676 : 0xFFFF5252; // Green or Red
    }
}
