# Tracking Tests

Related test file: [`tests/test_tracking.py`](../../tests/test_tracking.py)

## Purpose

These tests verify the basic tracking-error metrics and signal lag estimation used by the Setpoint Tracking Analysis page.

The production functions under test are:

```python
compute_tracking_error_metrics()
estimate_signal_lag_s()
```

## Tests Covered

### `test_compute_tracking_error_metrics_for_known_error_signal`

This test uses a known error signal:

```text
[1, -1, 2, -2]
```

Expected metrics:

- Samples: `4`
- Bias: `0`
- Mean absolute error: `1.5`
- RMSE: `sqrt(2.5)`
- Maximum absolute error: `2`
- Time offset: preserved from the provided input dictionary

This verifies the numerical correctness of the summary metrics.

### `test_compute_tracking_error_metrics_uses_zero_for_missing_time_offset`

This test uses an all-NaN error signal and a NaN time offset.

Expected behavior:

- The sample count is `0`.
- The reported time offset is sanitized to `0.0`.
- Error metrics such as RMSE remain NaN.

This prevents NaN time offsets from being displayed as meaningful values.

### `test_estimate_signal_lag_detects_delayed_response`

This test creates a synthetic reference signal and a delayed response signal.

Expected behavior:

- `estimate_signal_lag_s()` returns the known delay within one sample interval.

The synthetic signal uses multiple pulse-like features instead of a pure sine wave to avoid ambiguity from periodic correlation peaks.

## Interpretation

Passing these tests means that the tracking summary metrics and lag-estimation logic work for controlled synthetic signals.

## Limitations

Lag estimation in real flight logs can be affected by noise, filtering, estimator delay, irregular sampling, saturation, and rapidly changing setpoints. A detected lag should be interpreted as an analysis aid, not as automatic proof of controller delay.
