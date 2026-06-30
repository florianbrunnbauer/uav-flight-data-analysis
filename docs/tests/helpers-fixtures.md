# Helpers and Fixtures

Related files:

- [`tests/conftest.py`](../../tests/conftest.py)
- [`tests/helpers.py`](../../tests/helpers.py)

## Purpose

The helper files provide shared test infrastructure for all analysis-function tests.

They keep repeated setup code out of the individual test files and make the tests easier to read.

## `conftest.py`

`conftest.py` is automatically loaded by pytest. In this project it serves two purposes.

First, it adds the repository root to `sys.path`. This allows imports such as:

```python
from analysis import low_pass_filter_signal
```

to work reliably when pytest is run from the repository root or when the `tests/` folder is passed explicitly.

Second, it provides an optional safety stub for `pyulog` in isolated environments. The current unit tests do not read real `.ulg` files. They use fake log objects instead. The stub only prevents import failure when `analysis.py` imports modules that indirectly import `pyulog`.

In a normal project environment, the real `pyulog` package from `requirements.txt` should be installed and used.

## `helpers.py`

`helpers.py` contains shared helper objects.

### `FakeLog`

`FakeLog` is a minimal replacement for the real ULog reader. It exposes the same `get_topic()` method used by the analysis functions.

This allows tests to provide controlled synthetic DataFrames instead of real log topics.

Example concept:

```python
log = FakeLog({
    "vehicle_attitude": attitude_dataframe,
})
```

When the analysis function calls:

```python
log.get_topic("vehicle_attitude")
```

it receives the synthetic DataFrame.

### `make_quaternion_from_axis_angle()`

This helper creates simple test quaternions for single-axis rotations.

It is used by the attitude tests to verify that known rotations produce expected roll, pitch, and yaw angles.

## Why This Matters

The helper approach keeps the tests focused on the analysis functions themselves. It avoids coupling basic unit tests to real ULog files, PX4 topic availability, or external flight data.

## Limitations

The fake log object only tests behavior for topics and columns explicitly supplied in the tests. It does not validate the full `UlgReader` implementation or all PX4 topic variants.
