import numpy as np
import pandas as pd
import pytest

from analysis import analyze_actuator_outputs
from tests.helpers import FakeLog


def test_analyze_actuator_outputs_detects_active_outputs_and_summary_metrics():
    actuator_df = pd.DataFrame({
        "time_s": [0.0, 1.0, 2.0],
        "output[0]": [1000.0, 1100.0, 1200.0],
        "output[1]": [1000.0, 1000.0, 1000.0],  # constant, should not be active
        "output[2]": [900.0, 950.0, 1000.0],
    })
    log = FakeLog({"actuator_outputs": actuator_df})

    result_df, metrics, active_indices = analyze_actuator_outputs(log)

    assert active_indices == [0, 2]
    assert result_df["mean_motor_output"].tolist() == [950.0, 1025.0, 1100.0]
    assert result_df["motor_output_spread"].tolist() == [100.0, 150.0, 200.0]
    assert metrics["mean_motor_output"] == pytest.approx(np.mean([950.0, 1025.0, 1100.0]))
    assert metrics["max_motor_output"] == pytest.approx(1200.0)
    assert metrics["max_motor_output_spread"] == pytest.approx(200.0)
    assert metrics["mean_abs_motor_output_rate"] == pytest.approx(75.0)
    assert metrics["max_abs_motor_output_rate"] == pytest.approx(100.0)
