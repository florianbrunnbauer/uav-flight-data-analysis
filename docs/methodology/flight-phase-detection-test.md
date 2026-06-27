# Flight Phase Detection Test Page Methodology

## Page intent

The **Flight Phase Detection Test** page is a focused inspection page for the flight-phase classification logic used throughout the dashboard. It helps verify whether the detected flight phases are plausible when compared against altitude, position, horizontal speed, and vertical speed.

The page is mainly intended to answer the following questions:

- Does the automatic flight-phase classification match the visible motion of the vehicle?
- At which times does the vehicle transition between ground, hover, strolling, cruising, ascend, and descend phases?
- Are the selected phase thresholds reasonable for this log?
- Do altitude, North position, East position, horizontal speed, and vertical speed explain the phase labels?
- Are there suspicious phase changes that should be inspected on another page?

The page is best understood as a **phase-validation and motion-context page**. It is not a full diagnostic page and does not by itself prove the cause of a flight behavior.

## Required PX4 ULog topics

### `vehicle_local_position`

This is the only required PX4 topic for the current Flight Phase Detection Test page.

Required fields:

- `timestamp`
- `x`
- `y`
- `z`
- `vx`
- `vy`
- `vz`

Fields used by the current preprocessing but not directly shown in this page:

- `az`

The page uses the processed position dataframe returned by `flight.position`. This dataframe is created from `vehicle_local_position` and already contains the derived signals and phase labels used by the plots.

## Time base

For the full shared method, see [`methods/time-base.md`](methods/time-base.md).

All displayed signals use the relative time column:

```text
time_s = (timestamp - log_start_timestamp) / 1e6
```

The sidebar time-range slider filters the displayed position dataframe:

```text
selected rows = rows where selected_start_s <= time_s <= selected_end_s
```

All plots on this page use the filtered dataframe. This means the page is intentionally focused on the selected time interval rather than always showing the full flight.

## Signals shown on the page

### vehicle_local_position sample rate

The page displays an estimated sample rate for `vehicle_local_position`:

```text
dt = median(diff(time_s))
sample_rate_hz = 1 / dt
```

This value is useful because phase smoothing uses a fixed number of consecutive samples. For example, if the position topic is logged at approximately `10 Hz`, a 10-sample phase persistence rule corresponds to roughly `1 s`.

### Altitude plot

The altitude plot shows:

- x-axis: `time_s`
- y-axis: `altitude_m`
- background color: detected `flight_phase`

The plot helps verify ground, hover, ascend, and descend classification.

![Altitude plot](docs/screenshots/methodology/flight_phase_detection_test_altitude_plot.png)

### North position plot

The North position plot shows:

- x-axis: `time_s`
- y-axis: `x`
- background color: detected `flight_phase`

The plot helps identify motion along the local North axis.

![North position plot](docs/screenshots/methodology/flight_phase_detection_test_north_position.png)

### East position plot

The East position plot shows:

- x-axis: `time_s`
- y-axis: `y`
- background color: detected `flight_phase`

The plot helps identify motion along the local East axis.

![East position plot](docs/screenshots/methodology/flight_phase_detection_test_east_position.png)

### Horizontal speed plot

The horizontal speed plot shows:

- x-axis: `time_s`
- y-axis: `horizontal_speed_m_s`
- background color: detected `flight_phase`
- reference line at `0.35 m/s`
- reference line at `1.0 m/s`

The reference lines correspond to the current hover/strolling/cruising threshold logic.

![Horizontal speed plot](docs/screenshots/methodology/flight_phase_detection_test_horizontal_speed.png)

### Vertical speed plot

The vertical speed plot shows:

- x-axis: `time_s`
- y-axis: `vertical_speed_m_s`
- background color: detected `flight_phase`
- reference line at `0.5 m/s`
- reference line at `0.2 m/s`
- reference line at `-0.2 m/s`
- reference line at `-0.5 m/s`

The reference lines correspond to the near-level vertical-speed band and the shallow/rapid climb/descent split.

![Vertical speed plot](docs/screenshots/methodology/flight_phase_detection_test_vertical_speed.png)

### Phase legend

The sidebar contains a fixed phase legend. It displays the color associated with each phase defined in `phase_colors`.

The phase colors are used as transparent background bands behind the time-series plots. This allows the user to compare the classification result against the actual motion signals.

## Derived signals and formulas

For the full shared local-position method, see [`methods/local-position-signals.md`](methods/local-position-signals.md).

The Flight Phase Detection Test page uses the derived signals created during position preprocessing:

- `altitude_m` for the altitude plot and ground/airborne interpretation
- `horizontal_speed_m_s` for hover, strolling, cruising, and moving/stationary classification
- `vertical_speed_m_s` for level flight, ascend, and descend classification
- `x` and `y` for North/East position context

For the full shared phase method, see [`methods/flight-phase-classification.md`](methods/flight-phase-classification.md).

The page uses two phase columns created by the preprocessing:

```text
flight_phase_raw
flight_phase
```

The current plots use the smoothed `flight_phase` signal. A candidate phase must persist for at least 10 consecutive samples before it replaces the current phase. 

## Phase background generation

The page converts the selected `flight_phase` sequence into contiguous phase segments. Each segment contains:

```text
phase
start_time
end_time
```

The phase segments are then drawn as transparent vertical background rectangles behind each plot.

