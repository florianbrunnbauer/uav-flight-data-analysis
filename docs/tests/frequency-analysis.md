# Frequency Analysis Tests

Related test file: [`tests/test_frequency_analysis.py`](../../tests/test_frequency_analysis.py)

## Purpose

These tests verify the FFT and PSD functions used by the Vibration Analysis page.

The production functions under test are:

```python
compute_signal_fft()
compute_accel_psd()
compute_time_resolved_psd_surface()
```

## Tests Covered

### `test_compute_signal_fft_detects_known_sine_frequency`

This test creates a sine wave with:

- Sample rate: `200 Hz`
- Duration: `2 s`
- Frequency: `20 Hz`
- Amplitude: `3`

Expected behavior:

- The FFT output is not empty.
- The sample rate is detected correctly.
- The number of samples is correct.
- The dominant non-DC frequency is close to `20 Hz`.
- The estimated amplitude is close to the synthetic amplitude.

### `test_compute_accel_psd_detects_known_acceleration_frequency`

This test creates synthetic three-axis acceleration data with a known `25 Hz` vibration component.

Expected behavior:

- The PSD output is not empty.
- The sample rate is detected correctly.
- The dominant acceleration frequency is close to `25 Hz`.
- The selected accelerometer axis columns are reported correctly.

### `test_compute_time_resolved_psd_surface_returns_stable_time_frequency_grid`

This test creates a sine wave and computes sliding-window PSD heatmap data.

Expected behavior:

- A PSD surface is returned for the signal.
- The sample rate is detected correctly.
- The PSD window duration matches the requested value.
- The physical update interval matches the requested value.
- The PSD matrix shape matches the time and frequency axes.
- The dominant frequency in the first PSD row is close to the known input frequency.

## Interpretation

Passing these tests means that the FFT and PSD analysis functions can recover known frequencies from controlled synthetic signals and return output structures suitable for plotting.

## Limitations

These tests do not validate every possible sampling condition or every real-world vibration scenario. Real logs may contain impulses, changing sample rates, aliasing, noise, clipping, and missing sensor topics.
