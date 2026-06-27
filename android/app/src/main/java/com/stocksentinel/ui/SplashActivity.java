package com.stocksentinel.ui;

import android.content.Intent;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.view.animation.DecelerateInterpolator;

import androidx.appcompat.app.AppCompatActivity;

import com.stocksentinel.R;

/**
 * Splash screen showing startup branding animations before launching MainActivity.
 */
public class SplashActivity extends AppCompatActivity {

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_splash);

        View logoContainer = findViewById(R.id.logo_container);
        View footer = findViewById(R.id.splash_footer);

        // Start animating logo container: fade in and scale up smoothly
        logoContainer.animate()
                .alpha(1f)
                .scaleX(1f)
                .scaleY(1f)
                .setDuration(1000)
                .setInterpolator(new DecelerateInterpolator())
                .start();

        // Animate footer text after a small delay
        footer.postDelayed(() -> footer.animate()
                .alpha(1f)
                .setDuration(600)
                .start(), 400);

        // Transit to MainActivity after splash ends (1600ms total duration)
        new Handler(Looper.getMainLooper()).postDelayed(() -> {
            Intent intent = new Intent(SplashActivity.this, MainActivity.class);
            startActivity(intent);
            finish();
            overridePendingTransition(android.R.anim.fade_in, android.R.anim.fade_out);
        }, 1600);
    }
}
