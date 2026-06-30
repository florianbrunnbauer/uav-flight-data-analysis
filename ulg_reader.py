from pathlib import Path
import pandas as pd
from pyulog import ULog
import matplotlib.pyplot as plt


class UlgReader:
    def __init__(self, ulg_path: str | Path):
        self.ulg_path = Path(ulg_path)
        if not self.ulg_path.exists():
            raise FileNotFoundError(self.ulg_path)

        self.ulog = ULog(str(self.ulg_path))

        self.start_timestamp = min(
            d.data["timestamp"][0]
            for d in self.ulog.data_list
            if "timestamp" in d.data
        )

    def list_topics(self) -> list[str]:
        return sorted({d.name for d in self.ulog.data_list})

    def get_topic(self, topic_name: str) -> pd.DataFrame:
        matches = [d for d in self.ulog.data_list if d.name == topic_name]

        if not matches:
            raise ValueError(f"Topic not found: {topic_name}")

        data = matches[0].data
        df = pd.DataFrame(data)

        if "timestamp" in df.columns:
            df["time_s"] = (df["timestamp"] - self.start_timestamp) / 1e6


        return df

    def get_parameters(self) -> dict:
        return self.ulog.initial_parameters

    def get_info(self) -> dict:
        return self.ulog.msg_info_dict