The current logic only creates background segments for the selected time range. Therefore, the background coloring always corresponds to the currently displayed interval.

## Current classification thresholds shown on the page

The horizontal-speed plot marks:

| Reference line | Meaning |
|---:|---|
| `0.35 m/s` | boundary between hover and strolling when vertical motion is near level |
| `1.0 m/s` | boundary between strolling and cruising, and between stationary and moving climb/descent |

The vertical-speed plot marks:

| Reference line | Meaning |
|---:|---|
| `0.2 m/s` | upper bound of near-level vertical motion |
| `-0.2 m/s` | lower bound of near-level vertical motion |
| `0.5 m/s` | boundary between shallow and rapid ascend |
| `-0.5 m/s` | boundary between shallow and rapid descend |

These visual threshold lines make the page useful for checking whether a phase label changed for an understandable reason.

## What can be analyzed with this page

The Flight Phase Detection Test page is suitable for:

- validating whether phase labels are plausible for the selected time range
- checking whether hover periods are detected where altitude and position are nearly constant
- checking whether climb and descent phases align with vertical speed
- checking whether strolling and cruising phases align with horizontal speed
- identifying threshold flicker near `0.2 m/s`, `0.35 m/s`, `0.5 m/s`, or `1.0 m/s`
- finding candidate hover segments for the Hover Analysis page
- locating climb, descent, or cruise segments for actuator, vibration, or tracking analysis
- identifying whether the fixed thresholds need adjustment for a different vehicle or log

Examples of useful observations:

- If the background switches to `hover` while horizontal speed is clearly above `0.35 m/s`, the phase classification should be reviewed.
- If the background remains `ground` after takeoff, the local altitude estimate or ground threshold may be inappropriate.
- If a climb is classified as `shallow_stationary_ascend`, vertical speed should be positive but below or equal to `0.5 m/s`, and horizontal speed should stay below `1.0 m/s`.
- If the phase background changes repeatedly around a threshold, the log may be near the threshold boundary or the smoothing rule may need adjustment.
- If the page shows long `hover` intervals, those intervals are good candidates for the Hover Analysis page.

## Recommended workflow example

1. Upload the PX4 `.ulg` file and open the **Flight Phase Detection Test** page.
2. Use the sidebar time-range slider to select the interval you want to validate.
3. Check the displayed `vehicle_local_position` sample rate.
4. Inspect the altitude plot first to identify ground, climb, hover, and descent behavior.
5. Inspect the North and East position plots to see whether the vehicle is translating laterally.
6. Inspect the horizontal-speed plot and compare the signal against the `0.35 m/s` and `1.0 m/s` reference lines.
7. Inspect the vertical-speed plot and compare the signal against the `±0.2 m/s` and `±0.5 m/s` reference lines.
8. Compare the phase background color against the threshold lines and visible motion.
9. Note any time intervals where the phase label looks wrong or ambiguous.
10. Continue with the specialized page that matches the interesting interval:
    - **Hover Analysis** for long hover segments
    - **Actuator Output Analysis** for climb, descent, or high-demand maneuver segments
    - **Vibration Analysis** for phases with high vibration or clipping
    - **Setpoint Tracking Analysis** for controller-following behavior

## Clear limitations

### The page is mainly a phase-validation page

Despite the page name, the current implementation is not a broad statistical report. It does not show a phase table, summary cards, or per-phase metric aggregation. It mainly visualizes position-derived signals with phase background coloring.

### The page does not prove flight quality

A plausible phase label does not mean the vehicle performed well. For example, a `hover` phase only means that horizontal and vertical speeds were below the selected thresholds. It does not prove good hover stability, low drift, low vibration, good controller tracking, or low actuator effort.

### Thresholds are fixed project defaults

The phase logic uses fixed speed and altitude thresholds. These may not fit every UAV, payload, positioning source, flight mode, wind condition, sampling rate, or mission profile.

### The page depends on local-position quality

All displayed signals are derived from `vehicle_local_position`. Estimator drift, position jumps, bad velocity estimates, or irregular sampling can distort the plots and phase labels.

### Ground detection depends on local altitude

The `ground` phase is based on `altitude_m < 0.5 m`. If the local altitude origin is shifted or the estimator initializes away from the true ground level, ground detection may be wrong.

### Phase smoothing can hide short events

The smoothed `flight_phase` label suppresses phase changes that last fewer than 10 consecutive samples. This makes plots easier to read but can hide very short maneuvers.

### The displayed sample rate is an estimate

The sample rate is calculated from the median time difference between `vehicle_local_position` samples. It is useful for interpretation, but it does not show logging jitter, dropped samples, or local variations in sampling interval.

### Background colors are only as accurate as the phase labels

The colored bands are not independent measurements. They are visualizations of the classification result. If the classification is wrong, the background colors will also be wrong.

### No attitude, actuator, vibration, or setpoint context

The page does not use attitude, actuator outputs, IMU vibration metrics, controller setpoints, GPS quality, estimator innovations, battery voltage, or flight-mode information. These signals must be inspected on dedicated pages if causal interpretation is needed.

### Public logs may lack mission context

If the log comes from a public source or another operator, the intended maneuver, mission mode, commanded path, environmental conditions, and airframe configuration may be unknown. In that case, the page should be used conservatively as a motion and phase-screening tool.