# Testing Strategy

## Purpose

The purpose of the test suite is to verify the core analysis and signal-processing functions of the PX4 UAV flight log analysis dashboard.

The tests use deterministic synthetic data instead of real PX4 `.ulg` files. This keeps the tests lightweight, repeatable, and suitable for automated execution in GitHub Actions.

## Current Test Scope

The current unit tests cover the analysis layer, especially the functions in `analysis.py`:

- Low-pass filtering
- Quaternion-to-Euler conversion
- Attitude analysis
- Altitude analysis
- Flight phase classification
- Hover stability metrics
- Actuator output analysis
- Tracking error metrics
- Signal lag estimation
- FFT analysis
- PSD analysis
- Time-resolved PSD heatmap data generation

## Test Method

Most tests use small synthetic DataFrames with known expected outputs. This makes each result easy to verify.

Examples:

- A known quaternion is converted to a known roll, pitch, or yaw angle.
- A known PX4 NED `z` value is converted to positive altitude.
- A sine wave with a known frequency is used to verify FFT and PSD peak detection.
- A delayed synthetic response signal is used to verify lag estimation.
- A fake log object replaces the real ULog reader for analysis-function tests.

## Why Real `.ulg` Logs Are Not Used Here

The current tests are unit tests. They verify individual functions under controlled conditions.

Real PX4 logs are useful for later integration tests, but they are not ideal for the first test layer because they can introduce uncontrolled variation:

- Missing or renamed topics
- Different PX4 versions
- Irregular sampling
- Estimator artifacts
- Vehicle-specific configuration
- Mission-specific behavior

Real `.ulg` files should remain local and should not be committed to the repository.

## Current Test Files

| Test file | Documentation | Purpose |
|---|---|---|
| `tests/conftest.py` and `tests/helpers.py` | [Helpers and Fixtures](tests/helpers-fixtures.md) | Shared test setup and fake log object |
| `tests/test_filters.py` | [Filter Tests](tests/filters.md) | Low-pass filter behavior |
| `tests/test_attitude_altitude.py` | [Attitude and Altitude Tests](tests/attitude-altitude.md) | Quaternion, attitude, and altitude conversion |
| `tests/test_flight_phases.py` | [Flight Phase Tests](tests/flight-phases.md) | Rule-based phase classification and position-derived signals |
| `tests/test_hover_stability.py` | [Hover Stability Tests](tests/hover-stability.md) | Hover metrics and yaw unwrap handling |
| `tests/test_actuator_outputs.py` | [Actuator Output Tests](tests/actuator-outputs.md) | Active motor output detection and actuator summary metrics |
| `tests/test_tracking.py` | [Tracking Tests](tests/tracking.md) | Tracking error metrics and lag estimation |
| `tests/test_frequency_analysis.py` | [Frequency Analysis Tests](tests/frequency-analysis.md) | FFT, PSD, and time-resolved PSD outputs |

## How to Run the Tests

From the repository root:

```bash
python -m pytest
```

With the recommended virtual environment on Windows:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## Expected Result

A passing run should report all tests as passed, for example:

```text
33 passed
```

The exact runtime may differ between machines.

## Interpretation of Passing Tests

Passing tests mean that the core analysis functions behave as expected for controlled synthetic inputs.

Passing tests do not prove that every real PX4 flight log will be interpreted correctly. Real flight logs can contain missing topics, unusual sampling, estimator artifacts, and vehicle-specific behavior that require manual review and additional integration testing.

## Out of Scope

The current tests do not verify:

- Streamlit UI behavior
- Plot layout or visual appearance
- Full `.ulg` file import behavior
- All possible PX4 topic schemas
- Engineering validity of thresholds
- Causal interpretation of actuator/vibration correlation plots
- Vehicle-specific pass/fail limits

## Future Extensions

- Streamlit startup smoke test
- Optional local integration test with one `.ulg` file stored outside Git
- Tests for missing-topic behavior
- Tests for edge cases such as empty DataFrames and NaN-only signals
