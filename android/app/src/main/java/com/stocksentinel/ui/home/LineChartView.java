package com.stocksentinel.ui.home;

import android.animation.ValueAnimator;
import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.LinearGradient;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.Shader;
import android.util.AttributeSet;
import android.view.MotionEvent;
import android.view.View;
import android.view.animation.DecelerateInterpolator;

import androidx.annotation.Nullable;

import java.util.ArrayList;
import java.util.List;

/**
 * Premium custom line chart utilizing canvas bezier drawing, gradient shading, and touch tracking.
 */
public class LineChartView extends View {

    private Paint linePaint;
    private Paint fillPaint;
    private Paint dotPaint;
    private Paint dotOuterPaint;
    private Paint guidePaint;

    private List<Float> dataPoints = new ArrayList<>();
    private List<String> labels = new ArrayList<>();

    private float animationProgress = 0f;
    private float touchX = -1f;
    private int selectedIndex = -1;

    private OnSelectedPointListener listener;

    public interface OnSelectedPointListener {
        void onPointSelected(int index, float value, String label);
        void onSelectionCleared();
    }

    public LineChartView(Context context) {
        super(context);
        init();
    }

    public LineChartView(Context context, @Nullable AttributeSet attrs) {
        super(context, attrs);
        init();
    }

    private void init() {
        // Line Paint (glowing green/purple accent)
        linePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        linePaint.setColor(Color.parseColor("#FF00E676")); // green_accent
        linePaint.setStyle(Paint.Style.STROKE);
        linePaint.setStrokeWidth(8f);
        linePaint.setStrokeCap(Paint.Cap.ROUND);
        linePaint.setStrokeJoin(Paint.Join.ROUND);

        // Fill Paint (gradient underneath)
        fillPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        fillPaint.setStyle(Paint.Style.FILL);

        // Tracker Dot Paint
        dotPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        dotPaint.setColor(Color.parseColor("#FF00E676"));
        dotPaint.setStyle(Paint.Style.FILL);

        dotOuterPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        dotOuterPaint.setColor(Color.parseColor("#3300E676"));
        dotOuterPaint.setStyle(Paint.Style.FILL);

        // Vertical Guide Line Paint
        guidePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        guidePaint.setColor(Color.parseColor("#22FFE676"));
        guidePaint.setStyle(Paint.Style.STROKE);
        guidePaint.setStrokeWidth(3f);
        // Dash effect
        guidePaint.setPathEffect(new android.graphics.DashPathEffect(new float[]{10, 10}, 0));
    }

    public void setData(List<Float> points, List<String> labels) {
        this.dataPoints = points;
        this.labels = labels;
        this.touchX = -1f;
        this.selectedIndex = -1;
        if (listener != null) {
            listener.onSelectionCleared();
        }
        animateChart();
    }

    public void setOnSelectedPointListener(OnSelectedPointListener listener) {
        this.listener = listener;
    }

