"""
tests/test_alerts.py
====================
Unit tests for the AlertManager threshold evaluation engine.
No hardware or Firebase connection required.

Run with:
    cd backend
    python -m pytest tests/test_alerts.py -v
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["SIMULATION_MODE"] = "True"

import time
import unittest
from unittest.mock import MagicMock, patch

from managers.alert_manager import AlertManager
from utils.validators import AlertEvent, DetectionResult, SensorReading, now


def _reading(**overrides) -> SensorReading:
    """Helper — build a SensorReading with sensible defaults."""
    defaults = dict(
        timestamp=now(), pH=7.4, tds=220.0,
        turbidity=12.0, temperature=24.0, ammonia=0.05,
        source="simulation", mission_id="test_mission",
    )
    defaults.update(overrides)
    return SensorReading(**defaults)


def _detection(species_id: int = 0, confidence: float = 0.92) -> DetectionResult:
    return DetectionResult(
        timestamp=now(), species_id=species_id, confidence=confidence,
        bounding_box={"x": 0, "y": 0, "w": 100, "h": 100},
        latitude=30.05, longitude=31.23, mission_id="test_mission",
    )


class TestAlertManagerNormalReadings(unittest.TestCase):
    def setUp(self):
        self.callback = MagicMock()
        self.am = AlertManager(on_alert=self.callback)

    def test_no_alert_when_all_normal(self):
        reading = _reading()
        alerts = self.am.process_sensor(reading)
        self.assertEqual(alerts, [])
        self.callback.assert_not_called()

    def test_ph_critical_low_triggers(self):
        reading = _reading(pH=3.5)   # below critical_low=4.0
        alerts = self.am.process_sensor(reading)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].level, "critical")
        self.assertEqual(alerts[0].category, "pH")
        self.callback.assert_called_once()

    def test_ph_warning_high_triggers(self):
        reading = _reading(pH=9.0)   # above warning_high=8.5
        alerts = self.am.process_sensor(reading)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].level, "warning")

    def test_tds_critical_high(self):
        reading = _reading(tds=1500.0)   # above critical_high=1000
        alerts = self.am.process_sensor(reading)
        self.assertTrue(any(a.category == "tds" and a.level == "critical" for a in alerts))

    def test_turbidity_warning(self):
        reading = _reading(turbidity=75.0)   # above warning_high=50
        alerts = self.am.process_sensor(reading)
        self.assertTrue(any(a.category == "turbidity" and a.level == "warning" for a in alerts))

    def test_ammonia_critical(self):
        reading = _reading(ammonia=3.0)   # above critical_high=2.0
        alerts = self.am.process_sensor(reading)
        self.assertTrue(any(a.category == "ammonia" and a.level == "critical" for a in alerts))

    def test_multiple_violations_in_one_reading(self):
        reading = _reading(pH=3.0, ammonia=5.0, tds=1200.0)
        alerts = self.am.process_sensor(reading)
        self.assertGreaterEqual(len(alerts), 2)

    def test_none_sensor_values_skipped(self):
        reading = _reading(pH=None, tds=None)
        alerts = self.am.process_sensor(reading)
        self.assertEqual(alerts, [])


class TestAlertManagerCooldown(unittest.TestCase):
    def setUp(self):
        self.callback = MagicMock()
        self.am = AlertManager(on_alert=self.callback)

    def test_duplicate_alert_blocked_by_cooldown(self):
        reading = _reading(pH=3.5)
        self.am.process_sensor(reading)
        first_call_count = self.callback.call_count

        # second identical reading immediately after
        self.am.process_sensor(reading)
        self.assertEqual(self.callback.call_count, first_call_count)   # no new call

    def test_alert_re_emits_after_cooldown(self):
        """Patch _last_alert to simulate cooldown expiry."""
        reading = _reading(pH=3.5)
        self.am.process_sensor(reading)
        # manually expire the cooldown
        self.am._last_alert.clear()
        self.am.process_sensor(reading)
        self.assertEqual(self.callback.call_count, 2)


class TestAlertManagerDetections(unittest.TestCase):
    def setUp(self):
        self.callback = MagicMock()
        self.am = AlertManager(on_alert=self.callback)

    def test_water_hyacinth_detection_is_critical(self):
        det = _detection(species_id=0, confidence=0.95)
        alert = self.am.process_detection(det)
        self.assertIsNotNone(alert)
        self.assertEqual(alert.level, "critical")
        self.assertEqual(alert.category, "detection")
        self.callback.assert_called_once()

    def test_water_lettuce_detection_is_critical(self):
        det = _detection(species_id=1, confidence=0.88)
        alert = self.am.process_detection(det)
        self.assertIsNotNone(alert)
        self.assertEqual(alert.level, "critical")

    def test_unknown_plant_is_warning(self):
        det = _detection(species_id=3, confidence=0.70)
        alert = self.am.process_detection(det)
        self.assertIsNotNone(alert)
        self.assertEqual(alert.level, "warning")

    def test_detection_cooldown(self):
        det = _detection(species_id=0)
        self.am.process_detection(det)
        result = self.am.process_detection(det)
        self.assertIsNone(result)   # deduplicated


class TestAlertManagerGPS(unittest.TestCase):
    def setUp(self):
        self.am = AlertManager()

    def test_gps_lost_returns_warning(self):
        alert = self.am.process_gps_lost()
        self.assertIsNotNone(alert)
        self.assertEqual(alert.level, "warning")
        self.assertEqual(alert.category, "gps")


class TestAlertManagerHistory(unittest.TestCase):
    def setUp(self):
        self.am = AlertManager()

    def test_history_populated(self):
        reading = _reading(pH=3.0)
        self.am.process_sensor(reading)
        history = self.am.get_history()
        self.assertGreater(len(history), 0)
        self.assertIsInstance(history[0], AlertEvent)

    def test_get_history_limit(self):
        # generate several distinct alerts by clearing cooldown each time
        for ph in [3.0, 11.0]:
            self.am._last_alert.clear()
            self.am.process_sensor(_reading(pH=ph))
        history = self.am.get_history(limit=1)
        self.assertEqual(len(history), 1)

    def test_status_dict_structure(self):
        s = self.am.status()
        self.assertIn("total_alerts",  s)
        self.assertIn("history_size",  s)
        self.assertIn("recent_alerts", s)

    def test_history_to_dicts(self):
        self.am.process_sensor(_reading(pH=3.0))
        dicts = self.am.get_history_dicts()
        if dicts:
            self.assertIsInstance(dicts[0], dict)
            self.assertIn("level", dicts[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
