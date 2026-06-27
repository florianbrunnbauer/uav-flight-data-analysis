# Overview Page Methodology

## Page intent

The **Overview** page is the entry point for a first inspection of a PX4 `.ulg` flight log. Its purpose is to give a compact, high-level understanding of the flight before using more specialized pages such as hover analysis, actuator output analysis, vibration analysis, or setpoint tracking.

The page answers the following basic questions:

- How long was the recorded flight?
- How far did the vehicle travel in the local frame?
- What altitude, range, speed, climb, descent, roll, and pitch envelope did the log contain?
- Which broad flight phases were detected and how much time was spent in each phase?
- What did the trajectory look like in 3D, from above, over altitude, and with respect to distance from the local origin?

The page is designed for **orientation and screening**, not for final root-cause diagnosis. It should help identify interesting time windows and suspicious patterns that deserve deeper analysis on the dedicated pages.

## Required PX4 ULog topics

### `vehicle_local_position`

This is the primary topic for the Overview page. It is required for the flight path, altitude, speed, distance-from-home, flight summary metrics, and flight-phase statistics.

Required fields:

- `timestamp`
- `x`
- `y`
- `z`
- `vx`
- `vy`
- `vz`

Fields used by the current position preprocessing but not directly displayed on the Overview page:

- `az`

The local position frame is treated as a PX4 local NED-style frame. The reused local-position convention and derived signals are documented separately in [`methods/local-position-signals.md`](methods/local-position-signals.md).

### `vehicle_attitude`

This topic is required for the attitude summary metrics.

Required fields:

- `timestamp`
- `q[0]`
- `q[1]`
- `q[2]`
- `q[3]`

The quaternion is converted to Euler angles in degrees. The Overview page currently uses roll and pitch for maximum-attitude summary cards.

## Time base

For the full shared method, see [`methods/time-base.md`](methods/time-base.md).

All topics are converted to a relative time axis called `time_s`. The first available ULog timestamp is used as the zero reference, and timestamps are converted from microseconds to seconds:

```text
time_s = (timestamp - log_start_timestamp) / 1e6
```

This means all plots and metrics are shown relative to the beginning of the log, not as absolute wall-clock time.

## Signals shown on the page

### Summary cards

The page displays three groups of summary metrics:

#### Flight Summary

- Flight Time
- Distance Flown
- Max Range
- Max Altitude

#### Performance

- Max Ground Speed
- Avg Ground Speed
- Max Climb
- Max Descent

#### Attitude

- Max Roll
- Max Pitch

![Summary cards](docs/screenshots/methodology/overview_summary_card.png)

### Phase Statistics table

The phase table lists the detected flight phases and summarizes each phase by:

- phase name
- duration
- duration percentage
- number of samples
- average altitude
- average ground speed
- average vertical speed

![Phase Statistics table](docs/screenshots/methodology/overview_phase_statistics_table.png)

### 3D Flight Path

The 3D plot shows the complete local-position trajectory using:

- x-axis: North position `x` in meters
- y-axis: East position `y` in meters
- z-axis: calculated altitude `altitude_m` in meters

The selected time range is overlaid on top of the full trajectory to make it easier to locate the currently inspected segment within the complete flight. The same full-flight-plus-selected-period convention is also used in the top-down, altitude, and distance-from-home plots.

![3D Flight Path](docs/screenshots/methodology/overview_3d_flight_path.png)

### Top-Down Flight Path

The top-down plot shows the complete lateral flight path and overlays the selected time range. This makes it possible to inspect the selected segment while still seeing where it lies within the full mission.

- x-axis: East position `y` in meters
- y-axis: North position `x` in meters
- full flight trace: complete `vehicle_local_position` trajectory
- selected time-period trace: subset selected with the sidebar time-range slider

The axes are scaled equally so that the geometric shape of the path is not distorted.

![Top-Down Flight Path](docs/screenshots/methodology/overview_top_down_flight_path.png)

### Altitude Over Time

The altitude plot shows the complete `altitude_m` signal over `time_s` and overlays the selected time range. The full trace provides context for the complete climb/descent profile, while the selected trace highlights the currently inspected interval.

![Altitude Over Time](docs/screenshots/methodology/overview_altitude_over_time.png)

### Distance From Home Over Time

The range plot shows the complete `distance_from_home_m` signal over `time_s` and overlays the selected time range. The full trace helps identify the overall range envelope, while the selected trace makes it easier to inspect a specific excursion or return segment. In this project, “home” means the local-frame origin of the log, not necessarily the true takeoff point or an externally validated GPS home position.

![Distance From Home Over Time](docs/screenshots/methodology/overview_distance_from_home.png)

