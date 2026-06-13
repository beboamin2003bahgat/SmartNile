"""
tests/test_sensors.py
=====================
Unit tests for all sensor drivers.
Runs entirely in simulation mode — no hardware required.

Run with:
    cd backend
    python -m pytest tests/test_sensors.py -v
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# force simulation mode before any import reads settings
os.environ["SIMULATION_MODE"] = "True"

import time
import unittest

from sensors.ph_sensor    import PHSensor
from sensors.water_sensors import (
    TDSSensor, TurbiditySensor, DS18B20Sensor, MQ137Sensor
)
from sensors.base_sensor  import BaseSensor


class TestPHSensor(unittest.TestCase):
    def setUp(self):
        self.sensor = PHSensor(simulation=True)
        self.sensor.open()

    def tearDown(self):
        self.sensor.close()

    def test_read_returns_float(self):
        val = self.sensor.read()
        self.assertIsInstance(val, float)

    def test_read_within_physical_range(self):
        for _ in range(20):
            val = self.sensor.read()
            self.assertIsNotNone(val)
            self.assertGreaterEqual(val, 0.0)
            self.assertLessEqual(val, 14.0)

    def test_inject_value(self):
        self.sensor.simulation = False
        self.sensor.inject(7.55)
        val = self.sensor.read()
        self.assertEqual(val, 7.55)
        self.sensor.simulation = True

    def test_status_dict(self):
        self.sensor.read()
        s = self.sensor.status()
        self.assertIn("name",        s)
        self.assertIn("open",        s)
        self.assertIn("last_value",  s)
        self.assertEqual(s["name"], "pH")
        self.assertTrue(s["open"])

    def test_multiple_reads_vary(self):
        """Simulation values should not all be identical (has noise)."""
        vals = {self.sensor.read() for _ in range(10)}
        self.assertGreater(len(vals), 1)


class TestTDSSensor(unittest.TestCase):
    def setUp(self):
        self.sensor = TDSSensor(simulation=True)
        self.sensor.open()

    def tearDown(self):
        self.sensor.close()

    def test_read_returns_float(self):
        val = self.sensor.read()
        self.assertIsNotNone(val)
        self.assertIsInstance(val, float)

    def test_read_within_physical_range(self):
        for _ in range(10):
            val = self.sensor.read()
            self.assertGreaterEqual(val, 0.0)
            self.assertLessEqual(val, 5000.0)


class TestTurbiditySensor(unittest.TestCase):
    def setUp(self):
        self.sensor = TurbiditySensor(simulation=True)
        self.sensor.open()

    def tearDown(self):
        self.sensor.close()

    def test_read_returns_non_negative(self):
        for _ in range(10):
            val = self.sensor.read()
            self.assertIsNotNone(val)
            self.assertGreaterEqual(val, 0.0)


class TestDS18B20Sensor(unittest.TestCase):
    def setUp(self):
        self.sensor = DS18B20Sensor(simulation=True)
        self.sensor.open()

    def tearDown(self):
        self.sensor.close()

    def test_temperature_range(self):
        for _ in range(10):
            val = self.sensor.read()
            self.assertIsNotNone(val)
            self.assertGreater(val, -5.0)
            self.assertLess(val, 60.0)


class TestMQ137Sensor(unittest.TestCase):
    def setUp(self):
        self.sensor = MQ137Sensor(simulation=True)
        self.sensor.open()

    def tearDown(self):
        self.sensor.close()

    def test_warmup_guard(self):
        """Before warm-up completes, read() should return None."""
        self.assertFalse(self.sensor.is_warmed_up())
        val = self.sensor.read()
        self.assertIsNone(val)

    def test_warmup_remaining_decreases(self):
        t1 = self.sensor.warmup_remaining()
        time.sleep(0.1)
        t2 = self.sensor.warmup_remaining()
        self.assertLess(t2, t1)

    def test_read_after_warmup(self):
        """Force past warm-up by manipulating open time."""
        self.sensor._open_time = time.time() - 61
        self.assertTrue(self.sensor.is_warmed_up())
        val = self.sensor.read()
        self.assertIsNotNone(val)
        self.assertGreaterEqual(val, 0.0)


class TestBaseSensorInterface(unittest.TestCase):
    def test_cannot_instantiate_base(self):
        with self.assertRaises(TypeError):
            BaseSensor("test", simulation=True)   # abstract — must raise


if __name__ == "__main__":
    unittest.main(verbosity=2)
