# Tracking Error Metrics Methodology

## Method intent

This method describes how the dashboard compares commanded setpoints with measured vehicle response. It is shared by the **Setpoint Tracking Analysis** page for body-rate, attitude, and trajectory tracking.

The purpose is not only to calculate one tracking-error number. The method separates four related views of tracking behavior:

- raw setpoint tracking error
- tracking error after low-pass filtering the setpoint
- tracking error after compensating an estimated time offset
- tracking error after both setpoint filtering and time-offset compensation

This separation helps distinguish between poor tracking caused by high-frequency command content, poor tracking caused by response delay, and poor tracking that remains even after those diagnostic corrections.

## Required inputs

The method requires a dataframe with:

- a common time column `time_s`
- one or more setpoint columns
- one or more measured response columns
- finite overlapping samples in the selected time window

The specific source topics depend on the tracking type:

| Tracking type | Setpoint source | Measured response source |
|---|---|---|
| Body-rate tracking | `vehicle_rates_setpoint` | `vehicle_angular_velocity` |
| Attitude tracking | `vehicle_attitude_setpoint` | `vehicle_attitude` |
| Trajectory tracking | `trajectory_setpoint` | `vehicle_local_position` |

All comparisons use the relative log time described in [`time-base.md`](time-base.md).

## Unit conventions

The dashboard converts several PX4 signals into user-facing engineering units before calculating and displaying metrics:

| Signal group | Dashboard unit |
|---|---|
| Body rates | degrees per second `[deg/s]` |
| Attitude angles | degrees `[deg]` |
| Position | meters `[m]` |
| Altitude | meters `[m]` |
| Velocity | meters per second `[m/s]` |
| Vertical speed | meters per second `[m/s]` |

For trajectory tracking, PX4 local-position `z` uses the NED convention. Therefore altitude and vertical speed use the sign convention documented in [`local-position-signals.md`](local-position-signals.md):

```text
altitude_m = -z
vertical_speed_m_s = -vz
```

## Topic alignment

The tracking dataframes are aligned by time before the error signals are calculated. The implementation uses nearest-neighbor style alignment with `time_s` as the common key.

This is suitable for dashboard-level screening, but it is not a full reconstruction of PX4's internal control-loop timing. Small timing errors can remain if topics have different publication rates, delayed timestamps, or missing samples.

## Low-pass filtered setpoints

Filtered setpoints are generated with a first-order causal low-pass filter. The current default cutoff frequency is:

```text
DEFAULT_SETPOINT_LOW_PASS_CUTOFF_HZ = 2.0 Hz
```

The filter uses the actual sample spacing from `time_s`, not a fixed hard-coded timestep.

For each valid sample:

```text
tau_s = 1 / (2*pi*cutoff_hz)
alpha = dt_s / (tau_s + dt_s)
filtered[i] = filtered[i-1] + alpha * (signal[i] - filtered[i-1])
```

The first finite sample initializes the filter state. Samples with missing time or missing signal value remain `NaN` and do not update the filter state.

### Reason for filtering

The filtered setpoint is an analysis signal, not a replacement for the original PX4 setpoint. It helps answer whether high raw tracking error is caused mainly by rapid setpoint changes that the aircraft cannot physically follow within the selected time window.

If the filtered error is much lower than the raw error, the raw setpoint may contain high-frequency content or step-like changes. If the filtered error remains high, the issue is less likely to be explained only by high-frequency setpoint content.

## Angle handling

Yaw signals can cross the ±180° boundary. Direct subtraction near this boundary can create artificial jumps. Therefore yaw error is wrapped to the range:

```text
[-180°, 180°]
```

For filtering angular setpoints, the yaw signal is unwrapped before filtering and wrapped again afterward. This avoids false filter transients at the ±180° discontinuity.

Roll and pitch are not currently treated as wraparound signals in the same way because they are normally interpreted within a smaller attitude range for the analyzed flight logs.

For the quaternion-to-Euler conversion used by attitude tracking, see [`quaternion-to-euler.md`](quaternion-to-euler.md).

## Raw tracking error

The basic error definition is:

```text
error = setpoint - actual
```

The sign convention means:

- positive error: setpoint is above the measured response
- negative error: setpoint is below the measured response

For yaw attitude error, the wrapped angular difference is used:

```text
yaw_error = wrap_to_minus_180_plus_180(yaw_setpoint - yaw_actual)
```

## Time-offset estimation

The dashboard estimates the lag between setpoint and measured response with a cross-correlation search.

The current search limit is approximately:

```text
max_lag_s = 0.5 s
```

Before correlation, both the reference signal and response signal are mean-centered:

```text
reference_centered = reference - mean(reference)
response_centered = response - mean(response)
```

This makes the lag estimate focus on signal shape rather than static offset.

The lag with the highest correlation is selected. If the signal is too short, invalid, nearly constant, or otherwise unsuitable, the lag is treated as unavailable and sanitized to `0.0 s` for reporting where appropriate.

