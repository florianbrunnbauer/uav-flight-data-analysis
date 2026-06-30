# Attitude and Altitude Tests

Related test file: [`tests/test_attitude_altitude.py`](../../tests/test_attitude_altitude.py)

## Purpose

These tests verify the basic attitude and altitude conversions used throughout the dashboard.

The production functions under test are:

```python
quaternion_to_euler()
analyze_attitude()
analyze_altitude()
```

## Tests Covered

### `test_quaternion_to_euler_identity_quaternion`

This test checks that the identity quaternion produces zero roll, pitch, and yaw.

Input quaternion:

```text
w = 1, x = 0, y = 0, z = 0
```

Expected output:

```text
roll = 0°
pitch = 0°
yaw = 0°
```

### `test_quaternion_to_euler_single_axis_rotation`

This parametrized test checks simple single-axis rotations.

Covered cases:

- 90° roll
- 45° pitch
- 90° yaw

The pitch case deliberately avoids exactly 90°. Euler angles are singular at ±90° pitch, so roll and yaw are not uniquely defined at that point.

### `test_analyze_attitude_adds_roll_pitch_yaw_columns`

This test creates a synthetic `vehicle_attitude` topic containing a known yaw quaternion.

Expected behavior:

- `analyze_attitude()` adds `roll_deg`, `pitch_deg`, and `yaw_deg` columns.
- The yaw result matches the known synthetic input.

### `test_analyze_altitude_converts_ned_z_to_positive_altitude`

PX4 local position uses NED coordinates, where `z` is positive downward. The dashboard reports altitude as positive upward.

Input `z` values:

```text
0, -10, -20
```

Expected altitude values:

```text
0, 10, 20
```

The test also verifies the calculated altitude metrics:

- Maximum altitude
- Minimum altitude
- Altitude range
- Mean altitude

## Interpretation

Passing these tests means that the fundamental coordinate and attitude transformations behave as expected for controlled inputs.

## Limitations

These tests do not validate estimator quality, sensor alignment, or frame convention issues in arbitrary real logs. They only verify the implemented conversion logic.
