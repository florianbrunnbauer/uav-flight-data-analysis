import numpy as np
import pandas as pd
import pytest

from analysis import analyze_position, classify_flight_state, smooth_flight_phases
from tests.helpers import FakeLog


@pytest.mark.parametrize(
    ("vh", "vz", "altitude", "expected_phase"),
    [
        (0.0, 0.0, 0.49, "ground"),
        (0.10, 0.0, 2.0, "hover"),
        (0.50, 0.0, 2.0, "strolling"),
        (1.50, 0.0, 2.0, "cruising"),
        (0.50, 0.30, 2.0, "shallow_stationary_ascend"),
        (1.50, 0.30, 2.0, "shallow_moving_ascend"),
        (0.50, 0.70, 2.0, "rapid_stationary_ascend"),
        (1.50, 0.70, 2.0, "rapid_moving_ascend"),
        (0.50, -0.30, 2.0, "shallow_stationary_descend"),
        (1.50, -0.30, 2.0, "shallow_moving_descend"),
        (0.50, -0.70, 2.0, "rapid_stationary_descend"),
        (1.50, -0.70, 2.0, "rapid_moving_descend"),
    ],
)
def test_classify_flight_state_threshold_cases(vh, vz, altitude, expected_phase):
    assert classify_flight_state(vh=vh, vz=vz, altitude=altitude) == expected_phase


def test_smooth_flight_phases_rejects_short_transient_phase():
    raw_phases = ["ground"] * 10 + ["hover"] * 2 + ["cruising"] * 10

    smoothed = smooth_flight_phases(raw_phases, min_consecutive_samples=5)

    assert smoothed[:12] == ["ground"] * 12
    assert smoothed[12:] == ["cruising"] * 10


def test_analyze_position_adds_derived_motion_and_phase_columns():
    df = pd.DataFrame({
        "time_s": np.arange(20, dtype=float),
        "x": np.zeros(20),
        "y": np.zeros(20),
        "z": [-0.1] * 10 + [-2.0] * 10,
        "vx": np.zeros(20),
        "vy": np.zeros(20),
        "vz": np.zeros(20),
        "ax": np.zeros(20),
        "ay": np.zeros(20),
        "az": np.zeros(20),
    })
    log = FakeLog({"vehicle_local_position": df})

    result = analyze_position(log)

    assert result.loc[0, "altitude_m"] == pytest.approx(0.1)
    assert result.loc[10, "altitude_m"] == pytest.approx(2.0)
    assert result["horizontal_speed_m_s"].max() == pytest.approx(0.0)
    assert result["vertical_speed_m_s"].max() == pytest.approx(0.0)
    assert result["az_up_m_s2"].max() == pytest.approx(0.0)
    assert result["flight_phase"].iloc[:10].eq("ground").all()
    assert result["flight_phase"].iloc[10:].eq("hover").all()
