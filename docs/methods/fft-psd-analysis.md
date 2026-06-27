# FFT and PSD Analysis

## Purpose

This file documents the shared frequency-domain methodology used by the flight-data analysis dashboard. The goal is to explain how the project turns PX4 log signals into FFT spectra, PSD curves, dominant-frequency estimates, time-resolved PSD heatmaps, and frequency-band power metrics.

The method is currently used most heavily by the **Vibration Analysis** page. It is also used for actuator-control frequency content and can be reused by future pages that compare oscillations, vibration, or command-frequency behavior.

## Current implementation summary

The current implementation has three important design choices:

1. Sensor data is normalized before spectral analysis. Accelerometer and gyroscope columns are converted to consistent dashboard column names.
2. Frequency-domain calculations are performed on a uniformly resampled signal, because FFT and PSD calculations require approximately regular sample spacing.
3. PSD heatmaps are calculated in linear physical units, but can be displayed in dB to make weaker frequency content visible when one peak or transient dominates the color scale.

## Source signal selection

### Accelerometer source

For vibration analysis, the dashboard prefers high-rate accelerometer data from `sensor_combined`.

The accelerometer source priority is:

1. `sensor_combined: raw_accelerometer_m_s2[0..2]`
2. `sensor_combined: accelerometer_m_s2[0..2]`
3. fallback to `sensor_accel` if `sensor_combined` is unavailable or does not contain usable accelerometer fields

The normalized dashboard columns are:

- `accel_x_m_s2`
- `accel_y_m_s2`
- `accel_z_m_s2`
- `accel_magnitude_m_s2`
- `sensor_accel_axis_columns`

This means a plot label may still say `sensor_accel` for readability, but the actual source can be `sensor_combined`. The source-field table in the Vibration Analysis page should be checked when interpreting sample rate and FFT axes.

### Gyroscope source

For gyroscope vibration analysis, the dashboard prefers `sensor_combined`.

The gyroscope source priority is:

1. `sensor_combined: gyro_rad[0..2]`
2. fallback to `sensor_gyro` if `sensor_combined` is unavailable or does not contain usable gyroscope fields

The normalized dashboard columns are:

- `gyro_x_rad_s`
- `gyro_y_rad_s`
- `gyro_z_rad_s`
- `gyro_magnitude_rad_s`
- `sensor_gyro_axis_columns`

### Actuator-control source

For actuator-control FFT analysis, the implementation searches for topic variants such as:

- `actuator_controls`
- `actuator_controls_0`
- `actuator_controls_1`
- `actuator_controls_2`
- `actuator_controls_3`

Usable active control-vector fields are normalized to:

- `control_0`
- `control_1`
- `control_2`
- ...

The original actuator-controls topic and source column names are stored in metadata columns so the UI can report which fields were used.

## Source signal requirements

A signal can be used for FFT or PSD analysis when it has:

- a relative time column `time_s`
- at least one finite numeric signal column
- at least 16 usable samples after preparation
- non-constant variation

Constant signals are skipped because they do not contain useful oscillatory frequency content after mean removal.

For the shared time-axis convention, see [Time-Base Signal Handling](time-base.md).

## Uniform time-series preparation

FFT and PSD calculations assume a regularly sampled signal. PX4 ULog topics may contain irregular sample spacing, duplicate timestamps, missing samples, or different rates between topics. The dashboard therefore prepares a uniform time series before spectral analysis.

The preparation step is:

```text
1. Select time_s and the requested signal columns.
2. Keep only requested signal columns that exist in the dataframe.
3. Convert selected columns to numeric values.
4. Replace infinities with NaN.
5. Drop rows without a valid time_s value.
6. Sort by time_s.
7. Remove duplicate timestamps.
8. Drop rows where all requested signal columns are missing.
9. Estimate the median positive sample interval.
10. Build a uniform time grid from the first timestamp to the last timestamp.
11. Interpolate each usable signal onto the uniform time grid.
12. Fill edge gaps with nearest valid values so FFT input remains finite.
13. Return the uniform time vector, signal matrix, effective sample rate, and valid column list.
```

The median positive time step is used because it is more robust to occasional timestamp gaps than a simple mean time step.

## Sample rate estimate

After estimating the median time step, the effective sample rate is calculated as:

```text
sample_rate_hz = 1 / median_dt_s
```

This sample rate is used for frequency-bin calculation, PSD scaling, FFT amplitude scaling, and window sizing.

## Input-size limiting

The uniform time-series preparation accepts a maximum input point setting. If the estimated uniform sample count is larger than the configured limit, the method increases the effective time step by an integer decimation factor before building the uniform time grid.

This is a performance and memory safeguard. It keeps large logs usable in the dashboard, but it also reduces the effective sample rate and therefore reduces the maximum reliable frequency content available for the calculation.

## Mean removal

Before FFT or PSD calculation, the signal mean is removed:

```text
centered_signal = signal - mean(signal)
```

This reduces the DC component and makes oscillatory content easier to inspect. For accelerometer data, mean removal also helps separate vibration-like variation from static acceleration offset and gravity-related bias.

