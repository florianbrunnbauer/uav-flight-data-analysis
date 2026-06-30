import numpy as np
import pandas as pd
import pytest

from analysis import compute_accel_psd, compute_signal_fft, compute_time_resolved_psd_surface


def test_compute_signal_fft_detects_known_sine_frequency():
    sample_rate_hz = 200.0
    duration_s = 2.0
    frequency_hz = 20.0
    amplitude = 3.0
    t = np.arange(0.0, duration_s, 1.0 / sample_rate_hz)
    signal = amplitude * np.sin(2.0 * np.pi * frequency_hz * t)

    df = pd.DataFrame({"time_s": t, "signal": signal})

    fft_df, metrics = compute_signal_fft(df, ["signal"])
    non_dc_fft_df = fft_df[fft_df["frequency_hz"] > 0]
    peak_row = non_dc_fft_df.loc[non_dc_fft_df["amplitude"].idxmax()]

    assert metrics["sample_rate_hz"] == pytest.approx(sample_rate_hz)
    assert metrics["samples"] == len(t)
    assert peak_row["frequency_hz"] == pytest.approx(frequency_hz, abs=0.5)
    assert peak_row["amplitude"] == pytest.approx(amplitude, rel=0.05)


def test_compute_accel_psd_detects_known_acceleration_frequency():
    sample_rate_hz = 200.0
    duration_s = 3.0
    frequency_hz = 25.0
    t = np.arange(0.0, duration_s, 1.0 / sample_rate_hz)

    sensor_accel = pd.DataFrame({
        "time_s": t,
        "accel_x_m_s2": np.sin(2.0 * np.pi * frequency_hz * t),
        "accel_y_m_s2": 0.5 * np.sin(2.0 * np.pi * frequency_hz * t),
        "accel_z_m_s2": np.zeros_like(t),
    })

    psd_df, metrics = compute_accel_psd(sensor_accel)

    assert not psd_df.empty
    assert metrics["sensor_accel_sample_rate_hz"] == pytest.approx(sample_rate_hz)
    assert metrics["dominant_accel_frequency_hz"] == pytest.approx(frequency_hz, abs=0.5)
    assert metrics["sensor_accel_axis_columns"] == "accel_x_m_s2, accel_y_m_s2, accel_z_m_s2"


def test_compute_time_resolved_psd_surface_returns_stable_time_frequency_grid():
    sample_rate_hz = 200.0
    duration_s = 5.0
    frequency_hz = 30.0
    t = np.arange(0.0, duration_s, 1.0 / sample_rate_hz)

    df = pd.DataFrame({
        "time_s": t,
        "signal": np.sin(2.0 * np.pi * frequency_hz * t),
    })

    surfaces, metrics = compute_time_resolved_psd_surface(
        df,
        ["signal"],
        window_duration_s=1.0,
        time_step_s=0.5,
        max_frequency_hz=80.0,
    )

    assert "signal" in surfaces
    surface = surfaces["signal"]

    assert metrics["sample_rate_hz"] == pytest.approx(sample_rate_hz)
    assert metrics["window_duration_s"] == pytest.approx(1.0)
    assert metrics["actual_time_step_s"] == pytest.approx(0.5)
    assert metrics["segments"] == len(surface["time_s"])
    assert surface["psd"].shape == (len(surface["time_s"]), len(surface["frequency_hz"]))

    first_row_peak_idx = int(np.nanargmax(surface["psd"][0]))
    first_row_peak_frequency = surface["frequency_hz"][first_row_peak_idx]
    assert first_row_peak_frequency == pytest.approx(frequency_hz, abs=1.0)
