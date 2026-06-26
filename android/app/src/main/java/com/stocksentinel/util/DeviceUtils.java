package com.stocksentinel.util;

import android.content.Context;
import android.provider.Settings;

/**
 * Device utilities — unique device ID for watchlist and notifications.
 */
public class DeviceUtils {

    public static String getDeviceId(Context context) {
        return Settings.Secure.getString(
                context.getContentResolver(),
                Settings.Secure.ANDROID_ID
        );
    }
}