## Derived signals and formulas

The local-position-derived signals are documented separately in [`methods/local-position-signals.md`](methods/local-position-signals.md). The Overview page uses the following shared signals from that method:

- `altitude_m`
- `speed_m_s`
- `horizontal_speed_m_s`
- `vertical_speed_m_s`
- `distance_from_home_m`

The reused attitude conversion is documented separately in [`methods/quaternion-to-euler.md`](methods/quaternion-to-euler.md). The Overview page uses the converted Euler angles:

- `roll_deg`
- `pitch_deg`
- `yaw_deg`

The page itself does not introduce a separate coordinate convention. It uses the shared local-position and attitude methods and then derives page-level summary metrics from those processed signals.

## Derived overview metrics

### Flight Time

```text
flight_time_s = max(time_s)
```

Because `time_s` starts near zero, this is approximately the log duration.

### Distance Flown

The traveled distance is calculated as the sum of the Euclidean distance between consecutive local-position samples:

```text
dx = diff(x)
dy = diff(y)
dz = diff(z)
distance_step = sqrt(dx² + dy² + dz²)
distance_traveled_m = sum(distance_step)
```

This is a path-length estimate in the local position frame.

### Max Range

```text
max_distance_from_home_m = max(distance_from_home_m)
```

This is the largest horizontal distance from the local-frame origin.

### Max Altitude

```text
max_altitude_m = max(altitude_m)
```

### Max Ground Speed

```text
max_ground_speed_m_s = max(horizontal_speed_m_s)
```

### Avg Ground Speed

```text
avg_ground_speed_m_s = mean(horizontal_speed_m_s)
```

### Max Climb

```text
max_climb_rate_m_s = max(vertical_speed_m_s)
```

### Max Descent

```text
max_descent_rate_m_s = abs(min(vertical_speed_m_s))
```

### Max Roll and Max Pitch

```text
max_roll_deg = max(abs(roll_deg))
max_pitch_deg = max(abs(pitch_deg))
```

These are peak absolute attitude angles over the evaluated log.

## Flight-phase detection

For the full shared method, see [`methods/flight-phase-classification.md`](methods/flight-phase-classification.md).

The Overview page uses the flight phases calculated from `vehicle_local_position`. Phase classification is based on altitude, horizontal speed, and vertical speed.

The currently used thresholds are:

| Condition | Threshold |
|---|---:|
| Ground altitude threshold | `altitude_m < 0.5 m` |
| Hover vertical-speed threshold | `abs(vertical_speed_m_s) <= 0.2 m/s` |
| Hover horizontal-speed threshold | `horizontal_speed_m_s < 0.35 m/s` |
| Moving/cruising horizontal-speed threshold | `horizontal_speed_m_s >= 1.0 m/s` |
| Rapid climb/descent threshold | `abs(vertical_speed_m_s) > 0.5 m/s` |

The broad logic is:

- If altitude is below `0.5 m`, the phase is `ground`.
- If vertical speed is near zero and horizontal speed is below `0.35 m/s`, the phase is `hover`.
- If vertical speed is near zero and horizontal speed is between `0.35 m/s` and `1.0 m/s`, the phase is `strolling`.
- If vertical speed is near zero and horizontal speed is at least `1.0 m/s`, the phase is `cruising`.
- If vertical speed is positive, the phase is an ascend phase.
- If vertical speed is negative, the phase is a descend phase.
- Ascend and descend phases are further split into shallow/rapid and stationary/moving variants.

After raw classification, short phase changes are smoothed. A candidate phase must persist for at least 10 consecutive samples before it replaces the current phase. This reduces single-sample noise in the phase labels.

## Phase statistics

Phase statistics are calculated by assigning a duration to each position sample. For each row, the duration is the time difference to the next sample:

```text
dt_s = next_time_s - current_time_s
```

For the last row, the median sample interval is used as an approximation.

For each detected phase, the page derives:

```text
duration_s = sum(dt_s within phase)
duration_percent = duration_s / total_time_s * 100
samples = number of position samples in phase
avg_altitude_m = mean(altitude_m within phase)
avg_ground_speed_m_s = mean(horizontal_speed_m_s within phase)
avg_vertical_speed_m_s = mean(vertical_speed_m_s within phase)
```

Additional phase statistics may be computed internally, but the Overview table intentionally shows only the compact subset needed for a first inspection.

## What can be analyzed with this page

The Overview page is suitable for:

