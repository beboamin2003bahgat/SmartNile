// src/config/firestore.js
// =======================
// Every Firestore collection name and document field used in the dashboard.
// These MUST match the strings in backend/managers/firebase_manager.py exactly.
//
// Python backend writes to:          Dashboard reads from:
//   sensors/{auto}                     COLLECTIONS.SENSORS
//   gps/{auto}                         COLLECTIONS.GPS
//   alerts/{auto}                      COLLECTIONS.ALERTS
//   detections/{auto}                  COLLECTIONS.DETECTIONS
//   heartbeat/boat                     COLLECTIONS.HEARTBEAT / doc "boat"
//   missions/{mission_id}              COLLECTIONS.MISSIONS
//   reports/{auto}                     COLLECTIONS.REPORTS

export const COLLECTIONS = {
  SENSORS:    "sensors",
  GPS:        "gps",
  ALERTS:     "alerts",
  DETECTIONS: "detections",
  HEARTBEAT:  "heartbeat",
  MISSIONS:   "missions",
  REPORTS:    "reports",
};

// ── Sensor field names (match SensorReading.to_dict() keys) ─────────────────
export const SENSOR_FIELDS = {
  TIMESTAMP:   "timestamp",
  PH:          "pH",
  TDS:         "tds",
  TURBIDITY:   "turbidity",
  TEMPERATURE: "temperature",
  AMMONIA:     "ammonia",
  SOURCE:      "source",
  MISSION_ID:  "mission_id",
};

// ── GPS field names (match GPSFix.to_dict() keys) ────────────────────────────
export const GPS_FIELDS = {
  TIMESTAMP:   "timestamp",
  LATITUDE:    "latitude",
  LONGITUDE:   "longitude",
  ALTITUDE:    "altitude",
  SPEED:       "speed",
  HEADING:     "heading",
  SATELLITES:  "satellites",
  FIX_QUALITY: "fix_quality",
  MISSION_ID:  "mission_id",
};

// ── Detection field names (match DetectionResult.to_dict() keys) ─────────────
export const DETECTION_FIELDS = {
  TIMESTAMP:    "timestamp",
  SPECIES_ID:   "species_id",
  SPECIES_NAME: "species_name",
  CONFIDENCE:   "confidence",
  BBOX:         "bounding_box",
  LATITUDE:     "latitude",
  LONGITUDE:    "longitude",
  STORAGE_URL:  "storage_url",
  SEVERITY:     "severity",
  MISSION_ID:   "mission_id",
};

// ── Alert field names (match AlertEvent.to_dict() keys) ──────────────────────
export const ALERT_FIELDS = {
  TIMESTAMP:  "timestamp",
  LEVEL:      "level",
  CATEGORY:   "category",
  TITLE:      "title",
  MESSAGE:    "message",
  VALUE:      "value",
  THRESHOLD:  "threshold",
  UNIT:       "unit",
  LATITUDE:   "latitude",
  LONGITUDE:  "longitude",
  MISSION_ID: "mission_id",
};

// ── Heartbeat field names ────────────────────────────────────────────────────
export const HEARTBEAT_FIELDS = {
  TIMESTAMP:  "timestamp",
  STATUS:     "status",
  MISSION_ID: "mission_id",
  UTC:        "utc",
};

// ── How stale a heartbeat can be before we show "offline" (seconds) ──────────
export const HEARTBEAT_TIMEOUT_S = 30;

// ── How many historical sensor readings to load at once ──────────────────────
export const HISTORY_LIMIT = 60;

// ── How many detection rows to show in the table ────────────────────────────
export const DETECTIONS_LIMIT = 50;

// ── How many alerts to load ──────────────────────────────────────────────────
export const ALERTS_LIMIT = 100;

// ── How many GPS points to keep in memory for the route trail ────────────────
export const GPS_ROUTE_LIMIT = 500;
