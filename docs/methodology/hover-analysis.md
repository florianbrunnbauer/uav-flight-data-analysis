# Hover Analysis Page Methodology

## Page intent

The **Hover Analysis** page is a focused inspection page for hover segments detected in a PX4 `.ulg` flight log. Its purpose is to separate individual hover periods from the full flight and evaluate their local position, altitude, velocity, and attitude stability.

This page answers the following questions:

- Which hover segments were detected in the log?
- How long did each hover segment last?
- How stable was the vehicle altitude during a selected hover segment?
- How much horizontal drift occurred around the segment center?
- How much roll, pitch, and yaw variation occurred during hover?
- Which hover segment is more stable or less stable relative to the others?
- Do the detected hover segments look plausible in the altitude-over-time context?

The page is designed for **segment-level hover stability screening**. It is more specific than the Overview page because it does not summarize the whole flight. Instead, it isolates hover periods and evaluates each selected hover segment independently.

The page should not be interpreted as a final proof of controller quality, airframe balance, GPS quality, or tuning quality. It can identify suspicious hover behavior, but it cannot determine the root cause by itself.

## Required PX4 ULog topics

### `vehicle_local_position`

This topic is required for hover detection, hover segmentation, altitude stability, horizontal drift, and velocity stability.

Required fields:

- `timestamp`
- `x`
- `y`
- `z`
- `vx`
- `vy`
- `vz`

Fields used by the shared position preprocessing but not directly shown as raw fields on this page:

- `az`

The page uses the processed dataframe returned by `flight.position`. This dataframe already contains the derived local-position signals and detected flight phases.

### `vehicle_attitude`

This topic is required for roll, pitch, and yaw stability metrics.

Required fields:

- `timestamp`
- `q[0]`
- `q[1]`
- `q[2]`
- `q[3]`

The quaternion is converted to Euler angles in degrees before hover stability is calculated.

## Time base

For the full shared method, see [`methods/time-base.md`](methods/time-base.md).

All signals on the page use the relative time column:

```text
time_s = (timestamp - log_start_timestamp) / 1e6
```

Hover segments are defined by start and end times in this relative time axis. The segment start and end values are taken from contiguous stretches where `flight_phase == "hover"`.

## Hover segment detection

The Hover Analysis page does not independently classify hover from scratch. It uses the `flight_phase` column that was already added during local-position preprocessing.

The workflow is:

```text
1. Load processed vehicle_local_position dataframe.
2. Split the dataframe into contiguous phase segments.
3. Keep only segments where flight_phase == "hover".
4. Remove hover segments shorter than the sidebar minimum-duration threshold.
5. Let the user select one remaining hover segment for detailed analysis.
```

The sidebar control **Minimum hover duration [s]** filters out very short hover segments. In the current implementation, the default minimum duration is `3 s`, and the selectable range is `1 s` to `30 s`.

This filter is important because very short hover-like intervals may be transition artifacts rather than meaningful hover periods.

## Signals shown on the page

### Altitude with hover segments

The first plot shows the full altitude profile of the flight:

- x-axis: `time_s`
- y-axis: `altitude_m`
- highlighted regions: detected hover segments that pass the minimum-duration filter

This plot gives context before selecting a hover segment. It helps verify whether the detected hover segments occur during plausible altitude-hold periods.

![Altitude with hover segments](docs/screenshots/methodology/hover_analysis_altitude_with_hover_segments.png)

### Detected hover segments table

The table lists all hover segments that pass the minimum-duration filter. For each segment, the page shows:

- hover segment number
- start time
- end time
- duration
- mean altitude
- altitude RMS
- altitude 95th percentile absolute error
- RMS drift
- drift 95th percentile
- average ground speed
- roll standard deviation
- pitch standard deviation
- yaw standard deviation
- yaw range

The table is useful for comparing hover segments before choosing one for detailed inspection.

![Detected hover segments table](docs/screenshots/methodology/hover_analysis_detected_hover_segments_table.png)

### Hover selector

The selector lists each hover segment using a compact label containing:

- hover number
- start time
- end time
- duration
- RMS drift
- yaw standard deviation

The selected segment is then used for all detailed metrics and plots below.

![Hover selector](docs/screenshots/methodology/hover_analysis_hover_selector.png)

### Hover metric overview

The **Hover Metric Overview** plot compares selected hover metrics against adjustable reference bands.