- identifying the approximate mission profile of the log
- checking whether the trajectory looks plausible in the local frame
- finding the altitude and speed envelope of the flight
- identifying the maximum local range from the starting origin
- spotting large path discontinuities, altitude jumps, or unusual range behavior
- locating interesting time windows for deeper analysis
- comparing how much time was spent on ground, hover, cruise, climb, and descent phases
- deciding which specialized page should be used next

Examples of useful observations:

- A high distance flown with a small max range suggests repeated motion near the origin.
- A high max range with low distance flown suggests one directional excursion.
- Altitude jumps or discontinuities may indicate estimator or logging artifacts.
- Long hover time suggests that the Hover Analysis page may be useful.
- High climb/descent values suggest reviewing altitude behavior and possibly actuator demand.
- Unexpected phase distributions may indicate that the phase thresholds need adjustment for the vehicle or log.

## Recommended workflow example

1. Upload the PX4 `.ulg` file and open the **Overview** page.
2. Check **Flight Time**, **Distance Flown**, **Max Range**, and **Max Altitude** to understand the basic flight scale.
3. Check **Performance** to identify whether the flight contains aggressive horizontal movement, climbing, or descending.
4. Check **Max Roll** and **Max Pitch** for large attitude excursions.
5. Inspect the **Phase Statistics** table to understand how much of the log is ground, hover, cruise, ascend, or descend.
6. Use the sidebar time-range slider to isolate a suspicious or interesting part of the flight.
7. Use the 3D path to see where the selected segment occurs in the complete trajectory.
8. Use the top-down plot to inspect lateral movement without altitude distraction.
9. Use the altitude plot to inspect climb, descent, or altitude-hold behavior.
10. Use the distance-from-home plot to understand whether the vehicle moved away from or returned toward the local origin.
11. Write down the time window of any suspicious behavior.
12. Continue with the specialized page that best matches the observation:
    - **Basic Flight Statistics** for phase classification details
    - **Hover Analysis** for hover stability
    - **Actuator Output Analysis** for motor-output behavior
    - **Vibration Analysis** for IMU vibration and clipping
    - **Setpoint Tracking Analysis** for controller tracking behavior

## Clear limitations

### The page is descriptive, not diagnostic

The Overview page shows what happened in the log, but it usually cannot explain why it happened. For example, it can show high speed, high climb rate, or a strange trajectory shape, but it cannot by itself prove controller problems, airframe imbalance, motor saturation, poor tuning, wind disturbance, or estimator failure.

### Summary cards are currently full-log metrics

In the current implementation, the sidebar time-range slider affects the highlighted selected trace in the 3D path, top-down path, altitude plot, and distance-from-home plot. The full-flight trace remains visible as context. However, the main summary cards and phase-statistics table are computed from the full log. Therefore, the selected time range should not be interpreted as changing the summary metrics unless the implementation is later modified to recompute those metrics for the selected window.

### Local position is not globally validated

The page uses the local-position estimate from `vehicle_local_position`. It does not independently validate GPS quality, estimator health, coordinate-frame drift, or absolute geographic position.

### “Home” means local-frame origin

`distance_from_home_m` is calculated from `x` and `y` relative to the local origin. This may differ from the true takeoff point, mission home, or GPS home depending on the log and estimator initialization.

### Distance flown is sensitive to noise and sample quality

The distance-flown estimate sums sample-to-sample 3D displacement. Position noise, estimator jumps, irregular sampling, or logging artifacts can inflate the calculated distance.

### Flight phase labels depend on fixed thresholds

The phase classification uses fixed speed and altitude thresholds. These thresholds may not be suitable for every vehicle, flight mode, mission type, wind condition, or sampling rate. Treat phase labels as a practical screening tool, not as ground truth.

### Phase smoothing can hide short events

The 10-sample persistence rule reduces noisy phase flicker, but it can also suppress very short maneuvers or delay the visible phase transition.

### Attitude interpretation is limited

Only maximum absolute roll and pitch are shown in the Overview summary. The page does not evaluate attitude tracking, yaw behavior, oscillations, attitude-rate limits, or controller performance.

### No actuator, vibration, or setpoint context

The Overview page does not use actuator outputs, actuator controls, IMU vibration metrics, setpoints, controller integrator status, battery data, GPS accuracy, or estimator innovation signals. Those must be analyzed on dedicated pages or with additional diagnostics.

### No pass/fail thresholds

The page does not define whether a flight was good or bad. Without vehicle-specific requirements, test conditions, payload, controller settings, and mission intent, the metrics should be interpreted as exploratory indicators only.

### Uploaded logs may lack mission context

If the `.ulg` file comes from a public source or another operator, the intended mission, commanded trajectory, environmental conditions, airframe configuration, and tuning goals may be unknown. In that case, conclusions should be limited to what is directly supported by the logged signals.