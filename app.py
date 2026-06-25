import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import numpy as np
from plotly.subplots import make_subplots
from pathlib import Path

from flight_data import FlightData
from utils import format_duration, get_phase_segments
from phases import phase_colors, plot_colors, rgb_to_rgba, rgb_to_hex
from analysis import (
    compute_hover_stability_for_segment,
    compute_motor_pair_components,
    DEFAULT_SETPOINT_LOW_PASS_CUTOFF_HZ,
    recompute_rate_tracking_for_time_window,
    recompute_attitude_tracking_for_time_window,
    recompute_trajectory_tracking_for_time_window,
    compute_time_resolved_psd_surface,
    compute_signal_fft,
    compute_per_phase_vibration_statistics,
)


@st.cache_resource
def load_flight_data(path) -> FlightData:
    return FlightData(path)


def add_phase_background(fig, phase_segments, phase_colors):
    for segment in phase_segments:
        phase = segment["phase"]

        fig.add_vrect(
            x0=segment["start_time"],
            x1=segment["end_time"],
            fillcolor = rgb_to_rgba(
                phase_colors[phase],
                alpha=0.14
            ),
            opacity=1.0,
            line_width=0,
            layer="below",
        )

    return fig


# -------------------------------------------------
# Hover reference bands and visualization helpers
# -------------------------------------------------

DEFAULT_HOVER_REFERENCE_BANDS = {
    "altitude_rms_cm": {
        "label": "Altitude RMS",
        "unit": "cm",
        "low reference": 5.0,
        "elevated reference": 12.0,
        "description": "Altitude hold scatter around the segment mean.",
    },
    "altitude_p95_abs_cm": {
        "label": "Altitude 95%",
        "unit": "cm",
        "low reference": 10.0,
        "elevated reference": 25.0,
        "description": "95th percentile of absolute altitude error.",
    },
    "rms_drift_cm": {
        "label": "Drift RMS",
        "unit": "cm",
        "low reference": 15.0,
        "elevated reference": 30.0,
        "description": "Horizontal RMS drift around the hover center.",
    },
    "drift_p95_cm": {
        "label": "Drift 95%",
        "unit": "cm",
        "low reference": 30.0,
        "elevated reference": 60.0,
        "description": "95th percentile horizontal drift radius.",
    },
    "avg_ground_speed_m_s": {
        "label": "Avg ground speed",
        "unit": "m/s",
        "low reference": 0.10,
        "elevated reference": 0.25,
        "description": "Mean horizontal velocity during hover.",
    },
    "roll_std_deg": {
        "label": "Roll STD",
        "unit": "deg",
        "low reference": 1.0,
        "elevated reference": 2.0,
        "description": "Roll attitude variation.",
    },
    "pitch_std_deg": {
        "label": "Pitch STD",
        "unit": "deg",
        "low reference": 1.0,
        "elevated reference": 2.0,
        "description": "Pitch attitude variation.",
    },
    "yaw_std_deg": {
        "label": "Yaw STD",
        "unit": "deg",
        "low reference": 1.5,
        "elevated reference": 3.0,
        "description": "Heading variation after unwrap handling.",
    },
}


def classify_reference_level(value: float, low_reference_value: float, elevated_reference_value: float) -> str:
    """Classify a lower-is-better metric using reference bands."""
    if pd.isna(value):
        return "unknown"
    if value <= low_reference_value:
        return "low"
    if value <= elevated_reference_value:
        return "elevated"
    return "high"


def reference_level_color(status: str) -> str:
    """Return dashboard colors for reference levels."""
    return {
        "low": "#2ECC71",
        "elevated": "#F1C40F",
        "high": "#E74C3C",
        "unknown": "#95A5A6",
    }.get(status, "#95A5A6")


def build_hover_metrics_reference_dataframe(metrics: dict, reference_bands: dict) -> pd.DataFrame:
    """Build a compact DataFrame for hover reference bar visualization."""
    rows = []

    for metric_key, config in reference_bands.items():
        value = float(metrics.get(metric_key, np.nan))
        low_limit = float(config["low reference"])
        elevated_limit = float(config["elevated reference"])
        status = classify_reference_level(value, low_limit, elevated_limit)

        usage_percent = value / elevated_limit * 100 if elevated_limit > 0 else np.nan
        usage_percent_clipped = min(usage_percent, 150) if not pd.isna(usage_percent) else np.nan

        rows.append({
            "metric_key": metric_key,
            "metric": config["label"],
            "value": value,
            "unit": config["unit"],
            "low_limit": low_limit,
            "elevated_limit": elevated_limit,
            "status": status,
            "usage_percent": usage_percent,
            "usage_percent_clipped": usage_percent_clipped,
            "color": reference_level_color(status),
            "text": f"{value:.2f} {config['unit']} · {status.upper()}",
            "hover_text": (
                f"{config['label']}<br>"
                f"Value: {value:.3f} {config['unit']}<br>"
                f"Low reference: ≤ {low_limit:g} {config['unit']}<br>"
                f"Elevated reference: ≤ {elevated_limit:g} {config['unit']}<br>"
                f"Status: {status}<br>"
                f"{config['description']}"
            ),
        })

    return pd.DataFrame(rows)


def create_hover_reference_bar_chart(reference_df: pd.DataFrame) -> go.Figure:
    """Create a reference-normalized horizontal bar chart."""
    plot_df = reference_df.iloc[::-1].copy()

    fig = go.Figure()

    fig.add_trace(
        go.Bar(
            x=plot_df["usage_percent_clipped"],
            y=plot_df["metric"],
            orientation="h",
            marker_color=plot_df["color"],
            text=plot_df["text"],
            textposition="auto",
            hovertext=plot_df["hover_text"],
            hoverinfo="text",
            name="Hover metric reference bands",
        )
    )

    fig.add_vline(
        x=100,
        line_color="rgba(255,255,255,0.75)",
        line_dash="dash",
        line_width=1,
        annotation_text="elevated limit",
        annotation_position="top right",
    )

    fig.add_vline(
        x=50,
        line_color="rgba(255,255,255,0.35)",
        line_dash="dot",
        line_width=1,
        annotation_text="low region",
        annotation_position="top left",
    )

    fig.update_layout(
        title="Hover Metric Overview",
        height=430,
        margin=dict(l=20, r=30, t=60, b=35),
        xaxis_title="Percent of elevated reference [%]",
        yaxis_title=None,
        showlegend=False,
    )

    fig.update_xaxes(range=[0, 150], ticksuffix="%")

    return fig


def apply_hover_reference_controls(default_reference_bands: dict) -> dict:
    """Sidebar controls for hover reference bands."""
    reference_bands = {
        key: value.copy()
        for key, value in default_reference_bands.items()
    }

    with st.sidebar.expander("Hover metric reference bands", expanded=False):
        st.caption(
            "Lower values are better. These reference values are a practical baseline; "
            "adjust them for your vehicle, positioning source, wind, and test environment."
        )

        for metric_key, config in reference_bands.items():
            st.markdown(f"**{config['label']} [{config['unit']}]**")
            col_low, col_elevated = st.columns(2)

            with col_low:
                reference_bands[metric_key]["low reference"] = st.number_input(
                    "Low ≤",
                    min_value=0.0,
                    value=float(config["low reference"]),
                    step=max(float(config["low reference"]) / 10, 0.01),
                    key=f"{metric_key}_low_reference",
                )

            with col_elevated:
                min_elevated = max(
                    reference_bands[metric_key]["low reference"],
                    0.001,
                )
                elevated_value = max(float(config["elevated reference"]), min_elevated)
                reference_bands[metric_key]["elevated reference"] = st.number_input(
                    "Elevated ≤",
                    min_value=min_elevated,
                    value=elevated_value,
                    step=max(elevated_value / 10, 0.01),
                    key=f"{metric_key}_elevated_reference",
                )

    return reference_bands


def format_optional_value(value, unit: str = "", decimals: int = 3) -> str:
    """Format dashboard values while keeping missing data readable."""
    try:
        if pd.isna(value) or not np.isfinite(float(value)):
            return "n/a"
    except (TypeError, ValueError):
        return "n/a"

    formatted = f"{float(value):.{decimals}f}"
    return f"{formatted} {unit}".strip()


def format_optional_count(value) -> str:
    """Format count-like dashboard values while keeping missing data readable."""
    try:
        if pd.isna(value) or not np.isfinite(float(value)):
            return "n/a"
    except (TypeError, ValueError):
        return "n/a"

    return f"{float(value):.0f}"



def create_psd_heatmap_figure(surface: dict, title: str, colorbar_title: str) -> go.Figure:
    """Create a 2D time-frequency PSD heatmap from a time-resolved PSD dictionary."""
    fig = go.Figure()

    fig.add_trace(go.Heatmap(
        x=surface["frequency_hz"],
        y=surface["time_s"],
        z=surface["psd"],
        colorbar=dict(title=colorbar_title),
        name="PSD magnitude",
        hovertemplate=(
            "Frequency: %{x:.2f} Hz<br>"
            "Time: %{y:.2f} s<br>"
            "PSD: %{z:.6g}<extra></extra>"
        ),
    ))

    fig.update_layout(
        title=title,
        height=650,
        margin=dict(l=10, r=10, t=60, b=45),
    )
    fig.update_xaxes(title_text="Frequency [Hz]")
    fig.update_yaxes(title_text="Time [s]")

    return fig


st.set_page_config(page_title="UAV Flight Data Analysis",layout="wide")

st.title("UAV Flight Data Analysis Dashboard")

uploaded_file = st.file_uploader("Upload PX4 .ulg file",type=["ulg"])

