# Quaternion-to-Euler Conversion

## Purpose

This file documents the shared method used to convert PX4 attitude quaternions into roll, pitch, and yaw angles for dashboard plots and summary metrics.

The conversion is used wherever the analysis needs human-readable attitude angles instead of quaternion components.

## Source topic requirement

The method uses the PX4 ULog topic:

```text
vehicle_attitude
```

Required fields:

- `timestamp`
- `q[0]`
- `q[1]`
- `q[2]`
- `q[3]`

The log reader adds:

- `time_s`

## Quaternion convention used in this project

The implementation treats the quaternion components as:

```text
q[0] = w
q[1] = x
q[2] = y
q[3] = z
```

The conversion function is called as:

```python
quaternion_to_euler(q[0], q[1], q[2], q[3])
```

The resulting angles are returned in degrees:

```text
roll_deg
pitch_deg
yaw_deg
```

## Implemented formulas

Given:

```text
w = q[0]
x = q[1]
y = q[2]
z = q[3]
```

Roll is calculated as:

```text
roll = atan2(2(w x + y z), 1 - 2(x² + y²))
```

Pitch is calculated as:

```text
pitch = asin(clip(2(w y - z x), -1, 1))
```

Yaw is calculated as:

```text
yaw = atan2(2(w z + x y), 1 - 2(y² + z²))
```

The results are then converted from radians to degrees:

```text
roll_deg  = degrees(roll)
pitch_deg = degrees(pitch)
yaw_deg   = degrees(yaw)
```

The pitch input is clipped to the range `[-1, 1]` before applying `asin`. This prevents small numerical errors from producing invalid values slightly outside the mathematical domain of `asin`.

## Interpretation of the angles

### Roll

Roll describes rotation around the vehicle's forward/backward body axis. In the dashboard it is mainly used to show lateral attitude behavior and maximum absolute roll.

### Pitch

Pitch describes nose-up / nose-down attitude behavior. In the dashboard it is mainly used to show longitudinal attitude behavior and maximum absolute pitch.

### Yaw

Yaw describes heading angle. It is usually displayed separately from roll and pitch because yaw can span a much wider range.

## Use in the dashboard

The converted attitude signals are used for:

- roll / pitch / yaw time-series plots
- maximum absolute roll and pitch summary cards
- hover-attitude stability metrics
- attitude tracking analysis
- actuator-response interpretation

## Recommended validation checks

When using this method on a new log or after changing the implementation, check:

1. Roll and pitch remain in physically plausible ranges for the vehicle.
2. Yaw wrapping around `-180°` / `180°` is expected and not interpreted as a real jump.
3. The sign convention agrees with the PX4 local/body-frame convention used elsewhere in the project.
4. The quaternion components are not reordered accidentally.
5. The attitude plots are visually consistent with the flight path and velocity behavior.

## Limitations

### Euler angles can wrap

Yaw normally wraps at `-180°` / `180°`. A line plot may show a sudden jump at the wrap point even if the physical heading changed smoothly.

For statistics involving yaw drift, yaw should be unwrapped first when needed.

### Euler angles have singularities

Euler-angle representations have known singularity issues near `±90°` pitch. This is usually not a problem for normal multirotor flight, but it is a limitation of the representation.

### The method is convention-dependent

Quaternion-to-Euler conversion depends on quaternion ordering, rotation direction, and frame convention. This project uses the convention implemented in `analysis.py`. If the input topic or PX4 convention changes, the conversion must be rechecked.

### Roll and pitch summaries are not controller diagnostics

Maximum roll and pitch show the attitude envelope of the flight. They do not by themselves prove whether the controller is well tuned, whether the vehicle is balanced, or whether external disturbances were present.

### Yaw interpretation requires care

Yaw behavior can be affected by wrap-around, heading reference, estimator behavior, and commanded yaw setpoints. A yaw plot should not be over-interpreted without checking the relevant setpoint and estimator information.

## Practical interpretation rule

Use the converted Euler angles for readability and visual inspection. For deeper control or estimator analysis, always combine them with setpoints, angular rates, actuator outputs, and flight context.
