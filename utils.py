def format_duration(seconds):
    seconds = int(seconds)

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours > 0:
        return f"{hours:d}h {minutes:02d}m {secs:02d}s"

    return f"{minutes:d}m {secs:02d}s"


def get_phase_segments(df, phase_col="flight_phase"):
    segments = []

    if df.empty:
        return segments

    current_phase = df[phase_col].iloc[0]
    start_time = df["time_s"].iloc[0]

    for i in range(1, len(df)):
        phase = df[phase_col].iloc[i]

        if phase != current_phase:
            end_time = df["time_s"].iloc[i - 1]

            segments.append(
                {
                    "phase": current_phase,
                    "start_time": start_time,
                    "end_time": end_time,
                }
            )

            current_phase = phase
            start_time = df["time_s"].iloc[i]

    segments.append(
        {
            "phase": current_phase,
            "start_time": start_time,
            "end_time": df["time_s"].iloc[-1],
        }
    )

    return segments