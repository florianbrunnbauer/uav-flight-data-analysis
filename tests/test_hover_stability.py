import numpy as np
import pandas as pd
import pytest

from analysis import compute_hover_stability, compute_hover_stability_for_segment


def test_compute_hover_stability_returns_none_when_no_hover_phase_exists():
    position = pd.DataFrame({
        "time_s": [0.0, 1.0],
        "flight_phase": ["ground", "ground"],
    })
    attitude = pd.DataFrame({
        "time_s": [0.0, 1.0],
        "roll_deg": [0.0, 0.0],
        "pitch_deg": [0.0, 0.0],
    })

    assert compute_hover_stability(position, attitude) is None


def test_compute_hover_stability_basic_metrics():
    position = pd.DataFrame({
        "time_s": [0.0, 1.0, 2.0, 3.0],
        "flight_phase": ["hover"] * 4,
        "x": [-0.1, 0.1, -0.1, 0.1],
        "y": [0.0, 0.0, 0.0, 0.0],
        "altitude_m": [1.0, 1.1, 0.9, 1.0],
        "horizontal_speed_m_s": [0.05, 0.05, 0.05, 0.05],
        "dt_s": [1.0, 1.0, 1.0, 1.0],
    })
    attitude = pd.DataFrame({
        "time_s": [0.0, 1.0, 2.0, 3.0],
        "roll_deg": [0.0, 1.0, 2.0, 3.0],
        "pitch_deg": [0.0, 0.0, 0.0, 0.0],
    })

    metrics = compute_hover_stability(position, attitude)

    assert metrics["hover_time_s"] == pytest.approx(4.0)
    assert metrics["altitude_range_m"] == pytest.approx(0.2)
    assert metrics["max_drift_m"] == pytest.approx(0.1)
    assert metrics["avg_ground_speed_m_s"] == pytest.approx(0.05)
    assert metrics["roll_std_deg"] == pytest.approx(pd.Series([0.0, 1.0, 2.0, 3.0]).std())


def test_compute_hover_stability_for_segment_reports_cm_metrics_and_unwrapped_yaw():
    position = pd.DataFrame({
        "time_s": [0.0, 1.0, 2.0, 3.0],
        "x": [-0.1, 0.1, -0.1, 0.1],
        "y": [0.0, 0.0, 0.0, 0.0],
        "altitude_m": [1.0, 1.1, 0.9, 1.0],
        "horizontal_speed_m_s": [0.05, 0.05, 0.05, 0.05],
        "vertical_speed_m_s": [0.0, 0.0, 0.0, 0.0],
    })
    attitude = pd.DataFrame({
        "time_s": [0.0, 1.0, 2.0, 3.0],
        "roll_deg": [0.0, 1.0, 2.0, 3.0],
        "pitch_deg": [0.0, 0.0, 0.0, 0.0],
        "yaw_deg": [179.0, -179.0, -178.0, -177.0],
    })

    metrics, hover_df, hover_attitude_df = compute_hover_stability_for_segment(
        position,
        attitude,
        start_time=0.0,
        end_time=3.0,
    )

    assert metrics["duration_s"] == pytest.approx(4.0)
    assert metrics["mean_altitude_m"] == pytest.approx(1.0)
    assert metrics["altitude_rms_cm"] == pytest.approx(np.sqrt(50.0))
    assert metrics["max_drift_cm"] == pytest.approx(10.0)
    assert "altitude_drift_cm" in hover_df.columns
    assert "yaw_unwrapped_deg" in hover_attitude_df.columns
    assert metrics["yaw_range_deg"] == pytest.approx(4.0)
