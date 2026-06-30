# Flight Phase Tests

Related test file: [`tests/test_flight_phases.py`](../../tests/test_flight_phases.py)

## Purpose

These tests verify the rule-based flight phase classification and the derived position signals used by the dashboard.

The production functions under test are:

```python
classify_flight_state()
smooth_flight_phases()
analyze_position()
```

## Tests Covered

### `test_classify_flight_state_threshold_cases`

This parametrized test checks representative combinations of:

- Horizontal speed
- Vertical speed
- Altitude

Covered phase labels include:

- `ground`
- `hover`
- `strolling`
- `cruising`
- `shallow_stationary_ascend`
- `shallow_moving_ascend`
- `rapid_stationary_ascend`
- `rapid_moving_ascend`
- `shallow_stationary_descend`
- `shallow_moving_descend`
- `rapid_stationary_descend`
- `rapid_moving_descend`

Expected behavior:

- Each controlled input combination maps to the expected phase name.

### `test_smooth_flight_phases_rejects_short_transient_phase`

This test creates a short two-sample hover segment between longer ground and cruising segments.

Expected behavior:

- The short transient phase is rejected when it does not meet the minimum consecutive-sample requirement.

This verifies the debounce/smoothing logic used to avoid very short phase flicker.

### `test_analyze_position_adds_derived_motion_and_phase_columns`

This test uses a synthetic `vehicle_local_position` topic.

Expected derived signals include:

- `altitude_m`
- `speed_m_s`
- `horizontal_speed_m_s`
- `vertical_speed_m_s`
- `distance_from_home_m`
- `az_up_m_s2`
- `flight_phase_raw`
- `flight_phase`

The test checks that a first section below the ground altitude threshold is classified as `ground`, and a later section above the threshold with low speed is classified as `hover`.

## Interpretation

Passing these tests means that the phase rules and derived position signals behave as expected for controlled simple cases.

## Limitations

The tests do not prove that the thresholds are valid for every UAV, mission, or flight condition. The phase logic remains a rule-based approximation and may require tuning for different logs.
