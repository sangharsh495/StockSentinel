package com.stocksentinel.ui.home;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.TextView;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import com.google.android.material.bottomsheet.BottomSheetDialogFragment;
import android.widget.Button;
import com.google.android.material.slider.Slider;
import com.stocksentinel.R;
import com.stocksentinel.util.FormatUtils;

/**
 * Bottom Sheet Dialog permitting the user to interactively adjust and configure mock asset values.
 */
public class WealthSettingsBottomSheet extends BottomSheetDialogFragment {

    private Slider sliderIndianStocks;
    private Slider sliderUsStocks;
    private Slider sliderMutualFunds;
    private Slider sliderCash;

    private TextView valueIndianStocks;
    private TextView valueUsStocks;
    private TextView valueMutualFunds;
    private TextView valueCash;

    private float valIndian;
    private float valUs;
    private float valMf;
    private float valCash;

    private OnWealthSavedListener listener;

    public interface OnWealthSavedListener {
        void onWealthSaved(float indian, float us, float mf, float cash);
    }

    public static WealthSettingsBottomSheet newInstance(float indian, float us, float mf, float cash) {
        WealthSettingsBottomSheet fragment = new WealthSettingsBottomSheet();
        Bundle args = new Bundle();
        args.putFloat("indian", indian);
        args.putFloat("us", us);
        args.putFloat("mf", mf);
        args.putFloat("cash", cash);
        fragment.setArguments(args);
        return fragment;
    }

    public void setOnWealthSavedListener(OnWealthSavedListener listener) {
        this.listener = listener;
    }

    @Override
    public void onCreate(@Nullable Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        if (getArguments() != null) {
            valIndian = getArguments().getFloat("indian");
            valUs = getArguments().getFloat("us");
            valMf = getArguments().getFloat("mf");
            valCash = getArguments().getFloat("cash");
        }
    }

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater, @Nullable ViewGroup container, @Nullable Bundle savedInstanceState) {
        return inflater.inflate(R.layout.dialog_wealth_settings, container, false);
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        super.onViewCreated(view, savedInstanceState);

        sliderIndianStocks = view.findViewById(R.id.slider_indian_stocks);
        sliderUsStocks = view.findViewById(R.id.slider_us_stocks);
        sliderMutualFunds = view.findViewById(R.id.slider_mutual_funds);
        sliderCash = view.findViewById(R.id.slider_cash);

        valueIndianStocks = view.findViewById(R.id.value_indian_stocks);
        valueUsStocks = view.findViewById(R.id.value_us_stocks);
        valueMutualFunds = view.findViewById(R.id.value_mutual_funds);
        valueCash = view.findViewById(R.id.value_cash);

        Button btnSave = view.findViewById(R.id.btn_save);
        Button btnCancel = view.findViewById(R.id.btn_cancel);

        // Prepopulate current values
        setupSlider(sliderIndianStocks, valueIndianStocks, valIndian);
        setupSlider(sliderUsStocks, valueUsStocks, valUs);
        setupSlider(sliderMutualFunds, valueMutualFunds, valMf);
        setupSlider(sliderCash, valueCash, valCash);

        btnCancel.setOnClickListener(v -> dismiss());
        btnSave.setOnClickListener(v -> {
            if (listener != null) {
                listener.onWealthSaved(
                        sliderIndianStocks.getValue(),
                        sliderUsStocks.getValue(),
                        sliderMutualFunds.getValue(),
                        sliderCash.getValue()
                );
            }
            dismiss();
        });
    }

    private void setupSlider(Slider slider, TextView valueText, float currentValue) {
        // Clamp current value to slider limits
        float clamped = Math.max(slider.getValueFrom(), Math.min(slider.getValueTo(), currentValue));
        slider.setValue(clamped);
        valueText.setText(FormatUtils.formatPrice((double) clamped, "INR"));

        slider.addOnChangeListener((s, value, fromUser) -> {
            valueText.setText(FormatUtils.formatPrice((double) value, "INR"));
        });
    }
}
