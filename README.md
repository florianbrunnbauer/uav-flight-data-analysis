# UAV Flight Data Analysis Dashboard

A Streamlit-based tool for analyzing PX4 `.ulg` flight logs.

## Features

- Upload and inspect PX4 `.ulg` files
- Flight overview and basic flight statistics
- Flight phase detection
- Hover analysis
- Actuator output analysis
- Vibration analysis with time-domain signals and PSD/FFT tools
- Setpoint tracking analysis for rate, attitude, and trajectory tracking

## Project Structure

- `app.py` - Streamlit user interface
- `analysis.py` - signal processing and metric calculations
- `flight_data.py` - cached access to analyzed flight data
- `ulg_reader.py` - PX4 ULog reader wrapper
- `phases.py` - flight phase colors and plot colors
- `utils.py` - general helper functions

## Installation

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt