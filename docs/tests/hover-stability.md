# Hover Stability Tests

Related test file: [`tests/test_hover_stability.py`](../../tests/test_hover_stability.py)

## Purpose

These tests verify the hover stability metrics used by the Hover Analysis page.

The production functions under test are:

```python
compute_hover_stability()
compute_hover_stability_for_segment()
```

## Tests Covered

### `test_compute_hover_stability_returns_none_when_no_hover_phase_exists`

This test provides position data with no `hover` phase.

Expected behavior:

- `compute_hover_stability()` returns `None`.

This confirms that the function handles logs without detected hover segments safely.

### `test_compute_hover_stability_basic_metrics`

This test creates a synthetic hover segment with controlled position, altitude, speed, and attitude values.

Expected behavior:

- Hover duration is calculated from `dt_s`.
- Altitude range matches the known input.
- Maximum horizontal drift matches the known position offset.
- Average ground speed matches the input.
- Roll standard deviation matches the synthetic attitude signal.

### `test_compute_hover_stability_for_segment_reports_cm_metrics_and_unwrapped_yaw`

This test evaluates one selected time segment.

Expected behavior:

- Position drift and altitude drift are reported in centimeters.
- `altitude_drift_cm` is added to the returned hover DataFrame.
- Yaw is unwrapped before yaw statistics are calculated.
- A yaw sequence crossing ±180° does not create an artificial large yaw jump.

## Interpretation

Passing these tests means that the hover metric calculations work for controlled hover data and that yaw wrapping is handled correctly.

## Limitations

The tests do not define pass/fail flight-quality limits. Hover quality still depends on vehicle type, estimator quality, positioning source, wind, controller tuning, and mission requirements.
