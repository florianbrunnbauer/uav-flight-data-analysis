# Test Documentation Index

This folder documents the automated tests in the `tests/` directory.

The tests are grouped by analysis topic so that each test file has a clear purpose and can be reviewed independently.

## Test Groups

| Documentation | Test file | Main purpose |
|---|---|---|
| [Helpers and Fixtures](helpers-fixtures.md) | `tests/conftest.py`, `tests/helpers.py` | Shared import setup, optional `pyulog` stub, fake log object, quaternion helper |
| [Filter Tests](filters.md) | `tests/test_filters.py` | Low-pass filter behavior |
| [Attitude and Altitude Tests](attitude-altitude.md) | `tests/test_attitude_altitude.py` | Quaternion-to-Euler conversion, attitude analysis, altitude conversion |
| [Flight Phase Tests](flight-phases.md) | `tests/test_flight_phases.py` | Phase classification, smoothing, position-derived motion signals |
| [Hover Stability Tests](hover-stability.md) | `tests/test_hover_stability.py` | Hover metrics, centimeter-level segment metrics, yaw unwrap handling |
| [Actuator Output Tests](actuator-outputs.md) | `tests/test_actuator_outputs.py` | Active output detection and actuator summary metrics |
| [Tracking Tests](tracking.md) | `tests/test_tracking.py` | Tracking error metrics and lag estimation |
| [Frequency Analysis Tests](frequency-analysis.md) | `tests/test_frequency_analysis.py` | FFT, PSD, and time-resolved PSD grid generation |

## Running All Tests

```bash
python -m pytest
```

## Test Philosophy

The current tests are deterministic unit tests. They do not require a real `.ulg` file. This makes them suitable for local development and for future continuous integration.