## Hann window

The dashboard applies a Hann window before spectral calculation:

```text
windowed_signal = centered_signal * hann_window
```

The Hann window reduces spectral leakage when the analyzed time segment does not contain an integer number of signal periods. This is useful for flight logs because vibration and actuator signals rarely align perfectly with the FFT window boundaries.

## One-sided frequency bins

For real-valued time-domain signals, the dashboard uses a one-sided real FFT. The frequency bins are calculated from the sample count and sample spacing:

```text
frequency_hz = rfftfreq(n_samples, d = 1 / sample_rate_hz)
```

The DC bin at `0 Hz` is excluded from dominant-frequency detection and is hidden in some displayed FFT plots.

## Single-sided FFT amplitude

For actuator-control spectra and selected-window frequency-content comparison, the dashboard computes a single-sided amplitude spectrum.

The simplified calculation is:

```text
spectrum = rfft(centered_signal * hann_window)
amplitude = 2 * abs(spectrum) / coherent_gain
```

Where:

```text
coherent_gain = sum(hann_window)
```

The DC component is handled separately:

```text
amplitude[0] = abs(spectrum[0]) / coherent_gain
```

The displayed actuator-controls FFT hides or deemphasizes the DC component because the analysis is interested in oscillatory command content rather than the mean command level.

## Power spectral density

For vibration analysis, the dashboard calculates PSD so frequency content is represented as power per Hertz.

The simplified calculation is:

```text
spectrum = rfft(centered_signal * hann_window)
PSD = abs(spectrum)^2 / (sample_rate_hz * window_power)
```

Where:

```text
window_power = sum(hann_window^2)
```

PSD is used for accelerometer and gyroscope vibration analysis because it makes frequency-domain energy easier to compare across windows and frequency bands than raw FFT magnitude alone.

## Summed-axis PSD

For three-axis sensor topics, the dashboard can sum the PSD of the available x/y/z axes:

```text
summed_psd = PSD_x + PSD_y + PSD_z
```

This creates one combined spectrum for the sensor. It is useful for detecting a dominant vibration frequency independent of which body axis carries the strongest vibration.

## Dominant-frequency detection

The dominant frequency is selected as the largest non-DC spectral peak:

```text
dominant_frequency_hz = frequency of max(PSD or amplitude), excluding 0 Hz
```

For the full-log accelerometer vibration overview, the dashboard uses the summed three-axis accelerometer PSD and selects the largest non-DC PSD peak.

For the selected-window actuator-correlation frequency plot, the dashboard calculates summed actuator-control FFT amplitude and summed accelerometer FFT amplitude. It then marks the strongest selected-window accelerometer frequency and the strongest actuator-control frequency when available.

## Time-resolved PSD heatmaps

Time-resolved PSD heatmaps are calculated with sliding windows. Each row of the heatmap is one FFT/PSD estimate from a physical time window.

Important settings are:

| Setting | Meaning |
|---|---|
| `window_duration_s` | Physical duration used for each PSD estimate. |
| `time_step_s` | Physical update interval between PSD estimates. |
| `max_frequency_hz` | Highest displayed frequency. |
| `max_frequency_bins` | Optional display downsampling for frequency bins. |
| `max_input_points` | Maximum prepared input points before effective decimation is applied. |

The implementation uses a physical `time_step_s` instead of a user-facing fixed number of time bins. This is important because a fixed number of bins changes which windows are analyzed when the selected time range changes. A physical update interval keeps the y-axis meaning stable. For example, `time_step_s = 1.0` means approximately one PSD row per second.

The older `overlap` and `max_time_bins` arguments are retained for backward compatibility and emergency limiting. They should not be treated as the normal user-facing display-resolution controls.

## Window duration tradeoff

The PSD window duration controls the main time-frequency tradeoff:

- A longer window improves frequency resolution because it contains more samples.
- A longer window reduces time localization because each PSD row averages a longer interval.
- A shorter window improves time localization.
- A shorter window worsens frequency resolution and can make peaks broader or less stable.

The approximate frequency-bin spacing is:

```text
frequency_resolution_hz ≈ sample_rate_hz / window_samples
```

Because:

```text
window_samples ≈ window_duration_s * sample_rate_hz
```

Longer windows generally produce finer frequency spacing.

## PSD heatmap display scaling

The PSD heatmap matrix is calculated in linear physical units. The dB conversion is a display transform applied by the Streamlit/Plotly heatmap helper, not by the PSD calculation itself.

### Linear display

If dB display is disabled, the heatmap color value is the linear PSD value:

```text
display_value = PSD
```

The colorbar shows the physical PSD label, for example:

- `PSD [(m/s²)²/Hz]` for accelerometer heatmaps
- `PSD [(rad/s)²/Hz]` for gyroscope heatmaps

### Relative dB display

If dB display and relative dB mode are enabled, each heatmap is normalized to its own maximum finite positive PSD value:

```text
reference_psd = max(finite positive PSD values in this heatmap)
PSD_dB = 10 * log10(clipped_PSD / reference_psd)
```

