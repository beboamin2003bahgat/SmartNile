// src/hooks/useAlerts.js
// ======================
// Subscribes to the "alerts" Firestore collection.
//
// OUTPUT — each alert matches the shape the existing AlertsPage and
// DashboardPage "Recent Alerts" panel consume:
//
//   {
//     id:       "firebase-doc-id",
//     type:     "critical" | "warning" | "info",   ← maps from level field
//     sensor:   "pH",                              ← maps from category
//     message:  "CRITICAL: pH too low...",
//     time:     "09:58",
//     location: "Nile River",
//     level:    "critical",                        ← raw Python level
//     category: "pH",                              ← raw Python category
//     value:    3.5,
//     unit:     "pH",
//     lat:      null,
//     lon:      null,
//   }

import { useState, useEffect } from "react";
import {
  db,
  collection,
  query,
  orderBy,
  limit,
  onSnapshot,
} from "../services/firebase";
import { COLLECTIONS, ALERTS_LIMIT } from "../config/firestore";

// ── Maps Python alert level → dashboard type string ──────────────────────────
const LEVEL_TO_TYPE = {
  critical: "critical",
  warning:  "warning",
  info:     "info",
};

// ── Maps Python category → display sensor name ───────────────────────────────
const CATEGORY_DISPLAY = {
  pH:          "pH",
  tds:         "TDS",
  turbidity:   "Turbidity",
  temperature: "Temperature",
  ammonia:     "Ammonia",
  gps:         "GPS",
  detection:   "AI Detection",
  system:      "System",
};

function formatAlertTime(ts) {
  const d = ts > 1e10 ? new Date(ts) : new Date(ts * 1000);
  return d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false });
}

function normalise(docId, data) {
  return {
    id:       docId,
    type:     LEVEL_TO_TYPE[data.level] ?? "info",
    sensor:   CATEGORY_DISPLAY[data.category] ?? data.category ?? "System",
    message:  data.message ?? data.title ?? "Alert",
    time:     data.timestamp ? formatAlertTime(data.timestamp) : "–",
    location: data.latitude && data.longitude
      ? `${data.latitude.toFixed(3)}°N, ${data.longitude.toFixed(3)}°E`
      : "Nile River",
    // raw fields
    level:      data.level    ?? "info",
    category:   data.category ?? "system",
    title:      data.title    ?? "",
    value:      data.value    ?? null,
    threshold:  data.threshold ?? null,
    unit:       data.unit      ?? "",
    lat:        data.latitude  ?? null,
    lon:        data.longitude ?? null,
    timestamp:  data.timestamp ?? 0,
    mission_id: data.mission_id ?? "",
  };
}

// ── Static fallback matching original ALERTS array ───────────────────────────
const FALLBACK_ALERTS = [
  { id: "1", type: "warning",  sensor: "Turbidity",   message: "Turbidity rising — 6.2 NTU", time: "11:42", location: "Zone B", level: "warning",  category: "turbidity", title: "", value: 6.2,  unit: "NTU", lat: null, lon: null, timestamp: 0 },
  { id: "2", type: "info",     sensor: "GPS",         message: "Plant detection geo-tagged",  time: "10:05", location: "Zone A", level: "info",     category: "gps",       title: "", value: null, unit: "",    lat: null, lon: null, timestamp: 0 },
  { id: "3", type: "critical", sensor: "Ammonia",     message: "NH₃ spike — 0.68 ppm",        time: "09:58", location: "Zone C", level: "critical", category: "ammonia",   title: "", value: 0.68, unit: "ppm", lat: null, lon: null, timestamp: 0 },
  { id: "4", type: "info",     sensor: "Cloud",       message: "Firebase sync completed",     time: "09:30", location: "All",    level: "info",     category: "system",    title: "", value: null, unit: "",    lat: null, lon: null, timestamp: 0 },
];

export function useAlerts(useFirebase = true) {
  const [alerts, setAlerts] = useState(FALLBACK_ALERTS);
  const [isLive, setIsLive] = useState(false);

  useEffect(() => {
    if (!useFirebase) return;

    let unsubscribe;
    try {
      const q = query(
        collection(db, COLLECTIONS.ALERTS),
        orderBy("timestamp", "desc"),
        limit(ALERTS_LIMIT),
      );

      unsubscribe = onSnapshot(
        q,
        (snapshot) => {
          if (snapshot.empty) return;
          const docs = snapshot.docs.map(d => normalise(d.id, d.data()));
          setAlerts(docs);
          setIsLive(true);
        },
        (error) => {
          console.warn("[useAlerts] Firestore error:", error.message);
          setIsLive(false);
        }
      );
    } catch (err) {
      console.warn("[useAlerts] Firebase not configured:", err.message);
    }

    return () => unsubscribe?.();
  }, [useFirebase]);

  // ── Derived counts ──────────────────────────────────────────────────────
  const counts = {
    critical: alerts.filter(a => a.level === "critical").length,
    warning:  alerts.filter(a => a.level === "warning").length,
    info:     alerts.filter(a => a.level === "info").length,
    total:    alerts.length,
  };

  return { alerts, counts, isLive };
}
