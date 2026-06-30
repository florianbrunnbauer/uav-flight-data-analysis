import numpy as np
import pandas as pd
import pytest

from analysis import low_pass_filter_signal


def test_low_pass_filter_step_response_uses_actual_time_spacing():
    time_s = pd.Series([0.0, 1.0])
    signal = pd.Series([0.0, 10.0])

    filtered = low_pass_filter_signal(time_s, signal, cutoff_hz=1.0)

    tau_s = 1.0 / (2.0 * np.pi * 1.0)
    alpha = 1.0 / (tau_s + 1.0)
    expected_second_value = alpha * 10.0

    assert filtered.iloc[0] == pytest.approx(0.0)
    assert filtered.iloc[1] == pytest.approx(expected_second_value)


def test_low_pass_filter_invalid_cutoff_returns_original_signal():
    signal = pd.Series([1.0, 2.0, 3.0])
    filtered = low_pass_filter_signal([0.0, 1.0, 2.0], signal, cutoff_hz=0.0)

    pd.testing.assert_series_equal(filtered, signal.astype("float64"))


def test_low_pass_filter_rejects_length_mismatch():
    with pytest.raises(ValueError):
        low_pass_filter_signal([0.0, 1.0], [1.0], cutoff_hz=1.0)