The reference bands are exploratory. They are not pass/fail limits. They are intended to make relative differences easier to see and can be adjusted in the sidebar.

The current reference-band metrics are:

- Altitude RMS
- Altitude 95%
- Drift RMS
- Drift 95%
- Avg ground speed
- Roll STD
- Pitch STD
- Yaw STD

Each metric is classified as:

- `low`
- `elevated`
- `high`
- `unknown`

The classification is based on user-adjustable lower-is-better reference values.

![Hover metric overview](docs/screenshots/methodology/hover_analysis_hover_metrics_overview.png)

### Detailed hover stability metrics

The page displays selected stability metrics as cards grouped by topic:

#### General hover metrics

- Duration
- Avg Ground Speed
- Max Ground Speed

#### Altitude stability metrics

- Mean Altitude
- Altitude STD
- Altitude RMS
- Altitude Range
- Altitude 95%
- Altitude 99%

#### Drift stability metrics

- RMS Drift
- Drift 95%
- Drift 99%
- Drift STD
- Max Drift

#### Attitude stability metrics

- Mean Yaw
- Yaw Range
- Max Yaw Drift
- Yaw STD
- Roll STD
- Pitch STD

![Detailed hover stability metrics](docs/screenshots/methodology/hover_analysis_detailed_hover_stability_metrics.png)

### Normalized altitude plot

This plot shows altitude deviation around the selected hover segment mean:

- x-axis: `time_s`
- y-axis: `altitude_drift_cm`
- horizontal reference line at zero
- horizontal reference lines at positive and negative altitude standard deviation
- horizontal reference lines at positive and negative altitude 95th percentile absolute error

The fixed display range in the current implementation is approximately `-25 cm` to `25 cm`. Values outside this range may be clipped visually, so the metric cards should still be checked.

![Normalized altitude plot](docs/screenshots/methodology/hover_analysis_normalized_altitude.png)

### Horizontal drift magnitude plot

This plot shows the horizontal distance from the selected hover segment center:

- x-axis: `time_s`
- y-axis: `drift_from_center_cm`
- horizontal reference line at RMS drift
- horizontal reference line at drift 95th percentile

The fixed display range in the current implementation is approximately `0 cm` to `40 cm`. Values outside this range may be clipped visually.

![Horizontal drift magnitude plot](docs/screenshots/methodology/hover_analysis_horizontal_drift_magnitude.png)

### 2D XY hover drift plot

This plot shows the lateral hover movement around the calculated segment center:

- x-axis: East error `y_error_cm`
- y-axis: North error `x_error_cm`
- origin marker: calculated hover center

The axes are scaled equally so the shape of the drift pattern is not distorted.

![2D XY hover drift plot](docs/screenshots/methodology/hover_analysis_2d_xy_hover_drift.png)

### Velocity plot

The velocity plot shows:

- `horizontal_speed_m_s`
- `vertical_speed_m_s`

The plot helps verify whether the selected segment actually behaves like a hover period. Ideally, both signals should remain small and centered near the expected hover thresholds.

![Velocity plot](docs/screenshots/methodology/hover_analysis_velocity.png)

### Roll / Pitch plot

The roll/pitch plot shows:

- `roll_deg`
- `pitch_deg`

The plot is used to inspect attitude variation during hover. Large or periodic roll/pitch motion may indicate aggressive corrections, external disturbance, estimator problems, or controller behavior that should be checked on other pages.

![Roll / Pitch plot](docs/screenshots/methodology/hover_analysis_roll_pitch.png)

### Yaw drift plot

The yaw plot shows yaw deviation around the selected segment mean:

- x-axis: `time_s`
- y-axis: `yaw_drift_deg`
- horizontal reference line at zero
- horizontal reference lines at positive and negative yaw standard deviation

Yaw is unwrapped before the statistics are calculated. This prevents a transition through `-180° / +180°` from creating a false yaw jump.

![Yaw drift plot](docs/screenshots/methodology/hover_analysis_yaw_drift.png)

## Derived signals and formulas

The basic local-position formulas are documented in [`methods/local-position-signals.md`](methods/local-position-signals.md). The quaternion-to-Euler conversion is documented in [`methods/quaternion-to-euler.md`](methods/quaternion-to-euler.md).

The Hover Analysis page adds segment-specific derived signals.

### Segment duration

For the selected hover segment, the duration is calculated by assigning a duration to each position sample:

```text
dt_s = next_time_s - current_time_s
```

