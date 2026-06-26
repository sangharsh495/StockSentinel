package com.stocksentinel.notifications;

import android.app.NotificationManager;
import android.content.Context;
import android.util.Log;

import androidx.annotation.NonNull;
import androidx.core.app.NotificationCompat;

import com.google.firebase.messaging.FirebaseMessagingService;
import com.google.firebase.messaging.RemoteMessage;
import com.google.gson.JsonObject;
import com.stocksentinel.R;
import com.stocksentinel.StockSentinelApp;
import com.stocksentinel.data.api.ApiClient;
import com.stocksentinel.util.DeviceUtils;

import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;

/**
 * Firebase Cloud Messaging service — handles push notifications.
 */
public class FCMService extends FirebaseMessagingService {

    private static final String TAG = "FCMService";

    @Override
    public void onMessageReceived(@NonNull RemoteMessage remoteMessage) {
        super.onMessageReceived(remoteMessage);

        Log.d(TAG, "Message received from: " + remoteMessage.getFrom());

        String title = "StockSentinel";
        String body = "";
        String channelId = StockSentinelApp.CHANNEL_STOCK_ALERTS;

        // Check notification payload
        if (remoteMessage.getNotification() != null) {
            title = remoteMessage.getNotification().getTitle() != null
                    ? remoteMessage.getNotification().getTitle() : title;
            body = remoteMessage.getNotification().getBody() != null
                    ? remoteMessage.getNotification().getBody() : body;
        }

        // Check data payload for type-specific channel
        if (remoteMessage.getData().containsKey("type")) {
            String type = remoteMessage.getData().get("type");
            if ("dividend".equals(type)) {
                channelId = StockSentinelApp.CHANNEL_DIVIDEND_ALERTS;
            } else if ("ipo".equals(type)) {
                channelId = StockSentinelApp.CHANNEL_IPO_ALERTS;
            }
        }

        showNotification(title, body, channelId);
    }

    @Override
    public void onNewToken(@NonNull String token) {
        super.onNewToken(token);
        Log.d(TAG, "New FCM token: " + token);

        // Re-register with backend
        String deviceId = DeviceUtils.getDeviceId(this);
        JsonObject body = new JsonObject();
        body.addProperty("device_id", deviceId);
        body.addProperty("fcm_token", token);
        body.addProperty("platform", "android");

        ApiClient.getApi().registerDevice(body).enqueue(new Callback<JsonObject>() {
            @Override
            public void onResponse(@NonNull Call<JsonObject> call, @NonNull Response<JsonObject> response) {
                Log.d(TAG, "Token re-registered: " + response.body());
            }

            @Override
            public void onFailure(@NonNull Call<JsonObject> call, @NonNull Throwable t) {
                Log.w(TAG, "Token re-registration failed", t);
            }
        });
    }

    private void showNotification(String title, String body, String channelId) {
        NotificationCompat.Builder builder = new NotificationCompat.Builder(this, channelId)
                .setSmallIcon(R.drawable.ic_notification)
                .setContentTitle(title)
                .setContentText(body)
                .setAutoCancel(true)
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .setStyle(new NotificationCompat.BigTextStyle().bigText(body));

        NotificationManager manager = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager != null) {
            manager.notify((int) System.currentTimeMillis(), builder.build());
        }
    }
}
