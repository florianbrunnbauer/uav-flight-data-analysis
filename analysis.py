import numpy as np
import pandas as pd

from ulg_reader import UlgReader
from typing import Any


DEFAULT_SETPOINT_LOW_PASS_CUTOFF_HZ = 2.0


def remove_empty_columns(df: pd.DataFrame, treat_empty_strings_as_empty: bool = True) -> pd.DataFrame:
    """
    Remove columns from a DataFrame that contain no usable values.

    A column is considered empty if all values are NaN.
    If treat_empty_strings_as_empty=True, empty strings and whitespace-only
    strings are also treated as missing values.

    Returns a copy of the DataFrame with empty columns removed.
    """

    cleaned_df = df.copy()

    if treat_empty_strings_as_empty:
        cleaned_df = cleaned_df.replace(r"^\s*$", np.nan, regex=True)

    empty_columns = cleaned_df.columns[cleaned_df.isna().all()].tolist()

    return cleaned_df.drop(columns=empty_columns)


def low_pass_filter_signal(
    time_s: pd.Series | np.ndarray,
    signal: pd.Series | np.ndarray,
    cutoff_hz: float = DEFAULT_SETPOINT_LOW_PASS_CUTOFF_HZ,
) -> pd.Series:
    """Apply a first-order causal low-pass filter to a sampled signal.

    The filter uses the actual sample spacing in ``time_s``. NaN samples remain
    NaN in the output and do not update the filter state.
    """
    signal_series = pd.Series(signal, dtype="float64")
    time_series = pd.Series(time_s, dtype="float64")

    if len(signal_series) != len(time_series):
        raise ValueError("time_s and signal must have the same length")

    if cutoff_hz is None or pd.isna(cutoff_hz) or cutoff_hz <= 0:
        return signal_series.copy()

    tau_s = 1.0 / (2.0 * np.pi * float(cutoff_hz))
    filtered = np.full(len(signal_series), np.nan, dtype=float)

    last_filtered = np.nan
    last_time = np.nan

    for i, (current_time, current_value) in enumerate(
        zip(time_series.to_numpy(), signal_series.to_numpy())
    ):
        if not np.isfinite(current_time) or not np.isfinite(current_value):
            continue

        if not np.isfinite(last_filtered) or not np.isfinite(last_time):
            current_filtered = current_value
        else:
            dt_s = current_time - last_time
            if not np.isfinite(dt_s) or dt_s <= 0:
                current_filtered = current_value
            else:
                alpha = dt_s / (tau_s + dt_s)
                current_filtered = last_filtered + alpha * (current_value - last_filtered)

        filtered[i] = current_filtered
        last_filtered = current_filtered
        last_time = current_time

    return pd.Series(filtered, index=signal_series.index)


def unwrap_angle_deg(angle_deg: pd.Series | np.ndarray) -> pd.Series:
    """Unwrap an angle signal expressed in degrees."""
    angle_series = pd.Series(angle_deg, dtype="float64")
    values = angle_series.to_numpy()
    unwrapped = np.full(len(angle_series), np.nan, dtype=float)
    valid = np.isfinite(values)

    if valid.any():
        unwrapped[valid] = np.rad2deg(np.unwrap(np.deg2rad(values[valid])))

    return pd.Series(unwrapped, index=angle_series.index)


def wrap_angle_deg(angle_deg: pd.Series | np.ndarray) -> pd.Series:
    """Wrap an angle to the range [-180, 180] deg."""
    return ((pd.Series(angle_deg, dtype="float64") + 180.0) % 360.0) - 180.0


def add_low_pass_filtered_setpoint(
    df: pd.DataFrame,
    source_col: str,
    output_col: str,
    cutoff_hz: float = DEFAULT_SETPOINT_LOW_PASS_CUTOFF_HZ,
    time_col: str = "time_s",
    angle_deg: bool = False,
) -> pd.DataFrame:
    """Add a filtered copy of a setpoint column to ``df``."""
    result = df.copy()

    if source_col not in result.columns or time_col not in result.columns:
        result[output_col] = np.nan
        return result

    signal = result[source_col]
    if angle_deg:
        signal = unwrap_angle_deg(signal)

    filtered = low_pass_filter_signal(result[time_col], signal, cutoff_hz)

    if angle_deg:
        filtered = wrap_angle_deg(filtered)

    result[output_col] = filtered
    return result


def quaternion_to_euler(w, x, y, z):
    roll = np.arctan2(
        2 * (w * x + y * z),
        1 - 2 * (x**2 + y**2)
    )

    pitch = np.arcsin(
        np.clip(2 * (w * y - z * x), -1.0, 1.0)
    )

    yaw = np.arctan2(
        2 * (w * z + x * y),
        1 - 2 * (y**2 + z**2)
    )

    return np.degrees(roll), np.degrees(pitch), np.degrees(yaw)


def analyze_altitude(log:UlgReader):
    df:pd.DataFrame = log.get_topic("vehicle_local_position").copy()

    # PX4 local position uses NED coordinates.
    # z is positive downward, so altitude is -z.
    df["altitude_m"] = -df["z"]

    metrics = {
        "max_altitude_m": df["altitude_m"].max(),
        "min_altitude_m": df["altitude_m"].min(),
        "altitude_range_m": df["altitude_m"].max() - df["altitude_m"].min(),
        "mean_altitude_m": df["altitude_m"].mean(),
    }

    return df, metrics


def analyze_attitude(log:UlgReader):
    df = log.get_topic("vehicle_attitude").copy()

    # PX4 vehicle_attitude quaternion is usually q[0], q[1], q[2], q[3]
    df["roll_deg"], df["pitch_deg"], df["yaw_deg"] = quaternion_to_euler(
        df["q[0]"],
        df["q[1]"],
        df["q[2]"],
        df["q[3]"],
    )

    return df


def smooth_flight_phases(raw_phases, min_consecutive_samples):
    raw_phases = pd.Series(raw_phases).reset_index(drop=True)

    smoothed = []
    current_phase = raw_phases.iloc[0]

    i = 0

    while i < len(raw_phases):
        candidate_phase = raw_phases.iloc[i]

        j = i
        while j < len(raw_phases) and raw_phases.iloc[j] == candidate_phase:
            j += 1

        run_length = j - i

        if run_length >= min_consecutive_samples:
            current_phase = candidate_phase

        smoothed.extend([current_phase] * run_length)

        i = j

    return smoothed


def classify_flight_state(vh, vz, altitude):

    climbrate_description = ["shallow","rapid"]
    movement_description = ["stationary","moving"]
    climb_phases = ["ascend","descend"]

    ground_altitude_threshold = 0.5
    hover_vh_threshold = 0.35
    movement_vh_threshold = 1.0
    hover_vz_threshold = 0.2
    rapid_vz_threshold = 0.5

    if altitude < ground_altitude_threshold:
        return "ground"
    
    elif abs(vz) <= hover_vz_threshold:

        if vh < hover_vh_threshold:
            return "hover"

        elif vh < movement_vh_threshold:
            return "strolling"

        else:
            return "cruising"

    elif vz > 0:

        if vz <= rapid_vz_threshold:

            if vh < movement_vh_threshold:
                return f"{climbrate_description[0]}_{movement_description[0]}_{climb_phases[0]}"
            else:
                return f"{climbrate_description[0]}_{movement_description[1]}_{climb_phases[0]}"

        else:

            if vh < movement_vh_threshold:
                return f"{climbrate_description[1]}_{movement_description[0]}_{climb_phases[0]}"
            else:
                return f"{climbrate_description[1]}_{movement_description[1]}_{climb_phases[0]}"

    else:

        if vz >= -rapid_vz_threshold:

            if vh < movement_vh_threshold:
                return f"{climbrate_description[0]}_{movement_description[0]}_{climb_phases[1]}"
            else:
                return f"{climbrate_description[0]}_{movement_description[1]}_{climb_phases[1]}"

        else:

            if vh < movement_vh_threshold:
                return f"{climbrate_description[1]}_{movement_description[0]}_{climb_phases[1]}"
            else:
                return f"{climbrate_description[1]}_{movement_description[1]}_{climb_phases[1]}"


def analyze_position(log:UlgReader):

    df = log.get_topic("vehicle_local_position").copy()

    df["altitude_m"] = -df["z"]

    df["speed_m_s"] = np.sqrt(df["vx"]**2 + df["vy"]**2 + df["vz"]**2)

    df["horizontal_speed_m_s"] = np.sqrt(df["vx"]**2 + df["vy"]**2)

    df["vertical_speed_m_s"] = -df["vz"]

    df["distance_from_home_m"] = np.sqrt(df["x"]**2 + df["y"]**2)

    df["az_up_m_s2"] = -df["az"]

    # -------------------------------------------------
    # Flight phase detection
    # -------------------------------------------------

    df["flight_phase_raw"] = [
        classify_flight_state(vh, vz, altitude)
        for vh, vz, altitude in zip(
            df["horizontal_speed_m_s"],
            df["vertical_speed_m_s"],
            df["altitude_m"]
        )
    ]

    df["flight_phase"] = smooth_flight_phases(
        df["flight_phase_raw"],
        min_consecutive_samples=10
    )

    return df


def compute_flight_statistics(position,attitude):
    dx = position["x"].diff()
    dy = position["y"].diff()
    dz = position["z"].diff()

    distance_step = np.sqrt(dx**2 + dy**2 + dz**2)

    stats = {
    "flight_time_s": position["time_s"].max(),
    "max_altitude_m": position["altitude_m"].max(),
    "max_abs_speed_m_s": position["speed_m_s"].max(),
    "max_distance_from_home_m": position["distance_from_home_m"].max(),
    "distance_traveled_m": distance_step.sum(),
    "max_roll_deg": attitude["roll_deg"].abs().max(),
    "max_pitch_deg": attitude["pitch_deg"].abs().max(),
    "max_climb_rate_m_s": position["vertical_speed_m_s"].max(),
    "max_descent_rate_m_s": abs(position["vertical_speed_m_s"].min()),
    "avg_ground_speed_m_s": position["horizontal_speed_m_s"].mean(),
    "max_ground_speed_m_s": position["horizontal_speed_m_s"].max(),
    
    }

    return stats


def compute_phase_statistics(position:pd.DataFrame):

    df = position.copy()

    df["dt_s"] = df["time_s"].diff().shift(-1)

    # Last sample has no following timestamp.
    # Use median dt as a reasonable approximation.
    df["dt_s"] = df["dt_s"].fillna(df["dt_s"].median())

    total_time_s = df["dt_s"].sum()

    phase_stats = []

    for phase, phase_df in df.groupby("flight_phase"):

        duration_s = phase_df["dt_s"].sum()

        phase_stats.append({
            "phase": phase,
            "duration_s": duration_s,
            "duration_percent": duration_s / total_time_s * 100,
            "samples": len(phase_df),
            "avg_altitude_m": phase_df["altitude_m"].mean(),
            "max_altitude_m": phase_df["altitude_m"].max(),
            "avg_ground_speed_m_s": phase_df["horizontal_speed_m_s"].mean(),
            "max_ground_speed_m_s": phase_df["horizontal_speed_m_s"].max(),
            "avg_vertical_speed_m_s": phase_df["vertical_speed_m_s"].mean(),
            "max_climb_rate_m_s": phase_df["vertical_speed_m_s"].max(),
            "max_descent_rate_m_s": phase_df["vertical_speed_m_s"].min(),
        })

    return pd.DataFrame(phase_stats).sort_values(
        "duration_s",
        ascending=False
    )


def compute_hover_stability(position, attitude):
    hover = position[position["flight_phase"] == "hover"].copy()

    if hover.empty:
        return None

    # Match attitude to position timestamps approximately
    attitude_interp = pd.DataFrame({
        "time_s": hover["time_s"],
        "roll_deg": np.interp(
            hover["time_s"],
            attitude["time_s"],
            attitude["roll_deg"]
        ),
        "pitch_deg": np.interp(
            hover["time_s"],
            attitude["time_s"],
            attitude["pitch_deg"]
        ),
    })

    hover_center_x = hover["x"].mean()
    hover_center_y = hover["y"].mean()

    hover["drift_from_hover_center_m"] = np.sqrt(
        (hover["x"] - hover_center_x) ** 2 +
        (hover["y"] - hover_center_y) ** 2
    )

    metrics = {
        "hover_time_s": hover["dt_s"].sum() if "dt_s" in hover else len(hover) * hover["time_s"].diff().median(),
        "altitude_std_m": hover["altitude_m"].std(),
        "altitude_range_m": hover["altitude_m"].max() - hover["altitude_m"].min(),
        "horizontal_drift_std_m": hover["drift_from_hover_center_m"].std(),
        "max_drift_m": hover["drift_from_hover_center_m"].max(),
        "avg_ground_speed_m_s": hover["horizontal_speed_m_s"].mean(),
        "max_ground_speed_m_s": hover["horizontal_speed_m_s"].max(),
        "roll_std_deg": attitude_interp["roll_deg"].std(),
        "pitch_std_deg": attitude_interp["pitch_deg"].std(),
    }

    return metrics


def compute_hover_stability_for_segment(position: pd.DataFrame, attitude: pd.DataFrame, start_time: float, end_time: float):
    hover: pd.DataFrame = position[
        (position["time_s"] >= start_time) &
        (position["time_s"] <= end_time)
    ].copy()

    if hover.empty:
        return None

    # Match attitude to position timestamps approximately.
    # Yaw is unwrapped before statistics are calculated so that crossing +/-180 deg
    # does not create artificial yaw jumps.
    attitude_interp: pd.DataFrame = pd.DataFrame({
        "time_s": hover["time_s"],
        "roll_deg": np.interp(
            hover["time_s"],
            attitude["time_s"],
            attitude["roll_deg"],
        ),
        "pitch_deg": np.interp(
            hover["time_s"],
            attitude["time_s"],
            attitude["pitch_deg"],
        ),
        "yaw_deg": np.interp(
            hover["time_s"],
            attitude["time_s"],
            attitude["yaw_deg"],
        ),
    })

    attitude_interp["yaw_unwrapped_deg"] = np.rad2deg(
        np.unwrap(np.deg2rad(attitude_interp["yaw_deg"]))
    )

    attitude_interp["yaw_drift_deg"] = (
        attitude_interp["yaw_unwrapped_deg"] -
        attitude_interp["yaw_unwrapped_deg"].mean()
    )

    dt = hover["time_s"].diff().shift(-1)
    dt = dt.fillna(dt.median())
    hover["dt_s"] = dt

    center_x = hover["x"].mean()
    center_y = hover["y"].mean()
    mean_altitude = hover["altitude_m"].mean()

    # Position errors are expressed in centimeters for hover-stability reporting.
    hover["x_error_cm"] = (hover["x"] - center_x) * 100
    hover["y_error_cm"] = (hover["y"] - center_y) * 100
    hover["drift_from_center_cm"] = np.sqrt(
        hover["x_error_cm"] ** 2 +
        hover["y_error_cm"] ** 2
    )

    hover["altitude_drift_cm"] = (hover["altitude_m"] - mean_altitude) * 100

    abs_altitude_drift_cm = hover["altitude_drift_cm"].abs()

    return {
        "duration_s": hover["dt_s"].sum(),
        "mean_altitude_m": mean_altitude,

        # Vertical stability
        "altitude_std_cm": hover["altitude_drift_cm"].std(),
        "altitude_rms_cm": np.sqrt(np.mean(hover["altitude_drift_cm"] ** 2)),
        "altitude_p95_abs_cm": abs_altitude_drift_cm.quantile(0.95),
        "altitude_p99_abs_cm": abs_altitude_drift_cm.quantile(0.99),
        "altitude_range_cm": hover["altitude_drift_cm"].max() - hover["altitude_drift_cm"].min(),

        # Horizontal position stability
        "max_drift_cm": hover["drift_from_center_cm"].max(),
        "rms_drift_cm": np.sqrt(np.mean(hover["drift_from_center_cm"] ** 2)),
        "drift_p95_cm": hover["drift_from_center_cm"].quantile(0.95),
        "drift_p99_cm": hover["drift_from_center_cm"].quantile(0.99),
        "drift_std_cm": hover["drift_from_center_cm"].std(),

        # Velocity stability
        "avg_ground_speed_m_s": hover["horizontal_speed_m_s"].mean(),
        "max_ground_speed_m_s": hover["horizontal_speed_m_s"].max(),

        # Attitude stability
        "mean_roll_deg": attitude_interp["roll_deg"].mean(),
        "mean_pitch_deg": attitude_interp["pitch_deg"].mean(),
        "mean_yaw_deg": attitude_interp["yaw_unwrapped_deg"].mean(),
        "roll_std_deg": attitude_interp["roll_deg"].std(),
        "pitch_std_deg": attitude_interp["pitch_deg"].std(),
        "yaw_std_deg": attitude_interp["yaw_unwrapped_deg"].std(),
        "yaw_range_deg": attitude_interp["yaw_unwrapped_deg"].max() - attitude_interp["yaw_unwrapped_deg"].min(),
        "max_abs_roll_deg": attitude_interp["roll_deg"].abs().max(),
        "max_abs_pitch_deg": attitude_interp["pitch_deg"].abs().max(),
        "max_abs_yaw_drift_deg": attitude_interp["yaw_drift_deg"].abs().max(),
    }, hover, attitude_interp


