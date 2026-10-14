"""Sensor interface seam; simulations never report physical hardware as connected."""

import time
from abc import ABCMeta, abstractmethod


class SensorAdapter(metaclass=ABCMeta):
    @abstractmethod
    def read(self):
        """Return availability, source, state, values and observation time."""


class UnconfiguredSensor(SensorAdapter):
    def read(self):
        return {"available": False, "source": "unconfigured", "state": "UNKNOWN",
                "values": {}, "observed_at": time.time(),
                "message": "No physical sensor interface is configured"}


class MockSensor(SensorAdapter):
    def __init__(self, state="UNKNOWN"):
        self.state = state

    def read(self):
        return {"available": False, "source": "mock", "state": self.state,
                "values": {}, "observed_at": time.time(),
                "message": "Simulated test input; no physical sensor was read"}

