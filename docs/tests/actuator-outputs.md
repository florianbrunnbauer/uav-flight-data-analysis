# Actuator Output Tests

Related test file: [`tests/test_actuator_outputs.py`](../../tests/test_actuator_outputs.py)

## Purpose

These tests verify the actuator output summary logic used by the Actuator Output Analysis page.

The production function under test is:

```python
analyze_actuator_outputs()
```

## Tests Covered

### `test_analyze_actuator_outputs_detects_active_outputs_and_summary_metrics`

This test creates a synthetic `actuator_outputs` topic with three output channels:

- `output[0]`: active and varying
- `output[1]`: constant and therefore not treated as active
- `output[2]`: active and varying

Expected behavior:

- Only the varying outputs are identified as active motor outputs.
- Mean motor output is calculated row by row.
- Minimum and maximum motor output are calculated row by row.
- Motor output spread is calculated as max minus min.
- Output rate metrics are calculated from changes over time.

Verified metrics include:

- Active output indices
- Mean motor output
- Maximum motor output
- Maximum motor output spread
- Mean absolute motor output rate
- Maximum absolute motor output rate

## Interpretation

Passing this test means that the dashboard can correctly summarize active actuator output channels for simple controlled data.

## Limitations

The test does not prove the physical motor layout, motor direction, thrust direction, or whether actuator outputs directly correspond to measured motor RPM or thrust. The function analyzes command signals, not physical motor measurements.