The strongest value in that heatmap becomes `0 dB`. Weaker frequency content appears as negative dB values.

This is useful for visual inspection because weak spectral components remain visible even when one impulse or peak dominates the linear color scale.

However, relative dB heatmaps should not be used for absolute energy comparison between different heatmaps. Each heatmap has its own reference value.

### Absolute dB display

If dB display is enabled but relative mode is disabled, the display value is:

```text
PSD_dB = 10 * log10(clipped_PSD)
```

This preserves a more absolute PSD scale, but the numerical dB values are still tied to the signal units and implementation scaling.

### PSD floor and display clipping

Before the logarithm is applied, PSD values are clipped to a small positive floor to avoid `log10(0)`.

The displayed dB range is controlled by the sidebar setting:

```text
PSD heatmap dB display range
```

The default range is usually `-100 dB` to `0 dB` in relative mode. This clips the color scale only. It does not change the underlying PSD matrix, which remains available as linear PSD in the heatmap hover data.

## Frequency-band power

Band power summarizes how much PSD energy lies inside a selected frequency range:

```text
band_power = integral(PSD over band_low_hz to band_high_hz)
```

The implementation uses trapezoidal integration when at least two frequency bins are available inside the band. If only one bin is available, the PSD value is multiplied by the median frequency step as a fallback approximation.

Band power is useful for comparing vibration severity inside a frequency range of interest, but the selected band should be interpreted carefully. A meaningful band depends on sample rate, expected motor or propeller frequencies, structural resonances, and sensor bandwidth.

## Use in the dashboard

This method supports:

- full-log accelerometer PSD
- dominant accelerometer frequency detection
- selected-window accelerometer FFT comparison
- selected-window actuator-controls FFT
- selected-window actuator-control dominant frequency estimation
- selected-window accelerometer dominant frequency estimation
- time-resolved accelerometer PSD heatmaps
- time-resolved gyroscope PSD heatmaps
- optional linear PSD heatmap display
- optional relative or absolute dB heatmap display
- per-phase accelerometer dominant frequency
- per-phase gyroscope dominant frequency
- per-phase accelerometer band power
- per-phase gyroscope band power

## Interpretation notes

### FFT amplitude and PSD are not the same quantity

FFT amplitude is useful for showing signal oscillation amplitude at each frequency. PSD is useful for showing frequency-domain power density. They should not be treated as identical values.

### Dominant frequency identifies a peak, not a root cause

A dominant frequency marks where the strongest spectral component appears. It does not prove whether the cause is a motor, propeller, airframe resonance, controller oscillation, sensor artifact, maneuver, environmental disturbance, or logging artifact.

### Frequency content depends on the selected time window

Changing the selected time range changes the analyzed samples. A dominant frequency in a short window may differ from the dominant frequency of the full log.

### Time-resolved PSD rows are window-centered

Each heatmap row represents the center time of a sliding FFT window, not an instantaneous measurement. A row at `t = 50 s` represents the signal over the surrounding window, not only the exact sample at 50 seconds.

### Relative dB display is best for within-plot structure

Relative dB display is useful for seeing weaker peaks in one heatmap. It is not suitable for comparing absolute PSD strength between different heatmaps unless the same reference and settings are used deliberately.

## Limitations

### Sensor source can differ from the visual label

The dashboard normalizes high-rate `sensor_combined` fields into dashboard columns that are still displayed with familiar accelerometer and gyroscope labels. Always check the source-field table before interpreting sample rate, frequency limits, or exact source axes.

### Interpolation can affect spectra

Uniform resampling is necessary for FFT/PSD, but interpolation can smooth high-frequency content or alter signals when timestamps are irregular or data gaps are large.

### Effective decimation can reduce high-frequency content

For very large logs, the preparation step may increase the effective time step to stay below the maximum input point limit. This reduces the effective sample rate and can reduce the usable frequency range.

### Short windows reduce reliability

Very short selected intervals or very short PSD windows may not contain enough cycles of the vibration to estimate frequency content reliably.

### Spectral leakage remains possible

The Hann window reduces leakage but does not eliminate it. Strong transients or non-stationary signals can still smear energy across neighboring frequency bins.

### Aliasing is not independently corrected

The method uses the logged signal and estimated sample rate. It does not independently verify anti-alias filtering, sensor bandwidth, or whether high-frequency physical vibration was aliased into the logged frequency range.

### PSD scaling is implementation-specific

The dashboard uses consistent internal scaling for comparison, but values should be interpreted primarily as engineering screening indicators unless the exact sensor calibration, logging pipeline, filtering, and unit conventions are validated.

### Frequency-band choice is user-dependent

The default band-power range is a practical screening range, not a universal standard. Band limits should be adapted to the vehicle, sample rate, expected motor/propeller frequencies, and the analysis goal.

## Practical interpretation rule

Use FFT and PSD results to find suspicious frequencies, compare relative vibration behavior, and select time windows for deeper investigation. Do not use a frequency peak alone as proof of mechanical root cause.
