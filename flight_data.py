import numpy as np
import pandas as pd

from ulg_reader import UlgReader
from analysis import (analyze_attitude,analyze_position,compute_flight_statistics,compute_phase_statistics,
                      compute_hover_stability,analyze_actuator_outputs,analyze_body_rates,analyze_integrator_status,
                      analyze_rate_tracking,analyze_attitude_tracking,analyze_trajectory_tracking,analyze_vibration,
                      analyze_sensor_accel,analyze_sensor_gyro,analyze_actuator_controls)


class FlightData:
    def __init__(self, ulg_path):
        self.ulg_path = ulg_path
        self.log = UlgReader(ulg_path)

        self._position = None
        self._attitude = None
        self._flight_statistics = None
        self._phase_data = None
        self._phase_statistics = None
        self._hover_stability = None
        self._actuator_outputs = None
        self._actuator_metrics = None
        self._output_idx = None
        self._body_rates_data = None
        self._integrator_status_data = None
        self._rate_tracking_data = None
        self._attitude_tracking_data = None
        self._trajectory_tracking_data = None
        self._vibration_analysis_data = None
        self._sensor_accel_data = None
        self._sensor_gyro_data = None
        self._actuator_controls_data = None

    @property
    def position(self):
        if self._position is None:
            self._position = analyze_position(self.log)

        return self._position

    @property
    def attitude(self):
        if self._attitude is None:
            self._attitude = analyze_attitude(self.log)            

        return self._attitude

    @property
    def flight_statistics(self):
        if self._flight_statistics is None:
            self._flight_statistics = compute_flight_statistics(self.position,self.attitude)

        return self._flight_statistics
    
    @property
    def phase_statistics(self):
        if self._phase_statistics is None:
            self._phase_statistics = compute_phase_statistics(
                self.position
            )

        return self._phase_statistics
    
    @property
    def hover_stability(self):
        if self._hover_stability is None:
            self._hover_stability = compute_hover_stability(
                self.position,
                self.attitude
            )

        return self._hover_stability
    
    def get_phase(self, phase_name:str) -> pd.DataFrame:
        """applies a mask on the general dataframe filtering all results not containing the phase_name"""
        return self.position[self.position["flight_phase"] == phase_name].copy()
    
    @property
    def actuator_outputs(self):
        if self._actuator_outputs is None:
            self._actuator_outputs, self._actuator_metrics, self._output_idx = analyze_actuator_outputs(self.log)

        return self._actuator_outputs, self._actuator_metrics, self._output_idx
    
    @property
    def body_rates(self):
        if self._body_rates_data is None:
            self._body_rates_data = analyze_body_rates(self.log)

        return self._body_rates_data
    
    @property
    def integrator_status(self):
        if self._integrator_status_data is None:
            self._integrator_status_data = analyze_integrator_status(self.log)

        return self._integrator_status_data
    
    @property
    def rate_tracking(self):
        if self._rate_tracking_data is None:
            self._rate_tracking_data = analyze_rate_tracking(self.log)

        return self._rate_tracking_data
    
    @property
    def attitude_tracking(self):
        if self._attitude_tracking_data is None:
            self._attitude_tracking_data = analyze_attitude_tracking(self.log)

        return self._attitude_tracking_data
    
    @property
    def trajectory_tracking(self):
        if self._trajectory_tracking_data is None:
            self._trajectory_tracking_data = analyze_trajectory_tracking(self.log)

        return self._trajectory_tracking_data

    @property
    def vibration_analysis(self):
        if self._vibration_analysis_data is None:
            self._vibration_analysis_data = analyze_vibration(
                self.log,
                self.position,
            )

        return self._vibration_analysis_data

    @property
    def sensor_accel(self):
        if self._sensor_accel_data is None:
            self._sensor_accel_data = analyze_sensor_accel(self.log)

        return self._sensor_accel_data

    @property
    def sensor_gyro(self):
        if self._sensor_gyro_data is None:
            self._sensor_gyro_data = analyze_sensor_gyro(self.log)

        return self._sensor_gyro_data

    @property
    def actuator_controls(self):
        if self._actuator_controls_data is None:
            self._actuator_controls_data = analyze_actuator_controls(self.log)

        return self._actuator_controls_data

