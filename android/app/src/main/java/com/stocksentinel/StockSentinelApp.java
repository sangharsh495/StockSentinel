package com.stocksentinel;

import android.app.Application;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.os.Build;

/**
 * Application class — initializes notification channels.
 */
public class StockSentinelApp extends Application {

    public static final String CHANNEL_STOCK_ALERTS = "stock_alerts";
    public static final String CHANNEL_IPO_ALERTS = "ipo_alerts";
    public static final String CHANNEL_DIVIDEND_ALERTS = "dividend_alerts";

    @Override
    public void onCreate() {
        super.onCreate();
        createNotificationChannels();
    }

    private void createNotificationChannels() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationManager manager = getSystemService(NotificationManager.class);

            NotificationChannel stockChannel = new NotificationChannel(
                    CHANNEL_STOCK_ALERTS,
                    "Stock Alerts",
                    NotificationManager.IMPORTANCE_DEFAULT
            );
            stockChannel.setDescription("Price movement alerts for tracked stocks");

            NotificationChannel ipoChannel = new NotificationChannel(
                    CHANNEL_IPO_ALERTS,
                    "IPO Alerts",
                    NotificationManager.IMPORTANCE_HIGH
            );
            ipoChannel.setDescription("Upcoming IPO opening alerts");

            NotificationChannel dividendChannel = new NotificationChannel(
                    CHANNEL_DIVIDEND_ALERTS,
                    "Dividend Alerts",
                    NotificationManager.IMPORTANCE_HIGH
            );
            dividendChannel.setDescription("Dividend ex-date alerts");

            manager.createNotificationChannel(stockChannel);
            manager.createNotificationChannel(ipoChannel);
            manager.createNotificationChannel(dividendChannel);
        }
    }
}
