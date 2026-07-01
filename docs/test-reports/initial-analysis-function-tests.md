# Initial Analysis Function Test Report

## Test Date

`2026-06-30`

## Repository State

Commit:

```text
8e0db925794de5b27c28eeb7f24eedd18bde4225
```

Branch:

```text
main
```

## Environment

- Operating system: `Windows 11`
- Python version: `Python 3.13`
- Test framework: `pytest`
- Installation method: `venv`

## Command

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## Test Scope

The test run covered the core analysis-function tests:

- Low-pass filter
- Quaternion-to-Euler conversion
- Attitude analysis
- Altitude analysis
- Flight phase classification
- Hover stability metrics
- Actuator output analysis
- Tracking error metrics
- Lag estimation
- FFT analysis
- PSD analysis
- Time-resolved PSD heatmap data generation

## Result

```text
33 passed in 0.83s
```

## Failed Tests

```text
None
```

## Interpretation

Passing tests show that the implemented analysis functions behave as expected for controlled synthetic inputs.

This result does not validate every possible PX4 ULog schema, every real flight condition, Streamlit UI behavior, or the engineering interpretation of flight-test results.
