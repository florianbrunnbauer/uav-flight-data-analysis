import pandas as pd
import pytest

from analysis import analyze_altitude, analyze_attitude, quaternion_to_euler
from tests.helpers import FakeLog, make_quaternion_from_axis_angle


def test_quaternion_to_euler_identity_quaternion():
    roll, pitch, yaw = quaternion_to_euler(1.0, 0.0, 0.0, 0.0)

    assert roll == pytest.approx(0.0)
    assert pitch == pytest.approx(0.0)
    assert yaw == pytest.approx(0.0)


@pytest.mark.parametrize(
    ("axis", "angle_deg", "expected_roll", "expected_pitch", "expected_yaw"),
    [
        ("roll", 90.0, 90.0, 0.0, 0.0),
        # Do not use exactly +90 deg pitch here: Euler angles are singular at
        # +/-90 deg pitch, so roll/yaw are not uniquely defined there.
        ("pitch", 45.0, 0.0, 45.0, 0.0),
        ("yaw", 90.0, 0.0, 0.0, 90.0),
    ],
)
def test_quaternion_to_euler_single_axis_rotation(
    axis: str,
    angle_deg: float,
    expected_roll: float,
    expected_pitch: float,
    expected_yaw: float,
):
    q = make_quaternion_from_axis_angle(axis, angle_deg)

    roll, pitch, yaw = quaternion_to_euler(*q)

    assert roll == pytest.approx(expected_roll, abs=1e-9)
    assert pitch == pytest.approx(expected_pitch, abs=1e-9)
    assert yaw == pytest.approx(expected_yaw, abs=1e-9)


def test_analyze_attitude_adds_roll_pitch_yaw_columns():
    q_yaw_90 = make_quaternion_from_axis_angle("yaw", 90.0)
    log = FakeLog({
        "vehicle_attitude": pd.DataFrame({
            "time_s": [0.0],
            "q[0]": [q_yaw_90[0]],
            "q[1]": [q_yaw_90[1]],
            "q[2]": [q_yaw_90[2]],
            "q[3]": [q_yaw_90[3]],
        })
    })

    result = analyze_attitude(log)

    assert {"roll_deg", "pitch_deg", "yaw_deg"}.issubset(result.columns)
    assert result.loc[0, "roll_deg"] == pytest.approx(0.0)
    assert result.loc[0, "pitch_deg"] == pytest.approx(0.0)
    assert result.loc[0, "yaw_deg"] == pytest.approx(90.0)


def test_analyze_altitude_converts_ned_z_to_positive_altitude():
    log = FakeLog({
        "vehicle_local_position": pd.DataFrame({
            "time_s": [0.0, 1.0, 2.0],
            "z": [0.0, -10.0, -20.0],
        })
    })

    altitude_df, metrics = analyze_altitude(log)

    assert altitude_df["altitude_m"].tolist() == [0.0, 10.0, 20.0]
    assert metrics["max_altitude_m"] == pytest.approx(20.0)
    assert metrics["min_altitude_m"] == pytest.approx(0.0)
    assert metrics["altitude_range_m"] == pytest.approx(20.0)
    assert metrics["mean_altitude_m"] == pytest.approx(10.0)
