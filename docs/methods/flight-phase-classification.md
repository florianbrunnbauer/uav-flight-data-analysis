# Flight Phase Classification

## Purpose

This file documents the shared method used to classify the flight into broad phases such as ground, hover, strolling, cruising, ascend, and descend.

The method is intended as a practical screening tool. It helps structure plots, tables, hover detection, actuator analysis, vibration analysis, and page navigation. It is not a certified flight-mode detector and should not be interpreted as ground truth.

## Source topic requirement

The method uses the PX4 ULog topic:

```text
vehicle_local_position
```

Required fields:

- `timestamp`
- `x`
- `y`
- `z`
- `vx`
- `vy`
- `vz`

The log reader adds:

- `time_s`

## Derived input signals

The classification does not use raw `x`, `y`, and `z` directly. It first derives altitude, horizontal speed, and vertical speed.

### Altitude

PX4 local position uses a down-positive `z` coordinate. Therefore altitude is calculated as:

```text
altitude_m = -z
```

### Horizontal speed

```text
horizontal_speed_m_s = sqrt(vx² + vy²)
```

This is also used as ground speed in several dashboard pages.

### Vertical speed

PX4 local velocity `vz` is positive downward. Therefore upward vertical speed is calculated as:

```text
vertical_speed_m_s = -vz
```

Positive `vertical_speed_m_s` means climbing. Negative `vertical_speed_m_s` means descending.

## Thresholds

The current implementation uses fixed thresholds:

| Meaning | Variable | Threshold |
|---|---:|---:|
| Ground altitude threshold | `altitude_m` | `< 0.5 m` |
| Hover vertical-speed threshold | `abs(vertical_speed_m_s)` | `<= 0.2 m/s` |
| Hover horizontal-speed threshold | `horizontal_speed_m_s` | `< 0.35 m/s` |
| Movement / cruising threshold | `horizontal_speed_m_s` | `< 1.0 m/s` or `>= 1.0 m/s` |
| Rapid climb/descent threshold | `abs(vertical_speed_m_s)` | `> 0.5 m/s` |

These values are practical project defaults. They are not universal vehicle limits.

## Classification logic

For each position sample, the method evaluates altitude, horizontal speed, and vertical speed.

### 1. Ground

If altitude is below the ground threshold:

```text
altitude_m < 0.5
```

The phase is:

```text
ground
```

### 2. Near-level vertical motion

If vertical speed is close to zero:

```text
abs(vertical_speed_m_s) <= 0.2
```

The method classifies the sample by horizontal speed:

| Horizontal speed condition | Phase |
|---|---|
| `< 0.35 m/s` | `hover` |
| `>= 0.35 m/s` and `< 1.0 m/s` | `strolling` |
| `>= 1.0 m/s` | `cruising` |

### 3. Ascend

If vertical speed is positive and outside the near-level band:

```text
vertical_speed_m_s > 0.2
```

The phase is an ascend phase.

Ascend phases are split by climb rate and horizontal movement:

| Condition | Phase |
|---|---|
| `vertical_speed_m_s <= 0.5` and `horizontal_speed_m_s < 1.0` | `shallow_stationary_ascend` |
| `vertical_speed_m_s <= 0.5` and `horizontal_speed_m_s >= 1.0` | `shallow_moving_ascend` |
| `vertical_speed_m_s > 0.5` and `horizontal_speed_m_s < 1.0` | `rapid_stationary_ascend` |
| `vertical_speed_m_s > 0.5` and `horizontal_speed_m_s >= 1.0` | `rapid_moving_ascend` |

### 4. Descend

If vertical speed is negative and outside the near-level band:

```text
vertical_speed_m_s < -0.2
```

The phase is a descend phase.

Descend phases are split by descent rate and horizontal movement:

| Condition | Phase |
|---|---|
| `vertical_speed_m_s >= -0.5` and `horizontal_speed_m_s < 1.0` | `shallow_stationary_descend` |
| `vertical_speed_m_s >= -0.5` and `horizontal_speed_m_s >= 1.0` | `shallow_moving_descend` |
| `vertical_speed_m_s < -0.5` and `horizontal_speed_m_s < 1.0` | `rapid_stationary_descend` |
| `vertical_speed_m_s < -0.5` and `horizontal_speed_m_s >= 1.0` | `rapid_moving_descend` |

## Raw and smoothed phase labels

The classification produces two phase columns:

```text
flight_phase_raw
flight_phase
```

### `flight_phase_raw`

This is the direct sample-by-sample classification from the threshold logic.

### `flight_phase`

This is the smoothed phase label used by the dashboard. Short phase changes are suppressed unless the candidate phase persists for a minimum number of consecutive samples.

The current persistence setting is:

```text
min_consecutive_samples = 10
```

A new candidate phase must therefore last for at least 10 consecutive samples before replacing the current phase.

## Why smoothing is used

Without smoothing, small velocity noise around a threshold can make the phase label flicker rapidly between categories. This is especially likely near the boundaries between hover, strolling, shallow ascend, and shallow descend.

Smoothing makes plots and phase tables more readable by reducing single-sample or very short phase changes.

## Phase statistics

Phase statistics should be calculated from accumulated sample intervals:

```text
dt_s = next_time_s - current_time_s
duration_s = sum(dt_s within phase)
```

This is better than using only the first and last timestamp of a phase because the same phase can occur in multiple separated segments.

Common phase statistics include:

- duration
- duration percentage
- sample count
- average altitude
- average horizontal speed
- average vertical speed
- maximum altitude
- maximum ground speed
- maximum climb rate
- maximum descent rate

## Use in the dashboard

Flight phases are used for:

- Overview phase summary table
- Basic Flight Statistics phase-colored plots
- hover-segment detection
- actuator-output interpretation by phase
- vibration analysis by phase
- background phase shading in time-series plots
- selecting interesting time windows for deeper analysis

## Recommended usage

Use phase classification as an orientation tool. It is useful for answering questions like:

- Was the vehicle on ground, hovering, climbing, descending, or cruising?
- Which phase dominates the log?
- Which phase contains unusual actuator demand, vibration, or tracking error?
- Which hover segments are long enough for a dedicated hover-stability analysis?

## Limitations

### Fixed thresholds are not universal

The thresholds are project defaults. They may not fit every vehicle, mission, payload, wind condition, controller tuning, sampling rate, or positioning source.

### The method does not know the commanded flight mode

The classifier does not use PX4 flight mode, arming state, mission commands, offboard commands, or setpoints. It only looks at estimated motion.

### Hover does not prove stable hover

A `hover` label only means low horizontal and vertical motion according to the thresholds. It does not prove good position hold, low attitude variation, low vibration, or good controller performance.

### Ground detection depends on local altitude

Ground is detected from `altitude_m < 0.5 m`. If the local origin, estimator altitude, or takeoff reference is shifted, ground detection can be wrong.

### Smoothing can hide short events

The 10-sample persistence rule improves readability, but it can also hide short maneuvers or delay visible transitions.

### Phase labels are descriptive, not causal

The classifier describes motion state. It does not explain why the vehicle climbed, descended, drifted, accelerated, or vibrated.

### Public logs may lack mission context

If the log comes from a public source, the intended mission and test objective may be unknown. Phase labels should therefore be interpreted conservatively.

## Practical interpretation rule

Treat flight phases as a structured overview layer. They are very useful for grouping and visualizing the log, but final engineering conclusions should be supported by the relevant raw signals, setpoints, actuator outputs, vibration metrics, and mission context.
