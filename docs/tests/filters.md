# Filter Tests

Related test file: [`tests/test_filters.py`](../../tests/test_filters.py)

## Purpose

These tests verify the behavior of the first-order causal low-pass filter used for setpoint smoothing.

The production function under test is:

```python
low_pass_filter_signal()
```

## Tests Covered

### `test_low_pass_filter_step_response_uses_actual_time_spacing`

This test applies the filter to a simple step input.

Input:

- Time: `[0.0, 1.0]`
- Signal: `[0.0, 10.0]`
- Cutoff: `1.0 Hz`

Expected behavior:

- The first output sample equals the first valid input sample.
- The second output sample follows the first-order filter equation using the actual sample spacing.

This verifies that the filter uses the time vector rather than assuming a fixed sample rate.

### `test_low_pass_filter_invalid_cutoff_returns_original_signal`

This test passes a cutoff frequency of `0.0 Hz`.

Expected behavior:

- The function returns the original signal as a float series.

This verifies the intended bypass behavior for disabled or invalid filtering.

### `test_low_pass_filter_rejects_length_mismatch`

This test supplies time and signal arrays with different lengths.

Expected behavior:

- A `ValueError` is raised.

This protects against silently filtering misaligned data.

## Interpretation

Passing these tests means that the low-pass filter behaves correctly for basic controlled inputs and handles invalid usage safely.

## Limitations

These tests do not validate whether a specific cutoff frequency is appropriate for a real flight log. Cutoff selection is an analysis choice and depends on the vehicle, controller, setpoint frequency, and analysis objective.