## Time-compensated setpoint

For a positive estimated lag, the implementation interprets the actual response as delayed relative to the setpoint:

```text
actual(t) ≈ setpoint(t - lag_s)
```

The time-compensated setpoint is created by interpolation:

```text
time_compensated_setpoint(t) = setpoint(t - lag_s)
```

The time-compensated error is then:

```text
time_compensated_error = time_compensated_setpoint - actual
```

Values outside the available interpolation range are set to `NaN` and are not included in the metric calculations.

## Error-row variants

Where the required signals are available, the metrics table can contain these variants:

| Variant | Meaning | Reported `time_offset_s` |
|---|---|---|
| Raw | Original setpoint minus actual response | `0.0` |
| Filtered | Low-pass filtered setpoint minus actual response | `0.0` |
| Time-compensated | Original setpoint shifted by estimated lag, then compared with actual response | estimated lag |
| Filtered time-compensated | Filtered setpoint shifted by estimated lag, then compared with actual response | estimated lag |

Not every signal group has every variant. The available rows depend on the available PX4 fields and on the current implementation for that tracking type.

## Summary metrics

For each finite error signal, the following metrics are calculated:

| Metric | Formula / meaning |
|---|---|
| `samples` | Number of finite error samples in the selected time window. |
| `time_offset_s` | Estimated lag used for the row. Raw and filtered rows use `0.0 s`. |
| `bias` | `mean(error)` |
| `mean_abs_error` | `mean(abs(error))` |
| `rmse` | `sqrt(mean(error²))` |
| `p95_abs` | 95th percentile of `abs(error)` |
| `max_abs` | `max(abs(error))` |

### Interpretation of the metrics

`bias` is useful for persistent offset. A large positive or negative bias indicates that the response is consistently below or above the setpoint according to the implemented sign convention.

`mean_abs_error` is easier to interpret than bias when positive and negative errors cancel each other.

`rmse` penalizes large errors more strongly than mean absolute error. It is useful for finding axes with short but severe tracking deviations.

`p95_abs` is a robust high-error indicator. It is less sensitive to single-sample outliers than `max_abs`.

`max_abs` is useful for finding worst-case events, but it should always be checked visually because single-sample spikes can dominate it.

## Body-rate error magnitude

For body-rate tracking, the dashboard also calculates a compact three-axis error magnitude:

```text
rate_error_magnitude_deg_s = sqrt(
    roll_rate_error_deg_s² +
    pitch_rate_error_deg_s² +
    yaw_rate_error_deg_s²
)
```

This signal is used for the actuator-effort comparison. It is not a substitute for the per-axis metrics because it hides which axis caused the error.

## Selected-window recomputation

Tracking metrics are recalculated for the selected sidebar time window. This matters because tracking quality can be very different during hover, climb, descent, cruising, or aggressive maneuvers.

A full-log tracking score can hide localized problems. The selected-window approach allows the user to isolate a meaningful part of the flight before interpreting the metrics.

## Recommended interpretation workflow

1. Start with the raw setpoint-vs-actual plot.
2. Check whether the error is mostly offset, delay, overshoot, undershoot, or high-frequency mismatch.
3. Compare raw error metrics with filtered error metrics.
4. Compare filtered error metrics with filtered time-compensated metrics.
5. Treat a strong improvement after time compensation as evidence of delay, not as proof that the controller is otherwise perfect.
6. Inspect the time series before drawing conclusions from a single metric row.

## Clear limitations

### The filtered setpoint is diagnostic only

The filtered setpoint is created by the analysis tool. It is not necessarily the same signal used internally by PX4. It should be interpreted as a diagnostic aid for separating rapid setpoint content from lower-frequency tracking behavior.

### Cross-correlation lag is approximate

The lag estimate can be unreliable if the selected signal is nearly constant, too short, noisy, dominated by impulses, or not causally related. It is most meaningful when setpoint and response have similar shapes.

### Time compensation does not prove root cause

An improvement after time compensation suggests that delay contributes to the measured error. It does not prove whether the delay comes from estimator latency, controller behavior, actuator dynamics, filtering, logging timestamps, or topic alignment.

### Error metrics depend on the selected time window

Changing the selected time range can change all metrics. A window with aggressive setpoints is not directly comparable to a window with smooth setpoints unless the operating conditions are considered.

### Nearest-neighbor alignment is not exact synchronization

The dashboard aligns topics for analysis, but PX4 internal control loops may operate at different rates and with different timestamp semantics. The results should be treated as engineering-screening metrics, not exact control-loop reconstruction.

### Trajectory tracking is indirect

Trajectory tracking includes setpoint generation, estimator behavior, position control, velocity control, attitude control, and actuator response. Body-rate tracking is closer to the inner control loop and is usually more direct for controller-response screening.
