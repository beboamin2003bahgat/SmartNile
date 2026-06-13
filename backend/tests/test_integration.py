"""
tests/test_integration.py
==========================
End-to-end integration test for the complete Smart Nile data pipeline.

Tests the full chain:
  SensorManager → AlertManager → ReportManager → FirebaseManager (sim)

Runs entirely in SIMULATION_MODE=True with no hardware or Firebase
connection required.

Run with:
    cd backend
    python -m unittest tests.test_integration -v
"""

import os
import sys
import time
import threading
import unittest
from unittest.mock import MagicMock, patch

# Force simulation before any import reads settings
os.environ["SIMULATION_MODE"]     = "True"
os.environ["FIREBASE_PROJECT_ID"] = "test-project"
os.environ["MISSION_ID"]          = "test_mission_integration"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from managers.sensor_manager  import SensorManager
from managers.gps_manager     import GPSManager
from managers.alert_manager   import AlertManager
from managers.firebase_manager import FirebaseManager
from managers.report_manager  import ReportManager
from managers.ai_manager      import AIManager
from managers.camera_manager  import CameraManager
from utils.validators         import SensorReading, GPSFix, AlertEvent, DetectionResult, now


# ── Helper: collect N items emitted by a callback ────────────────────────────
def collect(n, timeout=10.0):
    """Returns a context manager that collects up to n callback calls."""
    items = []
    event = threading.Event()

    def cb(item):
        items.append(item)
        if len(items) >= n:
            event.set()

    return cb, items, event, timeout


class TestSensorManagerSimulation(unittest.TestCase):
    """SensorManager runs in simulation, emits valid SensorReading objects."""

    def test_emits_readings_within_timeout(self):
        readings = []
        done     = threading.Event()

        def on_reading(r):
            readings.append(r)
            if len(readings) >= 3:
                done.set()

        mgr = SensorManager(on_reading=on_reading)
        mgr.start()
        triggered = done.wait(timeout=12)
        mgr.stop()

        self.assertTrue(triggered, "Did not receive 3 readings within 12 s")
        self.assertGreaterEqual(len(readings), 3)

    def test_reading_has_all_sensor_fields(self):
        readings = []
        done     = threading.Event()

        def on_reading(r):
            readings.append(r)
            done.set()

        mgr = SensorManager(on_reading=on_reading)
        mgr.start()
        done.wait(timeout=8)
        mgr.stop()

        self.assertTrue(readings, "No readings received")
        r = readings[0]
        self.assertIsInstance(r, SensorReading)
        self.assertIsNotNone(r.pH)
        self.assertIsNotNone(r.tds)
        self.assertIsNotNone(r.turbidity)
        self.assertIsNotNone(r.temperature)
        # ammonia may be None during warm-up (60 s), that is expected

    def test_reading_values_in_physical_range(self):
        readings = []
        done     = threading.Event()

        def on_reading(r):
            readings.append(r)
            if len(readings) >= 5:
                done.set()

        mgr = SensorManager(on_reading=on_reading)
        mgr.start()
        done.wait(timeout=20)
        mgr.stop()

        for r in readings:
            if r.pH          is not None: self.assertBetween(r.pH,          0.0,  14.0)
            if r.tds         is not None: self.assertBetween(r.tds,         0.0, 5000.0)
            if r.turbidity   is not None: self.assertBetween(r.turbidity,   0.0, 3000.0)
            if r.temperature is not None: self.assertBetween(r.temperature, -5.0,  60.0)

    def assertBetween(self, val, lo, hi):
        self.assertGreaterEqual(val, lo, f"Value {val} below {lo}")
        self.assertLessEqual(   val, hi, f"Value {val} above {hi}")


class TestGPSManagerSimulation(unittest.TestCase):
    """GPSManager produces valid GPSFix objects within Egypt bounds."""

    def test_emits_fixes_within_timeout(self):
        fixes = []
        done  = threading.Event()

        def on_fix(f):
            fixes.append(f)
            if len(fixes) >= 3:
                done.set()

        mgr = GPSManager(on_fix=on_fix)
        mgr.start()
        triggered = done.wait(timeout=8)
        mgr.stop()

        self.assertTrue(triggered, "Did not receive 3 GPS fixes")
        for f in fixes:
            self.assertIsInstance(f, GPSFix)
            self.assertTrue(f.has_fix)
            self.assertTrue(f.is_in_egypt, f"Fix outside Egypt: {f.latitude}, {f.longitude}")

    def test_route_accumulates(self):
        mgr = GPSManager()
        mgr.start()
        time.sleep(3.5)
        mgr.stop()

        route = mgr.get_route()
        self.assertGreaterEqual(len(route), 2, "Route should accumulate fixes")