def analyze_actuator_outputs(log:UlgReader) -> tuple[pd.DataFrame, dict[str, Any], list[int]]:
    df:pd.DataFrame = log.get_topic("actuator_outputs").copy()

    active_output_indices = []

    for i in range(16):
        col = f"output[{i}]"

        if col not in df.columns:
            continue

        signal = df[col].dropna()

        if signal.empty:
            continue

        if signal.max() > 0 and signal.std() > 0:
            active_output_indices.append(i)

    motor_cols = [f"output[{i}]" for i in active_output_indices]

    df["mean_motor_output"] = df[motor_cols].mean(axis=1)
    df["min_motor_output"] = df[motor_cols].min(axis=1)
    df["max_motor_output"] = df[motor_cols].max(axis=1)

    df["motor_output_spread"] = (
        df["max_motor_output"] - df["min_motor_output"]
    )

    df["dt_s"] = df["time_s"].diff()

    for col in motor_cols:
        df[f"{col}_rate"] = df[col].diff() / df["dt_s"]
    
    rate_cols = [f"{col}_rate" for col in motor_cols]
    
    df["mean_abs_motor_output_rate"] = df[rate_cols].abs().mean(axis=1)
    df["max_abs_motor_output_rate"] = df[rate_cols].abs().max(axis=1)

    metrics = {
        "max_motor_output_spread": df["motor_output_spread"].max(),
        "mean_motor_output_spread": df["motor_output_spread"].mean(),
        "p95_motor_output_spread": df["motor_output_spread"].quantile(0.95),
        "max_motor_output": df["max_motor_output"].max(),
        "mean_motor_output": df["mean_motor_output"].mean(),
        "mean_abs_motor_output_rate": df["mean_abs_motor_output_rate"].mean(),
        "p95_abs_motor_output_rate": df["mean_abs_motor_output_rate"].quantile(0.95),
        "max_abs_motor_output_rate": df["max_abs_motor_output_rate"].max(),
    }

    return df, metrics, active_output_indices


def analyze_body_rates(log:UlgReader):
    df:pd.DataFrame = log.get_topic("vehicle_angular_velocity").copy()

    df["roll_rate_deg_s"] = np.degrees(df["xyz[0]"])
    df["pitch_rate_deg_s"] = np.degrees(df["xyz[1]"])
    df["yaw_rate_deg_s"] = np.degrees(df["xyz[2]"])

    return df


def analyze_integrator_status(log:UlgReader):
    df:pd.DataFrame = log.get_topic("rate_ctrl_status").copy()

    return df


def compute_motor_pair_components(actuator_df: pd.DataFrame,pair_config: list[tuple[int, int]],) -> pd.DataFrame:

    df = actuator_df.copy()

    for pair_number, (motor_a, motor_b) in enumerate(pair_config, start=1):
        col_a = f"output[{motor_a}]"
        col_b = f"output[{motor_b}]"

        pair_name = f"pair_{pair_number}_{motor_a}_{motor_b}"

        df[f"{pair_name}_mean_output"] = (
            df[col_a] + df[col_b]
        ) / 2

        df[f"{pair_name}_difference"] = (
            df[col_a] - df[col_b]
        )

        df[f"{pair_name}_differential_output"] = (
            df[col_a] - df[col_b]
        ) / 2

        df[f"{pair_name}_abs_differential_output"] = (
            df[f"{pair_name}_differential_output"].abs()
        )

    return df


def wrap_angle_error_deg(error_deg: pd.Series | np.ndarray) -> pd.Series:
    """Wrap angular error to the range [-180, 180] deg."""
    return ((pd.Series(error_deg) + 180.0) % 360.0) - 180.0


def sanitize_time_offset_s(time_offset_s: float | None) -> float:
    """Return a finite time offset value for reporting and compensation."""
    if time_offset_s is None:
        return 0.0

    try:
        if pd.isna(time_offset_s) or not np.isfinite(time_offset_s):
            return 0.0
    except TypeError:
        return 0.0

    return float(time_offset_s)


