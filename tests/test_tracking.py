import numpy as np
import pandas as pd
import pytest

from analysis import compute_tracking_error_metrics, estimate_signal_lag_s


def test_compute_tracking_error_metrics_for_known_error_signal():
    df = pd.DataFrame({"roll_error_deg": [1.0, -1.0, 2.0, -2.0]})

    metrics = compute_tracking_error_metrics(
        df,
        {"roll": "roll_error_deg"},
        {"roll": 0.123},
    )
    row = metrics.set_index("axis").loc["roll"]

    assert row["samples"] == 4
    assert row["time_offset_s"] == pytest.approx(0.123)
    assert row["bias"] == pytest.approx(0.0)
    assert row["mean_abs_error"] == pytest.approx(1.5)
    assert row["rmse"] == pytest.approx(np.sqrt(2.5))
    assert row["max_abs"] == pytest.approx(2.0)


def test_compute_tracking_error_metrics_uses_zero_for_missing_time_offset():
    df = pd.DataFrame({"pitch_error_deg": [np.nan, np.nan]})

    metrics = compute_tracking_error_metrics(
        df,
        {"pitch": "pitch_error_deg"},
        {"pitch": np.nan},
    )
    row = metrics.set_index("axis").loc["pitch"]

    assert row["samples"] == 0
    assert row["time_offset_s"] == pytest.approx(0.0)
    assert pd.isna(row["rmse"])


def test_estimate_signal_lag_detects_delayed_response():
    sample_rate_hz = 100.0
    t = np.arange(0.0, 10.0, 1.0 / sample_rate_hz)
    expected_delay_s = 0.12

    reference = (
        np.exp(-0.5 * ((t - 2.0) / 0.12) ** 2)
        + 0.6 * np.exp(-0.5 * ((t - 5.0) / 0.20) ** 2)
        - 0.4 * np.exp(-0.5 * ((t - 7.0) / 0.15) ** 2)
    )
    response = np.interp(t - expected_delay_s, t, reference, left=0.0, right=0.0)

    df = pd.DataFrame({"time_s": t, "reference": reference, "response": response})

    estimated_lag_s = estimate_signal_lag_s(
        df,
        reference_col="reference",
        response_col="response",
        max_lag_s=0.5,
    )

    assert estimated_lag_s == pytest.approx(expected_delay_s, abs=1.0 / sample_rate_hz)