For the last row, the median segment sample interval is used as an approximation.

```text
duration_s = sum(dt_s)
```

This avoids the common mistake of estimating duration only from the first and last sample without considering sample spacing.

### Hover segment center

The horizontal hover center is calculated from the selected hover segment:

```text
center_x = mean(x)
center_y = mean(y)
```

This center is not an externally known target position. It is only the mean position of the selected segment.

### Horizontal position error

The page reports hover drift in centimeters:

```text
x_error_cm = (x - center_x) * 100
y_error_cm = (y - center_y) * 100
```

### Drift from center

```text
drift_from_center_cm = sqrt(x_error_cm² + y_error_cm²)
```

This is the horizontal radial distance from the calculated hover center.

### Mean altitude

```text
mean_altitude_m = mean(altitude_m)
```

### Altitude drift

Altitude drift is reported in centimeters relative to the selected segment mean altitude:

```text
altitude_drift_cm = (altitude_m - mean_altitude_m) * 100
```

### Yaw unwrapping

Yaw is unwrapped before calculating yaw statistics:

```text
yaw_unwrapped_deg = unwrap(yaw_deg)
```

The unwrapping step avoids artificial discontinuities when yaw crosses the `-180° / +180°` boundary.

### Yaw drift

```text
yaw_drift_deg = yaw_unwrapped_deg - mean(yaw_unwrapped_deg)
```

This expresses yaw as a deviation around the selected hover segment mean.

### Attitude interpolation

The attitude dataframe and position dataframe may not have identical timestamps. For hover stability metrics, roll, pitch, and yaw are interpolated onto the hover position timestamps:

```text
roll_at_hover_time  = interpolate(roll_deg, hover_time_s)
pitch_at_hover_time = interpolate(pitch_deg, hover_time_s)
yaw_at_hover_time   = interpolate(yaw_deg, hover_time_s)
```

This allows one set of segment metrics to be computed on a common time axis.

## Derived hover metrics

### Altitude STD

```text
altitude_std_cm = std(altitude_drift_cm)
```

This measures the standard deviation of altitude around the selected segment mean.

### Altitude RMS

```text
altitude_rms_cm = sqrt(mean(altitude_drift_cm²))
```

This measures the root-mean-square altitude deviation from the selected segment mean.

### Altitude 95% and 99%

```text
altitude_p95_abs_cm = quantile(abs(altitude_drift_cm), 0.95)
altitude_p99_abs_cm = quantile(abs(altitude_drift_cm), 0.99)
```

These metrics describe the upper tail of absolute altitude deviation.

### Altitude range

```text
altitude_range_cm = max(altitude_drift_cm) - min(altitude_drift_cm)
```

This describes the peak-to-peak altitude variation within the selected segment.

### RMS drift

```text
rms_drift_cm = sqrt(mean(drift_from_center_cm²))
```

This measures the root-mean-square horizontal drift radius around the selected segment center.

### Drift 95% and 99%

```text
drift_p95_cm = quantile(drift_from_center_cm, 0.95)
drift_p99_cm = quantile(drift_from_center_cm, 0.99)
```

These metrics describe the upper tail of horizontal drift.

### Drift STD

```text
drift_std_cm = std(drift_from_center_cm)
```

This measures variation in the radial drift signal.

### Max drift

```text
max_drift_cm = max(drift_from_center_cm)
```

This is the largest horizontal distance from the calculated hover center.

### Ground-speed metrics

```text
avg_ground_speed_m_s = mean(horizontal_speed_m_s)
max_ground_speed_m_s = max(horizontal_speed_m_s)
```

These metrics indicate whether the segment is truly close to stationary in the horizontal plane.

### Roll and pitch metrics

```text
roll_std_deg = std(roll_deg)
pitch_std_deg = std(pitch_deg)
max_abs_roll_deg = max(abs(roll_deg))
max_abs_pitch_deg = max(abs(pitch_deg))
```

The page currently displays roll and pitch standard deviation as primary hover attitude metrics.

### Yaw metrics

```text
mean_yaw_deg = mean(yaw_unwrapped_deg)
yaw_std_deg = std(yaw_unwrapped_deg)
yaw_range_deg = max(yaw_unwrapped_deg) - min(yaw_unwrapped_deg)
max_abs_yaw_drift_deg = max(abs(yaw_drift_deg))
```

These metrics describe heading variation during the selected hover segment.