def compute_tracking_error_metrics(
    df: pd.DataFrame,
    error_columns: dict[str, str],
    time_offsets_s: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Compute tracking-error summary metrics for named error columns."""
    rows = []
    time_offsets_s = time_offsets_s or {}

    for axis_name, error_col in error_columns.items():
        if error_col not in df.columns:
            continue

        time_offset_s = sanitize_time_offset_s(
            time_offsets_s.get(axis_name, 0.0)
        )

        error = df[error_col].dropna()

        if error.empty:
            rows.append({
                "axis": axis_name,
                "samples": 0,
                "time_offset_s": time_offset_s,
                "bias": np.nan,
                "mean_abs_error": np.nan,
                "rmse": np.nan,
                "p95_abs": np.nan,
                "max_abs": np.nan,
            })
            continue

        abs_error = error.abs()

        rows.append({
            "axis": axis_name,
            "samples": len(error),
            "time_offset_s": time_offset_s,
            "bias": error.mean(),
            "mean_abs_error": abs_error.mean(),
            "rmse": np.sqrt(np.mean(error ** 2)),
            "p95_abs": abs_error.quantile(0.95),
            "max_abs": abs_error.max(),
        })

    return pd.DataFrame(rows)


def estimate_signal_lag_s(df: pd.DataFrame,reference_col: str,response_col: str,time_col: str = "time_s",max_lag_s: float = 0.5) -> float:

    data = df[[time_col, reference_col, response_col]].dropna().copy()

    if len(data) < 10:
        return np.nan

    dt = data[time_col].diff().median()

    if pd.isna(dt) or dt <= 0:
        return np.nan

    max_lag_samples = int(max_lag_s / dt)

    reference = data[reference_col].to_numpy()
    response = data[response_col].to_numpy()

    # Remove offsets so correlation focuses on shape, not mean level.
    reference = reference - np.mean(reference)
    response = response - np.mean(response)

    correlations = []
    lags = range(-max_lag_samples, max_lag_samples + 1)

    for lag in lags:
        if lag < 0:
            ref_segment = reference[-lag:]
            resp_segment = response[:lag]
        elif lag > 0:
            ref_segment = reference[:-lag]
            resp_segment = response[lag:]
        else:
            ref_segment = reference
            resp_segment = response

        if len(ref_segment) < 10:
            correlations.append(np.nan)
            continue

        corr = np.corrcoef(ref_segment, resp_segment)[0, 1]
        correlations.append(corr)

    if np.all(pd.isna(correlations)):
        return np.nan

    best_lag_samples = list(lags)[int(np.nanargmax(correlations))]

    return best_lag_samples * dt


def add_lag_compensated_error(
    df: pd.DataFrame,
    reference_col: str,
    response_col: str,
    lag_s: float,
    output_col: str,
    unit_col: str | None = None,
    time_col: str = "time_s",
    angle_error_deg: bool = False,
) -> pd.DataFrame:

    result = df.copy()
    lag_s = sanitize_time_offset_s(lag_s)

    nominal_offset = f"{output_col}_time_compensated_setpoint_{unit_col}"
    error_offset = f"{output_col}_time_compensated_error_{unit_col}"

    # If actual response lags by lag_s:
    # actual(t) ≈ reference(t - lag_s)
    result[nominal_offset] = np.interp(
        result[time_col] - lag_s,
        result[time_col],
        result[reference_col],
        left=np.nan,
        right=np.nan,
    )

    error = result[nominal_offset] - result[response_col]
    if angle_error_deg:
        error = wrap_angle_error_deg(error)

    result[error_offset] = error

    return result


def analyze_rate_tracking(
    log: UlgReader,
    low_pass_cutoff_hz: float = DEFAULT_SETPOINT_LOW_PASS_CUTOFF_HZ,
) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    """
    Compare desired body-rate setpoints with measured body angular velocity.

    Returns None if the required setpoint topic is not available in the log.
    Rates are reported in deg/s for dashboard readability.
    """
    try:
        actual = log.get_topic("vehicle_angular_velocity").copy()
        setpoint = log.get_topic("vehicle_rates_setpoint").copy()
    except ValueError:
        return None

    actual = actual.sort_values("time_s")
    setpoint = setpoint.sort_values("time_s")

    actual_rates = pd.DataFrame({
        "time_s": actual["time_s"],
        "roll_rate_actual_deg_s": np.degrees(actual["xyz[0]"]),
        "pitch_rate_actual_deg_s": np.degrees(actual["xyz[1]"]),
        "yaw_rate_actual_deg_s": np.degrees(actual["xyz[2]"]),
    })

    required_setpoint_cols = ["roll", "pitch", "yaw"]
    if not all(col in setpoint.columns for col in required_setpoint_cols):
        return None

    setpoint_rates = pd.DataFrame({
        "time_s": setpoint["time_s"],
        "roll_rate_setpoint_deg_s": np.degrees(setpoint["roll"]),
        "pitch_rate_setpoint_deg_s": np.degrees(setpoint["pitch"]),
        "yaw_rate_setpoint_deg_s": np.degrees(setpoint["yaw"]),
    })

    for axis in ["roll", "pitch", "yaw"]:
        setpoint_rates = add_low_pass_filtered_setpoint(
            setpoint_rates,
            f"{axis}_rate_setpoint_deg_s",
            f"{axis}_rate_filtered_setpoint_deg_s",
            low_pass_cutoff_hz,
            "time_s",
        )

    df = pd.merge_asof(
        actual_rates,
        setpoint_rates,
        on="time_s",
        direction="nearest",
    )

    time_offsets_s = {}

    for axis in ["roll", "pitch", "yaw"]:
        actual_col = f"{axis}_rate_actual_deg_s"
        setpoint_col = f"{axis}_rate_setpoint_deg_s"
        filtered_setpoint_col = f"{axis}_rate_filtered_setpoint_deg_s"

        df[f"{axis}_rate_error_deg_s"] = (
            df[setpoint_col] -
            df[actual_col]
        )
        df[f"{axis}_rate_abs_error_deg_s"] = df[f"{axis}_rate_error_deg_s"].abs()

        df[f"{axis}_rate_filtered_error_deg_s"] = (
            df[filtered_setpoint_col] -
            df[actual_col]
        )
        df[f"{axis}_rate_filtered_abs_error_deg_s"] = df[f"{axis}_rate_filtered_error_deg_s"].abs()

        time_offset_s = estimate_signal_lag_s(df,setpoint_col,actual_col,"time_s",0.5)
        time_offset_s = sanitize_time_offset_s(time_offset_s)

        filtered_time_offset_s = estimate_signal_lag_s(
            df,
            filtered_setpoint_col,
            actual_col,
            "time_s",
            0.5,
        )
        filtered_time_offset_s = sanitize_time_offset_s(filtered_time_offset_s)

        time_offsets_s[axis] = 0.0
        time_offsets_s[f"{axis}_filtered"] = 0.0
        time_offsets_s[f"{axis}_time_compensated"] = time_offset_s
        time_offsets_s[f"{axis}_filtered_time_compensated"] = filtered_time_offset_s

        df = add_lag_compensated_error(
            df,
            setpoint_col,
            actual_col,
            time_offset_s,
            f"{axis}_rate",
            "deg_s",
            "time_s",
        )
        df = add_lag_compensated_error(
            df,
            filtered_setpoint_col,
            actual_col,
            filtered_time_offset_s,
            f"{axis}_rate_filtered",
            "deg_s",
            "time_s",
        )

    df["rate_error_magnitude_deg_s"] = np.sqrt(
        df["roll_rate_error_deg_s"] ** 2 +
        df["pitch_rate_error_deg_s"] ** 2 +
        df["yaw_rate_error_deg_s"] ** 2
    )

    df["rate_filtered_error_magnitude_deg_s"] = np.sqrt(
        df["roll_rate_filtered_error_deg_s"] ** 2 +
        df["pitch_rate_filtered_error_deg_s"] ** 2 +
        df["yaw_rate_filtered_error_deg_s"] ** 2
    )

    metrics = compute_tracking_error_metrics(
        df,
        {
            "roll": "roll_rate_error_deg_s",
            "pitch": "pitch_rate_error_deg_s",
            "yaw": "yaw_rate_error_deg_s",
            "roll_filtered": "roll_rate_filtered_error_deg_s",
            "pitch_filtered": "pitch_rate_filtered_error_deg_s",
            "yaw_filtered": "yaw_rate_filtered_error_deg_s",
            "roll_time_compensated": "roll_rate_time_compensated_error_deg_s",
            "pitch_time_compensated": "pitch_rate_time_compensated_error_deg_s",
            "yaw_time_compensated": "yaw_rate_time_compensated_error_deg_s",
            "roll_filtered_time_compensated": "roll_rate_filtered_time_compensated_error_deg_s",
            "pitch_filtered_time_compensated": "pitch_rate_filtered_time_compensated_error_deg_s",
            "yaw_filtered_time_compensated": "yaw_rate_filtered_time_compensated_error_deg_s",
        },
        time_offsets_s,
    )

    return df, metrics


def analyze_attitude_tracking(
    log: UlgReader,
    low_pass_cutoff_hz: float = DEFAULT_SETPOINT_LOW_PASS_CUTOFF_HZ,
) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    """
    Compare attitude setpoint with measured vehicle attitude.

    Returns None if vehicle_attitude_setpoint is unavailable or does not contain
    usable attitude-setpoint fields.
    """
    try:
        actual = analyze_attitude(log).copy()
        setpoint = log.get_topic("vehicle_attitude_setpoint").copy()
    except ValueError:
        return None

    actual = actual.sort_values("time_s")
    setpoint = setpoint.sort_values("time_s")

    actual_attitude = actual[["time_s", "roll_deg", "pitch_deg", "yaw_deg"]].rename(
        columns={
            "roll_deg": "roll_actual_deg",
            "pitch_deg": "pitch_actual_deg",
            "yaw_deg": "yaw_actual_deg",
        }
    )

    if all(f"q_d[{i}]" in setpoint.columns for i in range(4)):
        roll_sp, pitch_sp, yaw_sp = quaternion_to_euler(
            setpoint["q_d[0]"],
            setpoint["q_d[1]"],
            setpoint["q_d[2]"],
            setpoint["q_d[3]"],
        )
    elif all(col in setpoint.columns for col in ["roll_body", "pitch_body", "yaw_body"]):
        roll_sp = np.degrees(setpoint["roll_body"])
        pitch_sp = np.degrees(setpoint["pitch_body"])
        yaw_sp = np.degrees(setpoint["yaw_body"])
    else:
        return None

    setpoint_attitude = pd.DataFrame({
        "time_s": setpoint["time_s"],
        "roll_setpoint_deg": roll_sp,
        "pitch_setpoint_deg": pitch_sp,
        "yaw_setpoint_deg": yaw_sp,
    })

    for axis in ["roll", "pitch", "yaw"]:
        setpoint_attitude = add_low_pass_filtered_setpoint(
            setpoint_attitude,
            f"{axis}_setpoint_deg",
            f"{axis}_filtered_setpoint_deg",
            low_pass_cutoff_hz,
            "time_s",
            angle_deg=(axis == "yaw"),
        )

    df = pd.merge_asof(
        actual_attitude,
        setpoint_attitude,
        on="time_s",
        direction="nearest",
    )

    time_offsets_s = {}

    df["roll_error_deg"] = df["roll_setpoint_deg"] - df["roll_actual_deg"]
    df["pitch_error_deg"] = df["pitch_setpoint_deg"] - df["pitch_actual_deg"]
    df["yaw_error_deg"] = wrap_angle_error_deg(
        df["yaw_setpoint_deg"] - df["yaw_actual_deg"]
    )

    df["roll_filtered_error_deg"] = df["roll_filtered_setpoint_deg"] - df["roll_actual_deg"]
    df["pitch_filtered_error_deg"] = df["pitch_filtered_setpoint_deg"] - df["pitch_actual_deg"]
    df["yaw_filtered_error_deg"] = wrap_angle_error_deg(
        df["yaw_filtered_setpoint_deg"] - df["yaw_actual_deg"]
    )

    for axis in ["roll", "pitch", "yaw"]:

        actual_col = f"{axis}_actual_deg"
        setpoint_col = f"{axis}_setpoint_deg"
        filtered_setpoint_col = f"{axis}_filtered_setpoint_deg"

        df[f"{axis}_abs_error_deg"] = df[f"{axis}_error_deg"].abs()
        df[f"{axis}_filtered_abs_error_deg"] = df[f"{axis}_filtered_error_deg"].abs()

        time_offset_s = estimate_signal_lag_s(df,setpoint_col,actual_col,"time_s",0.5)
        time_offset_s = sanitize_time_offset_s(time_offset_s)
        filtered_time_offset_s = estimate_signal_lag_s(
            df,
            filtered_setpoint_col,
            actual_col,
            "time_s",
            0.5,
        )
        filtered_time_offset_s = sanitize_time_offset_s(filtered_time_offset_s)

        time_offsets_s[axis] = 0.0
        time_offsets_s[f"{axis}_filtered"] = 0.0
        time_offsets_s[f"{axis}_time_compensated"] = time_offset_s
        time_offsets_s[f"{axis}_filtered_time_compensated"] = filtered_time_offset_s

        df = add_lag_compensated_error(
            df,
            setpoint_col,
            actual_col,
            time_offset_s,
            f"{axis}",
            "deg",
            "time_s",
            angle_error_deg=(axis == "yaw"),
        )
        df = add_lag_compensated_error(
            df,
            filtered_setpoint_col,
            actual_col,
            filtered_time_offset_s,
            f"{axis}_filtered",
            "deg",
            "time_s",
            angle_error_deg=(axis == "yaw"),
        )

    df["attitude_error_magnitude_deg"] = np.sqrt(
        df["roll_error_deg"] ** 2 +
        df["pitch_error_deg"] ** 2 +
        df["yaw_error_deg"] ** 2
    )

    df["attitude_filtered_error_magnitude_deg"] = np.sqrt(
        df["roll_filtered_error_deg"] ** 2 +
        df["pitch_filtered_error_deg"] ** 2 +
        df["yaw_filtered_error_deg"] ** 2
    )

    metrics = compute_tracking_error_metrics(
        df,
        {
            "roll": "roll_error_deg",
            "pitch": "pitch_error_deg",
            "yaw": "yaw_error_deg",
            "roll_filtered": "roll_filtered_error_deg",
            "pitch_filtered": "pitch_filtered_error_deg",
            "yaw_filtered": "yaw_filtered_error_deg",
            "roll_time_compensated": "roll_time_compensated_error_deg",
            "pitch_time_compensated": "pitch_time_compensated_error_deg",
            "yaw_time_compensated": "yaw_time_compensated_error_deg",
            "roll_filtered_time_compensated": "roll_filtered_time_compensated_error_deg",
            "pitch_filtered_time_compensated": "pitch_filtered_time_compensated_error_deg",
            "yaw_filtered_time_compensated": "yaw_filtered_time_compensated_error_deg",
        },
        time_offsets_s,
    )

    return df, metrics


def analyze_trajectory_tracking(
    log: UlgReader,
    low_pass_cutoff_hz: float = DEFAULT_SETPOINT_LOW_PASS_CUTOFF_HZ,
) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    """
    Compare trajectory setpoints with local-position estimates where available.

    Supports position and velocity setpoint fields that are present and finite in
    trajectory_setpoint. Returns None if the topic is unavailable.
    """
    try:
        position = analyze_position(log).copy()
        setpoint = log.get_topic("trajectory_setpoint").copy()
    except ValueError:
        return None

    position = position.sort_values("time_s")
    setpoint = setpoint.sort_values("time_s")

    base_cols = [
        "time_s", "x", "y", "z", "vx", "vy", "vz",
        "altitude_m", "vertical_speed_m_s",
    ]
    available_base_cols = [col for col in base_cols if col in position.columns]
    actual = position[available_base_cols].copy()

    rename_map = {
        "x": "x_actual_m",
        "y": "y_actual_m",
        "z": "z_actual_m",
        "vx": "vx_actual_m_s",
        "vy": "vy_actual_m_s",
        "vz": "vz_actual_m_s",
        "altitude_m": "altitude_actual_m",
        "vertical_speed_m_s": "vertical_speed_actual_m_s",
    }
    actual = actual.rename(columns=rename_map)

    setpoint_df = pd.DataFrame({"time_s": setpoint["time_s"]})

    if "x" in setpoint.columns:
        setpoint_df["x_setpoint_m"] = setpoint["x"]
        setpoint_df = add_low_pass_filtered_setpoint(
            setpoint_df,
            "x_setpoint_m",
            "x_filtered_setpoint_m",
            low_pass_cutoff_hz,
        )
    if "y" in setpoint.columns:
        setpoint_df["y_setpoint_m"] = setpoint["y"]
        setpoint_df = add_low_pass_filtered_setpoint(
            setpoint_df,
            "y_setpoint_m",
            "y_filtered_setpoint_m",
            low_pass_cutoff_hz,
        )
    if "z" in setpoint.columns:
        setpoint_df["z_setpoint_m"] = setpoint["z"]
        setpoint_df["altitude_setpoint_m"] = -setpoint["z"]
        setpoint_df = add_low_pass_filtered_setpoint(
            setpoint_df,
            "z_setpoint_m",
            "z_filtered_setpoint_m",
            low_pass_cutoff_hz,
        )
        setpoint_df["altitude_filtered_setpoint_m"] = -setpoint_df["z_filtered_setpoint_m"]
    if "vx" in setpoint.columns:
        setpoint_df["vx_setpoint_m_s"] = setpoint["vx"]
        setpoint_df = add_low_pass_filtered_setpoint(
            setpoint_df,
            "vx_setpoint_m_s",
            "vx_filtered_setpoint_m_s",
            low_pass_cutoff_hz,
        )
    if "vy" in setpoint.columns:
        setpoint_df["vy_setpoint_m_s"] = setpoint["vy"]
        setpoint_df = add_low_pass_filtered_setpoint(
            setpoint_df,
            "vy_setpoint_m_s",
            "vy_filtered_setpoint_m_s",
            low_pass_cutoff_hz,
        )
    if "vz" in setpoint.columns:
        setpoint_df["vz_setpoint_m_s"] = setpoint["vz"]
        setpoint_df["vertical_speed_setpoint_m_s"] = -setpoint["vz"]
        setpoint_df = add_low_pass_filtered_setpoint(
            setpoint_df,
            "vz_setpoint_m_s",
            "vz_filtered_setpoint_m_s",
            low_pass_cutoff_hz,
        )
        setpoint_df["vertical_speed_filtered_setpoint_m_s"] = -setpoint_df["vz_filtered_setpoint_m_s"]

    df = pd.merge_asof(
        actual,
        setpoint_df,
        on="time_s",
        direction="nearest",
    )

    error_columns = {}
    time_offsets_s = {}

    for axis in ["x", "y", "z"]:
        actual_col = f"{axis}_actual_m"
        setpoint_col = f"{axis}_setpoint_m"
        filtered_setpoint_col = f"{axis}_filtered_setpoint_m"
        if actual_col in df.columns and setpoint_col in df.columns:
            actual_col_no_nan = df[actual_col].dropna()
            setpoint_col_no_nan = df[setpoint_col].dropna()
            if not actual_col_no_nan.empty and not setpoint_col_no_nan.empty:
                error_col = f"{axis}_position_error_m"
                filtered_error_col = f"{axis}_position_filtered_error_m"
                metric_name = f"{axis}_position"
                filtered_metric_name = f"{axis}_position_filtered"

                df[error_col] = df[setpoint_col] - df[actual_col]
                error_columns[metric_name] = error_col
                time_offsets_s[metric_name] = 0.0

                if filtered_setpoint_col in df.columns:
                    df[filtered_error_col] = df[filtered_setpoint_col] - df[actual_col]
                    error_columns[filtered_metric_name] = filtered_error_col
                    time_offsets_s[filtered_metric_name] = 0.0

                    filtered_time_offset_s = estimate_signal_lag_s(
                        df,
                        filtered_setpoint_col,
                        actual_col,
                        "time_s",
                        0.5,
                    )
                    filtered_time_offset_s = sanitize_time_offset_s(filtered_time_offset_s)
                    filtered_time_compensated_metric_name = (
                        f"{metric_name}_filtered_time_compensated"
                    )
                    time_offsets_s[filtered_time_compensated_metric_name] = (
                        filtered_time_offset_s
                    )

                    df = add_lag_compensated_error(
                        df,
                        filtered_setpoint_col,
                        actual_col,
                        filtered_time_offset_s,
                        f"{axis}_position_filtered",
                        "m",
                        "time_s",
                    )
                    error_columns[filtered_time_compensated_metric_name] = (
                        f"{axis}_position_filtered_time_compensated_error_m"
                    )

    if "altitude_actual_m" in df.columns and "altitude_setpoint_m" in df.columns:

        actual_col_no_nan = df["altitude_actual_m"].dropna()
        setpoint_col_no_nan = df["altitude_setpoint_m"].dropna()

        if not actual_col_no_nan.empty and not setpoint_col_no_nan.empty:

            df["altitude_error_m"] = df["altitude_setpoint_m"] - df["altitude_actual_m"]
            error_columns["altitude"] = "altitude_error_m"
            time_offsets_s["altitude"] = 0.0

            if "altitude_filtered_setpoint_m" in df.columns:
                df["altitude_filtered_error_m"] = (
                    df["altitude_filtered_setpoint_m"] -
                    df["altitude_actual_m"]
                )
                error_columns["altitude_filtered"] = "altitude_filtered_error_m"
                time_offsets_s["altitude_filtered"] = 0.0

                filtered_time_offset_s = estimate_signal_lag_s(
                    df,
                    "altitude_filtered_setpoint_m",
                    "altitude_actual_m",
                    "time_s",
                    0.5,
                )
                filtered_time_offset_s = sanitize_time_offset_s(filtered_time_offset_s)
                time_offsets_s["altitude_filtered_time_compensated"] = (
                    filtered_time_offset_s
                )

                df = add_lag_compensated_error(
                    df,
                    "altitude_filtered_setpoint_m",
                    "altitude_actual_m",
                    filtered_time_offset_s,
                    "altitude_filtered",
                    "m",
                    "time_s",
                )
                error_columns["altitude_filtered_time_compensated"] = (
                    "altitude_filtered_time_compensated_error_m"
                )

    for axis in ["vx", "vy", "vz"]:
        actual_col = f"{axis}_actual_m_s"
        setpoint_col = f"{axis}_setpoint_m_s"
        filtered_setpoint_col = f"{axis}_filtered_setpoint_m_s"
        if actual_col in df.columns and setpoint_col in df.columns:
            actual_col_no_nan = df[actual_col].dropna()
            setpoint_col_no_nan = df[setpoint_col].dropna()
            if not actual_col_no_nan.empty and not setpoint_col_no_nan.empty:
                error_col = f"{axis}_velocity_error_m_s"
                filtered_error_col = f"{axis}_velocity_filtered_error_m_s"
                metric_name = f"{axis}_velocity"
                filtered_metric_name = f"{axis}_velocity_filtered"

                df[error_col] = df[setpoint_col] - df[actual_col]
                error_columns[metric_name] = error_col

                time_offset_s = estimate_signal_lag_s(df,setpoint_col,actual_col,"time_s",0.5)
                time_offset_s = sanitize_time_offset_s(time_offset_s)
                time_offsets_s[metric_name] = 0.0
                time_offsets_s[f"{axis}_velocity_time_compensated"] = time_offset_s

                if filtered_setpoint_col in df.columns:
                    df[filtered_error_col] = df[filtered_setpoint_col] - df[actual_col]
                    error_columns[filtered_metric_name] = filtered_error_col
                    time_offsets_s[filtered_metric_name] = 0.0

                    filtered_time_offset_s = estimate_signal_lag_s(
                        df,
                        filtered_setpoint_col,
                        actual_col,
                        "time_s",
                        0.5,
                    )
                    filtered_time_offset_s = sanitize_time_offset_s(filtered_time_offset_s)
                    filtered_time_compensated_metric_name = (
                        f"{metric_name}_filtered_time_compensated"
                    )
                    time_offsets_s[filtered_time_compensated_metric_name] = (
                        filtered_time_offset_s
                    )

                    df = add_lag_compensated_error(
                        df,
                        filtered_setpoint_col,
                        actual_col,
                        filtered_time_offset_s,
                        f"{axis}_velocity_filtered",
                        "m_s",
                        "time_s",
                    )
                    error_columns[filtered_time_compensated_metric_name] = (
                        f"{axis}_velocity_filtered_time_compensated_error_m_s"
                    )

                df = add_lag_compensated_error(df,setpoint_col,actual_col,time_offset_s,f"{axis}","m_s","time_s")
                error_columns[f"{axis}_velocity_time_compensated"] = f"{axis}_time_compensated_error_m_s"

    if "vertical_speed_actual_m_s" in df.columns and "vertical_speed_setpoint_m_s" in df.columns:
        df["vertical_speed_error_m_s"] = (
            df["vertical_speed_setpoint_m_s"] -
            df["vertical_speed_actual_m_s"]
        )
        error_columns["vertical_speed"] = "vertical_speed_error_m_s"

        if "vertical_speed_filtered_setpoint_m_s" in df.columns:
            df["vertical_speed_filtered_error_m_s"] = (
                df["vertical_speed_filtered_setpoint_m_s"] -
                df["vertical_speed_actual_m_s"]
            )
            error_columns["vertical_speed_filtered"] = "vertical_speed_filtered_error_m_s"
            time_offsets_s["vertical_speed_filtered"] = 0.0

            filtered_time_offset_s = estimate_signal_lag_s(
                df,
                "vertical_speed_filtered_setpoint_m_s",
                "vertical_speed_actual_m_s",
                "time_s",
                0.5,
            )
            filtered_time_offset_s = sanitize_time_offset_s(filtered_time_offset_s)
            time_offsets_s["vertical_speed_filtered_time_compensated"] = (
                filtered_time_offset_s
            )

            df = add_lag_compensated_error(
                df,
                "vertical_speed_filtered_setpoint_m_s",
                "vertical_speed_actual_m_s",
                filtered_time_offset_s,
                "vertical_speed_filtered",
                "m_s",
                "time_s",
            )
            error_columns["vertical_speed_filtered_time_compensated"] = (
                "vertical_speed_filtered_time_compensated_error_m_s"
            )

        time_offset_s = estimate_signal_lag_s(df,"vertical_speed_setpoint_m_s","vertical_speed_actual_m_s","time_s",0.5)
        time_offset_s = sanitize_time_offset_s(time_offset_s)
        time_offsets_s["vertical_speed"] = 0.0
        time_offsets_s["vertical_speed_time_compensated"] = time_offset_s

        df = add_lag_compensated_error(df,"vertical_speed_setpoint_m_s","vertical_speed_actual_m_s",time_offset_s,"vertical_speed","m_s","time_s")
        error_columns["vertical_speed_time_compensated"] = "vertical_speed_time_compensated_error_m_s"

    if all(col in df.columns for col in ["x_position_error_m", "y_position_error_m"]):
        df["horizontal_position_error_m"] = np.sqrt(
            df["x_position_error_m"] ** 2 + df["y_position_error_m"] ** 2
        )

    if all(col in df.columns for col in ["x_position_filtered_error_m", "y_position_filtered_error_m"]):
        df["horizontal_position_filtered_error_m"] = np.sqrt(
            df["x_position_filtered_error_m"] ** 2 + df["y_position_filtered_error_m"] ** 2
        )

    if all(col in df.columns for col in ["vx_velocity_error_m_s", "vy_velocity_error_m_s"]):
        df["horizontal_velocity_error_m_s"] = np.sqrt(
            df["vx_velocity_error_m_s"] ** 2 + df["vy_velocity_error_m_s"] ** 2
        )

    if all(col in df.columns for col in ["vx_velocity_filtered_error_m_s", "vy_velocity_filtered_error_m_s"]):
        df["horizontal_velocity_filtered_error_m_s"] = np.sqrt(
            df["vx_velocity_filtered_error_m_s"] ** 2 + df["vy_velocity_filtered_error_m_s"] ** 2
        )

    metrics = compute_tracking_error_metrics(df, error_columns, time_offsets_s)

    return df, metrics



# -------------------------------------------------
# Vibration analysis
# -------------------------------------------------

def _integrate_trapezoid(y: np.ndarray, x: np.ndarray) -> float:
    trapezoid_func = getattr(np, "trapezoid", None)
    if trapezoid_func is None:
        trapezoid_func = getattr(np, "trapz")
    return float(trapezoid_func(y, x))


def _existing_columns_from_candidates(df: pd.DataFrame, candidates: list[str]) -> list[str]:
    """Return matching scalar or PX4 array-expanded columns for candidate names."""
    columns: list[str] = []

    for candidate in candidates:
        if candidate in df.columns:
            columns.append(candidate)

        prefix = f"{candidate}["
        array_columns = [col for col in df.columns if col.startswith(prefix)]
        columns.extend(array_columns)

    # Preserve order while removing duplicates.
    return list(dict.fromkeys(columns))


def _first_existing_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    """Return the first matching scalar column from a candidate list."""
    for candidate in candidates:
        if candidate in df.columns:
            return candidate
    return None


def _coalesce_signal_columns(
    df: pd.DataFrame,
    candidates: list[str],
    output_col: str,
    reduction: str = "max",
) -> tuple[pd.DataFrame, str | None]:
    """Create a normalized signal column from scalar or array-expanded topic fields."""
    result = df.copy()
    columns = _existing_columns_from_candidates(result, candidates)

    if not columns:
        result[output_col] = np.nan
        return result, None

    numeric_data = result[columns].apply(pd.to_numeric, errors="coerce")

    if len(columns) == 1:
        result[output_col] = numeric_data.iloc[:, 0]
    elif reduction == "mean":
        result[output_col] = numeric_data.mean(axis=1)
    elif reduction == "sum":
        result[output_col] = numeric_data.sum(axis=1)
    else:
        result[output_col] = numeric_data.max(axis=1)

    return result, ", ".join(columns)


def _compute_total_clipping_count(df: pd.DataFrame, candidates: list[str]) -> tuple[float, str | None]:
    """Estimate total clipping from scalar or array-expanded clipping fields.

    PX4 logs may store clipping as cumulative counters or as per-sample values.
    Monotonic counter-like columns are integrated via positive increments, while
    non-monotonic event-like columns are summed directly.
    """
    columns = _existing_columns_from_candidates(df, candidates)

    if not columns:
        return np.nan, None

    total = 0.0

    for col in columns:
        signal = pd.to_numeric(df[col], errors="coerce").dropna()

        if signal.empty:
            continue

        if len(signal) == 1:
            total += float(max(signal.iloc[0], 0.0))
            continue

        diff = signal.diff().dropna()
        negative_diff_count = int((diff < 0).sum())
        positive_diff_sum = float(diff[diff > 0].sum())

        # Treat a mostly monotonic signal as a cumulative counter. Small resets
        # are handled by summing only positive increments.
        if negative_diff_count == 0 or negative_diff_count <= max(1, int(0.01 * len(diff))):
            total += positive_diff_sum
        else:
            total += float(signal.clip(lower=0).sum())

    return total, ", ".join(columns)


def _build_cumulative_clipping_counter(signal: pd.Series) -> pd.Series:
    """Build a cumulative clipping counter from counter-like or event-like data."""
    numeric_signal = pd.to_numeric(signal, errors="coerce")
    valid_signal = numeric_signal.dropna()

    if valid_signal.empty:
        return pd.Series(np.nan, index=signal.index, dtype="float64")

    if len(valid_signal) == 1:
        cumulative_valid = pd.Series(
            [max(float(valid_signal.iloc[0]), 0.0)],
            index=valid_signal.index,
            dtype="float64",
        )
    else:
        diff = valid_signal.diff()
        negative_diff_count = int((diff.dropna() < 0).sum())

        # Mostly monotonic signals are interpreted as already cumulative
        # counters. Plotting positive increments makes resets harmless and keeps
        # the visualized value relative to the start of the log.
        if negative_diff_count == 0 or negative_diff_count <= max(1, int(0.01 * len(diff.dropna()))):
            increments = diff.clip(lower=0).fillna(0.0)
        else:
            # Non-monotonic fields are interpreted as per-sample clipping events.
            increments = valid_signal.clip(lower=0)

        cumulative_valid = increments.cumsum()

    cumulative = cumulative_valid.reindex(signal.index).ffill().fillna(0.0)
    return cumulative.astype("float64")


def _add_cumulative_clipping_count(
    df: pd.DataFrame,
    candidates: list[str],
    output_col: str,
) -> tuple[pd.DataFrame, float, str | None]:
    """Add a normalized cumulative clipping-count signal to a dataframe."""
    result = df.copy()
    columns = _existing_columns_from_candidates(result, candidates)

    if not columns:
        result[output_col] = np.nan
        return result, np.nan, None

    cumulative_total = pd.Series(0.0, index=result.index, dtype="float64")

    for col in columns:
        cumulative_total = cumulative_total.add(
            _build_cumulative_clipping_counter(result[col]),
            fill_value=0.0,
        )

    result[output_col] = cumulative_total

    if result[output_col].dropna().empty:
        total_count = np.nan
    else:
        total_count = float(result[output_col].max())

    return result, total_count, ", ".join(columns)


def _find_accel_axis_columns(sensor_accel_df: pd.DataFrame) -> list[str]:
    """Find the three acceleration axis columns used by common PX4 ULog schemas."""
    candidate_sets = [
        ["x", "y", "z"],
        ["xyz[0]", "xyz[1]", "xyz[2]"],
        ["accel[0]", "accel[1]", "accel[2]"],
        ["acceleration[0]", "acceleration[1]", "acceleration[2]"],
        ["accelerometer_m_s2[0]", "accelerometer_m_s2[1]", "accelerometer_m_s2[2]"],
    ]

    for candidate_set in candidate_sets:
        if all(col in sensor_accel_df.columns for col in candidate_set):
            return candidate_set

    return []


def _find_gyro_axis_columns(sensor_gyro_df: pd.DataFrame) -> list[str]:
    """Find the three angular-rate axis columns used by common PX4 ULog schemas."""
    candidate_sets = [
        ["x", "y", "z"],
        ["xyz[0]", "xyz[1]", "xyz[2]"],
        ["gyro[0]", "gyro[1]", "gyro[2]"],
        ["angular_velocity[0]", "angular_velocity[1]", "angular_velocity[2]"],
        ["angular_velocity_rad_s[0]", "angular_velocity_rad_s[1]", "angular_velocity_rad_s[2]"],
        ["angular_rate[0]", "angular_rate[1]", "angular_rate[2]"],
    ]

    for candidate_set in candidate_sets:
        if all(col in sensor_gyro_df.columns for col in candidate_set):
            return candidate_set

    return []


def _normalize_xyz_sensor_topic(
    topic_df: pd.DataFrame,
    axis_cols: list[str],
    output_cols: list[str],
    magnitude_col: str,
    source_col: str,
) -> pd.DataFrame:
    """Return a compact, consistently named x/y/z sensor dataframe."""
    empty_columns = ["time_s", *output_cols, magnitude_col, source_col]

    if topic_df is None or topic_df.empty or "time_s" not in topic_df.columns or len(axis_cols) != 3:
        return pd.DataFrame(columns=empty_columns)

    result = pd.DataFrame({"time_s": pd.to_numeric(topic_df["time_s"], errors="coerce")})

    for source_axis_col, output_col in zip(axis_cols, output_cols):
        result[output_col] = pd.to_numeric(topic_df[source_axis_col], errors="coerce")

    result[magnitude_col] = np.sqrt(
        result[output_cols[0]] ** 2 +
        result[output_cols[1]] ** 2 +
        result[output_cols[2]] ** 2
    )
    result[source_col] = ", ".join(axis_cols)

    return (
        result
        .replace([np.inf, -np.inf], np.nan)
        .dropna(subset=["time_s"])
        .sort_values("time_s")
        .reset_index(drop=True)
    )


def analyze_sensor_accel(log: UlgReader) -> pd.DataFrame:
    """Return cached x/y/z acceleration from sensor_accel for time-domain plots."""
    try:
        sensor_accel = log.get_topic("sensor_accel").copy()
    except ValueError:
        return pd.DataFrame(columns=[
            "time_s",
            "accel_x_m_s2",
            "accel_y_m_s2",
            "accel_z_m_s2",
            "accel_magnitude_m_s2",
            "sensor_accel_axis_columns",
        ])

    axis_cols = _find_accel_axis_columns(sensor_accel)

    return _normalize_xyz_sensor_topic(
        sensor_accel,
        axis_cols,
        ["accel_x_m_s2", "accel_y_m_s2", "accel_z_m_s2"],
        "accel_magnitude_m_s2",
        "sensor_accel_axis_columns",
    )


def analyze_sensor_gyro(log: UlgReader) -> pd.DataFrame:
    """Return cached x/y/z angular velocity from sensor_gyro for time-domain plots."""
    try:
        sensor_gyro = log.get_topic("sensor_gyro").copy()
    except ValueError:
        return pd.DataFrame(columns=[
            "time_s",
            "gyro_x_rad_s",
            "gyro_y_rad_s",
            "gyro_z_rad_s",
            "gyro_magnitude_rad_s",
            "sensor_gyro_axis_columns",
        ])

    axis_cols = _find_gyro_axis_columns(sensor_gyro)

    return _normalize_xyz_sensor_topic(
        sensor_gyro,
        axis_cols,
        ["gyro_x_rad_s", "gyro_y_rad_s", "gyro_z_rad_s"],
        "gyro_magnitude_rad_s",
        "sensor_gyro_axis_columns",
    )


def compute_accel_psd(
    sensor_accel_df: pd.DataFrame,
    max_points: int = 65536,
) -> tuple[pd.DataFrame, dict[str, float | int | str]]:
    """Compute a summed three-axis acceleration PSD and dominant frequency.

    The accelerometer axes are interpolated onto a uniform time base before the
    FFT. The DC bin is excluded from dominant-frequency detection.
    """
    empty_result = pd.DataFrame(columns=["frequency_hz", "accel_psd"])
    empty_metrics: dict[str, float | int | str] = {
        "dominant_accel_frequency_hz": np.nan,
        "sensor_accel_sample_rate_hz": np.nan,
        "sensor_accel_samples": 0,
        "sensor_accel_axis_columns": "",
    }

    if sensor_accel_df is None or sensor_accel_df.empty or "time_s" not in sensor_accel_df.columns:
        return empty_result, empty_metrics

    axis_cols = _find_accel_axis_columns(sensor_accel_df)

    if len(axis_cols) != 3:
        return empty_result, empty_metrics

    data = sensor_accel_df[["time_s", *axis_cols]].copy()
    data = data.apply(pd.to_numeric, errors="coerce")
    data = data.replace([np.inf, -np.inf], np.nan).dropna()
    data = data.sort_values("time_s")
    data = data.drop_duplicates(subset="time_s", keep="first")

    if len(data) < 16:
        return empty_result, empty_metrics

    time_s = data["time_s"].to_numpy(dtype=float)
    dt_s = np.diff(time_s)
    median_dt_s = float(np.nanmedian(dt_s[dt_s > 0])) if np.any(dt_s > 0) else np.nan

    if not np.isfinite(median_dt_s) or median_dt_s <= 0:
        return empty_result, empty_metrics

    sample_rate_hz = 1.0 / median_dt_s

    uniform_time_s = np.arange(time_s[0], time_s[-1], median_dt_s)

    if len(uniform_time_s) < 16:
        return empty_result, empty_metrics

    if len(uniform_time_s) > max_points:
        uniform_time_s = uniform_time_s[:max_points]

    axis_matrix = []
    for col in axis_cols:
        values = np.interp(uniform_time_s, time_s, data[col].to_numpy(dtype=float))
        values = values - np.mean(values)
        axis_matrix.append(values)

    axis_matrix_np = np.vstack(axis_matrix)
    n_samples = axis_matrix_np.shape[1]
    window = np.hanning(n_samples)
    window_power = np.sum(window ** 2)

    frequencies_hz = np.fft.rfftfreq(n_samples, d=median_dt_s)
    summed_psd = np.zeros_like(frequencies_hz)

    for axis_values in axis_matrix_np:
        spectrum = np.fft.rfft(axis_values * window)
        axis_psd = (np.abs(spectrum) ** 2) / (sample_rate_hz * window_power)
        summed_psd += axis_psd

    psd_df = pd.DataFrame({
        "frequency_hz": frequencies_hz,
        "accel_psd": summed_psd,
    })

    if len(psd_df) <= 1 or psd_df["accel_psd"].iloc[1:].dropna().empty:
        dominant_frequency_hz = np.nan
    else:
        dominant_idx = int(psd_df["accel_psd"].iloc[1:].idxmax())
        dominant_frequency_hz = float(psd_df.loc[dominant_idx, "frequency_hz"])

    metrics = {
        "dominant_accel_frequency_hz": dominant_frequency_hz,
        "sensor_accel_sample_rate_hz": float(sample_rate_hz),
        "sensor_accel_samples": int(n_samples),
        "sensor_accel_axis_columns": ", ".join(axis_cols),
    }

    return psd_df, metrics


def compute_vibration_phase_statistics(vibration_df: pd.DataFrame) -> pd.DataFrame:
    """Compute vibration severity per detected flight phase."""
    required_cols = {"flight_phase", "accel_vibration_metric", "gyro_vibration_metric"}

    if vibration_df is None or vibration_df.empty or not required_cols.issubset(vibration_df.columns):
        return pd.DataFrame(columns=[
            "flight_phase",
            "samples",
            "max_accel_vibration_metric",
            "max_gyro_vibration_metric",
            "mean_accel_vibration_metric",
            "mean_gyro_vibration_metric",
            "combined_vibration_score",
            "worst_phase",
        ])

    grouped = vibration_df.dropna(subset=["flight_phase"]).groupby("flight_phase")

    phase_stats = grouped.agg(
        samples=("time_s", "count"),
        max_accel_vibration_metric=("accel_vibration_metric", "max"),
        max_gyro_vibration_metric=("gyro_vibration_metric", "max"),
        mean_accel_vibration_metric=("accel_vibration_metric", "mean"),
        mean_gyro_vibration_metric=("gyro_vibration_metric", "mean"),
    ).reset_index()

    max_accel_global = phase_stats["max_accel_vibration_metric"].max()
    max_gyro_global = phase_stats["max_gyro_vibration_metric"].max()

    accel_component = (
        phase_stats["max_accel_vibration_metric"] / max_accel_global
        if pd.notna(max_accel_global) and max_accel_global > 0
        else 0.0
    )
    gyro_component = (
        phase_stats["max_gyro_vibration_metric"] / max_gyro_global
        if pd.notna(max_gyro_global) and max_gyro_global > 0
        else 0.0
    )

    phase_stats["combined_vibration_score"] = accel_component + gyro_component
    phase_stats = phase_stats.sort_values("combined_vibration_score", ascending=False)
    phase_stats["worst_phase"] = False

    if not phase_stats.empty:
        phase_stats.loc[phase_stats.index[0], "worst_phase"] = True

    return phase_stats


def analyze_vibration(
    log: UlgReader,
    position: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any], pd.DataFrame, pd.DataFrame] | None:
    """Analyze IMU vibration and clipping health from PX4 ULog topics.

    Returns ``None`` when ``vehicle_imu_status`` is unavailable. The returned
    tuple contains the normalized vibration dataframe, overview metrics, phase
    statistics, and accelerometer PSD dataframe.
    """
    try:
        imu_status = log.get_topic("vehicle_imu_status").copy()
    except ValueError:
        return None

    imu_status = imu_status.sort_values("time_s")

    vibration_df, accel_metric_source = _coalesce_signal_columns(
        imu_status,
        ["accel_vibration_metric"],
        "accel_vibration_metric",
        reduction="max",
    )
    vibration_df, gyro_metric_source = _coalesce_signal_columns(
        vibration_df,
        ["gyro_vibration_metric"],
        "gyro_vibration_metric",
        reduction="max",
    )

    vibration_df, total_accel_clipping, accel_clipping_source = (
        _add_cumulative_clipping_count(
            vibration_df,
            ["accel_clipping", "delta_velocity_clipping"],
            "accel_clipping_count",
        )
    )
    vibration_df, total_gyro_clipping, gyro_clipping_source = (
        _add_cumulative_clipping_count(
            vibration_df,
            ["gyro_clipping", "delta_angle_clipping"],
            "gyro_clipping_count",
        )
    )

    if position is not None and not position.empty and "flight_phase" in position.columns:
        phase_lookup = position[["time_s", "flight_phase"]].dropna().sort_values("time_s")
        vibration_df = pd.merge_asof(
            vibration_df.sort_values("time_s"),
            phase_lookup,
            on="time_s",
            direction="nearest",
        )
    else:
        vibration_df["flight_phase"] = np.nan

    phase_stats = compute_vibration_phase_statistics(vibration_df)

    try:
        sensor_accel = log.get_topic("sensor_accel").copy()
    except ValueError:
        sensor_accel = pd.DataFrame()

    accel_psd_df, accel_psd_metrics = compute_accel_psd(sensor_accel)

    if not phase_stats.empty and "worst_phase" in phase_stats.columns and phase_stats["worst_phase"].any():
        worst_phase = str(phase_stats.loc[phase_stats["worst_phase"], "flight_phase"].iloc[0])
        worst_phase_score = float(phase_stats.loc[phase_stats["worst_phase"], "combined_vibration_score"].iloc[0])
    else:
        worst_phase = "unknown"
        worst_phase_score = np.nan

    metrics: dict[str, Any] = {
        "max_accel_vibration_metric": vibration_df["accel_vibration_metric"].max(),
        "max_gyro_vibration_metric": vibration_df["gyro_vibration_metric"].max(),
        "total_accel_clipping": total_accel_clipping,
        "total_gyro_clipping": total_gyro_clipping,
        "dominant_accel_frequency_hz": accel_psd_metrics["dominant_accel_frequency_hz"],
        "sensor_accel_sample_rate_hz": accel_psd_metrics["sensor_accel_sample_rate_hz"],
        "sensor_accel_samples": accel_psd_metrics["sensor_accel_samples"],
        "sensor_accel_axis_columns": accel_psd_metrics["sensor_accel_axis_columns"],
        "worst_flight_phase": worst_phase,
        "worst_flight_phase_score": worst_phase_score,
        "accel_vibration_metric_source": accel_metric_source or "not found",
        "gyro_vibration_metric_source": gyro_metric_source or "not found",
        "accel_clipping_source": accel_clipping_source or "not found",
        "gyro_clipping_source": gyro_clipping_source or "not found",
    }

    return vibration_df, metrics, phase_stats, accel_psd_df


def _prepare_uniform_time_series(
    df: pd.DataFrame,
    signal_columns: list[str],
    time_col: str = "time_s",
    max_points: int = 200000,
) -> tuple[np.ndarray, np.ndarray, float, list[str]]:
    """Interpolate selected signals onto a uniform time base for FFT/PSD work."""
    available_signal_columns = [col for col in signal_columns if col in df.columns]

    if (
        df is None or
        df.empty or
        time_col not in df.columns or
        not available_signal_columns
    ):
        return np.array([]), np.empty((0, 0)), np.nan, []

    data = df[[time_col, *available_signal_columns]].copy()
    data = data.apply(pd.to_numeric, errors="coerce")
    data = data.replace([np.inf, -np.inf], np.nan)
    data = data.dropna(subset=[time_col])
    data = data.sort_values(time_col)
    data = data.drop_duplicates(subset=time_col, keep="first")

    data = data.dropna(subset=available_signal_columns, how="all")

    if len(data) < 16:
        return np.array([]), np.empty((0, 0)), np.nan, []

    time_s = data[time_col].to_numpy(dtype=float)
    dt_s = np.diff(time_s)
    positive_dt_s = dt_s[dt_s > 0]

    if len(positive_dt_s) == 0:
        return np.array([]), np.empty((0, 0)), np.nan, []

    median_dt_s = float(np.nanmedian(positive_dt_s))

    if not np.isfinite(median_dt_s) or median_dt_s <= 0:
        return np.array([]), np.empty((0, 0)), np.nan, []

    n_uniform_estimate = int(np.floor((time_s[-1] - time_s[0]) / median_dt_s)) + 1

    if max_points is not None and max_points > 0 and n_uniform_estimate > max_points:
        decimation_factor = int(np.ceil(n_uniform_estimate / max_points))
        median_dt_s *= decimation_factor

    uniform_time_s = np.arange(time_s[0], time_s[-1] + median_dt_s * 0.5, median_dt_s)

    if len(uniform_time_s) < 16:
        return np.array([]), np.empty((0, 0)), np.nan, []

    uniform_signals = []
    valid_columns = []

    for col in available_signal_columns:
        signal_data = data[[time_col, col]].dropna()

        if len(signal_data) < 2:
            continue

        signal_time_s = signal_data[time_col].to_numpy(dtype=float)
        signal_values = signal_data[col].to_numpy(dtype=float)

        if np.nanstd(signal_values) == 0:
            continue

        interpolated = np.interp(
            uniform_time_s,
            signal_time_s,
            signal_values,
            left=np.nan,
            right=np.nan,
        )

        finite = np.isfinite(interpolated)
        if finite.sum() < 16:
            continue

        # Keep FFT input finite by filling edge gaps with nearest valid values.
        interpolated_series = pd.Series(interpolated).ffill().bfill()
        uniform_signals.append(interpolated_series.to_numpy(dtype=float))
        valid_columns.append(col)

    if not uniform_signals:
        return np.array([]), np.empty((0, 0)), np.nan, []

    sample_rate_hz = 1.0 / median_dt_s
    return uniform_time_s, np.vstack(uniform_signals), sample_rate_hz, valid_columns


def compute_time_resolved_psd_surface(
    df: pd.DataFrame,
    signal_columns: list[str],
    time_col: str = "time_s",
    window_duration_s: float = 1.0,
    overlap: float | None = None,
    time_step_s: float | None = 1.0,
    max_frequency_hz: float | None = 250.0,
    max_time_bins: int | None = None,
    max_frequency_bins: int = 220,
    max_input_points: int = 200000,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Compute sliding-window PSD heatmap data for several signals.

    ``window_duration_s`` controls how much signal is used for each FFT/PSD
    estimate. ``time_step_s`` controls the physical update interval between PSD
    estimates. This makes the y-axis sampling stable and interpretable: a value
    of 1.0 means one PSD row roughly every second.

    ``overlap`` and ``max_time_bins`` are kept only for backwards compatibility.
    New calls should prefer ``time_step_s`` and should not use ``max_time_bins``
    as a display-resolution control because it changes which PSD windows are
    analyzed.
    """
    empty_metrics: dict[str, Any] = {
        "sample_rate_hz": np.nan,
        "window_samples": 0,
        "window_duration_s": window_duration_s,
        "requested_time_step_s": time_step_s,
        "actual_time_step_s": np.nan,
        "step_samples": 0,
        "segments": 0,
        "frequency_bins": 0,
        "signal_columns": "",
    }

    uniform_time_s, signal_matrix, sample_rate_hz, valid_columns = _prepare_uniform_time_series(
        df,
        signal_columns,
        time_col=time_col,
        max_points=max_input_points,
    )

    if len(uniform_time_s) < 16 or signal_matrix.size == 0 or not np.isfinite(sample_rate_hz):
        return {}, empty_metrics

    window_duration_s = float(window_duration_s) if window_duration_s is not None else 1.0
    if not np.isfinite(window_duration_s) or window_duration_s <= 0:
        window_duration_s = 1.0

    nperseg = int(round(window_duration_s * sample_rate_hz))
    nperseg = max(16, nperseg)
    nperseg = min(nperseg, signal_matrix.shape[1])

    if nperseg < 16:
        return {}, empty_metrics

    if time_step_s is not None:
        try:
            time_step_s = float(time_step_s)
        except (TypeError, ValueError):
            time_step_s = np.nan

    if time_step_s is not None and np.isfinite(time_step_s) and time_step_s > 0:
        step_samples = max(1, int(round(time_step_s * sample_rate_hz)))
    else:
        # Backwards-compatible fallback for older callers that still use overlap.
        overlap = float(overlap) if overlap is not None else 0.5
        overlap = min(max(overlap, 0.0), 0.95)
        step_samples = max(1, int(round(nperseg * (1.0 - overlap))))
        time_step_s = step_samples / sample_rate_hz

    actual_time_step_s = step_samples / sample_rate_hz

    start_indices = np.arange(0, signal_matrix.shape[1] - nperseg + 1, step_samples)

    if len(start_indices) == 0:
        return {}, empty_metrics

    # Backwards compatibility / emergency safety only. The Streamlit UI no longer
    # exposes this as a user-facing resolution control because it changes the
    # analyzed windows.
    if max_time_bins is not None and max_time_bins > 0 and len(start_indices) > max_time_bins:
        selected_indices = np.linspace(0, len(start_indices) - 1, max_time_bins).round().astype(int)
        start_indices = start_indices[selected_indices]

    segment_times_s = uniform_time_s[start_indices + nperseg // 2]

    window = np.hanning(nperseg)
    window_power = np.sum(window ** 2)
    if window_power <= 0:
        return {}, empty_metrics

    frequencies_hz = np.fft.rfftfreq(nperseg, d=1.0 / sample_rate_hz)

    frequency_mask = np.ones_like(frequencies_hz, dtype=bool)
    if max_frequency_hz is not None and np.isfinite(float(max_frequency_hz)) and max_frequency_hz > 0:
        frequency_mask &= frequencies_hz <= float(max_frequency_hz)

    frequency_indices = np.where(frequency_mask)[0]

    if len(frequency_indices) == 0:
        return {}, empty_metrics

    if max_frequency_bins is not None and max_frequency_bins > 0 and len(frequency_indices) > max_frequency_bins:
        selected_frequency_indices = np.linspace(
            0,
            len(frequency_indices) - 1,
            max_frequency_bins,
        ).round().astype(int)
        frequency_indices = frequency_indices[selected_frequency_indices]

    plot_frequencies_hz = frequencies_hz[frequency_indices]
    surfaces: dict[str, dict[str, Any]] = {}

    for signal_values, col in zip(signal_matrix, valid_columns):
        psd_rows = []

        for start_idx in start_indices:
            segment = signal_values[start_idx:start_idx + nperseg]
            segment = segment - np.nanmean(segment)
            spectrum = np.fft.rfft(segment * window)
            psd = (np.abs(spectrum) ** 2) / (sample_rate_hz * window_power)
            psd_rows.append(psd[frequency_indices])

        psd_matrix = np.vstack(psd_rows) if psd_rows else np.empty((0, len(plot_frequencies_hz)))

        surfaces[col] = {
            "frequency_hz": plot_frequencies_hz,
            "time_s": segment_times_s,
            "psd": psd_matrix,
            "sample_rate_hz": sample_rate_hz,
            "window_samples": nperseg,
            "window_duration_s": nperseg / sample_rate_hz,
            "requested_time_step_s": time_step_s,
            "actual_time_step_s": actual_time_step_s,
            "step_samples": step_samples,
        }

    metrics = {
        "sample_rate_hz": float(sample_rate_hz),
        "window_samples": int(nperseg),
        "window_duration_s": float(nperseg / sample_rate_hz),
        "requested_time_step_s": float(time_step_s) if time_step_s is not None and np.isfinite(time_step_s) else np.nan,
        "actual_time_step_s": float(actual_time_step_s),
        "step_samples": int(step_samples),
        "segments": int(len(segment_times_s)),
        "frequency_bins": int(len(plot_frequencies_hz)),
        "signal_columns": ", ".join(valid_columns),
    }

    return surfaces, metrics


def _find_actuator_controls_topics(log: UlgReader) -> list[str]:
    """Find actuator_controls topic variants in old and new PX4 ULog schemas."""
    try:
        topics = log.list_topics()
    except Exception:
        topics = []

    preferred_topics = [
        "actuator_controls",
        "actuator_controls_0",
        "actuator_controls_1",
        "actuator_controls_2",
        "actuator_controls_3",
    ]

    matching_topics = [topic for topic in topics if topic.startswith("actuator_controls")]
    ordered_topics = preferred_topics + matching_topics

    return list(dict.fromkeys(ordered_topics))


def _find_actuator_control_columns(df: pd.DataFrame) -> list[str]:
    """Find usable actuator control vector columns."""
    candidate_prefixes = [
        "control[",
        "controls[",
        "actuator_controls[",
    ]

    columns = []

    for prefix in candidate_prefixes:
        columns.extend([col for col in df.columns if col.startswith(prefix)])

    # Fallback for any schema that stores explicit scalar control channels.
    fallback_candidates = [
        "roll", "pitch", "yaw", "thrust",
        "control_0", "control_1", "control_2", "control_3",
    ]
    columns.extend([col for col in fallback_candidates if col in df.columns])

    ordered_columns = list(dict.fromkeys(columns))

    active_columns = []
    for col in ordered_columns:
        signal = pd.to_numeric(df[col], errors="coerce").dropna()
        if len(signal) < 2:
            continue
        if np.nanstd(signal.to_numpy(dtype=float)) > 0:
            active_columns.append(col)

    return active_columns


def analyze_actuator_controls(log: UlgReader) -> pd.DataFrame:
    """Return actuator_controls channels for FFT analysis.

    Supports both ``actuator_controls`` and instance-specific topic names such
    as ``actuator_controls_0``. Returns an empty dataframe when the topic is not
    available in the log.
    """
    empty_columns = ["time_s", "actuator_controls_topic", "actuator_controls_columns"]

    for topic in _find_actuator_controls_topics(log):
        try:
            topic_df = log.get_topic(topic).copy()
        except ValueError:
            continue

        if topic_df.empty or "time_s" not in topic_df.columns:
            continue

        control_columns = _find_actuator_control_columns(topic_df)
        if not control_columns:
            continue

        result = pd.DataFrame({
            "time_s": pd.to_numeric(topic_df["time_s"], errors="coerce"),
        })

        rename_map = {}
        for i, source_col in enumerate(control_columns):
            output_col = f"control_{i}"
            result[output_col] = pd.to_numeric(topic_df[source_col], errors="coerce")
            rename_map[output_col] = source_col

        result["actuator_controls_topic"] = topic
        result["actuator_controls_columns"] = ", ".join(control_columns)

        return (
            result
            .replace([np.inf, -np.inf], np.nan)
            .dropna(subset=["time_s"])
            .sort_values("time_s")
            .reset_index(drop=True)
        )

    return pd.DataFrame(columns=empty_columns)


def compute_signal_fft(
    df: pd.DataFrame,
    signal_columns: list[str],
    time_col: str = "time_s",
    max_points: int = 65536,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Compute single-sided FFT amplitude spectra for selected signals."""
    empty_result = pd.DataFrame(columns=["frequency_hz", "amplitude", "signal"])
    empty_metrics: dict[str, Any] = {
        "sample_rate_hz": np.nan,
        "samples": 0,
        "signal_columns": "",
    }

    uniform_time_s, signal_matrix, sample_rate_hz, valid_columns = _prepare_uniform_time_series(
        df,
        signal_columns,
        time_col=time_col,
        max_points=max_points,
    )

    if len(uniform_time_s) < 16 or signal_matrix.size == 0 or not np.isfinite(sample_rate_hz):
        return empty_result, empty_metrics

    n_samples = signal_matrix.shape[1]
    window = np.hanning(n_samples)
    coherent_gain = np.sum(window)

    if coherent_gain <= 0:
        return empty_result, empty_metrics

    frequencies_hz = np.fft.rfftfreq(n_samples, d=1.0 / sample_rate_hz)
    rows = []

    for signal_values, col in zip(signal_matrix, valid_columns):
        centered = signal_values - np.nanmean(signal_values)
        spectrum = np.fft.rfft(centered * window)
        amplitude = 2.0 * np.abs(spectrum) / coherent_gain
        if len(amplitude) > 0:
            amplitude[0] = np.abs(spectrum[0]) / coherent_gain

        rows.append(pd.DataFrame({
            "frequency_hz": frequencies_hz,
            "amplitude": amplitude,
            "signal": col,
        }))

    fft_df = pd.concat(rows, ignore_index=True) if rows else empty_result

    metrics = {
        "sample_rate_hz": float(sample_rate_hz),
        "samples": int(n_samples),
        "signal_columns": ", ".join(valid_columns),
    }

    return fft_df, metrics



def _safe_rms(values: pd.Series | np.ndarray) -> float:
    """Compute RMS for finite values only."""
    numeric = pd.to_numeric(pd.Series(values), errors="coerce")
    numeric = numeric.replace([np.inf, -np.inf], np.nan).dropna()

    if numeric.empty:
        return np.nan

    return float(np.sqrt(np.mean(np.square(numeric.to_numpy(dtype=float)))))


def _compute_centered_xyz_metrics(
    df: pd.DataFrame,
    axis_columns: list[str],
    prefix: str,
    axis_unit_suffix: str,
) -> dict[str, float]:
    """Compute AC axis RMS, vector RMS, p95 vector magnitude, and crest factor."""
    metrics = {
        f"{prefix}_rms_x_{axis_unit_suffix}": np.nan,
        f"{prefix}_rms_y_{axis_unit_suffix}": np.nan,
        f"{prefix}_rms_z_{axis_unit_suffix}": np.nan,
        f"{prefix}_vector_rms_{axis_unit_suffix}": np.nan,
        f"p95_{prefix}_magnitude_{axis_unit_suffix}": np.nan,
        f"{prefix}_crest_factor": np.nan,
    }

    if df is None or df.empty or not all(col in df.columns for col in axis_columns):
        return metrics

    axis_data = df[axis_columns].apply(pd.to_numeric, errors="coerce")
    axis_data = axis_data.replace([np.inf, -np.inf], np.nan).dropna()

    if axis_data.empty:
        return metrics

    centered = axis_data - axis_data.mean(axis=0)

    axis_names = ["x", "y", "z"]
    for axis_name, col in zip(axis_names, axis_columns):
        metrics[f"{prefix}_rms_{axis_name}_{axis_unit_suffix}"] = _safe_rms(centered[col])

    vector_magnitude = np.sqrt(np.square(centered).sum(axis=1))
    vector_rms = _safe_rms(vector_magnitude)

    metrics[f"{prefix}_vector_rms_{axis_unit_suffix}"] = vector_rms
    metrics[f"p95_{prefix}_magnitude_{axis_unit_suffix}"] = (
        float(pd.Series(vector_magnitude).quantile(0.95))
        if len(vector_magnitude) > 0
        else np.nan
    )

    if pd.notna(vector_rms) and vector_rms > 0:
        metrics[f"{prefix}_crest_factor"] = float(np.nanmax(vector_magnitude) / vector_rms)

    return metrics


def _add_centered_vector_magnitude(
    df: pd.DataFrame,
    axis_columns: list[str],
    output_col: str,
) -> pd.DataFrame:
    """Add vector magnitude after removing the mean from each axis."""
    result = df.copy()
    result[output_col] = np.nan

    if result.empty or not all(col in result.columns for col in axis_columns):
        return result

    axis_data = result[axis_columns].apply(pd.to_numeric, errors="coerce")
    axis_data = axis_data.replace([np.inf, -np.inf], np.nan)

    complete_rows = axis_data.dropna()
    if complete_rows.empty:
        return result

    centered = complete_rows - complete_rows.mean(axis=0)
    result.loc[complete_rows.index, output_col] = np.sqrt(np.square(centered).sum(axis=1))

    return result


def _assign_flight_phase_to_topic(
    topic_df: pd.DataFrame,
    position: pd.DataFrame,
) -> pd.DataFrame:
    """Attach nearest detected flight phase to a topic dataframe."""
    if topic_df is None or topic_df.empty or "time_s" not in topic_df.columns:
        return pd.DataFrame()

    result = topic_df.copy().sort_values("time_s")

    if "flight_phase" in result.columns:
        return result

    if (
        position is None or
        position.empty or
        "time_s" not in position.columns or
        "flight_phase" not in position.columns
    ):
        result["flight_phase"] = np.nan
        return result

    phase_lookup = (
        position[["time_s", "flight_phase"]]
        .dropna(subset=["time_s", "flight_phase"])
        .sort_values("time_s")
    )

    if phase_lookup.empty:
        result["flight_phase"] = np.nan
        return result

    result = pd.merge_asof(
        result,
        phase_lookup,
        on="time_s",
        direction="nearest",
    )

    return result


def _compute_phase_durations(position: pd.DataFrame) -> pd.DataFrame:
    """Compute duration and position sample count per detected phase."""
    if (
        position is None or
        position.empty or
        "time_s" not in position.columns or
        "flight_phase" not in position.columns
    ):
        return pd.DataFrame(columns=["flight_phase", "duration_s", "position_samples"])

    duration_df = position[["time_s", "flight_phase"]].dropna().copy()
    duration_df = duration_df.sort_values("time_s")

    if duration_df.empty:
        return pd.DataFrame(columns=["flight_phase", "duration_s", "position_samples"])

    dt_s = duration_df["time_s"].diff().shift(-1)
    median_dt_s = duration_df["time_s"].diff().median()

    if pd.isna(median_dt_s) or median_dt_s <= 0:
        median_dt_s = 0.0

    duration_df["dt_s"] = dt_s.fillna(median_dt_s).clip(lower=0.0)

    return (
        duration_df
        .groupby("flight_phase")
        .agg(
            duration_s=("dt_s", "sum"),
            position_samples=("time_s", "count"),
        )
        .reset_index()
    )


def _split_contiguous_time_segments(
    df: pd.DataFrame,
    time_col: str = "time_s",
    max_gap_factor: float = 5.0,
) -> list[pd.DataFrame]:
    """Split a sorted dataframe into contiguous time segments."""
    if df is None or df.empty or time_col not in df.columns:
        return []

    data = df.dropna(subset=[time_col]).sort_values(time_col).copy()
    if data.empty:
        return []

    time_values = pd.to_numeric(data[time_col], errors="coerce").to_numpy(dtype=float)
    positive_dt = np.diff(time_values)
    positive_dt = positive_dt[positive_dt > 0]

    if len(positive_dt) == 0:
        return [data]

    median_dt_s = float(np.nanmedian(positive_dt))
    if not np.isfinite(median_dt_s) or median_dt_s <= 0:
        return [data]

    max_gap_s = max_gap_factor * median_dt_s
    split_positions = np.where(np.diff(time_values) > max_gap_s)[0] + 1

    if len(split_positions) == 0:
        return [data]

    index_chunks = np.split(np.arange(len(data)), split_positions)
    return [data.iloc[index_chunk].copy() for index_chunk in index_chunks if len(index_chunk) > 0]


def _compute_single_signal_psd_summary(
    df: pd.DataFrame,
    signal_col: str,
    band_low_hz: float,
    band_high_hz: float,
    time_col: str = "time_s",
    max_points: int = 65536,
) -> dict[str, float]:
    """Compute dominant frequency and integrated band power for one signal."""
    empty_summary = {
        "dominant_frequency_hz": np.nan,
        "band_power": np.nan,
        "peak_psd": np.nan,
        "duration_s": np.nan,
    }

    if df is None or df.empty or signal_col not in df.columns or time_col not in df.columns:
        return empty_summary

    uniform_time_s, signal_matrix, sample_rate_hz, valid_columns = _prepare_uniform_time_series(
        df,
        [signal_col],
        time_col=time_col,
        max_points=max_points,
    )

    if (
        len(uniform_time_s) < 16 or
        signal_matrix.size == 0 or
        not valid_columns or
        not np.isfinite(sample_rate_hz) or
        sample_rate_hz <= 0
    ):
        return empty_summary

    signal_values = signal_matrix[0]
    signal_values = signal_values - np.nanmean(signal_values)
    n_samples = len(signal_values)

    if n_samples < 16:
        return empty_summary

    window = np.hanning(n_samples)
    window_power = np.sum(window ** 2)

    if window_power <= 0:
        return empty_summary

    frequencies_hz = np.fft.rfftfreq(n_samples, d=1.0 / sample_rate_hz)
    spectrum = np.fft.rfft(signal_values * window)
    psd = (np.abs(spectrum) ** 2) / (sample_rate_hz * window_power)

    non_dc_mask = frequencies_hz > 0
    if not non_dc_mask.any():
        return empty_summary

    non_dc_psd = psd[non_dc_mask]
    non_dc_freq = frequencies_hz[non_dc_mask]

    if len(non_dc_psd) == 0 or not np.isfinite(non_dc_psd).any():
        return empty_summary

    peak_idx = int(np.nanargmax(non_dc_psd))
    dominant_frequency_hz = float(non_dc_freq[peak_idx])
    peak_psd = float(non_dc_psd[peak_idx])

    low_hz = float(band_low_hz) if band_low_hz is not None and np.isfinite(float(band_low_hz)) else 0.0
    high_hz = float(band_high_hz) if band_high_hz is not None and np.isfinite(float(band_high_hz)) else float(frequencies_hz[-1])

    low_hz = max(0.0, low_hz)
    high_hz = max(low_hz, high_hz)

    band_mask = (frequencies_hz >= low_hz) & (frequencies_hz <= high_hz)

    if band_mask.sum() >= 2:
        band_power = float(_integrate_trapezoid(psd[band_mask], frequencies_hz[band_mask]))
    elif band_mask.sum() == 1 and len(frequencies_hz) > 1:
        frequency_step_hz = float(np.nanmedian(np.diff(frequencies_hz)))
        band_power = float(psd[band_mask][0] * frequency_step_hz)
    else:
        band_power = np.nan

    duration_s = float(uniform_time_s[-1] - uniform_time_s[0]) if len(uniform_time_s) > 1 else np.nan

    return {
        "dominant_frequency_hz": dominant_frequency_hz,
        "band_power": band_power,
        "peak_psd": peak_psd,
        "duration_s": duration_s,
    }



def _compute_xyz_psd_summary(
    df: pd.DataFrame,
    axis_columns: list[str],
    band_low_hz: float,
    band_high_hz: float,
    time_col: str = "time_s",
    max_points: int = 65536,
) -> dict[str, float]:
    """Compute dominant frequency and band power from summed x/y/z PSD."""
    empty_summary = {
        "dominant_frequency_hz": np.nan,
        "band_power": np.nan,
        "peak_psd": np.nan,
        "duration_s": np.nan,
    }

    if df is None or df.empty or time_col not in df.columns:
        return empty_summary

    available_axes = [col for col in axis_columns if col in df.columns]
    if not available_axes:
        return empty_summary

    uniform_time_s, signal_matrix, sample_rate_hz, valid_columns = _prepare_uniform_time_series(
        df,
        available_axes,
        time_col=time_col,
        max_points=max_points,
    )

    if (
        len(uniform_time_s) < 16 or
        signal_matrix.size == 0 or
        not valid_columns or
        not np.isfinite(sample_rate_hz) or
        sample_rate_hz <= 0
    ):
        return empty_summary

    n_samples = signal_matrix.shape[1]
    if n_samples < 16:
        return empty_summary

    window = np.hanning(n_samples)
    window_power = np.sum(window ** 2)

    if window_power <= 0:
        return empty_summary

    frequencies_hz = np.fft.rfftfreq(n_samples, d=1.0 / sample_rate_hz)
    summed_psd = np.zeros_like(frequencies_hz, dtype=float)

    for signal_values in signal_matrix:
        centered = signal_values - np.nanmean(signal_values)
        spectrum = np.fft.rfft(centered * window)
        summed_psd += (np.abs(spectrum) ** 2) / (sample_rate_hz * window_power)

    non_dc_mask = frequencies_hz > 0
    if not non_dc_mask.any():
        return empty_summary

    non_dc_psd = summed_psd[non_dc_mask]
    non_dc_freq = frequencies_hz[non_dc_mask]

    if len(non_dc_psd) == 0 or not np.isfinite(non_dc_psd).any():
        return empty_summary

    peak_idx = int(np.nanargmax(non_dc_psd))
    dominant_frequency_hz = float(non_dc_freq[peak_idx])
    peak_psd = float(non_dc_psd[peak_idx])

    low_hz = float(band_low_hz) if band_low_hz is not None and np.isfinite(float(band_low_hz)) else 0.0
    high_hz = float(band_high_hz) if band_high_hz is not None and np.isfinite(float(band_high_hz)) else float(frequencies_hz[-1])

    low_hz = max(0.0, low_hz)
    high_hz = max(low_hz, high_hz)

    band_mask = (frequencies_hz >= low_hz) & (frequencies_hz <= high_hz)

    if band_mask.sum() >= 2:
        band_power = float(_integrate_trapezoid(summed_psd[band_mask], frequencies_hz[band_mask]))
    elif band_mask.sum() == 1 and len(frequencies_hz) > 1:
        frequency_step_hz = float(np.nanmedian(np.diff(frequencies_hz)))
        band_power = float(summed_psd[band_mask][0] * frequency_step_hz)
    else:
        band_power = np.nan

    duration_s = float(uniform_time_s[-1] - uniform_time_s[0]) if len(uniform_time_s) > 1 else np.nan

    return {
        "dominant_frequency_hz": dominant_frequency_hz,
        "band_power": band_power,
        "peak_psd": peak_psd,
        "duration_s": duration_s,
    }


def _compute_segmented_xyz_psd_summary(
    df: pd.DataFrame,
    axis_columns: list[str],
    band_low_hz: float,
    band_high_hz: float,
    min_segment_samples: int = 32,
    min_segment_duration_s: float = 0.25,
) -> dict[str, float]:
    """Aggregate summed-axis spectral metrics over contiguous segments of one phase."""
    summaries = []

    for segment_df in _split_contiguous_time_segments(df):
        if len(segment_df) < min_segment_samples:
            continue

        segment_duration_s = segment_df["time_s"].max() - segment_df["time_s"].min()
        if pd.isna(segment_duration_s) or segment_duration_s < min_segment_duration_s:
            continue

        summary = _compute_xyz_psd_summary(
            segment_df,
            axis_columns,
            band_low_hz,
            band_high_hz,
        )

        if pd.notna(summary["dominant_frequency_hz"]):
            summaries.append(summary)

    if not summaries:
        return {
            "dominant_frequency_hz": np.nan,
            "band_power": np.nan,
            "peak_psd": np.nan,
        }

    best_peak_summary = max(
        summaries,
        key=lambda item: item["peak_psd"] if pd.notna(item["peak_psd"]) else -np.inf,
    )

    weighted_band_power_sum = 0.0
    duration_sum = 0.0

    for summary in summaries:
        duration_s = summary.get("duration_s", np.nan)
        band_power = summary.get("band_power", np.nan)

        if pd.notna(duration_s) and duration_s > 0 and pd.notna(band_power):
            weighted_band_power_sum += float(band_power) * float(duration_s)
            duration_sum += float(duration_s)

    band_power = (
        weighted_band_power_sum / duration_sum
        if duration_sum > 0
        else np.nan
    )

    return {
        "dominant_frequency_hz": float(best_peak_summary["dominant_frequency_hz"]),
        "band_power": band_power,
        "peak_psd": float(best_peak_summary["peak_psd"]),
    }


def _compute_segmented_psd_summary(
    df: pd.DataFrame,
    signal_col: str,
    band_low_hz: float,
    band_high_hz: float,
    min_segment_samples: int = 32,
    min_segment_duration_s: float = 0.25,
) -> dict[str, float]:
    """Aggregate spectral metrics over multiple contiguous segments of one phase."""
    summaries = []

    for segment_df in _split_contiguous_time_segments(df):
        if len(segment_df) < min_segment_samples:
            continue

        segment_duration_s = segment_df["time_s"].max() - segment_df["time_s"].min()
        if pd.isna(segment_duration_s) or segment_duration_s < min_segment_duration_s:
            continue

        summary = _compute_single_signal_psd_summary(
            segment_df,
            signal_col,
            band_low_hz,
            band_high_hz,
        )

        if pd.notna(summary["dominant_frequency_hz"]):
            summaries.append(summary)

    if not summaries:
        return {
            "dominant_frequency_hz": np.nan,
            "band_power": np.nan,
            "peak_psd": np.nan,
        }

    best_peak_summary = max(
        summaries,
        key=lambda item: item["peak_psd"] if pd.notna(item["peak_psd"]) else -np.inf,
    )

    weighted_band_power_sum = 0.0
    duration_sum = 0.0

    for summary in summaries:
        duration_s = summary.get("duration_s", np.nan)
        band_power = summary.get("band_power", np.nan)

        if pd.notna(duration_s) and duration_s > 0 and pd.notna(band_power):
            weighted_band_power_sum += float(band_power) * float(duration_s)
            duration_sum += float(duration_s)

    band_power = (
        weighted_band_power_sum / duration_sum
        if duration_sum > 0
        else np.nan
    )

    return {
        "dominant_frequency_hz": float(best_peak_summary["dominant_frequency_hz"]),
        "band_power": band_power,
        "peak_psd": float(best_peak_summary["peak_psd"]),
    }


def _sum_positive_counter_increments_by_phase(
    df: pd.DataFrame,
    count_col: str,
) -> dict[str, float]:
    """Sum positive counter increments per contiguous phase segment."""
    if (
        df is None or
        df.empty or
        "flight_phase" not in df.columns or
        "time_s" not in df.columns or
        count_col not in df.columns
    ):
        return {}

    data = df[["time_s", "flight_phase", count_col]].dropna(subset=["time_s", "flight_phase"]).copy()
    data[count_col] = pd.to_numeric(data[count_col], errors="coerce")
    data = data.dropna(subset=[count_col]).sort_values("time_s")

    if data.empty:
        return {}

    phase_changed = data["flight_phase"] != data["flight_phase"].shift()
    data["phase_segment_id"] = phase_changed.cumsum()

    counts: dict[str, float] = {}

    for (_, phase_segment_id), segment_df in data.groupby(["flight_phase", "phase_segment_id"], sort=False):
        phase = str(segment_df["flight_phase"].iloc[0])
        signal = segment_df[count_col].dropna()

        if len(signal) < 2:
            increment = 0.0
        else:
            increment = float(signal.diff().clip(lower=0.0).fillna(0.0).sum())

        counts[phase] = counts.get(phase, 0.0) + increment

    return counts


def compute_per_phase_vibration_statistics(
    position: pd.DataFrame,
    sensor_accel: pd.DataFrame,
    sensor_gyro: pd.DataFrame,
    vibration_df: pd.DataFrame,
    band_low_hz: float = 20.0,
    band_high_hz: float = 250.0,
) -> pd.DataFrame:
    """Compute per-phase vibration metrics from accel, gyro, and clipping data.

    Axis RMS, vector RMS, p95 magnitude, crest factor, dominant frequency, and
    band power use mean-centered x/y/z signals so the table emphasizes vibration
    instead of static bias or gravity. Clipping counts are derived from positive
    increments of the normalized cumulative clipping counters.
    """
    empty_columns = [
        "flight_phase",
        "duration_s",
        "position_samples",
        "accel_samples",
        "gyro_samples",
        "accel_rms_x_m_s2",
        "accel_rms_y_m_s2",
        "accel_rms_z_m_s2",
        "accel_vector_rms_m_s2",
        "gyro_rms_x_rad_s",
        "gyro_rms_y_rad_s",
        "gyro_rms_z_rad_s",
        "gyro_vector_rms_rad_s",
        "p95_accel_magnitude_m_s2",
        "p95_gyro_magnitude_rad_s",
        "accel_crest_factor",
        "gyro_crest_factor",
        "accel_clipping_count",
        "gyro_clipping_count",
        "total_clipping_count",
        "accel_dominant_frequency_hz",
        "gyro_dominant_frequency_hz",
        "accel_band_power",
        "gyro_band_power",
    ]

    phase_duration_df = _compute_phase_durations(position)
    accel_df = _assign_flight_phase_to_topic(sensor_accel, position)
    gyro_df = _assign_flight_phase_to_topic(sensor_gyro, position)
    vib_df = _assign_flight_phase_to_topic(vibration_df, position)

    accel_axis_cols = ["accel_x_m_s2", "accel_y_m_s2", "accel_z_m_s2"]
    gyro_axis_cols = ["gyro_x_rad_s", "gyro_y_rad_s", "gyro_z_rad_s"]

    phases = set()
    if not phase_duration_df.empty and "flight_phase" in phase_duration_df.columns:
        phases.update(phase_duration_df["flight_phase"].dropna().astype(str).tolist())
    if not accel_df.empty and "flight_phase" in accel_df.columns:
        phases.update(accel_df["flight_phase"].dropna().astype(str).tolist())
    if not gyro_df.empty and "flight_phase" in gyro_df.columns:
        phases.update(gyro_df["flight_phase"].dropna().astype(str).tolist())
    if not vib_df.empty and "flight_phase" in vib_df.columns:
        phases.update(vib_df["flight_phase"].dropna().astype(str).tolist())

    if not phases:
        return pd.DataFrame(columns=empty_columns)

    duration_lookup = {}
    sample_lookup = {}
    if not phase_duration_df.empty:
        duration_lookup = dict(zip(phase_duration_df["flight_phase"].astype(str), phase_duration_df["duration_s"]))
        sample_lookup = dict(zip(phase_duration_df["flight_phase"].astype(str), phase_duration_df["position_samples"]))

    accel_clipping_lookup = _sum_positive_counter_increments_by_phase(vib_df, "accel_clipping_count")
    gyro_clipping_lookup = _sum_positive_counter_increments_by_phase(vib_df, "gyro_clipping_count")

    rows = []

    for phase in sorted(phases):
        accel_phase_df = (
            accel_df[accel_df["flight_phase"].astype(str) == phase].copy()
            if not accel_df.empty and "flight_phase" in accel_df.columns
            else pd.DataFrame()
        )
        gyro_phase_df = (
            gyro_df[gyro_df["flight_phase"].astype(str) == phase].copy()
            if not gyro_df.empty and "flight_phase" in gyro_df.columns
            else pd.DataFrame()
        )

        accel_metrics = _compute_centered_xyz_metrics(
            accel_phase_df,
            accel_axis_cols,
            "accel",
            "m_s2",
        )
        gyro_metrics = _compute_centered_xyz_metrics(
            gyro_phase_df,
            gyro_axis_cols,
            "gyro",
            "rad_s",
        )

        accel_psd_summary = _compute_segmented_xyz_psd_summary(
            accel_phase_df,
            accel_axis_cols,
            band_low_hz,
            band_high_hz,
        )
        gyro_psd_summary = _compute_segmented_xyz_psd_summary(
            gyro_phase_df,
            gyro_axis_cols,
            band_low_hz,
            band_high_hz,
        )

        accel_clipping_count = accel_clipping_lookup.get(phase, np.nan)
        gyro_clipping_count = gyro_clipping_lookup.get(phase, np.nan)

        if pd.notna(accel_clipping_count) or pd.notna(gyro_clipping_count):
            total_clipping_count = np.nansum([accel_clipping_count, gyro_clipping_count])
        else:
            total_clipping_count = np.nan

        rows.append({
            "flight_phase": phase,
            "duration_s": float(duration_lookup.get(phase, np.nan)),
            "position_samples": int(sample_lookup.get(phase, 0)),
            "accel_samples": int(len(accel_phase_df)),
            "gyro_samples": int(len(gyro_phase_df)),
            **accel_metrics,
            **gyro_metrics,
            "accel_clipping_count": accel_clipping_count,
            "gyro_clipping_count": gyro_clipping_count,
            "total_clipping_count": total_clipping_count,
            "accel_dominant_frequency_hz": accel_psd_summary["dominant_frequency_hz"],
            "gyro_dominant_frequency_hz": gyro_psd_summary["dominant_frequency_hz"],
            "accel_band_power": accel_psd_summary["band_power"],
            "gyro_band_power": gyro_psd_summary["band_power"],
        })

    result = pd.DataFrame(rows)

    for col in empty_columns:
        if col not in result.columns:
            result[col] = np.nan

    return result[empty_columns].sort_values("duration_s", ascending=False, na_position="last").reset_index(drop=True)


# -------------------------------------------------
# Selected-window tracking metric recomputation
# -------------------------------------------------

def recompute_rate_tracking_for_time_window(
    df: pd.DataFrame,
    max_lag_s: float = 0.5,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Recompute rate-tracking errors, selected-window lags, and metrics.

    The full tracking dataframe is still useful for plotting and caching, but the
    dashboard slider should report statistics only for the selected window. This
    helper takes the already window-filtered dataframe, recalculates the lag for
    that window, rebuilds the time-compensated error columns, and then computes
    the usual summary metrics.
    """
    result = df.copy().sort_values("time_s")
    error_columns: dict[str, str] = {}
    time_offsets_s: dict[str, float] = {}

    for axis in ["roll", "pitch", "yaw"]:
        actual_col = f"{axis}_rate_actual_deg_s"
        setpoint_col = f"{axis}_rate_setpoint_deg_s"
        filtered_setpoint_col = f"{axis}_rate_filtered_setpoint_deg_s"

        if actual_col in result.columns and setpoint_col in result.columns:
            error_col = f"{axis}_rate_error_deg_s"
            result[error_col] = result[setpoint_col] - result[actual_col]
            error_columns[axis] = error_col
            time_offsets_s[axis] = 0.0

            if len(result) >= 2:
                time_offset_s = sanitize_time_offset_s(
                    estimate_signal_lag_s(
                        result,
                        setpoint_col,
                        actual_col,
                        "time_s",
                        max_lag_s,
                    )
                )
                result = add_lag_compensated_error(
                    result,
                    setpoint_col,
                    actual_col,
                    time_offset_s,
                    f"{axis}_rate",
                    "deg_s",
                    "time_s",
                )
                error_columns[f"{axis}_time_compensated"] = (
                    f"{axis}_rate_time_compensated_error_deg_s"
                )
                time_offsets_s[f"{axis}_time_compensated"] = time_offset_s

        if actual_col in result.columns and filtered_setpoint_col in result.columns:
            filtered_error_col = f"{axis}_rate_filtered_error_deg_s"
            result[filtered_error_col] = result[filtered_setpoint_col] - result[actual_col]
            error_columns[f"{axis}_filtered"] = filtered_error_col
            time_offsets_s[f"{axis}_filtered"] = 0.0

            if len(result) >= 2:
                filtered_time_offset_s = sanitize_time_offset_s(
                    estimate_signal_lag_s(
                        result,
                        filtered_setpoint_col,
                        actual_col,
                        "time_s",
                        max_lag_s,
                    )
                )
                result = add_lag_compensated_error(
                    result,
                    filtered_setpoint_col,
                    actual_col,
                    filtered_time_offset_s,
                    f"{axis}_rate_filtered",
                    "deg_s",
                    "time_s",
                )
                error_columns[f"{axis}_filtered_time_compensated"] = (
                    f"{axis}_rate_filtered_time_compensated_error_deg_s"
                )
                time_offsets_s[f"{axis}_filtered_time_compensated"] = (
                    filtered_time_offset_s
                )

    if all(
        col in result.columns
        for col in [
            "roll_rate_error_deg_s",
            "pitch_rate_error_deg_s",
            "yaw_rate_error_deg_s",
        ]
    ):
        result["rate_error_magnitude_deg_s"] = np.sqrt(
            result["roll_rate_error_deg_s"] ** 2 +
            result["pitch_rate_error_deg_s"] ** 2 +
            result["yaw_rate_error_deg_s"] ** 2
        )

    if all(
        col in result.columns
        for col in [
            "roll_rate_filtered_error_deg_s",
            "pitch_rate_filtered_error_deg_s",
            "yaw_rate_filtered_error_deg_s",
        ]
    ):
        result["rate_filtered_error_magnitude_deg_s"] = np.sqrt(
            result["roll_rate_filtered_error_deg_s"] ** 2 +
            result["pitch_rate_filtered_error_deg_s"] ** 2 +
            result["yaw_rate_filtered_error_deg_s"] ** 2
        )

    metrics = compute_tracking_error_metrics(
        result,
        error_columns,
        time_offsets_s,
    )

    return result, metrics


def recompute_attitude_tracking_for_time_window(
    df: pd.DataFrame,
    max_lag_s: float = 0.5,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Recompute attitude-tracking errors, selected-window lags, and metrics."""
    result = df.copy().sort_values("time_s")
    error_columns: dict[str, str] = {}
    time_offsets_s: dict[str, float] = {}

    for axis in ["roll", "pitch", "yaw"]:
        actual_col = f"{axis}_actual_deg"
        setpoint_col = f"{axis}_setpoint_deg"
        filtered_setpoint_col = f"{axis}_filtered_setpoint_deg"
        angle_error_deg = axis == "yaw"

        if actual_col in result.columns and setpoint_col in result.columns:
            error_col = f"{axis}_error_deg"
            error = result[setpoint_col] - result[actual_col]
            if angle_error_deg:
                error = wrap_angle_error_deg(error)
            result[error_col] = error
            error_columns[axis] = error_col
            time_offsets_s[axis] = 0.0

            if len(result) >= 2:
                time_offset_s = sanitize_time_offset_s(
                    estimate_signal_lag_s(
                        result,
                        setpoint_col,
                        actual_col,
                        "time_s",
                        max_lag_s,
                    )
                )
                result = add_lag_compensated_error(
                    result,
                    setpoint_col,
                    actual_col,
                    time_offset_s,
                    f"{axis}",
                    "deg",
                    "time_s",
                    angle_error_deg=angle_error_deg,
                )
                error_columns[f"{axis}_time_compensated"] = (
                    f"{axis}_time_compensated_error_deg"
                )
                time_offsets_s[f"{axis}_time_compensated"] = time_offset_s

        if actual_col in result.columns and filtered_setpoint_col in result.columns:
            filtered_error_col = f"{axis}_filtered_error_deg"
            filtered_error = result[filtered_setpoint_col] - result[actual_col]
            if angle_error_deg:
                filtered_error = wrap_angle_error_deg(filtered_error)
            result[filtered_error_col] = filtered_error
            error_columns[f"{axis}_filtered"] = filtered_error_col
            time_offsets_s[f"{axis}_filtered"] = 0.0

            if len(result) >= 2:
                filtered_time_offset_s = sanitize_time_offset_s(
                    estimate_signal_lag_s(
                        result,
                        filtered_setpoint_col,
                        actual_col,
                        "time_s",
                        max_lag_s,
                    )
                )
                result = add_lag_compensated_error(
                    result,
                    filtered_setpoint_col,
                    actual_col,
                    filtered_time_offset_s,
                    f"{axis}_filtered",
                    "deg",
                    "time_s",
                    angle_error_deg=angle_error_deg,
                )
                error_columns[f"{axis}_filtered_time_compensated"] = (
                    f"{axis}_filtered_time_compensated_error_deg"
                )
                time_offsets_s[f"{axis}_filtered_time_compensated"] = (
                    filtered_time_offset_s
                )

    if all(
        col in result.columns
        for col in ["roll_error_deg", "pitch_error_deg", "yaw_error_deg"]
    ):
        result["attitude_error_magnitude_deg"] = np.sqrt(
            result["roll_error_deg"] ** 2 +
            result["pitch_error_deg"] ** 2 +
            result["yaw_error_deg"] ** 2
        )

    if all(
        col in result.columns
        for col in [
            "roll_filtered_error_deg",
            "pitch_filtered_error_deg",
            "yaw_filtered_error_deg",
        ]
    ):
        result["attitude_filtered_error_magnitude_deg"] = np.sqrt(
            result["roll_filtered_error_deg"] ** 2 +
            result["pitch_filtered_error_deg"] ** 2 +
            result["yaw_filtered_error_deg"] ** 2
        )

    metrics = compute_tracking_error_metrics(
        result,
        error_columns,
        time_offsets_s,
    )

    return result, metrics


def recompute_trajectory_tracking_for_time_window(
    df: pd.DataFrame,
    max_lag_s: float = 0.5,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Recompute trajectory-tracking errors, selected-window lags, and metrics."""
    result = df.copy().sort_values("time_s")

    result = remove_empty_columns(result, True)

    error_columns: dict[str, str] = {}
    time_offsets_s: dict[str, float] = {}

    # Position setpoints: raw and filtered errors are reported. The previous
    # analysis intentionally only applies time compensation to the filtered
    # position setpoint because that was the requested correction layer.
    for axis in ["x", "y", "z"]:
        actual_col = f"{axis}_actual_m"
        setpoint_col = f"{axis}_setpoint_m"
        filtered_setpoint_col = f"{axis}_filtered_setpoint_m"
        metric_name = f"{axis}_position"

        if actual_col in result.columns and setpoint_col in result.columns:
            error_col = f"{axis}_position_error_m"
            result[error_col] = result[setpoint_col] - result[actual_col]
            error_columns[metric_name] = error_col
            time_offsets_s[metric_name] = 0.0

        if actual_col in result.columns and filtered_setpoint_col in result.columns:
            filtered_metric_name = f"{metric_name}_filtered"
            filtered_error_col = f"{axis}_position_filtered_error_m"
            result[filtered_error_col] = result[filtered_setpoint_col] - result[actual_col]
            error_columns[filtered_metric_name] = filtered_error_col
            time_offsets_s[filtered_metric_name] = 0.0

            if len(result) >= 2:
                filtered_time_offset_s = sanitize_time_offset_s(
                    estimate_signal_lag_s(
                        result,
                        filtered_setpoint_col,
                        actual_col,
                        "time_s",
                        max_lag_s,
                    )
                )
                filtered_time_metric_name = (
                    f"{metric_name}_filtered_time_compensated"
                )
                result = add_lag_compensated_error(
                    result,
                    filtered_setpoint_col,
                    actual_col,
                    filtered_time_offset_s,
                    f"{axis}_position_filtered",
                    "m",
                    "time_s",
                )
                error_columns[filtered_time_metric_name] = (
                    f"{axis}_position_filtered_time_compensated_error_m"
                )
                time_offsets_s[filtered_time_metric_name] = filtered_time_offset_s

    if "altitude_actual_m" in result.columns and "altitude_setpoint_m" in result.columns:
        result["altitude_error_m"] = (
            result["altitude_setpoint_m"] - result["altitude_actual_m"]
        )
        error_columns["altitude"] = "altitude_error_m"
        time_offsets_s["altitude"] = 0.0

    if "altitude_actual_m" in result.columns and "altitude_filtered_setpoint_m" in result.columns:
        result["altitude_filtered_error_m"] = (
            result["altitude_filtered_setpoint_m"] - result["altitude_actual_m"]
        )
        error_columns["altitude_filtered"] = "altitude_filtered_error_m"
        time_offsets_s["altitude_filtered"] = 0.0

        if len(result) >= 2:
            filtered_time_offset_s = sanitize_time_offset_s(
                estimate_signal_lag_s(
                    result,
                    "altitude_filtered_setpoint_m",
                    "altitude_actual_m",
                    "time_s",
                    max_lag_s,
                )
            )
            result = add_lag_compensated_error(
                result,
                "altitude_filtered_setpoint_m",
                "altitude_actual_m",
                filtered_time_offset_s,
                "altitude_filtered",
                "m",
                "time_s",
            )
            error_columns["altitude_filtered_time_compensated"] = (
                "altitude_filtered_time_compensated_error_m"
            )
            time_offsets_s["altitude_filtered_time_compensated"] = (
                filtered_time_offset_s
            )

    for axis in ["vx", "vy", "vz"]:
        actual_col = f"{axis}_actual_m_s"
        setpoint_col = f"{axis}_setpoint_m_s"
        filtered_setpoint_col = f"{axis}_filtered_setpoint_m_s"
        metric_name = f"{axis}_velocity"

        if actual_col in result.columns and setpoint_col in result.columns:
            error_col = f"{axis}_velocity_error_m_s"
            result[error_col] = result[setpoint_col] - result[actual_col]
            error_columns[metric_name] = error_col
            time_offsets_s[metric_name] = 0.0

            if len(result) >= 2:
                time_offset_s = sanitize_time_offset_s(
                    estimate_signal_lag_s(
                        result,
                        setpoint_col,
                        actual_col,
                        "time_s",
                        max_lag_s,
                    )
                )
                result = add_lag_compensated_error(
                    result,
                    setpoint_col,
                    actual_col,
                    time_offset_s,
                    f"{axis}",
                    "m_s",
                    "time_s",
                )
                error_columns[f"{metric_name}_time_compensated"] = (
                    f"{axis}_time_compensated_error_m_s"
                )
                time_offsets_s[f"{metric_name}_time_compensated"] = time_offset_s

        if actual_col in result.columns and filtered_setpoint_col in result.columns:
            filtered_metric_name = f"{metric_name}_filtered"
            filtered_error_col = f"{axis}_velocity_filtered_error_m_s"
            result[filtered_error_col] = result[filtered_setpoint_col] - result[actual_col]
            error_columns[filtered_metric_name] = filtered_error_col
            time_offsets_s[filtered_metric_name] = 0.0

            if len(result) >= 2:
                filtered_time_offset_s = sanitize_time_offset_s(
                    estimate_signal_lag_s(
                        result,
                        filtered_setpoint_col,
                        actual_col,
                        "time_s",
                        max_lag_s,
                    )
                )
                filtered_time_metric_name = (
                    f"{metric_name}_filtered_time_compensated"
                )
                result = add_lag_compensated_error(
                    result,
                    filtered_setpoint_col,
                    actual_col,
                    filtered_time_offset_s,
                    f"{axis}_velocity_filtered",
                    "m_s",
                    "time_s",
                )
                error_columns[filtered_time_metric_name] = (
                    f"{axis}_velocity_filtered_time_compensated_error_m_s"
                )
                time_offsets_s[filtered_time_metric_name] = filtered_time_offset_s

    if "vertical_speed_actual_m_s" in result.columns and "vertical_speed_setpoint_m_s" in result.columns:
        result["vertical_speed_error_m_s"] = (
            result["vertical_speed_setpoint_m_s"] -
            result["vertical_speed_actual_m_s"]
        )
        error_columns["vertical_speed"] = "vertical_speed_error_m_s"
        time_offsets_s["vertical_speed"] = 0.0

        if len(result) >= 2:
            time_offset_s = sanitize_time_offset_s(
                estimate_signal_lag_s(
                    result,
                    "vertical_speed_setpoint_m_s",
                    "vertical_speed_actual_m_s",
                    "time_s",
                    max_lag_s,
                )
            )
            result = add_lag_compensated_error(
                result,
                "vertical_speed_setpoint_m_s",
                "vertical_speed_actual_m_s",
                time_offset_s,
                "vertical_speed",
                "m_s",
                "time_s",
            )
            error_columns["vertical_speed_time_compensated"] = (
                "vertical_speed_time_compensated_error_m_s"
            )
            time_offsets_s["vertical_speed_time_compensated"] = time_offset_s

    if "vertical_speed_actual_m_s" in result.columns and "vertical_speed_filtered_setpoint_m_s" in result.columns:
        result["vertical_speed_filtered_error_m_s"] = (
            result["vertical_speed_filtered_setpoint_m_s"] -
            result["vertical_speed_actual_m_s"]
        )
        error_columns["vertical_speed_filtered"] = "vertical_speed_filtered_error_m_s"
        time_offsets_s["vertical_speed_filtered"] = 0.0
    
        if len(result) >= 2:
            filtered_time_offset_s = sanitize_time_offset_s(
                estimate_signal_lag_s(
                    result,
                    "vertical_speed_filtered_setpoint_m_s",
                    "vertical_speed_actual_m_s",
                    "time_s",
                    max_lag_s,
                )
            )
            result = add_lag_compensated_error(
                result,
                "vertical_speed_filtered_setpoint_m_s",
                "vertical_speed_actual_m_s",
                filtered_time_offset_s,
                "vertical_speed_filtered",
                "m_s",
                "time_s",
            )
            error_columns["vertical_speed_filtered_time_compensated"] = (
                "vertical_speed_filtered_time_compensated_error_m_s"
            )
            time_offsets_s["vertical_speed_filtered_time_compensated"] = (
                filtered_time_offset_s
            )

    if all(col in result.columns for col in ["x_position_error_m", "y_position_error_m"]):
        result["horizontal_position_error_m"] = np.sqrt(
            result["x_position_error_m"] ** 2 +
            result["y_position_error_m"] ** 2
        )

    if all(
        col in result.columns
        for col in ["x_position_filtered_error_m", "y_position_filtered_error_m"]
    ):
        result["horizontal_position_filtered_error_m"] = np.sqrt(
            result["x_position_filtered_error_m"] ** 2 +
            result["y_position_filtered_error_m"] ** 2
        )

    if all(col in result.columns for col in ["vx_velocity_error_m_s", "vy_velocity_error_m_s"]):
        result["horizontal_velocity_error_m_s"] = np.sqrt(
            result["vx_velocity_error_m_s"] ** 2 +
            result["vy_velocity_error_m_s"] ** 2
        )

    if all(
        col in result.columns
        for col in ["vx_velocity_filtered_error_m_s", "vy_velocity_filtered_error_m_s"]
    ):
        result["horizontal_velocity_filtered_error_m_s"] = np.sqrt(
            result["vx_velocity_filtered_error_m_s"] ** 2 +
            result["vy_velocity_filtered_error_m_s"] ** 2
        )

    metrics = compute_tracking_error_metrics(
        result,
        error_columns,
        time_offsets_s,
    )

    return result, metrics
