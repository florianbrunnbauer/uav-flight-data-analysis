import math

import pandas as pd


class FakeLog:
    """Minimal log object exposing the get_topic() method used by analysis.py."""

    def __init__(self, topics: dict[str, pd.DataFrame]):
        self.topics = topics

    def get_topic(self, topic_name: str) -> pd.DataFrame:
        if topic_name not in self.topics:
            raise ValueError(f"Topic not found: {topic_name}")
        return self.topics[topic_name].copy()


def make_quaternion_from_axis_angle(axis: str, angle_deg: float) -> tuple[float, float, float, float]:
    angle_rad = math.radians(angle_deg)
    half_angle = angle_rad / 2.0
    w = math.cos(half_angle)
    s = math.sin(half_angle)

    if axis == "roll":
        return w, s, 0.0, 0.0
    if axis == "pitch":
        return w, 0.0, s, 0.0
    if axis == "yaw":
        return w, 0.0, 0.0, s
    raise ValueError(axis)