class TestAlertManagerPipeline(unittest.TestCase):
    """AlertManager correctly evaluates readings and fires callbacks."""

    def test_critical_ph_triggers_callback(self):
        received = []
        am = AlertManager(on_alert=lambda a: received.append(a))

        # inject a clearly critical pH
        reading = SensorReading(
            timestamp=now(), pH=3.0, tds=200.0,
            turbidity=5.0, temperature=22.0, ammonia=0.1,
            source="test", mission_id="test"
        )
        am.process_sensor(reading)

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].level, "critical")
        self.assertEqual(received[0].category, "pH")

    def test_normal_reading_no_alert(self):
        received = []
        am = AlertManager(on_alert=lambda a: received.append(a))

        reading = SensorReading(
            timestamp=now(), pH=7.2, tds=200.0,
            turbidity=3.0, temperature=23.0, ammonia=0.05,
            source="test", mission_id="test"
        )
        am.process_sensor(reading)
        self.assertEqual(received, [])

    def test_detection_alert_is_critical(self):
        received = []
        am = AlertManager(on_alert=lambda a: received.append(a))

        det = DetectionResult(
            timestamp=now(), species_id=0, confidence=0.95,
            bounding_box={"x": 0, "y": 0, "w": 100, "h": 100},
            latitude=30.05, longitude=31.23, mission_id="test"
        )
        am.process_detection(det)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].level, "critical")


class TestReportManagerAccumulation(unittest.TestCase):
    """ReportManager accumulates data and generates a valid report."""

    def test_generate_now_returns_path(self):
        rm = ReportManager()
        rm.start()

        # feed some data
        for i in range(5):
            reading = SensorReading(
                timestamp=now() - i * 10,
                pH=7.0 + i * 0.1, tds=200.0, turbidity=4.0,
                temperature=22.0, ammonia=0.05,
                source="test", mission_id="test"
            )
            rm.record_reading(reading)

        path = rm.generate_now()
        rm.stop()

        self.assertIsNotNone(path, "generate_now() should return a file path")
        import os
        self.assertTrue(os.path.exists(path), f"Report file not found: {path}")

    def test_report_contains_sensor_stats(self):
        import json
        rm = ReportManager()
        rm.start()

        for i in range(10):
            rm.record_reading(SensorReading(
                timestamp=now(), pH=7.0, tds=250.0, turbidity=5.0,
                temperature=23.0, ammonia=0.1, source="test", mission_id="test"
            ))

        path = rm.generate_now()
        rm.stop()

        with open(path) as fh:
            data = json.load(fh)

        self.assertIn("sensor_stats",  data)
        self.assertIn("gps_summary",   data)
        self.assertIn("alerts_summary", data)
        self.assertIn("detections_summary", data)
        self.assertIn("pH", data["sensor_stats"])


class TestFirebaseManagerSimulation(unittest.TestCase):
    """FirebaseManager in simulation mode logs writes without crashing."""

    def test_push_sensor_no_exception(self):
        fm = FirebaseManager()
        fm.start()
        reading = SensorReading(
            timestamp=now(), pH=7.2, tds=220.0, turbidity=3.5,
            temperature=23.0, ammonia=0.05, source="test", mission_id="test"
        )
        fm.push_sensor(reading)
        time.sleep(0.5)
        s = fm.status()
        self.assertTrue(s["simulation"])
        self.assertGreaterEqual(s["total_writes"], 1)
        fm.stop()

    def test_offline_buffer_fills_when_disconnected(self):
        fm = FirebaseManager()
        fm._sim = False   # pretend not simulation but also not connected
        fm._connected = False
        fm.start()

        for _ in range(5):
            fm.push_sensor(SensorReading(
                timestamp=now(), pH=7.2, tds=220.0, turbidity=3.0,
                temperature=22.0, ammonia=0.04, source="test", mission_id="test"
            ))
        time.sleep(1.0)

        pending = fm._buffer.pending_count()
        self.assertGreater(pending, 0, "Offline buffer should have queued writes")
        fm.stop()


class TestValidatorDataClasses(unittest.TestCase):
    """SensorReading + GPSFix + DetectionResult contract validation."""

    def test_sensor_reading_rejects_out_of_range_ph(self):
        r = SensorReading(timestamp=now(), pH=99.0, tds=None, turbidity=None, temperature=None, ammonia=None)
        self.assertIsNone(r.pH)
        self.assertIn("pH", r.errors)

    def test_gps_fix_egypt_bounds(self):
        f_egypt  = GPSFix(timestamp=now(), latitude=30.05, longitude=31.23, fix_quality=1)
        f_abroad = GPSFix(timestamp=now(), latitude=51.50, longitude=-0.12, fix_quality=1)
        self.assertTrue(f_egypt.is_in_egypt)
        self.assertFalse(f_abroad.is_in_egypt)

    def test_detection_to_dict_has_species_name(self):
        d = DetectionResult(
            timestamp=now(), species_id=0, confidence=0.92,
            bounding_box={"x": 0, "y": 0, "w": 100, "h": 100},
            mission_id="test"
        )
        data = d.to_dict()
        self.assertEqual(data["species_name"], "water_hyacinth")
        self.assertEqual(data["severity"], "high")

    def test_sensor_reading_to_dict_excludes_none(self):
        r = SensorReading(timestamp=now(), pH=7.2, tds=None, turbidity=4.0,
                          temperature=22.0, ammonia=None, source="test", mission_id="t")
        d = r.to_dict()
        self.assertIn("pH",          d)
        self.assertNotIn("tds",      d)   # None stripped
        self.assertNotIn("ammonia",  d)   # None stripped


if __name__ == "__main__":
    unittest.main(verbosity=2)
