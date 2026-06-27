# Local Position Signals

## Purpose

This file documents the shared local-position signal convention used throughout the flight-data analysis dashboard. The goal is to define the position- and velocity-derived signals once, so page-specific methodology files can reference the same assumptions instead of repeating the same formulas.

These signals are used by the Overview, Basic Flight Statistics, Hover Analysis, Actuator Output Analysis, Vibration Analysis, and Setpoint Tracking pages.

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

Additional field used by some dashboard pages:

- `az`

The topic is loaded through `UlgReader.get_topic()`, which adds the shared relative time column `time_s`. For details, see [Time-Base Signal Handling](time-base.md).

## Coordinate convention

The dashboard treats `vehicle_local_position` as a local NED-style estimate:

| Field | Interpretation | Unit |
|---|---|---:|
| `x` | local North position | m |
| `y` | local East position | m |
| `z` | local Down position | m |
| `vx` | local North velocity | m/s |
| `vy` | local East velocity | m/s |
| `vz` | local Down velocity | m/s |

Because `z` and `vz` are down-positive, the dashboard converts them into up-positive altitude and vertical speed for readability.

## Derived signals

### Altitude

```text
altitude_m = -z
```

Positive `altitude_m` means the vehicle is above the local origin. This is easier to interpret in plots than the down-positive PX4 `z` coordinate.

### Total speed

```text
speed_m_s = sqrt(vx² + vy² + vz²)
```

This is the magnitude of the 3D local velocity vector.

### Horizontal speed / ground speed

```text
horizontal_speed_m_s = sqrt(vx² + vy²)
```

This is the horizontal velocity magnitude in the local North-East plane. It is used as the dashboard's ground-speed signal.

### Vertical speed

```text
vertical_speed_m_s = -vz
```

Positive values indicate upward motion. Negative values indicate downward motion.

### Distance from home / local origin

```text
distance_from_home_m = sqrt(x² + y²)
```

This is the 2D horizontal distance from the local-frame origin. Altitude is not included.

In this project, “home” means the local origin of `vehicle_local_position`. It should not automatically be interpreted as the true takeoff point, GPS home position, or mission home position.

### Upward acceleration

```text
az_up_m_s2 = -az
```

This is used where the dashboard wants to display acceleration in an up-positive convention. It is only available if the `az` field exists in `vehicle_local_position`.

## Use in the dashboard

The derived local-position signals are used for:

- 3D flight-path visualization
- top-down flight-path visualization
- altitude-over-time plots
- distance-from-home plots
- speed and vertical-speed plots
- flight summary metrics
- phase classification
- hover-segment selection
- actuator-response context
- vibration and phase correlation
- trajectory tracking comparisons

## Relation to flight-phase classification

Flight-phase classification depends directly on three derived local-position signals:

```text
altitude_m
horizontal_speed_m_s
vertical_speed_m_s
```

The phase classifier uses these signals to distinguish ground, hover, strolling, cruising, ascend, and descend phases. For the full phase logic, see [Flight Phase Classification](flight-phase-classification.md).

## Interpretation notes

### Local frame, not global position

The signals describe motion in the local estimator frame. They do not directly provide latitude, longitude, GPS accuracy, or global position quality.

### Altitude is relative

`altitude_m` is relative to the local `z` origin. It is not automatically height above ground level unless the local origin coincides with the ground reference.

### Distance from home is a 2D range

`distance_from_home_m` ignores altitude. A vehicle climbing vertically above the origin can have a near-zero distance from home even at high altitude.

### Speed signs differ by axis convention

The original PX4 `vz` is down-positive. The dashboard's `vertical_speed_m_s` is up-positive. This makes climb positive and descent negative.

## Limitations

### Estimator-dependent signals

All derived signals depend on the quality of `vehicle_local_position`. Estimator drift, reset events, poor GPS/vision input, bad velocity estimates, or discontinuities can distort the derived metrics.

### Local origin may not equal true home

The local origin can differ from the actual takeoff point or configured mission home position. Treat `distance_from_home_m` as distance from the local origin unless the log confirms otherwise.

### Distance and speed are sensitive to noise

Sample-to-sample position noise can inflate distance traveled. Velocity noise can affect horizontal-speed, vertical-speed, and phase classification.

### No independent validation

This method does not validate the estimator, GPS quality, barometer quality, or external motion-capture source. It only documents how the dashboard derives signals from the logged local-position topic.
