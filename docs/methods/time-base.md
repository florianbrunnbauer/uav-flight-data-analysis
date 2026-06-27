# Time-Based Signal Handling

## Purpose

This file documents the shared time-base convention used throughout the flight-data analysis tool. The goal is to make all logged PX4 topics comparable on one common relative time axis.

Many dashboard pages rely on this method because plots, time-range sliders, topic alignment, interpolation, FFT windows, and per-phase duration calculations all require a consistent time representation.

## Source topic requirement

The method requires every used ULog topic to contain a `timestamp` field. PX4 ULog timestamps are stored in microseconds.

The method is applied centrally in `ulg_reader.py` when a topic is loaded with:

```python
log.get_topic(topic_name)
```

The returned `DataFrame` contains an added column:

```text
time_s
```

## Implementation

The log reader first determines a common log start timestamp:

```text
log_start_timestamp = minimum first timestamp among all topics that contain timestamp
```

For every loaded topic, the relative time is calculated as:

```text
time_s = (timestamp - log_start_timestamp) / 1e6
```

Where:

- `timestamp` is the original PX4 ULog timestamp in microseconds.
- `log_start_timestamp` is the earliest first timestamp found in the log.
- `1e6` converts microseconds to seconds.
- `time_s` is the resulting relative time in seconds.

## Interpretation

`time_s` is a relative log time axis. It does **not** represent wall-clock time, GPS time, local computer time, or UTC time.

A value of:

```text
time_s = 0
```

means the earliest timestamp found in the log, not necessarily takeoff, arming, or the first sample of the currently inspected topic.

Because every topic is converted with the same reference timestamp, signals from different topics can be plotted and compared on the same x-axis.

## Use in the dashboard

The shared `time_s` signal is used for:

- x-axes in time-series plots
- sidebar time-range selection
- filtering the displayed time window
- interpolating one topic onto another topic's timestamps
- nearest-neighbor merging of topics with different sample rates
- FFT and PSD window placement
- phase-duration accumulation
- hover-segment selection
- actuator and vibration correlation plots

## Topic alignment

Different PX4 topics are often logged at different sample rates. For example, position, attitude, actuator outputs, IMU status, and raw sensor topics may not have identical timestamps.

The project uses different strategies depending on the analysis:

- **Direct plotting:** the topic is plotted on its own `time_s` axis.
- **Interpolation:** one signal is interpolated onto another signal's timestamps when a continuous comparison is needed.
- **Nearest-neighbor merge:** `pd.merge_asof(..., direction="nearest")` is used when two topics need to be approximately time-aligned.
- **Uniform resampling:** FFT and PSD functions interpolate signals onto a uniform time grid before spectral analysis.

## Duration calculation

For phase statistics and segment-based metrics, duration should be accumulated from sample intervals rather than simply using the difference between the first and last sample.

The preferred method is:

```text
dt_s = next_time_s - current_time_s
duration_s = sum(dt_s)
```

For the last sample, the median sample interval is used as a practical approximation when needed.

This is important because phase labels can appear in multiple separate segments. Calculating only `last_time - first_time` can overestimate the duration if the phase appears in disconnected intervals.

## Recommended usage

Use `time_s` for all internal dashboard plots and calculations unless an analysis explicitly requires absolute timestamps.

When comparing two topics, always check whether the topics have different sample rates before interpreting point-by-point differences.

When deriving statistics for a selected time range, filter the relevant topic first:

```python
plot_df = df[
    (df["time_s"] >= selected_time_range[0]) &
    (df["time_s"] <= selected_time_range[1])
].copy()
```

## Limitations

### Relative time only

`time_s` is not an absolute timestamp. It should not be used to infer the real date, time of day, GPS time, or time zone.

### Topic start times may differ

Not every topic starts exactly at `time_s = 0`. A topic may begin later than the earliest timestamp in the log.

### Sampling may be irregular

The method does not force topics to have a constant sample rate. Some analyses must explicitly handle irregular sampling, missing samples, and gaps.

### Nearest-neighbor alignment can hide timing differences

When two topics are merged using nearest-neighbor matching, the result is convenient but approximate. It does not prove that the two samples were recorded at the exact same instant.

### No clock-drift correction

The method assumes that all logged topic timestamps share the same PX4 time base. It does not perform independent clock-drift correction between sensors.

### Selected time range may not affect every metric

Some dashboard pages display full-log summary metrics while using the selected time range only for plots. The page-specific methodology file should state clearly whether metrics are full-log or selected-window metrics.

## Practical interpretation rule

Use `time_s` as a consistent engineering time axis for log-internal analysis. Treat it as reliable for comparing events inside the same ULog file, but not as a real-world timestamp.