    private void animateChart() {
        ValueAnimator animator = ValueAnimator.ofFloat(0f, 1f);
        animator.setDuration(800);
        animator.setInterpolator(new DecelerateInterpolator());
        animator.addUpdateListener(animation -> {
            animationProgress = (float) animation.getAnimatedValue();
            invalidate();
        });
        animator.start();
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        if (dataPoints == null || dataPoints.size() < 2) return;

        int width = getWidth();
        int height = getHeight();
        int paddingBottom = 40;
        int paddingTop = 40;
        int paddingLeft = 10;
        int paddingRight = 10;

        int chartWidth = width - paddingLeft - paddingRight;
        int chartHeight = height - paddingTop - paddingBottom;

        float minVal = Float.MAX_VALUE;
        float maxVal = Float.MIN_VALUE;
        for (float val : dataPoints) {
            if (val < minVal) minVal = val;
            if (val > maxVal) maxVal = val;
        }

        // Add 10% breathing room to min/max
        float diff = maxVal - minVal;
        if (diff == 0) diff = 1f;
        minVal -= diff * 0.1f;
        maxVal += diff * 0.1f;
        float range = maxVal - minVal;

        // Calculate horizontal coordinates
        float[] xCoords = new float[dataPoints.size()];
        float[] yCoords = new float[dataPoints.size()];
        float stepX = (float) chartWidth / (dataPoints.size() - 1);

        for (int i = 0; i < dataPoints.size(); i++) {
            xCoords[i] = paddingLeft + (i * stepX);
            // Invert Y coordinate because canvas 0 is top
            float ratio = (dataPoints.get(i) - minVal) / range;
            yCoords[i] = paddingTop + (chartHeight * (1f - ratio));
        }

        // Draw Guide lines and trackers if touching
        if (touchX >= 0 && selectedIndex >= 0 && selectedIndex < dataPoints.size()) {
            float selX = xCoords[selectedIndex];
            float selY = yCoords[selectedIndex];

            // Draw vertical dashed guide line
            canvas.drawLine(selX, paddingTop, selX, height - paddingBottom, guidePaint);

            // Tracker dot outer ring
            canvas.drawCircle(selX, selY, 20f, dotOuterPaint);
            // Tracker dot center
            canvas.drawCircle(selX, selY, 10f, dotPaint);
        }

        // Draw smooth Bezier path
        Path linePath = new Path();
        Path fillPath = new Path();

        linePath.moveTo(xCoords[0], yCoords[0]);
        fillPath.moveTo(xCoords[0], yCoords[0]);

        // Draw bezier curves
        for (int i = 0; i < dataPoints.size() - 1; i++) {
            float x1 = xCoords[i];
            float y1 = yCoords[i];
            float x2 = xCoords[i + 1];
            float y2 = yCoords[i + 1];

            // Control points for cubic bezier curves
            float controlX1 = x1 + (x2 - x1) / 2f;
            float controlY1 = y1;
            float controlX2 = x1 + (x2 - x1) / 2f;
            float controlY2 = y2;

            // Apply animation progress by scaling transition coordinates
            float animatedX2 = x1 + (x2 - x1) * animationProgress;
            float animatedY2 = y1 + (y2 - y1) * animationProgress;
            float animatedCX1 = x1 + (controlX1 - x1) * animationProgress;
            float animatedCY1 = y1 + (controlY1 - y1) * animationProgress;
            float animatedCX2 = x1 + (controlX2 - x1) * animationProgress;
            float animatedCY2 = y1 + (controlY2 - y1) * animationProgress;

            linePath.cubicTo(animatedCX1, animatedCY1, animatedCX2, animatedCY2, animatedX2, animatedY2);
            fillPath.cubicTo(animatedCX1, animatedCY1, animatedCX2, animatedCY2, animatedX2, animatedY2);
        }

        // Complete fill path down to baseline
        float lastAnimatedX = xCoords[0] + (xCoords[xCoords.length - 1] - xCoords[0]) * animationProgress;
        fillPath.lineTo(lastAnimatedX, height - paddingBottom);
        fillPath.lineTo(xCoords[0], height - paddingBottom);
        fillPath.close();

        // Update fill paint shader with linear gradient dynamically
        fillPaint.setShader(new LinearGradient(
                0, paddingTop, 0, height - paddingBottom,
                Color.parseColor("#4400E676"), // green tint translucent
                Color.TRANSPARENT,
                Shader.TileMode.CLAMP
        ));

        // Draw components
        canvas.drawPath(fillPath, fillPaint);
        canvas.drawPath(linePath, linePaint);
    }

    @Override
    public boolean onTouchEvent(MotionEvent event) {
        if (dataPoints == null || dataPoints.isEmpty()) return false;

        float x = event.getX();
        switch (event.getAction()) {
            case MotionEvent.ACTION_DOWN:
            case MotionEvent.ACTION_MOVE:
                touchX = x;
                selectedIndex = findClosestIndex(x);
                if (selectedIndex >= 0 && listener != null) {
                    listener.onPointSelected(
                            selectedIndex,
                            dataPoints.get(selectedIndex),
                            labels.size() > selectedIndex ? labels.get(selectedIndex) : ""
                    );
                }
                invalidate();
                return true;
            case MotionEvent.ACTION_UP:
            case MotionEvent.ACTION_CANCEL:
                touchX = -1f;
                selectedIndex = -1;
                if (listener != null) {
                    listener.onSelectionCleared();
                }
                invalidate();
                return true;
        }
        return super.onTouchEvent(event);
    }

    private int findClosestIndex(float x) {
        int width = getWidth();
        int paddingLeft = 10;
        int paddingRight = 10;
        int chartWidth = width - paddingLeft - paddingRight;
        float stepX = (float) chartWidth / (dataPoints.size() - 1);

        int index = Math.round((x - paddingLeft) / stepX);
        return Math.max(0, Math.min(index, dataPoints.size() - 1));
    }
}