## What can be analyzed with this page

The Hover Analysis page is suitable for:

- comparing multiple detected hover segments in one log
- checking whether a selected hover segment is stable enough to inspect further
- identifying altitude oscillation during hover
- identifying lateral drift around a hover center
- checking whether hover motion is biased in one direction
- detecting yaw drift or yaw oscillation during hover
- comparing roll/pitch activity during otherwise stationary flight
- finding time windows for deeper actuator, tracking, vibration, or estimator analysis

Examples of useful observations:

- High altitude RMS with low horizontal drift suggests vertical control or altitude-estimation issues may be worth checking.
- High RMS drift with low altitude RMS suggests horizontal position hold or external disturbance may be more relevant than altitude control.
- High average ground speed during a hover-labeled segment may indicate that the hover threshold is too permissive or the phase classification is wrong for this vehicle.
- High yaw drift with stable roll and pitch suggests heading behavior should be inspected separately.
- Repeated oscillatory roll/pitch during hover may justify checking controller tracking, actuator output, or vibration behavior in the same time window.

## Recommended workflow example

1. Open the **Hover Analysis** page.
2. Check the altitude overview plot to see where hover segments occur in the flight.
3. Adjust **Minimum hover duration [s]** to remove very short hover-like segments that are not useful for analysis.
4. Review the **Detected Hover Segments** table.
5. Compare duration, mean altitude, altitude RMS, RMS drift, yaw STD, and yaw range.
6. Select one hover segment from the selector.
7. Inspect the **Hover Metric Overview** to compare the selected segment against the current reference bands.
8. Adjust reference bands only if you have a reason, such as a known vehicle baseline, test requirement, or measurement environment.
9. Check the detailed altitude, drift, velocity, roll/pitch, and yaw plots.
10. Note the start and end time of any suspicious segment.
11. Continue with another page depending on the observation:
    - **Basic Flight Statistics** if the hover label itself looks questionable.
    - **Actuator Output Analysis** if hover drift or attitude correction appears related to motor-output behavior.
    - **Vibration Analysis** if the hover segment contains oscillations or possible IMU vibration.
    - **Setpoint Tracking Analysis** if hover errors may be related to setpoint-following behavior.

## Clear limitations

### The page depends on phase classification quality

Hover segments are selected from the existing `flight_phase` column. If the phase classification thresholds are unsuitable for the vehicle or log, the Hover Analysis page may analyze the wrong segments. The hover label should always be checked against altitude, horizontal speed, and vertical speed.

### The hover center is calculated, not commanded

The horizontal center is the mean `x` and `y` position of the selected segment. It is not necessarily the intended target position, GPS mission waypoint, takeoff point, or pilot-commanded hover location.

### Good relative stability does not prove good absolute position accuracy

A vehicle can appear stable around its local-position estimate even if the global position estimate is biased or drifting. This page does not independently validate GPS quality, optical flow, estimator innovations, or absolute position accuracy.

### Reference bands are not pass/fail limits

The hover metric reference bands are practical visualization aids. They are adjustable and exploratory. Without vehicle-specific requirements, baseline logs, test conditions, wind information, and sensor quality information, they should not be interpreted as objective pass/fail thresholds.

### Fixed plot ranges can hide large excursions

Some plots use fixed display ranges for readability. If a signal exceeds the displayed range, the plot may visually clip the excursion. The numerical metric cards and table should therefore be checked in addition to the plots.

### Interpolation can hide timing details

Attitude is interpolated onto the hover position timestamps. This is useful for common segment metrics, but it can hide small timing differences between topics. For detailed time-delay analysis, use the setpoint tracking page or inspect the original topic rates.

### Yaw unwrapping is necessary but not a full heading-quality check

Yaw unwrapping prevents artificial wraparound jumps, but it does not validate magnetometer quality, estimator yaw consistency, or heading reference accuracy.

### Hover stability does not prove controller performance by itself

Stable hover metrics can suggest good behavior, but they do not prove that the controller is well tuned. Unstable hover metrics can indicate a problem, but they do not prove the cause. Wind, estimator drift, GPS quality, airframe imbalance, actuator limits, vibration, payload, and mission context may all affect hover behavior.

### Public or unknown logs have limited interpretability

If the log comes from a public database or another operator, the mission intent, vehicle configuration, control mode, environment, and expected hover tolerance may be unknown. In that case, conclusions should remain descriptive and exploratory.