if uploaded_file:

    temp_path = Path("temp_uploaded.ulg")
    temp_path.write_bytes(uploaded_file.read())

    flight: FlightData = load_flight_data(str(temp_path))

    # ---------------- SIDEBAR ----------------

    st.sidebar.header("Analysis")

    page = st.sidebar.radio(
        "Analysis Page",
        [
            "Overview",
            # "3D Flight Path",
            # "Flight Overview",
            "Basic Flight Statistics",
            "Hover Analysis",
            "Actuator Output Analysis",
            "Vibration Analysis",
            "Setpoint Tracking Analysis",
        ]
    )

    if page == "3D Flight Path":

        st.header("3D Flight Path")

        df = flight.position

        fig = px.line_3d(df, x="x",y="y",z="altitude_m",title="3D Flight Path")

        fig.update_traces(line=dict(width=4))

        fig.update_layout(scene=dict(xaxis_title = "North [m]",
                                     yaxis_title="East [m]",
                                     zaxis_title= "Altitude [m]",
                                     aspectmode="data"),
                                     height=800,
                                     )

        st.plotly_chart(fig,width="stretch")

    elif page == "Flight Overview":

        st.header("Flight Overview")

        # -------------------------------------------------
        # Load data
        # -------------------------------------------------

        pos_df = flight.position
        att_df = flight.attitude

        # -------------------------------------------------
        # Layout
        # -------------------------------------------------

        left_col, right_col = st.columns([2, 1])

        # -------------------------------------------------
        # 3D path
        # -------------------------------------------------

        with left_col:

            st.subheader("3D Flight Path")

            fig_path = px.line_3d(
                pos_df,
                x="x",
                y="y",
                z="altitude_m",
                title="Local Position Flight Path"
            )

            fig_path.update_traces(
                line=dict(width=4)
            )

            fig_path.update_layout(
                scene=dict(
                    xaxis_title="North [m]",
                    yaxis_title="East [m]",
                    zaxis_title="Altitude [m]",
                    aspectmode="data"
                ),
                height=750
            )

            st.plotly_chart(
                fig_path,
                width="stretch"
            )

        # -------------------------------------------------
        # Velocity and attitude plots
        # -------------------------------------------------

        with right_col:

            st.subheader("Velocity")

            fig_velocity = px.line(
                pos_df,
                x="time_s",
                y=[
                    "speed_m_s",
                    "horizontal_speed_m_s",
                    "vertical_speed_m_s",
                ],
                title="Velocity Over Time",
                labels={
                    "time_s": "Time [s]",
                    "value": "Velocity [m/s]",
                    "variable": "Signal",
                }
            )

            st.plotly_chart(fig_velocity,width="stretch")

            st.subheader("Roll / Pitch / Yaw")

            fig_attitude = make_subplots(
                specs=[[{"secondary_y": True}]]
                )

            # -------------------------------------------------
            # Roll
            # -------------------------------------------------

            fig_attitude.add_trace(
                go.Scatter(
                    x=att_df["time_s"],
                    y=att_df["roll_deg"],
                    name="Roll [deg]",
                    line=dict(color=rgb_to_hex(plot_colors["roll"])),
                ),
                secondary_y=False,
            )

            # -------------------------------------------------
            # Pitch
            # -------------------------------------------------

            fig_attitude.add_trace(
                go.Scatter(
                    x=att_df["time_s"],
                    y=att_df["pitch_deg"],
                    name="Pitch [deg]",
                    line=dict(color=rgb_to_hex(plot_colors["pitch"])),
                ),
                secondary_y=False,
            )

            # -------------------------------------------------
            # Yaw
            # -------------------------------------------------

            fig_attitude.add_trace(
                go.Scatter(
                    x=att_df["time_s"],
                    y=att_df["yaw_deg"],
                    name="Yaw [deg]",
                    line=dict(color=rgb_to_hex(plot_colors["yaw"])),
                ),
                secondary_y=True,
            )

            # -------------------------------------------------
            # Axis labels
            # -------------------------------------------------

            fig_attitude.update_xaxes(title_text="Time [s]")

            fig_attitude.update_yaxes(title_text="Roll / Pitch [deg]",range=[-30, 30],secondary_y=False)

            fig_attitude.update_yaxes(title_text="Yaw [deg]",range=[-180, 180],secondary_y=True)

            # -------------------------------------------------
            # Layout
            # -------------------------------------------------

            fig_attitude.update_layout(
                title="Attitude Over Time",
                height=400,
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="right",
                    x=1
                )
            )

            st.plotly_chart(fig_attitude,width="stretch")

    elif page == "Overview":

        st.header("Flight Overview")

        pos_df = flight.position
        stats = flight.flight_statistics

        flight_time = format_duration(stats["flight_time_s"])

        with st.sidebar:

            st.subheader("Display Controls")

            time_min = float(pos_df["time_s"].min())
            time_max = float(pos_df["time_s"].max())

            selected_time_range = st.slider(
                "Displayed time range [s]",
                min_value=time_min,
                max_value=time_max,
                value=(time_min, time_max),
                step=1.0,
            )

        # ------------------------------------------------
        # Apply selected time range
        # ------------------------------------------------

        plot_pos_df = pos_df[
            (pos_df["time_s"] >= selected_time_range[0]) &
            (pos_df["time_s"] <= selected_time_range[1])
        ].copy()


        # -------------------------------------------------
        # Statistics cards
        # -------------------------------------------------

        st.subheader("Flight Summary")

        c1, c2, c3, c4 = st.columns(4)

        c1.metric("Flight Time", flight_time)
        c2.metric("Distance Flown", f"{stats['distance_traveled_m']:.1f} m")
        c3.metric("Max Range", f"{stats['max_distance_from_home_m']:.1f} m")
        c4.metric("Max Altitude", f"{stats['max_altitude_m']:.1f} m")

        st.subheader("Performance")

        c5, c6, c7, c8 = st.columns(4)

        c5.metric("Max Ground Speed", f"{stats['max_ground_speed_m_s']:.1f} m/s")
        c6.metric("Avg Ground Speed", f"{stats['avg_ground_speed_m_s']:.1f} m/s")
        c7.metric("Max Climb", f"{stats['max_climb_rate_m_s']:.1f} m/s")
        c8.metric("Max Descent", f"{stats['max_descent_rate_m_s']:.1f} m/s")

        st.subheader("Attitude")

        c9, c10, c11, c12 = st.columns(4)

        c9.metric("Max Roll", f"{stats['max_roll_deg']:.1f}°")
        c10.metric("Max Pitch", f"{stats['max_pitch_deg']:.1f}°")

        st.subheader("Phase Statistics")

        phase_stats = flight.phase_statistics.copy()

        phase_stats["duration"] = phase_stats["duration_s"].apply(
            format_duration
        )

        st.dataframe(
            phase_stats[
                [
                    "phase",
                    "duration",
                    "duration_percent",
                    "samples",
                    "avg_altitude_m",
                    "avg_ground_speed_m_s",
                    "avg_vertical_speed_m_s",
                ]
            ].style.format({
                "duration_percent": "{:.1f} %",
                "avg_altitude_m": "{:.1f}",
                "avg_ground_speed_m_s": "{:.2f}",
                "avg_vertical_speed_m_s": "{:.2f}",
            }),
            width="stretch",
        )

        st.divider()

        # -------------------------------------------------
        # Plot layout
        # -------------------------------------------------

        left_col, right_col = st.columns([2, 1])

        # -------------------------------------------------
        # Left: 3D flight path
        # -------------------------------------------------

        with left_col:

            st.subheader("3D Flight Path")

            fig_3d = go.Figure()

            fig_3d.add_trace(go.Scatter3d(
                x= pos_df["x"],
                y= pos_df["y"],
                z= pos_df["altitude_m"],
                mode="lines",
                name="Full Flight",
                line=dict(width=4,color="RGB(0,188,255)"),
                
            ))

            fig_3d.add_trace(go.Scatter3d(
                x= plot_pos_df["x"],
                y= plot_pos_df["y"],
                z= plot_pos_df["altitude_m"],
                mode="lines",
                name="Selected Time Period",
                line=dict(width=4,color="RGB(255,0,0)"),
                
            ))

            fig_3d.update_layout(
                scene=dict(
                    xaxis_title="North [m]",
                    yaxis_title="East [m]",
                    zaxis_title="Altitude [m]",
                    aspectmode="data"
                ),
                height=750
            )            

            st.plotly_chart(fig_3d,width="stretch")

        # -------------------------------------------------
        # Right: 2D path + altitude
        # -------------------------------------------------

        with right_col:

            st.subheader("Top-Down Flight Path")

            fig_2d = go.Figure()

            fig_2d.add_trace(go.Scatter(
                x=pos_df["y"],
                y=pos_df["x"],
                mode="lines",
                name="Full Flight",
                line=dict(color="RGB(0,188,255)"),
            ))

            fig_2d.add_trace(go.Scatter(
                x=plot_pos_df["y"],
                y=plot_pos_df["x"],
                mode="lines",
                name="Selected Time Period",
                line=dict(color="RGB(255,0,0)"),
            ))

            fig_2d.update_layout(title="Top-Down View")

            fig_2d.update_xaxes(title="East [m]")
            fig_2d.update_yaxes(title="North [m]",scaleanchor="x",scaleratio=1)

            fig_2d.update_layout(height=360)

            st.plotly_chart(fig_2d,width="stretch")

            st.subheader("Altitude Over Time")

            fig_altitude = go.Figure()

            fig_altitude.add_trace(go.Scatter(
                x=pos_df["time_s"],
                y=pos_df["altitude_m"],
                mode="lines",
                name="Full Flight",
                line=dict(color="RGB(0,188,255)"),
            ))

            fig_altitude.add_trace(go.Scatter(
                x=plot_pos_df["time_s"],
                y=plot_pos_df["altitude_m"],
                mode="lines",
                name="Selected Time Period",
                line=dict(color="RGB(255,0,0)"),
            ))

            fig_altitude.update_layout(title="Altitude Profile")

            fig_altitude.update_xaxes(title="Time [s]")
            fig_altitude.update_yaxes(title="Altitude [m]")

            fig_altitude.update_layout(height=360)

            st.plotly_chart(fig_altitude,width="stretch")

            st.subheader("Distance From Home Over Time")

            fig_range = go.Figure()

            fig_range.add_trace(go.Scatter(
                x=pos_df["time_s"],
                y=pos_df["distance_from_home_m"],
                mode="lines",
                name="Full Flight",
                line=dict(color="RGB(0,188,255)"),
            ))

            fig_range.add_trace(go.Scatter(
                x=plot_pos_df["time_s"],
                y=plot_pos_df["distance_from_home_m"],
                mode="lines",
                name="Selected Time Period",
                line=dict(color="RGB(255,0,0)"),
            ))

            fig_range.update_layout(title="Distance From Home")

            fig_range.update_xaxes(title="Time [s]")
            fig_range.update_yaxes(title="Distance From Home [m]")

            fig_range.update_layout(height=360)

            st.plotly_chart(fig_range,width="stretch")

    elif page == "Basic Flight Statistics":

        st.header("Flight Phase Detection Test")

        pos_df = flight.position.copy()

        # -------------------------------------------------
        # Sidebar controls
        # -------------------------------------------------

        with st.sidebar:

            st.subheader("Basic Flight Statistics Controls")

            time_min = float(pos_df["time_s"].min())
            time_max = float(pos_df["time_s"].max())

            selected_time_range = st.slider(
                "Displayed time range [s]",
                min_value=time_min,
                max_value=time_max,
                value=(time_min, time_max),
                step=1.0,
            )

            # available_phases = list(phase_colors.keys())

            # selected_phases = st.multiselect(
            #     "Show flight phases",
            #     available_phases,
            #     default=available_phases,
            # )

            st.divider()

            st.subheader("Phase Legend")

            for phase, rgb in phase_colors.items():

                color = rgb_to_rgba(rgb, alpha=0.35)

                st.markdown(
                    f"""
                    <div style="display:flex; align-items:center; margin-bottom:8px;">
                        <div style="width:18px; height:18px; background:{color}; margin-right:8px; border-radius:3px; "></div>
                        <div style="font-size:13px;">{phase}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        # -------------------------------------------------
        # Calculate sample rate
        # -------------------------------------------------

        dt = pos_df["time_s"].diff().median()

        sample_rate_hz = 1 / dt

        st.metric(
            "vehicle_local_position sample rate",
            f"{sample_rate_hz:.1f} Hz"
        )

        # -------------------------------------------------
        # Implement time synchronization
        # -------------------------------------------------

        plot_df = pos_df[
            (pos_df["time_s"] >= selected_time_range[0]) & 
            (pos_df["time_s"] <= selected_time_range[1])
            ].copy()

        # -------------------------------------------------
        # Get background coloring
        # -------------------------------------------------

        phase_segments = get_phase_segments(plot_df)

        # -------------------------------------------------
        # Main plots
        # -------------------------------------------------

        plot_configs = [
            {
                "position_column": "altitude_m",
                "velocity_column": "vertical_speed_m_s",
                "position_name": "Altitude [m]",
                "velocity_name": "Vertical Speed [m/s]",
            },
            {
                "position_column": "x",
                "velocity_column": "vx",
                "position_name": "North [m]",
                "velocity_name": "North Velocity [m/s]",
            },
            {
                "position_column": "y",
                "velocity_column": "vy",
                "position_name": "East [m]",
                "velocity_name": "East Velocity [m/s]",
            },
        ]

        for config in plot_configs:

            # fig_phase = make_subplots(
            # specs=[[{"secondary_y": True}]]
            # )

            # position_column = config["position_column"]
            # velocity_column = config["velocity_column"]

            # Full position reference line
            # fig_phase.add_trace(
            #     go.Scatter(
            #         x=plot_df["time_s"],
            #         y=plot_df[position_column],
            #         mode="lines",
            #         name=config["position_name"],
            #         line=dict(width=2),
            #     ),
            #     secondary_y=False,
            # )

            # Velocity reference line
            # fig_phase.add_trace(
            #     go.Scatter(
            #         x=plot_df["time_s"],
            #         y=plot_df[velocity_column],
            #         mode="lines",
            #         name=config["velocity_name"],
            #         line=dict(width=2, dash="dot"),
            #     ),
            #     secondary_y=True,
            # )

            # # Phase overlays
            # for phase in selected_phases:

            #     phase_y = plot_df[position_column].where(
            #         plot_df["flight_phase"] == phase
            #     )

            #     fig_phase.add_trace(
            #         go.Scatter(
            #             x=plot_df["time_s"],
            #             y=phase_y,
            #             mode="lines",
            #             name=phase,
            #             line=dict(width=4),
            #         ),
            #         secondary_y=False,
            #     )

            # fig_pahse = add_phase_background(
            #     fig_phase,
            #     phase_segments,
            #     phase_colors
            # )

            # fig_phase.update_layout(
            #     title=f"{config["position_name"]} With Detected Flight Phases and Velocity",
            #     height=650,
            #     legend=dict(
            #         orientation="h",
            #         yanchor="bottom",
            #         y=1.02,
            #         xanchor="right",
            #         x=1
            #     )
            # )

            # fig_phase.update_xaxes(title_text="Time [s]")
            # fig_phase.update_yaxes(title_text=config["position_name"],secondary_y=False)
            # fig_phase.update_yaxes(title_text=config["velocity_name"],secondary_y=True)

            # st.plotly_chart(fig_phase, width="stretch")

            position_column = config["position_column"]

            fig_phase = px.line(
                plot_df,
                x="time_s",
                y=position_column,
                title=f"{config['position_name']}",
                width=20,
            )

            fig_pahse = add_phase_background(
                fig_phase,
                phase_segments,
                phase_colors
            )

            st.plotly_chart(fig_pahse, width="stretch")

        fig = px.line(
            plot_df,
            x="time_s",
            y="horizontal_speed_m_s",
            title="Horizontal Speed"
        )

        fig.add_hline(y=0.35,line_color="rgba(255,255,255,0.6)",line_dash="dot",line_width=1)
        fig.add_hline(y=1.0,line_color="rgba(255,255,255,0.6)",line_dash="dot",line_width=1)

        fig = add_phase_background(
            fig,
            phase_segments,
            phase_colors
        )

        st.plotly_chart(fig, width="stretch")

        fig = px.line(
            plot_df,
            x="time_s",
            y="vertical_speed_m_s",
            title="Vertical Speed"
        )

        fig.add_hline(y=0.5,line_color="rgba(255,255,255,0.6)",line_dash="dot",line_width=1)
        fig.add_hline(y=0.2,line_color="rgba(255,255,255,0.6)",line_dash="dot",line_width=1)
        fig.add_hline(y=-0.2,line_color="rgba(255,255,255,0.6)",line_dash="dot",line_width=1)
        fig.add_hline(y=-0.5,line_color="rgba(255,255,255,0.6)",line_dash="dot",line_width=1)

        fig = add_phase_background(
            fig,
            phase_segments,
            phase_colors
        )

        st.plotly_chart(fig, width="stretch")

    elif page == "Hover Analysis":

        st.header("Hover Analysis")

        pos_df: pd.DataFrame = flight.position
        att_df: pd.DataFrame = flight.attitude

        all_segments: list = get_phase_segments(pos_df)
        hover_segments: list = [
            segment for segment in all_segments
            if segment["phase"] == "hover"
        ]

        if not hover_segments:
            st.info("No hover segments detected.")
            st.stop()

        with st.sidebar:
            st.subheader("Hover Analysis Controls")

            min_hover_duration_s = st.slider(
                "Minimum hover duration [s]",
                min_value=1.0,
                max_value=30.0,
                value=3.0,
                step=1.0,
            )

        hover_metric_references = apply_hover_reference_controls(
            DEFAULT_HOVER_REFERENCE_BANDS
        )

        hover_segments = [
            segment for segment in hover_segments
            if segment["end_time"] - segment["start_time"] >= min_hover_duration_s
        ]

        if not hover_segments:
            st.info("No hover segments remain after applying the minimum-duration filter.")
            st.stop()

        # -------------------------------------------------
        # Overview altitude plot
        # -------------------------------------------------

        fig_altitude = px.line(
            pos_df,
            x="time_s",
            y="altitude_m",
            title="Altitude With Hover Segments",
            labels={
                "time_s": "Time [s]",
                "altitude_m": "Altitude [m]",
            }
        )

        for segment in hover_segments:
            fig_altitude.add_vrect(
                x0=segment["start_time"],
                x1=segment["end_time"],
                fillcolor=rgb_to_rgba(phase_colors["hover"], alpha=0.25),
                line_width=0,
                layer="below",
            )

        fig_altitude.update_layout(height=350)

        st.plotly_chart(fig_altitude, width="stretch")

        # -------------------------------------------------
        # Hover segment summary
        # -------------------------------------------------

        st.subheader("Detected Hover Segments")

        hover_summary = []

        for i, segment in enumerate(hover_segments):
            result = compute_hover_stability_for_segment(
                pos_df,
                att_df,
                segment["start_time"],
                segment["end_time"],
            )

            if result is None:
                continue

            metrics, _, _ = result

            hover_summary.append({
                "hover": i + 1,
                "start_s": segment["start_time"],
                "end_s": segment["end_time"],
                **metrics,
            })

        hover_summary_df = pd.DataFrame(hover_summary)

        if hover_summary_df.empty:
            st.info("No hover segments could be evaluated.")
            st.stop()

        st.dataframe(
            hover_summary_df[
                [
                    "hover",
                    "start_s",
                    "end_s",
                    "duration_s",
                    "mean_altitude_m",
                    "altitude_rms_cm",
                    "altitude_p95_abs_cm",
                    "rms_drift_cm",
                    "drift_p95_cm",
                    "avg_ground_speed_m_s",
                    "roll_std_deg",
                    "pitch_std_deg",
                    "yaw_std_deg",
                    "yaw_range_deg",
                ]
            ].style.format({
                "start_s": "{:.1f}",
                "end_s": "{:.1f}",
                "duration_s": "{:.1f}",
                "mean_altitude_m": "{:.2f}",
                "altitude_rms_cm": "{:.2f}",
                "altitude_p95_abs_cm": "{:.2f}",
                "rms_drift_cm": "{:.2f}",
                "drift_p95_cm": "{:.2f}",
                "avg_ground_speed_m_s": "{:.3f}",
                "roll_std_deg": "{:.3f}",
                "pitch_std_deg": "{:.3f}",
                "yaw_std_deg": "{:.3f}",
                "yaw_range_deg": "{:.3f}",
            }),
            width="stretch",
        )

        # -------------------------------------------------
        # Hover selector
        # -------------------------------------------------

        hover_options = {
            f"Hover {int(row['hover'])}: {row['start_s']:.1f}s - {row['end_s']:.1f}s | "
            f"{row['duration_s']:.1f}s | RMS drift {row['rms_drift_cm']:.1f} cm | "
            f"Yaw STD {row['yaw_std_deg']:.2f}°": row
            for _, row in hover_summary_df.iterrows()
        }

        selected_label = st.selectbox(
            "Select hover segment",
            list(hover_options.keys())
        )

        selected_hover = hover_options[selected_label]

        start_time = selected_hover["start_s"]
        end_time = selected_hover["end_s"]

        hover_metrics, hover_df, hover_attitude_df = compute_hover_stability_for_segment(
            pos_df,
            att_df,
            start_time,
            end_time,
        )

        # -------------------------------------------------
        # Hover Metric Overview
        # -------------------------------------------------

        st.subheader("Hover Metric Overview")

        metric_reference_df = build_hover_metrics_reference_dataframe(
            hover_metrics,
            hover_metric_references,
        )

        fig_reference = create_hover_reference_bar_chart(metric_reference_df)
        st.plotly_chart(fig_reference, width="stretch")

        st.caption(
            "Reference bands are exploratory and are not pass/fail limits. "
            "They are used to make relative differences between hover segments easier to see. "
            "Without mission requirements and vehicle-specific baseline data, "
            "these values should not be interpreted as absolute stability criteria."
        )

        with st.expander("Show hover metric reference values", expanded=False):
            st.dataframe(
                metric_reference_df[
                    [
                        "metric",
                        "value",
                        "unit",
                        "low_limit",
                        "elevated_limit",
                        "status",
                        "usage_percent",
                    ]
                ].style.format({
                    "value": "{:.3f}",
                    "low_limit": "{:.3f}",
                    "elevated_limit": "{:.3f}",
                    "usage_percent": "{:.1f} %",
                }),
                width="stretch",
            )

        # -------------------------------------------------
        # Metrics
        # -------------------------------------------------

        st.subheader("Detailed Hover Stability Metrics")

        c1, c2, c3, c4 = st.columns(4)

        c1.metric("Duration", format_duration(hover_metrics["duration_s"]))
        c2.metric("Avg Ground Speed", f"{hover_metrics['avg_ground_speed_m_s']:.3f} m/s")
        c3.metric("Max Ground Speed", f"{hover_metrics['max_ground_speed_m_s']:.3f} m/s")

        st.subheader("Altitude Stability Metrics")

        c5, c6, c7, c8 = st.columns(4)

        c5.metric("Mean Altitude", f"{hover_metrics['mean_altitude_m']:.2f} m")
        c6.metric("Altitude STD", f"{hover_metrics['altitude_std_cm']:.2f} cm")
        c7.metric("Altitude RMS", f"{hover_metrics['altitude_rms_cm']:.2f} cm")
        c8.metric("Altitude Range", f"{hover_metrics['altitude_range_cm']:.2f} cm")

        c9, c10, c11, c12 = st.columns(4)

        c9.metric("Altitude 95%", f"{hover_metrics['altitude_p95_abs_cm']:.2f} cm")
        c10.metric("Altitude 99%", f"{hover_metrics['altitude_p99_abs_cm']:.2f} cm")
        
        st.subheader("Drift Stability Metrics")

        c13, c14, c15, c16 = st.columns(4)

        c13.metric("RMS Drift", f"{hover_metrics['rms_drift_cm']:.2f} cm")
        c14.metric("Drift 95%", f"{hover_metrics['drift_p95_cm']:.2f} cm")
        c15.metric("Drift 99%", f"{hover_metrics['drift_p99_cm']:.2f} cm")
        c16.metric("Drift STD", f"{hover_metrics['drift_std_cm']:.2f} cm")

        c17, c18, c19, c20 = st.columns(4)

        c17.metric("Max Drift", f"{hover_metrics['max_drift_cm']:.2f} cm")

        st.subheader("Attitude Stability Metrics")

        c21, c22, c23, c24 = st.columns(4)

        c21.metric("Mean Yaw", f"{hover_metrics['mean_yaw_deg']:.2f}°")
        c22.metric("Yaw Range", f"{hover_metrics['yaw_range_deg']:.3f}°")
        c23.metric("Max Yaw Drift", f"{hover_metrics['max_abs_yaw_drift_deg']:.3f}°")
        c24.metric("Yaw STD", f"{hover_metrics['yaw_std_deg']:.3f}°")

        c25, c26, c27, c28 = st.columns(4)

        c25.metric("Roll STD", f"{hover_metrics['roll_std_deg']:.3f}°")
        c26.metric("Pitch STD", f"{hover_metrics['pitch_std_deg']:.3f}°")

        # -------------------------------------------------
        # Altitude stability
        # -------------------------------------------------

        fig = px.line(
            hover_df,
            "time_s",
            "altitude_drift_cm",
            title="Normalized Altitude [cm]",
            labels={
                "time_s": "Time [s]",
                "altitude_drift_cm": "Normalized Altitude [cm]",
            }
        )

        fig.add_hline(y=hover_metrics["altitude_std_cm"], line_color="rgba(255,255,255,0.6)", line_dash="dot", line_width=1, annotation_text="STD", annotation_position="top left")
        fig.add_hline(y=-hover_metrics["altitude_std_cm"], line_color="rgba(255,255,255,0.6)", line_dash="dot", line_width=1, annotation_text="STD", annotation_position="top left")
        fig.add_hline(y=hover_metrics["altitude_p95_abs_cm"], line_color="rgba(255,255,255,0.4)", line_dash="dash", line_width=1, annotation_text="P 95%", annotation_position="top left")
        fig.add_hline(y=-hover_metrics["altitude_p95_abs_cm"], line_color="rgba(255,255,255,0.4)", line_dash="dash", line_width=1, annotation_text="P 95%", annotation_position="top left")
        fig.add_hline(y=0, line_color="rgba(255,255,255,0.8)", line_width=1)

        fig.update_yaxes(range=[-25, 25])

        st.plotly_chart(fig, width="stretch")

        # -------------------------------------------------
        # Horizontal drift magnitude
        # -------------------------------------------------

        fig = px.line(
            hover_df,
            "time_s",
            "drift_from_center_cm",
            title="Drift from center [cm]",
            labels={
                "time_s": "Time [s]",
                "drift_from_center_cm": "Drift from center [cm]",
            }
        )

        fig.add_hline(y=hover_metrics["rms_drift_cm"], line_color="rgba(255,255,255,0.6)", line_dash="dot", line_width=1, annotation_text="RMS", annotation_position="top left")
        fig.add_hline(y=hover_metrics["drift_p95_cm"], line_color="rgba(255,255,255,0.4)", line_dash="dash", line_width=1, annotation_text="P 95%", annotation_position="top left")
        fig.add_hline(y=0, line_color="rgba(255,255,255,0.8)", line_width=2)

        fig.update_yaxes(range=[0, 40])

        st.plotly_chart(fig, width="stretch")

        # -------------------------------------------------
        # 2D XY hover drift
        # -------------------------------------------------

        fig_xy = px.line(
            hover_df,
            x="y_error_cm",
            y="x_error_cm",
            title="Hover XY Drift Around Segment Center",
            labels={
                "y_error_cm": "East error [cm]",
                "x_error_cm": "North error [cm]",
            }
        )

        fig_xy.add_trace(
            go.Scatter(
                x=[0],
                y=[0],
                mode="markers",
                name="Hover center",
                marker=dict(size=10),
            )
        )

        fig_xy.update_yaxes(scaleanchor="x", scaleratio=1, range=[-40, 40])
        fig_xy.update_xaxes(range=[-40, 40])
        fig_xy.update_layout(height=550)

        st.plotly_chart(fig_xy, width="stretch")

        # -------------------------------------------------
        # Velocity
        # -------------------------------------------------

        fig = make_subplots()

        fig.add_trace(go.Scatter(
            x=hover_df["time_s"],
            y=hover_df["horizontal_speed_m_s"],
            mode="lines",
            name="Horizontal speed"
        ))

        fig.add_trace(go.Scatter(
            x=hover_df["time_s"],
            y=hover_df["vertical_speed_m_s"],
            mode="lines",
            name="Vertical speed",
        ))
        
        fig.update_layout(
            title="Velocity",
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            )
        )
        fig.add_hline(y=0, line_color="rgba(255,255,255,0.8)", line_width=1)
        
        fig.update_xaxes(title_text="Time [s]")
        fig.update_yaxes(title_text="Velocity [m/s]", range=[-0.2, 0.35])

        st.plotly_chart(fig, width="stretch")

        # -------------------------------------------------
        # Roll and pitch attitude
        # -------------------------------------------------

        fig = make_subplots()

        fig.add_trace(go.Scatter(
            x=hover_attitude_df["time_s"],
            y=hover_attitude_df["roll_deg"],
            mode="lines",
            name="Roll",
            line=dict(color=rgb_to_hex(plot_colors["roll"])),
        ))

        fig.add_trace(go.Scatter(
            x=hover_attitude_df["time_s"],
            y=hover_attitude_df["pitch_deg"],
            mode="lines",
            name="Pitch",
            line=dict(color=rgb_to_hex(plot_colors["pitch"])),
        ))
        
        fig.update_layout(
            title="Roll / Pitch Analysis",
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            )
        )
        fig.add_hline(y=0, line_color="rgba(255,255,255,0.8)", line_width=1)
        
        fig.update_xaxes(title_text="Time [s]")
        fig.update_yaxes(title_text="Roll / Pitch [°]", range=[-5, 5])

        st.plotly_chart(fig, width="stretch")

        # -------------------------------------------------
        # Yaw attitude
        # -------------------------------------------------

        fig = go.Figure()

        fig.add_trace(go.Scatter(
            x=hover_attitude_df["time_s"],
            y=hover_attitude_df["yaw_drift_deg"],
            name= "Yaw Drift",
            line=dict(color=rgb_to_hex(plot_colors["yaw"])),
        ))

        fig.update_layout(
            title="Yaw Drift Around Segment Mean [deg]", 
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            )
        )

        fig.add_hline(y=hover_metrics["yaw_std_deg"], line_color="rgba(255,255,255,0.6)", line_dash="dot", line_width=1, annotation_text="STD", annotation_position="top left")
        fig.add_hline(y=-hover_metrics["yaw_std_deg"], line_color="rgba(255,255,255,0.6)", line_dash="dot", line_width=1, annotation_text="STD", annotation_position="top left")
        fig.add_hline(y=0, line_color="rgba(255,255,255,0.8)", line_width=1)

        fig.update_xaxes(title_text= "Time [s]")
        fig.update_yaxes(title_text= "Yaw drift [°]", range=[-5, 5])

        st.plotly_chart(fig, width="stretch")

    elif page == "Actuator Output Analysis":

        st.header("Actuator Output Analysis")

        motor_output_df, motor_output_metrics, active_output_indices = flight.actuator_outputs
        pos_df: pd.DataFrame = flight.position
        attitude_rates_df: pd.DataFrame = flight.body_rates
        attitude_df: pd.DataFrame = flight.attitude
        integrator_df: pd.DataFrame = flight.integrator_status

        with st.sidebar:

            st.subheader("Actuator Analysis Controls")

            time_min = float(pos_df["time_s"].min())
            time_max = float(pos_df["time_s"].max())

            selected_time_range = st.slider(
                "Displayed time range [s]",
                min_value=time_min,
                max_value=time_max,
                value=(time_min, time_max),
                step=1.0,
            )

            st.divider()

            st.subheader("Phase Legend")

            for phase, rgb in phase_colors.items():

                color = rgb_to_rgba(rgb, alpha=0.35)

                st.markdown(
                    f"""
                    <div style="display:flex; align-items:center; margin-bottom:8px;">
                        <div style="width:18px; height:18px; background:{color}; margin-right:8px; border-radius:3px; "></div>
                        <div style="font-size:13px;">{phase}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            st.divider()

        with st.sidebar.expander("Motor Pair Analysis", expanded=False):
            max_pairs = len(active_output_indices) // 2

            num_pairs = st.number_input(
                "Number of motor pairs",
                min_value=1,
                max_value=max_pairs,
                value=min(3, max_pairs),
                step=1,
            )

            pair_config = []
            used_outputs = set()

            for pair_number in range(int(num_pairs)):
                st.markdown(f"**Pair {pair_number + 1}**")

                available_a = [
                    idx for idx in active_output_indices
                    if idx not in used_outputs
                ]

                if not available_a:
                    break
                
                col_a, col_b = st.columns(2)

                with col_a:
                    motor_a = st.selectbox(
                        "Output A",
                        available_a,
                        key=f"pair_{pair_number}_output_a",
                    )

                available_b = [
                    idx for idx in active_output_indices
                    if idx not in used_outputs and idx != motor_a
                ]

                if not available_b:
                    break
                
                with col_b:
                    motor_b = st.selectbox(
                        "Output B",
                        available_b,
                        key=f"pair_{pair_number}_output_b",
                    )

                pair_config.append((motor_a, motor_b))
                used_outputs.update([motor_a, motor_b])

        c1, c2, c3, c4 = st.columns(4)

        c1.metric("Mean Motor Output",f"{motor_output_metrics['mean_motor_output']:.0f} µs")
        c2.metric("Max Motor Output",f"{motor_output_metrics['max_motor_output']:.0f} µs")
        c3.metric("Mean Output Spread",f"{motor_output_metrics['mean_motor_output_spread']:.0f} µs")
        c4.metric("P95 Output Spread",f"{motor_output_metrics['p95_motor_output_spread']:.0f} µs")

        # ------------------------------------------------
        # Apply selected time range
        # ------------------------------------------------

        plot_motor_output_df = motor_output_df[
            (motor_output_df["time_s"] >= selected_time_range[0]) &
            (motor_output_df["time_s"] <= selected_time_range[1])
        ].copy()

        plot_pos_df = pos_df[
            (pos_df["time_s"] >= selected_time_range[0]) & 
            (pos_df["time_s"] <= selected_time_range[1])
        ].copy()
        
        plot_attitude_rates_df = attitude_rates_df[
            (attitude_rates_df["time_s"] >= selected_time_range[0]) & 
            (attitude_rates_df["time_s"] <= selected_time_range[1])
        ].copy()

        plot_attitude_df = attitude_df[
            (attitude_df["time_s"] >= selected_time_range[0]) & 
            (attitude_df["time_s"] <= selected_time_range[1])
        ].copy()

        plot_integrator_df = integrator_df[
            (integrator_df["time_s"] >= selected_time_range[0]) &
            (integrator_df["time_s"] <= selected_time_range[1])
        ].copy()

        phase_segments: list = get_phase_segments(plot_pos_df)

        # ------------------------------------------------
        # Output graph
        # ------------------------------------------------

        st.subheader("Motor Command Overview")

        fig = go.Figure()
        
        for i in active_output_indices:
        
            fig.add_trace(go.Scatter(
                x=plot_motor_output_df["time_s"],
                y=plot_motor_output_df[f"output[{i}]"],
                mode="lines",
                name=f"Actuator Output {i}"
            ))

        fig.add_trace(go.Scatter(
            x=plot_motor_output_df["time_s"],
            y=plot_motor_output_df["mean_motor_output"],
            mode="lines",
            name="Mean Motor Output"
        ))

        fig = add_phase_background(fig,phase_segments,phase_colors)

        fig.update_layout(
            title="Actuator Output [PWM-equivalent]",
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            )
        )

        fig.update_xaxes(title_text="Time [s]")
        fig.update_yaxes(title_text="Motor Command [µs, assumed PWM]")

        st.plotly_chart(fig, width="stretch")

        # ------------------------------------------------
        # Rotational response 
        # ------------------------------------------------

        st.subheader("Vehicle Response")

        fig = go.Figure()

        fig.add_trace(go.Scatter(
            x=plot_attitude_rates_df["time_s"],
            y=plot_attitude_rates_df["roll_rate_deg_s"],
            mode="lines",
            name="Roll Body Rate",
            line=dict(color=rgb_to_hex(plot_colors["roll"])),
        ))

        fig.add_trace(go.Scatter(
            x=plot_attitude_rates_df["time_s"],
            y=plot_attitude_rates_df["pitch_rate_deg_s"],
            mode="lines",
            name="Pitch Body Rate",
            line=dict(color=rgb_to_hex(plot_colors["pitch"])),
        ))

        fig.add_trace(go.Scatter(
            x=plot_attitude_rates_df["time_s"],
            y=plot_attitude_rates_df["yaw_rate_deg_s"],
            mode="lines",
            name="Yaw Body Rate",
            line=dict(color=rgb_to_hex(plot_colors["yaw"])),
        ))

        fig = add_phase_background(fig,phase_segments,phase_colors)

        fig.update_layout(
            title="Rotational Response",
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            )
        )

        fig.update_xaxes(title_text="Time [s]")
        fig.update_yaxes(title_text="Rate [°/s]")

        st.plotly_chart(fig, width="stretch")

        # ------------------------------------------------
        # Attitude 
        # ------------------------------------------------

        fig = go.Figure()

        fig.add_trace(go.Scatter(
            x=plot_attitude_df["time_s"],
            y=plot_attitude_df["roll_deg"],
            mode="lines",
            name="Roll",
            line=dict(color=rgb_to_hex(plot_colors["roll"])),
            )
        )

        fig.add_trace(go.Scatter(
            x=plot_attitude_df["time_s"],
            y=plot_attitude_df["pitch_deg"],
            mode="lines",
            name="Pitch",
            line=dict(color=rgb_to_hex(plot_colors["pitch"])),
            )
        )

        fig = add_phase_background(fig,phase_segments,phase_colors)

        fig.update_layout(
            title="Roll/Pitch Over Time",
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            )
        )

        fig.update_xaxes(title_text="Time [s]")
        fig.update_yaxes(title_text="Roll / Pitch [°]")

        st.plotly_chart(fig,width="stretch")

        fig = go.Figure()

        fig.add_trace(go.Scatter(
            x=plot_attitude_df["time_s"],
            y=plot_attitude_df["yaw_deg"],
            mode="lines",
            name="Yaw",
            line=dict(color=rgb_to_hex(plot_colors["yaw"])),
            )
        )

        fig = add_phase_background(fig,phase_segments,phase_colors)

        fig.update_layout(
            title="Yaw Over Time",
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            )
        )

        fig.update_xaxes(title_text="Time [s]")
        fig.update_yaxes(title_text="Yaw [deg]")

        st.plotly_chart(fig, width="stretch")

        # ------------------------------------------------
        # Vehicle acceleration
        # ------------------------------------------------

        fig = go.Figure()

        fig.add_trace(go.Scatter(
            x=plot_pos_df["time_s"],
            y=plot_pos_df["ax"],
            mode="lines",
            name="North Acceleration")
        )

        fig.add_trace(go.Scatter(
            x=plot_pos_df["time_s"],
            y=plot_pos_df["ay"],
            mode="lines",
            name="East Acceleration")
        )

        fig.add_trace(go.Scatter(
            x=plot_pos_df["time_s"],
            y=plot_pos_df["az_up_m_s2"],
            mode="lines",
            name="Upward Acceleration")
        )

        fig = add_phase_background(fig,phase_segments,phase_colors)

        fig.update_layout(
            title="Vehicle Acceleration",
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            )
        )

        fig.update_xaxes(title_text="Time [s]")
        fig.update_yaxes(title_text="Acceleration [m/s²]")

        st.plotly_chart(fig, width="stretch")

        # ------------------------------------------------
        # Motor output spread 
        # ------------------------------------------------

        st.subheader("Motor Balance")

        fig = go.Figure()

        fig.add_trace(go.Scatter(
            x=plot_motor_output_df["time_s"],
            y=plot_motor_output_df["motor_output_spread"],
            mode="lines",
            name="Motor Output Spread"
        ))

        fig = add_phase_background(fig,phase_segments,phase_colors)

        fig.add_hline(motor_output_metrics["mean_motor_output_spread"], line_color="rgba(255,255,255,0.6)", line_dash="dash", line_width=1, annotation_text="Mean", annotation_position="top left")
        fig.add_hline(motor_output_metrics["p95_motor_output_spread"], line_color="rgba(255,255,255,0.6)", line_dash="dot", line_width=1, annotation_text="P95", annotation_position="top left")

        fig.update_layout(
            title="Motor Output Spread Over Time",
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            )
        )

        fig.update_xaxes(title_text="Time [s]")
        fig.update_yaxes(title_text="Output spread [µs, assumed PWM]")

        st.plotly_chart(fig, width="stretch")

        # ------------------------------------------------
        # Characteristics per Flight Phase
        # ------------------------------------------------ 

        st.subheader("Phase-Based Actuator Statistics")

        phase_df = plot_pos_df[["time_s", "flight_phase"]].sort_values("time_s")
        act_df = plot_motor_output_df.sort_values("time_s")

        act_df = pd.merge_asof(act_df, phase_df, on="time_s", direction="nearest")

        phase_actuator_stats = (
            act_df
            .groupby("flight_phase")
            .agg(
                mean_motor_output=("mean_motor_output", "mean"),
                max_motor_output=("max_motor_output", "max"),
                mean_output_spread=("motor_output_spread", "mean"),
                p95_output_spread=("motor_output_spread", lambda x: x.quantile(0.95)),
            )
            .reset_index()
        )

        st.dataframe(
            phase_actuator_stats[
                [
                    "flight_phase",
                    "mean_motor_output",
                    "max_motor_output",
                    "mean_output_spread",
                    "p95_output_spread",
                ]
            ].style.format({
                "mean_motor_output": "{:.2f}",
                "max_motor_output": "{:.2f}",
                "mean_output_spread": "{:.2f}",
                "p95_output_spread": "{:.2f}",
            }),
            width="stretch",
        )

        # ------------------------------------------------
        # User-Defined Motor Pair Analysis
        # ------------------------------------------------

        st.subheader("User-Defined Motor Pair Analysis")

        st.caption(
            "Motor pairs are user-defined and should be interpreted as exploratory. "
            "The pair mean output represents the common command component of the selected outputs. "
            "The differential output represents the opposite command component. "
            "These signals do not prove physical motor placement without the actual airframe geometry."
        )

        pair_df:pd.DataFrame = compute_motor_pair_components(plot_motor_output_df,pair_config)

        fig = go.Figure()

        for pair_number, (motor_a, motor_b) in enumerate(pair_config, start=1):
            pair_name = f"pair_{pair_number}_{motor_a}_{motor_b}"

            fig.add_trace(go.Scatter(
                x=pair_df["time_s"],
                y=pair_df[f"{pair_name}_mean_output"],
                mode="lines",
                name=f"Pair {pair_number} mean ({motor_a}, {motor_b})",
            ))

        fig = add_phase_background(fig, phase_segments, phase_colors)

        fig.update_layout(title="Pair Common Output")
        fig.update_xaxes(title_text="Time [s]")
        fig.update_yaxes(title_text="Pair mean output [µs, assumed PWM]")

        st.plotly_chart(fig, width="stretch")

        fig = go.Figure()

        for pair_number, (motor_a, motor_b) in enumerate(pair_config, start=1):
            pair_name = f"pair_{pair_number}_{motor_a}_{motor_b}"

            fig.add_trace(go.Scatter(
                x=pair_df["time_s"],
                y=pair_df[f"{pair_name}_differential_output"],
                mode="lines",
                name=f"Pair {pair_number} differential ({motor_a}, {motor_b})",
            ))

        fig = add_phase_background(fig, phase_segments, phase_colors)

        fig.add_hline(
            y=0,
            line_color="rgba(255,255,255,0.8)",
            line_width=1,
        )

        fig.update_layout(title="Pair Differential Output")
        fig.update_xaxes(title_text="Time [s]")
        fig.update_yaxes(title_text="Differential output [µs, assumed PWM]")

        st.plotly_chart(fig, width="stretch")

        # ------------------------------------------------
        # Advanced Controller Diagnostics
        # ------------------------------------------------

        with st.expander("Advanced Controller Diagnostics", expanded=False):
            fig = go.Figure()

            fig.add_trace(go.Scatter(
                x= plot_integrator_df["time_s"],
                y= plot_integrator_df["rollspeed_integ"],
                mode= "lines",
                name="Roll Rate Integrator",
                line=dict(color=rgb_to_hex(plot_colors["roll"]))
            ))

            fig.add_trace(go.Scatter(
                x= plot_integrator_df["time_s"],
                y= plot_integrator_df["pitchspeed_integ"],
                mode= "lines",
                name="Pitch Rate Integrator",
                line=dict(color=rgb_to_hex(plot_colors["pitch"]))
            ))

            fig.add_trace(go.Scatter(
                x= plot_integrator_df["time_s"],
                y= plot_integrator_df["yawspeed_integ"],
                mode= "lines",
                name="Yaw Rate Integrator",
                line=dict(color=rgb_to_hex(plot_colors["yaw"]))
            ))

            fig = add_phase_background(fig,phase_segments,phase_colors) 

            fig.update_layout(
                title="Rate Controller Integrator Status",
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="right",
                    x=1
                )
            )

            fig.update_xaxes(title_text="Time [s]")
            fig.update_yaxes(title_text="Integrator state [- or controller-output units]")

            st.plotly_chart(fig, width="stretch")

    elif page == "Vibration Analysis":

        st.header("Vibration Analysis")

        st.caption(
            "This page summarizes IMU vibration health from vehicle_imu_status and "
            "estimates the dominant accelerometer vibration frequency from sensor_accel. "
            "The worst flight phase is derived by merging the IMU status timestamps with "
            "the flight phases already produced by classify_flight_state()."
        )

        vibration_result = flight.vibration_analysis

        if vibration_result is None:
            st.info(
                "vehicle_imu_status was not found in this log, so the vibration "
                "health overview cannot be calculated."
            )
            st.stop()

        vibration_df, vibration_metrics, vibration_phase_stats, accel_psd_df = vibration_result
        pos_df: pd.DataFrame = flight.position
        sensor_accel_df: pd.DataFrame = flight.sensor_accel
        sensor_gyro_df: pd.DataFrame = flight.sensor_gyro
        actuator_controls_df: pd.DataFrame = flight.actuator_controls

        try:
            motor_output_df, motor_output_metrics, active_output_indices = flight.actuator_outputs
        except Exception:
            motor_output_df = pd.DataFrame()
            motor_output_metrics = {}
            active_output_indices = []

        with st.sidebar:
            st.subheader("Vibration Analysis Controls")

            time_min = float(pos_df["time_s"].min())
            time_max = float(pos_df["time_s"].max())

            selected_time_range = st.slider(
                "Displayed time range [s]",
                min_value=time_min,
                max_value=time_max,
                value=(time_min, time_max),
                step=1.0,
                key="vibration_analysis_time_range",
            )

            with st.expander("PSD / FFT settings", expanded=False):
                psd_window_duration_s = st.slider(
                    "PSD window duration [s]",
                    min_value=0.25,
                    max_value=5.0,
                    value=1.0,
                    step=0.25,
                    key="vibration_psd_surface_window_duration_s",
                )

                psd_update_interval_s = st.number_input(
                    "PSD update interval [s]",
                    min_value=0.10,
                    max_value=30.0,
                    value=1.0,
                    step=0.10,
                    key="vibration_psd_update_interval_s",
                )

                psd_surface_max_frequency_hz = st.number_input(
                    "PSD heatmap max frequency [Hz]",
                    min_value=1.0,
                    max_value=2000.0,
                    value=250.0,
                    step=25.0,
                    key="vibration_psd_surface_max_frequency_hz",
                )

                actuator_fft_max_frequency_hz = st.number_input(
                    "Actuator FFT max frequency [Hz]",
                    min_value=1.0,
                    max_value=2000.0,
                    value=250.0,
                    step=25.0,
                    key="vibration_actuator_fft_max_frequency_hz",
                )

                per_phase_band_power_low_hz = st.number_input(
                    "Per-phase band power lower frequency [Hz]",
                    min_value=0.0,
                    max_value=1999.0,
                    value=20.0,
                    step=5.0,
                    key="vibration_per_phase_band_power_low_hz",
                )

                per_phase_band_power_high_hz = st.number_input(
                    "Per-phase band power upper frequency [Hz]",
                    min_value=float(per_phase_band_power_low_hz + 1.0),
                    max_value=2000.0,
                    value=max(250.0, float(per_phase_band_power_low_hz + 1.0)),
                    step=5.0,
                    key="vibration_per_phase_band_power_high_hz",
                )

            st.divider()

            st.subheader("Phase Legend")

            for phase, rgb in phase_colors.items():

                color = rgb_to_rgba(rgb, alpha=0.35)

                st.markdown(
                    f"""
                    <div style="display:flex; align-items:center; margin-bottom:8px;">
                        <div style="width:18px; height:18px; background:{color}; margin-right:8px; border-radius:3px; "></div>
                        <div style="font-size:13px;">{phase}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        plot_vibration_df = vibration_df[
            (vibration_df["time_s"] >= selected_time_range[0]) &
            (vibration_df["time_s"] <= selected_time_range[1])
        ].copy()

        plot_pos_df = pos_df[
            (pos_df["time_s"] >= selected_time_range[0]) &
            (pos_df["time_s"] <= selected_time_range[1])
        ].copy()

        if sensor_accel_df is not None and not sensor_accel_df.empty and "time_s" in sensor_accel_df.columns:
            plot_sensor_accel_df = sensor_accel_df[
                (sensor_accel_df["time_s"] >= selected_time_range[0]) &
                (sensor_accel_df["time_s"] <= selected_time_range[1])
            ].copy()
        else:
            plot_sensor_accel_df = pd.DataFrame()

        if sensor_gyro_df is not None and not sensor_gyro_df.empty and "time_s" in sensor_gyro_df.columns:
            plot_sensor_gyro_df = sensor_gyro_df[
                (sensor_gyro_df["time_s"] >= selected_time_range[0]) &
                (sensor_gyro_df["time_s"] <= selected_time_range[1])
            ].copy()
        else:
            plot_sensor_gyro_df = pd.DataFrame()

        if actuator_controls_df is not None and not actuator_controls_df.empty and "time_s" in actuator_controls_df.columns:
            plot_actuator_controls_df = actuator_controls_df[
                (actuator_controls_df["time_s"] >= selected_time_range[0]) &
                (actuator_controls_df["time_s"] <= selected_time_range[1])
            ].copy()
        else:
            plot_actuator_controls_df = pd.DataFrame()

        if motor_output_df is not None and not motor_output_df.empty and "time_s" in motor_output_df.columns:
            plot_motor_output_df = motor_output_df[
                (motor_output_df["time_s"] >= selected_time_range[0]) &
                (motor_output_df["time_s"] <= selected_time_range[1])
            ].copy()
        else:
            plot_motor_output_df = pd.DataFrame()

        phase_segments: list = get_phase_segments(plot_pos_df)

        st.subheader("Vibration Health Overview")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric(
            "Max accel vibration metric",
            format_optional_value(vibration_metrics.get("max_accel_vibration_metric"), decimals=4),
        )
        c2.metric(
            "Max gyro vibration metric",
            format_optional_value(vibration_metrics.get("max_gyro_vibration_metric"), decimals=4),
        )
        c3.metric(
            "Total accel clipping",
            format_optional_count(vibration_metrics.get("total_accel_clipping")),
        )
        c4.metric(
            "Total gyro clipping",
            format_optional_count(vibration_metrics.get("total_gyro_clipping")),
        )

        c5, c6, c7, c8 = st.columns(4)
        c5.metric(
            "Dominant accel frequency",
            format_optional_value(vibration_metrics.get("dominant_accel_frequency_hz"), "Hz", decimals=2),
        )
        c6.metric(
            "sensor_accel sample rate",
            format_optional_value(vibration_metrics.get("sensor_accel_sample_rate_hz"), "Hz", decimals=1),
        )
        c7.metric(
            "sensor_accel FFT samples",
            format_optional_count(vibration_metrics.get("sensor_accel_samples")),
        )
        c8.metric(
            "Worst flight phase",
            vibration_metrics.get("worst_flight_phase", "unknown"),
        )

        with st.expander("Show source fields used for the health overview", expanded=False):
            source_df = pd.DataFrame([
                {
                    "metric": "accel_vibration_metric",
                    "source field(s)": vibration_metrics.get("accel_vibration_metric_source", "not found"),
                },
                {
                    "metric": "gyro_vibration_metric",
                    "source field(s)": vibration_metrics.get("gyro_vibration_metric_source", "not found"),
                },
                {
                    "metric": "total_accel_clipping",
                    "source field(s)": vibration_metrics.get("accel_clipping_source", "not found"),
                },
                {
                    "metric": "total_gyro_clipping",
                    "source field(s)": vibration_metrics.get("gyro_clipping_source", "not found"),
                },
                {
                    "metric": "sensor_accel FFT axes",
                    "source field(s)": vibration_metrics.get("sensor_accel_axis_columns", "not found"),
                },
                {
                    "metric": "sensor_accel time-domain axes",
                    "source field(s)": (
                        sensor_accel_df["sensor_accel_axis_columns"].dropna().iloc[0]
                        if (
                            sensor_accel_df is not None and
                            not sensor_accel_df.empty and
                            "sensor_accel_axis_columns" in sensor_accel_df.columns and
                            not sensor_accel_df["sensor_accel_axis_columns"].dropna().empty
                        )
                        else "not found"
                    ),
                },
                {
                    "metric": "sensor_gyro time-domain axes",
                    "source field(s)": (
                        sensor_gyro_df["sensor_gyro_axis_columns"].dropna().iloc[0]
                        if (
                            sensor_gyro_df is not None and
                            not sensor_gyro_df.empty and
                            "sensor_gyro_axis_columns" in sensor_gyro_df.columns and
                            not sensor_gyro_df["sensor_gyro_axis_columns"].dropna().empty
                        )
                        else "not found"
                    ),
                },
                {
                    "metric": "actuator_controls FFT",
                    "source field(s)": (
                        f"{actuator_controls_df['actuator_controls_topic'].dropna().iloc[0]}: "
                        f"{actuator_controls_df['actuator_controls_columns'].dropna().iloc[0]}"
                        if (
                            actuator_controls_df is not None and
                            not actuator_controls_df.empty and
                            "actuator_controls_topic" in actuator_controls_df.columns and
                            "actuator_controls_columns" in actuator_controls_df.columns and
                            not actuator_controls_df["actuator_controls_topic"].dropna().empty and
                            not actuator_controls_df["actuator_controls_columns"].dropna().empty
                        )
                        else "not found"
                    ),
                },
            ])
            st.dataframe(source_df, width="stretch")

        st.caption(
            "Clipping totals are calculated from accel_clipping / delta_velocity_clipping "
            "and gyro_clipping / delta_angle_clipping fields when present. Counter-like "
            "signals are integrated by positive increments; event-like signals are summed."
        )

        st.subheader("Actuator correlation")

        st.caption(
            "This segment compares IMU vibration indicators against actuator demand. "
            "The scatter plots are time-aligned with nearest-neighbor matching, the "
            "frequency plot compares selected-window accelerometer content with "
            "actuator-control FFT content, and the clipping plot overlays clipping events "
            "with observed motor-output limits. These plots show correlation only; they do "
            "not prove causality without airframe geometry, motor mapping, and controlled tests."
        )

        actuator_correlation_df = pd.DataFrame()

        if plot_vibration_df.empty or plot_motor_output_df.empty:
            st.info(
                "Actuator correlation requires both vehicle_imu_status and actuator_outputs "
                "samples in the selected time range."
            )
        else:
            vibration_correlation_columns = [
                "time_s",
                "accel_vibration_metric",
                "gyro_vibration_metric",
            ]
            if "flight_phase" in plot_vibration_df.columns:
                vibration_correlation_columns.append("flight_phase")

            motor_correlation_columns = [
                "time_s",
                "mean_motor_output",
                "motor_output_spread",
                "min_motor_output",
                "max_motor_output",
            ]

            required_vibration_columns = set(vibration_correlation_columns)
            required_motor_columns = set(motor_correlation_columns)

            if not required_vibration_columns.issubset(plot_vibration_df.columns):
                st.info("Required vibration metric columns are missing for actuator correlation.")
            elif not required_motor_columns.issubset(plot_motor_output_df.columns):
                st.info("Required actuator output summary columns are missing for actuator correlation.")
            else:
                actuator_correlation_df = pd.merge_asof(
                    plot_vibration_df[vibration_correlation_columns]
                    .dropna(subset=["time_s"])
                    .sort_values("time_s"),
                    plot_motor_output_df[motor_correlation_columns]
                    .dropna(subset=["time_s"])
                    .sort_values("time_s"),
                    on="time_s",
                    direction="nearest",
                )

                phase_color_map = {
                    phase: rgb_to_hex(rgb)
                    for phase, rgb in phase_colors.items()
                }

                accel_motor_corr_df = actuator_correlation_df.dropna(
                    subset=["mean_motor_output", "accel_vibration_metric"]
                ).copy()

                if accel_motor_corr_df.empty:
                    st.info("No finite accel vibration metric / mean motor output samples are available.")
                else:
                    scatter_color_col = (
                        "flight_phase"
                        if "flight_phase" in accel_motor_corr_df.columns
                        else None
                    )
                    fig_accel_motor_corr = px.scatter(
                        accel_motor_corr_df,
                        x="mean_motor_output",
                        y="accel_vibration_metric",
                        color=scatter_color_col,
                        color_discrete_map=phase_color_map if scatter_color_col else None,
                        hover_data={
                            "time_s": ":.2f",
                            "mean_motor_output": ":.1f",
                            "accel_vibration_metric": ":.6f",
                        },
                        title="Accel Vibration Metric vs Mean Motor Output",
                        labels={
                            "mean_motor_output": "Mean motor output [µs, assumed PWM]",
                            "accel_vibration_metric": "Accel vibration metric",
                            "flight_phase": "Flight phase",
                        },
                    )
                    fig_accel_motor_corr.update_traces(marker=dict(size=6), opacity=0.7)
                    fig_accel_motor_corr.update_layout(height=520)
                    st.plotly_chart(fig_accel_motor_corr, width="stretch")

                gyro_spread_corr_df = actuator_correlation_df.dropna(
                    subset=["motor_output_spread", "gyro_vibration_metric"]
                ).copy()

                if gyro_spread_corr_df.empty:
                    st.info("No finite gyro vibration metric / motor output spread samples are available.")
                else:
                    scatter_color_col = (
                        "flight_phase"
                        if "flight_phase" in gyro_spread_corr_df.columns
                        else None
                    )
                    fig_gyro_spread_corr = px.scatter(
                        gyro_spread_corr_df,
                        x="motor_output_spread",
                        y="gyro_vibration_metric",
                        color=scatter_color_col,
                        color_discrete_map=phase_color_map if scatter_color_col else None,
                        hover_data={
                            "time_s": ":.2f",
                            "motor_output_spread": ":.1f",
                            "gyro_vibration_metric": ":.6f",
                        },
                        title="Gyro Vibration Metric vs Motor Output Spread",
                        labels={
                            "motor_output_spread": "Motor output spread [µs, assumed PWM]",
                            "gyro_vibration_metric": "Gyro vibration metric",
                            "flight_phase": "Flight phase",
                        },
                    )
                    fig_gyro_spread_corr.update_traces(marker=dict(size=6), opacity=0.7)
                    fig_gyro_spread_corr.update_layout(height=520)
                    st.plotly_chart(fig_gyro_spread_corr, width="stretch")

        st.markdown("**Dominant frequency vs actuator-control frequency content**")

        actuator_fft_df = pd.DataFrame()
        actuator_fft_metrics = {}
        actuator_frequency_content_df = pd.DataFrame()

        if plot_actuator_controls_df.empty:
            st.info(
                "No actuator_controls topic was found in the selected time range, so the "
                "frequency-content comparison cannot be calculated."
            )
        else:
            actuator_control_cols = [
                col for col in plot_actuator_controls_df.columns
                if col.startswith("control_")
            ]

            actuator_fft_df, actuator_fft_metrics = compute_signal_fft(
                plot_actuator_controls_df,
                actuator_control_cols,
            )

            if not actuator_fft_df.empty:
                actuator_frequency_content_df = (
                    actuator_fft_df[
                        (actuator_fft_df["frequency_hz"] > 0) &
                        (actuator_fft_df["frequency_hz"] <= float(actuator_fft_max_frequency_hz))
                    ]
                    .groupby("frequency_hz", as_index=False)["amplitude"]
                    .sum()
                    .rename(columns={"amplitude": "summed_actuator_control_amplitude"})
                )

            if actuator_frequency_content_df.empty:
                st.info(
                    "The selected actuator_controls time range is too short or contains too "
                    "little finite data for FFT analysis."
                )
            else:
                accel_frequency_content_df = pd.DataFrame()
                selected_accel_dominant_frequency_hz = np.nan

                if not plot_sensor_accel_df.empty:
                    accel_fft_columns = [
                        col for col in [
                            "accel_x_m_s2",
                            "accel_y_m_s2",
                            "accel_z_m_s2",
                            "accel_magnitude_m_s2",
                        ]
                        if col in plot_sensor_accel_df.columns
                    ]

                    accel_fft_df, accel_fft_metrics = compute_signal_fft(
                        plot_sensor_accel_df,
                        accel_fft_columns,
                    )

                    if not accel_fft_df.empty:
                        accel_frequency_content_df = (
                            accel_fft_df[
                                (accel_fft_df["frequency_hz"] > 0) &
                                (accel_fft_df["frequency_hz"] <= float(actuator_fft_max_frequency_hz))
                            ]
                            .groupby("frequency_hz", as_index=False)["amplitude"]
                            .sum()
                            .rename(columns={"amplitude": "summed_accel_amplitude"})
                        )

                        if not accel_frequency_content_df.empty:
                            dominant_idx = accel_frequency_content_df["summed_accel_amplitude"].idxmax()
                            selected_accel_dominant_frequency_hz = float(
                                accel_frequency_content_df.loc[dominant_idx, "frequency_hz"]
                            )

                dominant_actuator_frequency_hz = np.nan
                if not actuator_frequency_content_df.empty:
                    dominant_actuator_idx = actuator_frequency_content_df[
                        "summed_actuator_control_amplitude"
                    ].idxmax()
                    dominant_actuator_frequency_hz = float(
                        actuator_frequency_content_df.loc[dominant_actuator_idx, "frequency_hz"]
                    )

                fig_frequency_correlation = make_subplots(specs=[[{"secondary_y": True}]])

                fig_frequency_correlation.add_trace(
                    go.Scatter(
                        x=actuator_frequency_content_df["frequency_hz"],
                        y=actuator_frequency_content_df["summed_actuator_control_amplitude"],
                        mode="lines",
                        name="Summed actuator-control FFT amplitude",
                    ),
                    secondary_y=False,
                )

                if not accel_frequency_content_df.empty:
                    fig_frequency_correlation.add_trace(
                        go.Scatter(
                            x=accel_frequency_content_df["frequency_hz"],
                            y=accel_frequency_content_df["summed_accel_amplitude"],
                            mode="lines",
                            name="Summed accel FFT amplitude",
                        ),
                        secondary_y=True,
                    )

                if pd.notna(selected_accel_dominant_frequency_hz):
                    fig_frequency_correlation.add_vline(
                        x=selected_accel_dominant_frequency_hz,
                        line_dash="dash",
                        line_width=1,
                        annotation_text="selected accel dominant",
                        annotation_position="top right",
                    )
                elif pd.notna(vibration_metrics.get("dominant_accel_frequency_hz")):
                    fig_frequency_correlation.add_vline(
                        x=float(vibration_metrics.get("dominant_accel_frequency_hz")),
                        line_dash="dash",
                        line_width=1,
                        annotation_text="log accel dominant",
                        annotation_position="top right",
                    )

                if pd.notna(dominant_actuator_frequency_hz):
                    fig_frequency_correlation.add_vline(
                        x=dominant_actuator_frequency_hz,
                        line_dash="dot",
                        line_width=1,
                        annotation_text="actuator dominant",
                        annotation_position="bottom right",
                    )

                fig_frequency_correlation.update_layout(
                    title="Dominant Accelerometer Frequency vs Actuator-Control Frequency Content",
                    height=560,
                    legend=dict(
                        orientation="h",
                        yanchor="bottom",
                        y=1.02,
                        xanchor="right",
                        x=1,
                    ),
                )
                fig_frequency_correlation.update_xaxes(title_text="Frequency [Hz]")
                fig_frequency_correlation.update_yaxes(
                    title_text="Summed actuator-control FFT amplitude [control units]",
                    secondary_y=False,
                )
                fig_frequency_correlation.update_yaxes(
                    title_text="Summed acceleration FFT amplitude [m/s²]",
                    secondary_y=True,
                )

                st.plotly_chart(fig_frequency_correlation, width="stretch")

                c1, c2, c3 = st.columns(3)
                c1.metric(
                    "Selected accel dominant frequency",
                    format_optional_value(selected_accel_dominant_frequency_hz, "Hz", decimals=2),
                )
                c2.metric(
                    "Actuator-control dominant frequency",
                    format_optional_value(dominant_actuator_frequency_hz, "Hz", decimals=2),
                )
                c3.metric(
                    "Actuator FFT sample rate",
                    format_optional_value(actuator_fft_metrics.get("sample_rate_hz"), "Hz", decimals=1),
                )

        st.markdown("**Clipping events overlaid with motor limits**")

        if plot_vibration_df.empty or plot_motor_output_df.empty:
            st.info(
                "Clipping / motor-limit overlay requires both vehicle_imu_status and "
                "actuator_outputs samples in the selected time range."
            )
        elif not all(
            col in plot_motor_output_df.columns
            for col in ["mean_motor_output", "min_motor_output", "max_motor_output"]
        ):
            st.info("Motor output limit columns are missing for the clipping overlay.")
        else:
            clipping_columns = ["time_s"]
            for col in ["accel_clipping_count", "gyro_clipping_count"]:
                if col in plot_vibration_df.columns:
                    clipping_columns.append(col)

            if len(clipping_columns) == 1:
                st.info("No accel or gyro clipping counter columns are available for the clipping overlay.")
            else:
                clipping_motor_df = pd.merge_asof(
                    plot_motor_output_df[
                        [
                            "time_s",
                            "mean_motor_output",
                            "min_motor_output",
                            "max_motor_output",
                        ]
                    ]
                    .dropna(subset=["time_s"])
                    .sort_values("time_s"),
                    plot_vibration_df[clipping_columns]
                    .dropna(subset=["time_s"])
                    .sort_values("time_s"),
                    on="time_s",
                    direction="nearest",
                )

                if clipping_motor_df.empty:
                    st.info("No time-aligned clipping and motor output samples are available.")
                else:
                    for col in ["accel_clipping_count", "gyro_clipping_count"]:
                        if col in clipping_motor_df.columns:
                            clipping_motor_df[f"{col}_increment"] = (
                                clipping_motor_df[col]
                                .diff()
                                .clip(lower=0.0)
                                .fillna(0.0)
                            )

                    observed_upper_motor_limit = clipping_motor_df["max_motor_output"].max()
                    observed_lower_motor_limit = clipping_motor_df["min_motor_output"].min()

                    fig_clipping_limits = make_subplots(specs=[[{"secondary_y": True}]])

                    fig_clipping_limits.add_trace(
                        go.Scatter(
                            x=clipping_motor_df["time_s"],
                            y=clipping_motor_df["max_motor_output"],
                            mode="lines",
                            name="Max motor output",
                        ),
                        secondary_y=False,
                    )
                    fig_clipping_limits.add_trace(
                        go.Scatter(
                            x=clipping_motor_df["time_s"],
                            y=clipping_motor_df["mean_motor_output"],
                            mode="lines",
                            name="Mean motor output",
                        ),
                        secondary_y=False,
                    )
                    fig_clipping_limits.add_trace(
                        go.Scatter(
                            x=clipping_motor_df["time_s"],
                            y=clipping_motor_df["min_motor_output"],
                            mode="lines",
                            name="Min motor output",
                        ),
                        secondary_y=False,
                    )

                    if "accel_clipping_count" in clipping_motor_df.columns:
                        fig_clipping_limits.add_trace(
                            go.Scatter(
                                x=clipping_motor_df["time_s"],
                                y=clipping_motor_df["accel_clipping_count"],
                                mode="lines",
                                name="Accel clipping count",
                            ),
                            secondary_y=True,
                        )
                    if "gyro_clipping_count" in clipping_motor_df.columns:
                        fig_clipping_limits.add_trace(
                            go.Scatter(
                                x=clipping_motor_df["time_s"],
                                y=clipping_motor_df["gyro_clipping_count"],
                                mode="lines",
                                name="Gyro clipping count",
                            ),
                            secondary_y=True,
                        )

                    accel_clip_events = (
                        clipping_motor_df[clipping_motor_df["accel_clipping_count_increment"] > 0]
                        if "accel_clipping_count_increment" in clipping_motor_df.columns
                        else pd.DataFrame()
                    )
                    gyro_clip_events = (
                        clipping_motor_df[clipping_motor_df["gyro_clipping_count_increment"] > 0]
                        if "gyro_clipping_count_increment" in clipping_motor_df.columns
                        else pd.DataFrame()
                    )

                    if not accel_clip_events.empty:
                        fig_clipping_limits.add_trace(
                            go.Scatter(
                                x=accel_clip_events["time_s"],
                                y=np.full(len(accel_clip_events), observed_upper_motor_limit),
                                mode="markers",
                                name="Accel clipping event",
                                marker=dict(size=9, symbol="x"),
                                hovertemplate=(
                                    "Time: %{x:.2f} s<br>"
                                    "At observed upper motor limit marker<extra></extra>"
                                ),
                            ),
                            secondary_y=False,
                        )
                    if not gyro_clip_events.empty:
                        fig_clipping_limits.add_trace(
                            go.Scatter(
                                x=gyro_clip_events["time_s"],
                                y=np.full(len(gyro_clip_events), observed_lower_motor_limit),
                                mode="markers",
                                name="Gyro clipping event",
                                marker=dict(size=9, symbol="diamond"),
                                hovertemplate=(
                                    "Time: %{x:.2f} s<br>"
                                    "At observed lower motor limit marker<extra></extra>"
                                ),
                            ),
                            secondary_y=False,
                        )

                    fig_clipping_limits = add_phase_background(
                        fig_clipping_limits,
                        phase_segments,
                        phase_colors,
                    )

                    if pd.notna(observed_upper_motor_limit):
                        fig_clipping_limits.add_hline(
                            y=observed_upper_motor_limit,
                            line_dash="dash",
                            line_width=1,
                            annotation_text="observed upper motor limit",
                            annotation_position="top left",
                        )
                    if pd.notna(observed_lower_motor_limit):
                        fig_clipping_limits.add_hline(
                            y=observed_lower_motor_limit,
                            line_dash="dash",
                            line_width=1,
                            annotation_text="observed lower motor limit",
                            annotation_position="bottom left",
                        )

                    fig_clipping_limits.update_layout(
                        title="Clipping Events Overlaid With Motor Output Limits",
                        height=560,
                        legend=dict(
                            orientation="h",
                            yanchor="bottom",
                            y=1.02,
                            xanchor="right",
                            x=1,
                        ),
                    )
                    fig_clipping_limits.update_xaxes(title_text="Time [s]")
                    fig_clipping_limits.update_yaxes(
                        title_text="Motor output [µs, assumed PWM]",
                        secondary_y=False,
                    )
                    fig_clipping_limits.update_yaxes(
                        title_text="Cumulative clipping count",
                        secondary_y=True,
                    )

                    st.plotly_chart(fig_clipping_limits, width="stretch")
                    st.caption(
                        "Motor limits in this plot are inferred from the observed min/max "
                        "actuator_outputs values in the selected time range. They are not "
                        "parameter-based PWM limits unless the log actually reaches those limits."
                    )

        st.subheader("Per-Phase Vibration Table")

        st.caption(
            "This table summarizes the selected time range by detected flight phase. "
            "RMS, p95 magnitude, crest factor, dominant frequency, and band power are "
            "computed from mean-centered x/y/z sensor signals so the values emphasize "
            "vibration instead of static offset or gravity. Band power uses the frequency "
            f"range {per_phase_band_power_low_hz:.1f}–{per_phase_band_power_high_hz:.1f} Hz."
        )

        per_phase_vibration_table = compute_per_phase_vibration_statistics(
            plot_pos_df,
            plot_sensor_accel_df,
            plot_sensor_gyro_df,
            plot_vibration_df,
            band_low_hz=float(per_phase_band_power_low_hz),
            band_high_hz=float(per_phase_band_power_high_hz),
        )

        if per_phase_vibration_table.empty:
            st.info("No per-phase vibration table could be calculated for the selected time range.")
        else:
            display_per_phase_vibration_table = per_phase_vibration_table.rename(columns={
                "flight_phase": "Flight phase",
                "duration_s": "Duration [s]",
                "position_samples": "Position samples",
                "accel_samples": "Accel samples",
                "gyro_samples": "Gyro samples",
                "accel_rms_x_m_s2": "Accel RMS x [m/s²]",
                "accel_rms_y_m_s2": "Accel RMS y [m/s²]",
                "accel_rms_z_m_s2": "Accel RMS z [m/s²]",
                "accel_vector_rms_m_s2": "Accel vector RMS [m/s²]",
                "gyro_rms_x_rad_s": "Gyro RMS x [rad/s]",
                "gyro_rms_y_rad_s": "Gyro RMS y [rad/s]",
                "gyro_rms_z_rad_s": "Gyro RMS z [rad/s]",
                "gyro_vector_rms_rad_s": "Gyro vector RMS [rad/s]",
                "p95_accel_magnitude_m_s2": "P95 accel magnitude [m/s²]",
                "p95_gyro_magnitude_rad_s": "P95 gyro magnitude [rad/s]",
                "accel_crest_factor": "Accel crest factor",
                "gyro_crest_factor": "Gyro crest factor",
                "accel_clipping_count": "Accel clipping count",
                "gyro_clipping_count": "Gyro clipping count",
                "total_clipping_count": "Clipping count",
                "accel_dominant_frequency_hz": "Accel dominant frequency [Hz]",
                "gyro_dominant_frequency_hz": "Gyro dominant frequency [Hz]",
                "accel_band_power": "Accel band power",
                "gyro_band_power": "Gyro band power",
            })

            st.dataframe(
                display_per_phase_vibration_table.style.format({
                    "Duration [s]": "{:.2f}",
                    "Position samples": "{:.0f}",
                    "Accel samples": "{:.0f}",
                    "Gyro samples": "{:.0f}",
                    "Accel RMS x [m/s²]": "{:.4f}",
                    "Accel RMS y [m/s²]": "{:.4f}",
                    "Accel RMS z [m/s²]": "{:.4f}",
                    "Accel vector RMS [m/s²]": "{:.4f}",
                    "Gyro RMS x [rad/s]": "{:.5f}",
                    "Gyro RMS y [rad/s]": "{:.5f}",
                    "Gyro RMS z [rad/s]": "{:.5f}",
                    "Gyro vector RMS [rad/s]": "{:.5f}",
                    "P95 accel magnitude [m/s²]": "{:.4f}",
                    "P95 gyro magnitude [rad/s]": "{:.5f}",
                    "Accel crest factor": "{:.3f}",
                    "Gyro crest factor": "{:.3f}",
                    "Accel clipping count": "{:.0f}",
                    "Gyro clipping count": "{:.0f}",
                    "Clipping count": "{:.0f}",
                    "Accel dominant frequency [Hz]": "{:.2f}",
                    "Gyro dominant frequency [Hz]": "{:.2f}",
                    "Accel band power": "{:.6g}",
                    "Gyro band power": "{:.6g}",
                }, na_rep="n/a"),
                width="stretch",
            )

        st.subheader("Time-Domain Vibration Signals")

        st.caption(
            "This segment shows the raw time-domain sensor signals used for vibration screening: "
            "sensor_accel x/y/z acceleration plus magnitude, sensor_gyro x/y/z angular velocity "
            "plus magnitude, vehicle_imu_status clipping counters, and vehicle_imu_status "
            "accel/gyro vibration metrics."
        )

        if plot_sensor_accel_df.empty:
            st.info("No usable sensor_accel x/y/z samples are available in the selected time range.")
        else:
            fig_accel_time = go.Figure()

            accel_axis_columns = {
                "accel_x_m_s2": "x acceleration",
                "accel_y_m_s2": "y acceleration",
                "accel_z_m_s2": "z acceleration",
                "accel_magnitude_m_s2": "acceleration magnitude",
            }

            for col, label in accel_axis_columns.items():
                if col in plot_sensor_accel_df.columns:
                    fig_accel_time.add_trace(go.Scatter(
                        x=plot_sensor_accel_df["time_s"],
                        y=plot_sensor_accel_df[col],
                        mode="lines",
                        name=label,
                    ))

            fig_accel_time = add_phase_background(
                fig_accel_time,
                phase_segments,
                phase_colors,
            )

            fig_accel_time.update_layout(
                title="sensor_accel Acceleration Over Time",
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="right",
                    x=1,
                ),
            )
            fig_accel_time.update_xaxes(title_text="Time [s]")
            fig_accel_time.update_yaxes(title_text="Acceleration [m/s²]")

            st.plotly_chart(fig_accel_time, width="stretch")

        if plot_sensor_gyro_df.empty:
            st.info("No usable sensor_gyro x/y/z samples are available in the selected time range.")
        else:
            fig_gyro_time = go.Figure()

            gyro_axis_columns = {
                "gyro_x_rad_s": "x angular velocity",
                "gyro_y_rad_s": "y angular velocity",
                "gyro_z_rad_s": "z angular velocity",
                "gyro_magnitude_rad_s": "gyro magnitude",
            }

            for col, label in gyro_axis_columns.items():
                if col in plot_sensor_gyro_df.columns:
                    fig_gyro_time.add_trace(go.Scatter(
                        x=plot_sensor_gyro_df["time_s"],
                        y=plot_sensor_gyro_df[col],
                        mode="lines",
                        name=label,
                    ))

            fig_gyro_time = add_phase_background(
                fig_gyro_time,
                phase_segments,
                phase_colors,
            )

            fig_gyro_time.update_layout(
                title="sensor_gyro Angular Velocity Over Time",
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="right",
                    x=1,
                ),
            )
            fig_gyro_time.update_xaxes(title_text="Time [s]")
            fig_gyro_time.update_yaxes(title_text="Angular velocity [rad/s]")

            st.plotly_chart(fig_gyro_time, width="stretch")

        if plot_vibration_df.empty:
            st.info("No vehicle_imu_status samples are available in the selected time range.")
        else:
            fig_clipping = go.Figure()

            if "accel_clipping_count" in plot_vibration_df.columns:
                fig_clipping.add_trace(go.Scatter(
                    x=plot_vibration_df["time_s"],
                    y=plot_vibration_df["accel_clipping_count"],
                    mode="lines",
                    name="Accel clipping count",
                ))

            if "gyro_clipping_count" in plot_vibration_df.columns:
                fig_clipping.add_trace(go.Scatter(
                    x=plot_vibration_df["time_s"],
                    y=plot_vibration_df["gyro_clipping_count"],
                    mode="lines",
                    name="Gyro clipping count",
                ))

            fig_clipping = add_phase_background(
                fig_clipping,
                phase_segments,
                phase_colors,
            )

            fig_clipping.update_layout(
                title="vehicle_imu_status Clipping Counters Over Time",
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="right",
                    x=1,
                ),
            )
            fig_clipping.update_xaxes(title_text="Time [s]")
            fig_clipping.update_yaxes(title_text="Cumulative clipping count")

            st.plotly_chart(fig_clipping, width="stretch")

            fig_vibration = make_subplots(specs=[[{"secondary_y": True}]])

            fig_vibration.add_trace(
                go.Scatter(
                    x=plot_vibration_df["time_s"],
                    y=plot_vibration_df["accel_vibration_metric"],
                    mode="lines",
                    name="Accel vibration metric",
                ),
                secondary_y=False,
            )

            fig_vibration.add_trace(
                go.Scatter(
                    x=plot_vibration_df["time_s"],
                    y=plot_vibration_df["gyro_vibration_metric"],
                    mode="lines",
                    name="Gyro vibration metric",
                ),
                secondary_y=True,
            )

            fig_vibration = add_phase_background(
                fig_vibration,
                phase_segments,
                phase_colors,
            )

            fig_vibration.update_layout(
                title="vehicle_imu_status Vibration Metrics Over Time",
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="right",
                    x=1,
                ),
            )

            fig_vibration.update_xaxes(title_text="Time [s]")
            fig_vibration.update_yaxes(title_text="Accel vibration metric", secondary_y=False)
            fig_vibration.update_yaxes(title_text="Gyro vibration metric", secondary_y=True)

            st.plotly_chart(fig_vibration, width="stretch")

        st.subheader("Time-Resolved PSD Heatmap Analysis")

        st.caption(
            "This segment uses sliding-window FFT/PSD analysis to show how vibration frequency "
            "content changes over time as a 2D heatmap. Use the sidebar PSD / FFT settings to adjust "
            "the FFT window duration, the physical PSD update interval, and the displayed frequency limit."
        )

        accel_surface_columns = {
            "accel_x_m_s2": "x acceleration",
            "accel_y_m_s2": "y acceleration",
            "accel_z_m_s2": "z acceleration",
            "accel_magnitude_m_s2": "acceleration magnitude",
        }

        if plot_sensor_accel_df.empty:
            st.info("No usable sensor_accel samples are available for the selected time range.")
        else:
            accel_surfaces, accel_surface_metrics = compute_time_resolved_psd_surface(
                plot_sensor_accel_df,
                list(accel_surface_columns.keys()),
                window_duration_s=psd_window_duration_s,
                time_step_s=float(psd_update_interval_s),
                max_frequency_hz=float(psd_surface_max_frequency_hz),
            )

            accel_surface_options = [
                col for col in accel_surface_columns.keys()
                if col in accel_surfaces
            ]

            if not accel_surface_options:
                st.info(
                    "The selected sensor_accel time range is too short or contains too little "
                    "finite data for a time-resolved PSD heatmap."
                )
            else:
                c1, c2, c3, c4, c5 = st.columns(5)
                c1.metric(
                    "Accel PSD sample rate",
                    format_optional_value(accel_surface_metrics.get("sample_rate_hz"), "Hz", decimals=1),
                )
                c2.metric(
                    "Accel PSD window",
                    format_optional_value(accel_surface_metrics.get("window_duration_s"), "s", decimals=2),
                )
                c3.metric(
                    "Accel PSD update",
                    format_optional_value(accel_surface_metrics.get("actual_time_step_s"), "s", decimals=2),
                )
                c4.metric(
                    "Accel PSD windows",
                    format_optional_count(accel_surface_metrics.get("segments")),
                )
                c5.metric(
                    "Accel PSD frequency bins",
                    format_optional_count(accel_surface_metrics.get("frequency_bins")),
                )

                selected_accel_surface_col = st.selectbox(
                    "Displayed accelerometer PSD heatmap signal",
                    accel_surface_options,
                    format_func=lambda col: accel_surface_columns.get(col, col),
                    key="selected_accel_psd_heatmap_signal",
                )

                fig_accel_heatmap = create_psd_heatmap_figure(
                    accel_surfaces[selected_accel_surface_col],
                    f"sensor_accel Time-Resolved PSD Heatmap - {accel_surface_columns[selected_accel_surface_col]}",
                    "PSD [(m/s²)²/Hz]",
                )
                st.plotly_chart(fig_accel_heatmap, width="stretch")

        gyro_surface_columns = {
            "gyro_x_rad_s": "x angular velocity",
            "gyro_y_rad_s": "y angular velocity",
            "gyro_z_rad_s": "z angular velocity",
            "gyro_magnitude_rad_s": "gyro magnitude",
        }

        if plot_sensor_gyro_df.empty:
            st.info("No usable sensor_gyro samples are available for the selected time range.")
        else:
            gyro_surfaces, gyro_surface_metrics = compute_time_resolved_psd_surface(
                plot_sensor_gyro_df,
                list(gyro_surface_columns.keys()),
                window_duration_s=psd_window_duration_s,
                time_step_s=float(psd_update_interval_s),
                max_frequency_hz=float(psd_surface_max_frequency_hz),
            )

            gyro_surface_options = [
                col for col in gyro_surface_columns.keys()
                if col in gyro_surfaces
            ]

            if not gyro_surface_options:
                st.info(
                    "The selected sensor_gyro time range is too short or contains too little "
                    "finite data for a time-resolved PSD heatmap."
                )
            else:
                c1, c2, c3, c4, c5 = st.columns(5)
                c1.metric(
                    "Gyro PSD sample rate",
                    format_optional_value(gyro_surface_metrics.get("sample_rate_hz"), "Hz", decimals=1),
                )
                c2.metric(
                    "Gyro PSD window",
                    format_optional_value(gyro_surface_metrics.get("window_duration_s"), "s", decimals=2),
                )
                c3.metric(
                    "Gyro PSD update",
                    format_optional_value(gyro_surface_metrics.get("actual_time_step_s"), "s", decimals=2),
                )
                c4.metric(
                    "Gyro PSD windows",
                    format_optional_count(gyro_surface_metrics.get("segments")),
                )
                c5.metric(
                    "Gyro PSD frequency bins",
                    format_optional_count(gyro_surface_metrics.get("frequency_bins")),
                )

                selected_gyro_surface_col = st.selectbox(
                    "Displayed gyroscope PSD heatmap signal",
                    gyro_surface_options,
                    format_func=lambda col: gyro_surface_columns.get(col, col),
                    key="selected_gyro_psd_heatmap_signal",
                )

                fig_gyro_heatmap = create_psd_heatmap_figure(
                    gyro_surfaces[selected_gyro_surface_col],
                    f"sensor_gyro Time-Resolved PSD Heatmap - {gyro_surface_columns[selected_gyro_surface_col]}",
                    "PSD [(rad/s)²/Hz]",
                )
                st.plotly_chart(fig_gyro_heatmap, width="stretch")

        st.subheader("Actuator Controls FFT")

        st.caption(
            "This plot shows the single-sided FFT amplitude spectrum for the active "
            "actuator_controls channels found in the log. The DC component is hidden so "
            "the command-frequency content is easier to compare."
        )

        if plot_actuator_controls_df.empty:
            st.info(
                "No actuator_controls topic was found in this log. Expected names include "
                "actuator_controls or actuator_controls_0."
            )
        else:
            actuator_control_cols = [
                col for col in plot_actuator_controls_df.columns
                if col.startswith("control_")
            ]

            actuator_fft_df, actuator_fft_metrics = compute_signal_fft(
                plot_actuator_controls_df,
                actuator_control_cols,
            )

            if actuator_fft_df.empty:
                st.info(
                    "The selected actuator_controls time range is too short or contains too "
                    "little finite data for FFT analysis."
                )
            else:
                source_columns = []
                if "actuator_controls_columns" in plot_actuator_controls_df.columns:
                    source_text = plot_actuator_controls_df["actuator_controls_columns"].dropna()
                    if not source_text.empty:
                        source_columns = [item.strip() for item in str(source_text.iloc[0]).split(",")]

                label_map = {
                    f"control_{i}": f"control_{i} ({source_columns[i]})"
                    for i in range(min(len(source_columns), len(actuator_control_cols)))
                }

                plot_actuator_fft_df = actuator_fft_df[
                    (actuator_fft_df["frequency_hz"] > 0) &
                    (actuator_fft_df["frequency_hz"] <= float(actuator_fft_max_frequency_hz))
                ].copy()

                fig_actuator_fft = go.Figure()

                for signal_name, signal_fft_df in plot_actuator_fft_df.groupby("signal"):
                    fig_actuator_fft.add_trace(go.Scatter(
                        x=signal_fft_df["frequency_hz"],
                        y=signal_fft_df["amplitude"],
                        mode="lines",
                        name=label_map.get(signal_name, signal_name),
                    ))

                fig_actuator_fft.update_layout(
                    title="actuator_controls FFT Amplitude Spectrum",
                    legend=dict(
                        orientation="h",
                        yanchor="bottom",
                        y=1.02,
                        xanchor="right",
                        x=1,
                    ),
                )
                fig_actuator_fft.update_xaxes(title_text="Frequency [Hz]")
                fig_actuator_fft.update_yaxes(title_text="Single-sided amplitude [control units]")

                st.plotly_chart(fig_actuator_fft, width="stretch")

                c1, c2, c3 = st.columns(3)
                c1.metric(
                    "Actuator FFT sample rate",
                    format_optional_value(actuator_fft_metrics.get("sample_rate_hz"), "Hz", decimals=1),
                )
                c2.metric(
                    "Actuator FFT samples",
                    format_optional_count(actuator_fft_metrics.get("samples")),
                )
                c3.metric(
                    "Actuator FFT channels",
                    format_optional_count(len(actuator_control_cols)),
                )

        st.subheader("Acceleration Frequency Content")

        if accel_psd_df.empty:
            st.info(
                "sensor_accel was not found or no usable acceleration axes were detected, "
                "so the dominant accelerometer frequency could not be calculated."
            )
        else:
            max_available_frequency_hz = float(accel_psd_df["frequency_hz"].max())

            if max_available_frequency_hz > 1.0:
                default_max_frequency_hz = min(max_available_frequency_hz, 250.0)

                displayed_max_frequency_hz = st.slider(
                    "Displayed PSD frequency range [Hz]",
                    min_value=1.0,
                    max_value=max_available_frequency_hz,
                    value=default_max_frequency_hz,
                    step=1.0,
                    key="vibration_psd_max_frequency_hz",
                )
            else:
                displayed_max_frequency_hz = max_available_frequency_hz

            plot_psd_df = accel_psd_df[
                accel_psd_df["frequency_hz"] <= displayed_max_frequency_hz
            ].copy()

            fig_psd = go.Figure()

            fig_psd.add_trace(go.Scatter(
                x=plot_psd_df["frequency_hz"],
                y=plot_psd_df["accel_psd"],
                mode="lines",
                name="Summed accel PSD",
            ))

            dominant_frequency_hz = vibration_metrics.get("dominant_accel_frequency_hz")
            if pd.notna(dominant_frequency_hz):
                fig_psd.add_vline(
                    x=float(dominant_frequency_hz),
                    line_color="rgba(255,255,255,0.7)",
                    line_dash="dash",
                    line_width=1,
                    annotation_text="dominant",
                    annotation_position="top right",
                )

            fig_psd.update_layout(
                title="sensor_accel Frequency Spectrum",
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="right",
                    x=1,
                ),
            )
            fig_psd.update_xaxes(title_text="Frequency [Hz]")
            fig_psd.update_yaxes(title_text="Summed acceleration PSD")

            st.plotly_chart(fig_psd, width="stretch")

        st.subheader("Worst Flight Phase")

        st.caption(
            "The worst phase is the phase with the highest combined score from the "
            "phase maxima of accel_vibration_metric and gyro_vibration_metric. Each "
            "metric is normalized by its global phase maximum before the two scores are added."
        )

        if vibration_phase_stats.empty:
            st.info("No phase-based vibration statistics could be calculated.")
        else:
            display_phase_stats = vibration_phase_stats.copy()
            display_phase_stats["worst_phase"] = display_phase_stats["worst_phase"].map(
                {True: "yes", False: ""}
            )

            st.dataframe(
                display_phase_stats[
                    [
                        "flight_phase",
                        "worst_phase",
                        "samples",
                        "max_accel_vibration_metric",
                        "max_gyro_vibration_metric",
                        "mean_accel_vibration_metric",
                        "mean_gyro_vibration_metric",
                        "combined_vibration_score",
                    ]
                ].style.format({
                    "max_accel_vibration_metric": "{:.5f}",
                    "max_gyro_vibration_metric": "{:.5f}",
                    "mean_accel_vibration_metric": "{:.5f}",
                    "mean_gyro_vibration_metric": "{:.5f}",
                    "combined_vibration_score": "{:.3f}",
                }),
                width="stretch",
            )

    elif page == "Setpoint Tracking Analysis":

        st.header("Setpoint Tracking Analysis")

        st.caption(
            "This page compares commanded setpoints with measured vehicle response. "
            "It is intended to support controller-performance screening. "
            "Large tracking errors are diagnostic indicators, not automatic proof of bad tuning or mechanical faults."
        )

        pos_df: pd.DataFrame = flight.position
        motor_output_df, motor_output_metrics, output_idx = flight.actuator_outputs

        rate_tracking = flight.rate_tracking
        attitude_tracking = flight.attitude_tracking
        trajectory_tracking = flight.trajectory_tracking

        with st.sidebar:
            st.subheader("Setpoint Tracking Controls")

            time_min = float(pos_df["time_s"].min())
            time_max = float(pos_df["time_s"].max())

            selected_time_range = st.slider(
                "Displayed time range [s]",
                min_value=time_min,
                max_value=time_max,
                value=(time_min, time_max),
                step=1.0,
                key="setpoint_tracking_time_range",
            )

            st.divider()

            st.subheader("Phase Legend")

            for phase, rgb in phase_colors.items():
                color = rgb_to_rgba(rgb, alpha=0.35)

                st.markdown(
                    f"""
                    <div style="display:flex; align-items:center; margin-bottom:8px;">
                        <div style="width:18px; height:18px; background:{color}; margin-right:8px; border-radius:3px; "></div>
                        <div style="font-size:13px;">{phase}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        plot_pos_df = pos_df[
            (pos_df["time_s"] >= selected_time_range[0]) &
            (pos_df["time_s"] <= selected_time_range[1])
        ].copy()

        plot_motor_output_df = motor_output_df[
            (motor_output_df["time_s"] >= selected_time_range[0]) &
            (motor_output_df["time_s"] <= selected_time_range[1])
        ].copy()

        phase_segments: list = get_phase_segments(plot_pos_df)

        available_sections = []
        if rate_tracking is not None:
            available_sections.append("rate tracking")
        if attitude_tracking is not None:
            available_sections.append("attitude tracking")
        if trajectory_tracking is not None:
            available_sections.append("trajectory tracking")

        if not available_sections:
            st.info(
                "No supported setpoint-tracking topics were found in this log. "
                "Expected topics include vehicle_rates_setpoint, vehicle_attitude_setpoint, "
                "and/or trajectory_setpoint."
            )
            st.stop()

        st.info(
            "Available analyses in this log: " + ", ".join(available_sections) + "."
        )

        st.caption(
            f"Filtered setpoints use a first-order causal low-pass filter "
            f"with a {DEFAULT_SETPOINT_LOW_PASS_CUTOFF_HZ:.1f} Hz cutoff. "
            "All metric cards and tables are recalculated only for the selected "
            "time window from the sidebar slider, including the displayed "
            "time-offset values. The filtered and filtered time-compensated "
            "metrics use the same bias, MAE, RMSE, P95, and max-absolute-error "
            "definitions as the original setpoint metrics."
        )

        def get_metric(metrics_df: pd.DataFrame, axis: str, column: str) -> float:
            if metrics_df is None or metrics_df.empty:
                return np.nan
            selected = metrics_df.loc[metrics_df["axis"] == axis, column]
            if selected.empty:
                return np.nan
            return float(selected.iloc[0])

        # ------------------------------------------------
        # Body-rate setpoint tracking
        # ------------------------------------------------

        if rate_tracking is not None:
            rate_tracking_df, _rate_tracking_metrics = rate_tracking

            plot_rate_tracking_df = rate_tracking_df[
                (rate_tracking_df["time_s"] >= selected_time_range[0]) &
                (rate_tracking_df["time_s"] <= selected_time_range[1])
            ].copy()

            plot_rate_tracking_df, rate_tracking_metrics = (
                recompute_rate_tracking_for_time_window(plot_rate_tracking_df)
            )

            st.subheader("Body-Rate Tracking")

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Roll Rate RMSE", f"{get_metric(rate_tracking_metrics, 'roll', 'rmse'):.2f} °/s")
            c2.metric("Pitch Rate RMSE", f"{get_metric(rate_tracking_metrics, 'pitch', 'rmse'):.2f} °/s")
            c3.metric("Yaw Rate RMSE", f"{get_metric(rate_tracking_metrics, 'yaw', 'rmse'):.2f} °/s")
            c4.metric("Yaw Rate P95 ABS", f"{get_metric(rate_tracking_metrics, 'yaw', 'p95_abs'):.2f} °/s")

            c5, c6, c7, c8 = st.columns(4)
            c5.metric("Roll Rate Filtered RMSE", f"{get_metric(rate_tracking_metrics, 'roll_filtered', 'rmse'):.2f} °/s")
            c6.metric("Pitch Rate Filtered RMSE", f"{get_metric(rate_tracking_metrics, 'pitch_filtered', 'rmse'):.2f} °/s")
            c7.metric("Yaw Rate Filtered RMSE", f"{get_metric(rate_tracking_metrics, 'yaw_filtered', 'rmse'):.2f} °/s")
            c8.metric("Yaw Rate Filtered P95 ABS", f"{get_metric(rate_tracking_metrics, 'yaw_filtered', 'p95_abs'):.2f} °/s")

            c9, c10, c11, c12 = st.columns(4)
            c9.metric("Roll Rate Filtered + Time RMSE", f"{get_metric(rate_tracking_metrics, 'roll_filtered_time_compensated', 'rmse'):.2f} °/s")
            c10.metric("Pitch Rate Filtered + Time RMSE", f"{get_metric(rate_tracking_metrics, 'pitch_filtered_time_compensated', 'rmse'):.2f} °/s")
            c11.metric("Yaw Rate Filtered + Time RMSE", f"{get_metric(rate_tracking_metrics, 'yaw_filtered_time_compensated', 'rmse'):.2f} °/s")
            c12.metric("Yaw Rate Filtered + Time Offset", f"{get_metric(rate_tracking_metrics, 'yaw_filtered_time_compensated', 'time_offset_s'):.3f} s")

            selected_rate_axis = st.selectbox(
                "Displayed body-rate axis",
                ["roll", "pitch", "yaw"],
                key="selected_rate_tracking_axis",
            )

            fig = go.Figure()

            fig.add_trace(go.Scatter(
                x=plot_rate_tracking_df["time_s"],
                y=plot_rate_tracking_df[f"{selected_rate_axis}_rate_setpoint_deg_s"],
                mode="lines",
                name=f"{selected_rate_axis.capitalize()} rate setpoint",
                # line=dict(dash="dash"),
            ))

            fig.add_trace(go.Scatter(
                x=plot_rate_tracking_df["time_s"],
                y=plot_rate_tracking_df[f"{selected_rate_axis}_rate_actual_deg_s"],
                mode="lines",
                name=f"{selected_rate_axis.capitalize()} body rate actual",
            ))

            fig.add_trace(go.Scatter(
                x=plot_rate_tracking_df["time_s"],
                y=plot_rate_tracking_df[f"{selected_rate_axis}_rate_time_compensated_setpoint_deg_s"],
                mode="lines",
                name=f"{selected_rate_axis.capitalize()} rate setpoint time compensated",
            ))

            fig = add_phase_background(fig, phase_segments, phase_colors)

            fig.update_layout(
                title=f"{selected_rate_axis.capitalize()} Rate Setpoint vs Actual",
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="right",
                    x=1,
                ),
            )

            fig.update_xaxes(title_text="Time [s]")
            fig.update_yaxes(title_text="Body rate [°/s]")

            st.plotly_chart(fig, width="stretch")

            fig_filtered = go.Figure()

            fig_filtered.add_trace(go.Scatter(
                x=plot_rate_tracking_df["time_s"],
                y=plot_rate_tracking_df[f"{selected_rate_axis}_rate_filtered_setpoint_deg_s"],
                mode="lines",
                name=f"{selected_rate_axis.capitalize()} rate filtered setpoint",
            ))

            fig_filtered.add_trace(go.Scatter(
                x=plot_rate_tracking_df["time_s"],
                y=plot_rate_tracking_df[f"{selected_rate_axis}_rate_actual_deg_s"],
                mode="lines",
                name=f"{selected_rate_axis.capitalize()} body rate actual",
            ))

            filtered_time_compensated_rate_col = (
                f"{selected_rate_axis}_rate_filtered_time_compensated_setpoint_deg_s"
            )
            if filtered_time_compensated_rate_col in plot_rate_tracking_df.columns:
                fig_filtered.add_trace(go.Scatter(
                    x=plot_rate_tracking_df["time_s"],
                    y=plot_rate_tracking_df[filtered_time_compensated_rate_col],
                    mode="lines",
                    name=(
                        f"{selected_rate_axis.capitalize()} rate filtered setpoint "
                        "time compensated"
                    ),
                ))

            fig_filtered = add_phase_background(fig_filtered, phase_segments, phase_colors)

            fig_filtered.update_layout(
                title=f"{selected_rate_axis.capitalize()} Rate Filtered Setpoint vs Actual",
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="right",
                    x=1,
                ),
            )

            fig_filtered.update_xaxes(title_text="Time [s]")
            fig_filtered.update_yaxes(title_text="Body rate [°/s]")

            st.plotly_chart(fig_filtered, width="stretch")

            fig = go.Figure()

            for axis in ["roll", "pitch", "yaw"]:
                fig.add_trace(go.Scatter(
                    x=plot_rate_tracking_df["time_s"],
                    y=plot_rate_tracking_df[f"{axis}_rate_error_deg_s"],
                    mode="lines",
                    name=f"{axis.capitalize()} rate error",
                ))

            fig = add_phase_background(fig, phase_segments, phase_colors)
            fig.add_hline(y=0, line_color="rgba(255,255,255,0.8)", line_width=1)

            fig.update_layout(
                title="Body-Rate Tracking Error",
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="right",
                    x=1,
                ),
            )

            fig.update_xaxes(title_text="Time [s]")
            fig.update_yaxes(title_text="Setpoint - actual [°/s]")

            st.plotly_chart(fig, width="stretch")

            # ------------------------------------------------
            # Tracking error versus actuator effort
            # ------------------------------------------------

            st.subheader("Tracking Error vs Actuator Effort")

            tracking_effort_df = pd.merge_asof(
                plot_rate_tracking_df[["time_s", "rate_error_magnitude_deg_s"]].sort_values("time_s"),
                plot_motor_output_df[["time_s", "motor_output_spread", "mean_motor_output"]].sort_values("time_s"),
                on="time_s",
                direction="nearest",
            )

            fig = make_subplots(specs=[[{"secondary_y": True}]])

            fig.add_trace(
                go.Scatter(
                    x=tracking_effort_df["time_s"],
                    y=tracking_effort_df["rate_error_magnitude_deg_s"],
                    mode="lines",
                    name="Rate error magnitude",
                ),
                secondary_y=False,
            )

            fig.add_trace(
                go.Scatter(
                    x=tracking_effort_df["time_s"],
                    y=tracking_effort_df["motor_output_spread"],
                    mode="lines",
                    name="Motor output spread",
                ),
                secondary_y=True,
            )

            fig = add_phase_background(fig, phase_segments, phase_colors)

            fig.update_layout(
                title="Rate Error Magnitude and Motor Output Spread",
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="right",
                    x=1,
                ),
            )

            fig.update_xaxes(title_text="Time [s]")
            fig.update_yaxes(title_text="Rate error magnitude [°/s]", secondary_y=False)
            fig.update_yaxes(title_text="Output spread [µs, assumed PWM]", secondary_y=True)

            st.plotly_chart(fig, width="stretch")

            st.dataframe(
                rate_tracking_metrics.style.format({
                    "time_offset_s": "{:.3f}",
                    "bias": "{:.3f}",
                    "mean_abs_error": "{:.3f}",
                    "rmse": "{:.3f}",
                    "p95_abs": "{:.3f}",
                    "max_abs": "{:.3f}",
                }),
                width="stretch",
            )

        else:
            st.warning(
                "Body-rate tracking is unavailable because vehicle_rates_setpoint "
                "or vehicle_angular_velocity is missing or not usable in this log."
            )

        # ------------------------------------------------
        # Attitude setpoint tracking
        # ------------------------------------------------

        if attitude_tracking is not None:
            attitude_tracking_df, _attitude_tracking_metrics = attitude_tracking

            plot_attitude_tracking_df = attitude_tracking_df[
                (attitude_tracking_df["time_s"] >= selected_time_range[0]) &
                (attitude_tracking_df["time_s"] <= selected_time_range[1])
            ].copy()

            plot_attitude_tracking_df, attitude_tracking_metrics = (
                recompute_attitude_tracking_for_time_window(plot_attitude_tracking_df)
            )

            st.subheader("Attitude Tracking")

            c1, c2, c3 = st.columns(3)
            c1.metric("Roll Attitude RMSE", f"{get_metric(attitude_tracking_metrics, 'roll', 'rmse'):.2f} °")
            c2.metric("Pitch Attitude RMSE", f"{get_metric(attitude_tracking_metrics, 'pitch', 'rmse'):.2f} °")
            c3.metric("Yaw Attitude RMSE", f"{get_metric(attitude_tracking_metrics, 'yaw', 'rmse'):.2f} °")

            c4, c5, c6 = st.columns(3)
            c4.metric("Roll Attitude Filtered RMSE", f"{get_metric(attitude_tracking_metrics, 'roll_filtered', 'rmse'):.2f} °")
            c5.metric("Pitch Attitude Filtered RMSE", f"{get_metric(attitude_tracking_metrics, 'pitch_filtered', 'rmse'):.2f} °")
            c6.metric("Yaw Attitude Filtered RMSE", f"{get_metric(attitude_tracking_metrics, 'yaw_filtered', 'rmse'):.2f} °")

            c7, c8, c9 = st.columns(3)
            c7.metric("Roll Attitude Filtered + Time RMSE", f"{get_metric(attitude_tracking_metrics, 'roll_filtered_time_compensated', 'rmse'):.2f} °")
            c8.metric("Pitch Attitude Filtered + Time RMSE", f"{get_metric(attitude_tracking_metrics, 'pitch_filtered_time_compensated', 'rmse'):.2f} °")
            c9.metric("Yaw Attitude Filtered + Time RMSE", f"{get_metric(attitude_tracking_metrics, 'yaw_filtered_time_compensated', 'rmse'):.2f} °")

            selected_attitude_axis = st.selectbox(
                "Displayed attitude axis",
                ["roll", "pitch", "yaw"],
                key="selected_attitude_tracking_axis",
            )

            fig = go.Figure()

            fig.add_trace(go.Scatter(
                x=plot_attitude_tracking_df["time_s"],
                y=plot_attitude_tracking_df[f"{selected_attitude_axis}_setpoint_deg"],
                mode="lines",
                name=f"{selected_attitude_axis.capitalize()} attitude setpoint",
                # line=dict(dash="dash"),
            ))

            fig.add_trace(go.Scatter(
                x=plot_attitude_tracking_df["time_s"],
                y=plot_attitude_tracking_df[f"{selected_attitude_axis}_actual_deg"],
                mode="lines",
                name=f"{selected_attitude_axis.capitalize()} attitude actual",
            ))

            fig.add_trace(go.Scatter(
                x=plot_attitude_tracking_df["time_s"],
                y=plot_attitude_tracking_df[f"{selected_attitude_axis}_time_compensated_setpoint_deg"],
                mode="lines",
                name=f"{selected_attitude_axis.capitalize()} setpoint time compensated",
            ))

            fig = add_phase_background(fig, phase_segments, phase_colors)

            fig.update_layout(
                title=f"{selected_attitude_axis.capitalize()} Attitude Setpoint vs Actual",
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="right",
                    x=1,
                ),
            )

            fig.update_xaxes(title_text="Time [s]")
            fig.update_yaxes(title_text="Attitude [°]")

            st.plotly_chart(fig, width="stretch")

            fig_filtered = go.Figure()

            fig_filtered.add_trace(go.Scatter(
                x=plot_attitude_tracking_df["time_s"],
                y=plot_attitude_tracking_df[f"{selected_attitude_axis}_filtered_setpoint_deg"],
                mode="lines",
                name=f"{selected_attitude_axis.capitalize()} attitude filtered setpoint",
            ))

            fig_filtered.add_trace(go.Scatter(
                x=plot_attitude_tracking_df["time_s"],
                y=plot_attitude_tracking_df[f"{selected_attitude_axis}_actual_deg"],
                mode="lines",
                name=f"{selected_attitude_axis.capitalize()} attitude actual",
            ))

            filtered_time_compensated_attitude_col = (
                f"{selected_attitude_axis}_filtered_time_compensated_setpoint_deg"
            )
            if filtered_time_compensated_attitude_col in plot_attitude_tracking_df.columns:
                fig_filtered.add_trace(go.Scatter(
                    x=plot_attitude_tracking_df["time_s"],
                    y=plot_attitude_tracking_df[filtered_time_compensated_attitude_col],
                    mode="lines",
                    name=(
                        f"{selected_attitude_axis.capitalize()} attitude filtered setpoint "
                        "time compensated"
                    ),
                ))

            fig_filtered = add_phase_background(fig_filtered, phase_segments, phase_colors)

            fig_filtered.update_layout(
                title=f"{selected_attitude_axis.capitalize()} Attitude Filtered Setpoint vs Actual",
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="right",
                    x=1,
                ),
            )

            fig_filtered.update_xaxes(title_text="Time [s]")
            fig_filtered.update_yaxes(title_text="Attitude [°]")

            st.plotly_chart(fig_filtered, width="stretch")

            fig = go.Figure()

            for axis in ["roll", "pitch", "yaw"]:
                fig.add_trace(go.Scatter(
                    x=plot_attitude_tracking_df["time_s"],
                    y=plot_attitude_tracking_df[f"{axis}_error_deg"],
                    mode="lines",
                    name=f"{axis.capitalize()} attitude error",
                ))

            fig = add_phase_background(fig, phase_segments, phase_colors)
            fig.add_hline(y=0, line_color="rgba(255,255,255,0.8)", line_width=1)

            fig.update_layout(
                title="Attitude Tracking Error",
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="right",
                    x=1,
                ),
            )

            fig.update_xaxes(title_text="Time [s]")
            fig.update_yaxes(title_text="Setpoint - actual [°]")

            st.plotly_chart(fig, width="stretch")

            st.dataframe(
                attitude_tracking_metrics.style.format({
                    "time_offset_s": "{:.3f}",
                    "bias": "{:.3f}",
                    "mean_abs_error": "{:.3f}",
                    "rmse": "{:.3f}",
                    "p95_abs": "{:.3f}",
                    "max_abs": "{:.3f}",
                }),
                width="stretch",
            )

        else:
            st.warning(
                "Attitude tracking is unavailable because vehicle_attitude_setpoint "
                "or usable attitude-setpoint fields are missing in this log."
            )

        # ------------------------------------------------
        # Trajectory setpoint tracking
        # ------------------------------------------------

        if trajectory_tracking is not None:
            trajectory_tracking_df, _trajectory_tracking_metrics = trajectory_tracking

            plot_trajectory_tracking_df = trajectory_tracking_df[
                (trajectory_tracking_df["time_s"] >= selected_time_range[0]) &
                (trajectory_tracking_df["time_s"] <= selected_time_range[1])
            ].copy()

            plot_trajectory_tracking_df, trajectory_tracking_metrics = (
                recompute_trajectory_tracking_for_time_window(plot_trajectory_tracking_df)
            )

            st.subheader("Trajectory Tracking")

            trajectory_options = {}

            if all(col in plot_trajectory_tracking_df.columns for col in ["x_actual_m", "x_setpoint_m", "x_filtered_setpoint_m"]):
                trajectory_options["North position"] = ("x_actual_m", "x_setpoint_m", "x_filtered_setpoint_m", "Position [m]", None, "x_position_filtered_time_compensated_setpoint_m", "x_position")
            if all(col in plot_trajectory_tracking_df.columns for col in ["y_actual_m", "y_setpoint_m", "y_filtered_setpoint_m"]):
                trajectory_options["East position"] = ("y_actual_m", "y_setpoint_m", "y_filtered_setpoint_m", "Position [m]", None, "y_position_filtered_time_compensated_setpoint_m", "y_position")
            if all(col in plot_trajectory_tracking_df.columns for col in ["z_actual_m", "z_setpoint_m", "z_filtered_setpoint_m"]):
                trajectory_options["Down position"] = ("z_actual_m", "z_setpoint_m", "z_filtered_setpoint_m", "Position [m]", None, "z_position_filtered_time_compensated_setpoint_m", "z_position")
            if all(col in plot_trajectory_tracking_df.columns for col in ["altitude_actual_m", "altitude_setpoint_m", "altitude_filtered_setpoint_m"]):
                trajectory_options["Altitude"] = ("altitude_actual_m", "altitude_setpoint_m", "altitude_filtered_setpoint_m", "Altitude [m]", None, "altitude_filtered_time_compensated_setpoint_m", "altitude")
            if all(col in plot_trajectory_tracking_df.columns for col in ["vx_actual_m_s", "vx_setpoint_m_s", "vx_filtered_setpoint_m_s"]):
                trajectory_options["North velocity"] = ("vx_actual_m_s", "vx_setpoint_m_s", "vx_filtered_setpoint_m_s", "Velocity [m/s]", "vx_time_compensated_setpoint_m_s", "vx_velocity_filtered_time_compensated_setpoint_m_s", "vx_velocity")
            if all(col in plot_trajectory_tracking_df.columns for col in ["vy_actual_m_s", "vy_setpoint_m_s", "vy_filtered_setpoint_m_s"]):
                trajectory_options["East velocity"] = ("vy_actual_m_s", "vy_setpoint_m_s", "vy_filtered_setpoint_m_s", "Velocity [m/s]", "vy_time_compensated_setpoint_m_s", "vy_velocity_filtered_time_compensated_setpoint_m_s", "vy_velocity")
            if all(col in plot_trajectory_tracking_df.columns for col in ["vz_actual_m_s", "vz_setpoint_m_s", "vz_filtered_setpoint_m_s"]):
                trajectory_options["Down velocity"] = ("vz_actual_m_s", "vz_setpoint_m_s", "vz_filtered_setpoint_m_s", "Velocity [m/s]", "vz_time_compensated_setpoint_m_s", "vz_velocity_filtered_time_compensated_setpoint_m_s", "vz_velocity")
            if all(col in plot_trajectory_tracking_df.columns for col in ["vertical_speed_actual_m_s", "vertical_speed_setpoint_m_s", "vertical_speed_filtered_setpoint_m_s"]):
                trajectory_options["Vertical speed"] = ("vertical_speed_actual_m_s", "vertical_speed_setpoint_m_s", "vertical_speed_filtered_setpoint_m_s", "Velocity [m/s]", "vertical_speed_time_compensated_setpoint_m_s", "vertical_speed_filtered_time_compensated_setpoint_m_s", "vertical_speed")

            if trajectory_options:
                selected_trajectory_signal = st.selectbox(
                    "Displayed trajectory signal",
                    list(trajectory_options.keys()),
                    key="selected_trajectory_tracking_signal",
                )

                (
                    actual_col,
                    setpoint_col,
                    filtered_setpoint_col,
                    y_label,
                    time_corrected_col,
                    filtered_time_corrected_col,
                    metric_axis,
                ) = trajectory_options[selected_trajectory_signal]

                c1, c2, c3 = st.columns(3)
                c1.metric(
                    f"{selected_trajectory_signal} RMSE",
                    f"{get_metric(trajectory_tracking_metrics, metric_axis, 'rmse'):.3f}",
                )
                c2.metric(
                    f"{selected_trajectory_signal} Filtered RMSE",
                    f"{get_metric(trajectory_tracking_metrics, metric_axis + '_filtered', 'rmse'):.3f}",
                )
                c3.metric(
                    f"{selected_trajectory_signal} Filtered + Time RMSE",
                    f"{get_metric(trajectory_tracking_metrics, metric_axis + '_filtered_time_compensated', 'rmse'):.3f}",
                )

                fig = go.Figure()

                fig.add_trace(go.Scatter(
                    x=plot_trajectory_tracking_df["time_s"],
                    y=plot_trajectory_tracking_df[setpoint_col],
                    mode="lines",
                    name=f"{selected_trajectory_signal} setpoint",
                    # line=dict(dash="dash"),
                ))

                fig.add_trace(go.Scatter(
                    x=plot_trajectory_tracking_df["time_s"],
                    y=plot_trajectory_tracking_df[actual_col],
                    mode="lines",
                    name=f"{selected_trajectory_signal} actual",
                ))

                if time_corrected_col is not None:
                    fig.add_trace(go.Scatter(
                        x=plot_trajectory_tracking_df["time_s"],
                        y=plot_trajectory_tracking_df[time_corrected_col],
                        mode="lines",
                        name=f"{selected_trajectory_signal} setpoint time compensated",
                    ))

                fig = add_phase_background(fig, phase_segments, phase_colors)

                fig.update_layout(
                    title=f"{selected_trajectory_signal} Setpoint vs Actual",
                    legend=dict(
                        orientation="h",
                        yanchor="bottom",
                        y=1.02,
                        xanchor="right",
                        x=1,
                    ),
                )

                fig.update_xaxes(title_text="Time [s]")
                fig.update_yaxes(title_text=y_label)

                st.plotly_chart(fig, width="stretch")

                fig_filtered = go.Figure()

                fig_filtered.add_trace(go.Scatter(
                    x=plot_trajectory_tracking_df["time_s"],
                    y=plot_trajectory_tracking_df[filtered_setpoint_col],
                    mode="lines",
                    name=f"{selected_trajectory_signal} filtered setpoint",
                ))

                fig_filtered.add_trace(go.Scatter(
                    x=plot_trajectory_tracking_df["time_s"],
                    y=plot_trajectory_tracking_df[actual_col],
                    mode="lines",
                    name=f"{selected_trajectory_signal} actual",
                ))

                if (
                    filtered_time_corrected_col is not None and
                    filtered_time_corrected_col in plot_trajectory_tracking_df.columns
                ):
                    fig_filtered.add_trace(go.Scatter(
                        x=plot_trajectory_tracking_df["time_s"],
                        y=plot_trajectory_tracking_df[filtered_time_corrected_col],
                        mode="lines",
                        name=f"{selected_trajectory_signal} filtered setpoint time compensated",
                    ))

                fig_filtered = add_phase_background(fig_filtered, phase_segments, phase_colors)

                fig_filtered.update_layout(
                    title=f"{selected_trajectory_signal} Filtered Setpoint vs Actual",
                    legend=dict(
                        orientation="h",
                        yanchor="bottom",
                        y=1.02,
                        xanchor="right",
                        x=1,
                    ),
                )

                fig_filtered.update_xaxes(title_text="Time [s]")
                fig_filtered.update_yaxes(title_text=y_label)

                st.plotly_chart(fig_filtered, width="stretch")

            if not trajectory_tracking_metrics.empty:
                st.dataframe(
                    trajectory_tracking_metrics.style.format({
                        "time_offset_s": "{:.3f}",
                        "bias": "{:.3f}",
                        "mean_abs_error": "{:.3f}",
                        "rmse": "{:.3f}",
                        "p95_abs": "{:.3f}",
                        "max_abs": "{:.3f}",
                    }),
                    width="stretch",
                )
            else:
                st.info(
                    "trajectory_setpoint was found, but no finite position or velocity "
                    "setpoint fields could be evaluated."
                )

        else:
            st.warning("Trajectory tracking is unavailable because trajectory_setpoint is missing in this log.")

        with st.expander("How to interpret this page", expanded=False):
            st.markdown(
                """
                **Good tracking** means the measured response follows the setpoint with low error.  
                **Large error during high motor output spread** can indicate that the vehicle needed strong differential actuator effort while still not fully achieving the commanded response.  
                **Large error near high motor output values** can indicate possible actuator-authority limitations, but it is not proof of saturation unless the outputs are visibly clipped near their configured limits.  
                **Persistent non-zero error or integrator offset** can indicate bias compensation, disturbance, or tuning limitations, but it does not by itself prove mechanical imbalance.  
                **Filtered-setpoint metrics** are useful for checking whether high-frequency command changes dominate the raw tracking error. **Filtered + time-compensated metrics** additionally test whether the remaining filtered error is mainly caused by delay. They should be read together with the unfiltered and raw time-compensated metrics.
                """
            )


# streamlit run app.py