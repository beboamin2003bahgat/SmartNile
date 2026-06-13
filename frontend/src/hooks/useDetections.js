// src/hooks/useDetections.js
// ==========================
// Subscribes to the "detections" Firestore collection.
//
// OUTPUT — each detection object matches the shape the dashboard's
// DetectionPage table and NileMap component already expect:
//
//   {
//     id:          "auto-firebase-id",
//     type:        "Water Hyacinth" | "Water Lettuce" | "Algae Bloom" | "Unknown Plant",
//     confidence:  94.2,              ← percent (0–100)
//     lat:         30.0444,
//     lon:         31.2357,
//     time:        "08:23:12",        ← formatted local time string
//     status:      "Confirmed" | "Review",
//     storage_url: "https://...",     ← snapshot image (may be null)
//     severity:    "high" | "medium" | "low",
//     species_id:  0,
//     raw_confidence: 0.942,          ← original 0–1 float
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
import { COLLECTIONS, DETECTIONS_LIMIT } from "../config/firestore";

// ── Species name normalisation (Python uses snake_case) ──────────────────────
const SPECIES_DISPLAY = {
  water_hyacinth: "Water Hyacinth",
  water_lettuce:  "Water Lettuce",
  algae_bloom:    "Algae Bloom",
  unknown_plant:  "Unknown Plant",
};

function formatTime(ts) {
  // ts is Unix epoch seconds from Python
  const d = ts > 1e10 ? new Date(ts) : new Date(ts * 1000);
  return d.toLocaleTimeString("en-US", { hour12: false });
}

function normalise(docId, data) {
  const conf     = typeof data.confidence === "number" ? data.confidence : 0;
  const confPct  = conf <= 1 ? +(conf * 100).toFixed(1) : +conf.toFixed(1);
  const specName = SPECIES_DISPLAY[data.species_name] || data.species_name || "Unknown Plant";
  const status   = confPct >= 80 ? "Confirmed" : "Review";

  return {
    id:             docId,
    type:           specName,
    confidence:     confPct,
    raw_confidence: conf,
    lat:            data.latitude  ?? null,
    lon:            data.longitude ?? null,
    time:           data.timestamp ? formatTime(data.timestamp) : "–",
    status,
    storage_url:    data.storage_url  ?? null,
    severity:       data.severity     ?? "medium",
    species_id:     data.species_id   ?? -1,
    mission_id:     data.mission_id   ?? "",
    timestamp:      data.timestamp    ?? 0,
  };
}

// ── Static fallback matching the original DETECTIONS array ───────────────────
const FALLBACK_DETECTIONS = [
  { id: "1", type: "Water Hyacinth", confidence: 94.2, lat: 30.0444, lon: 31.2357, time: "08:23:12", status: "Confirmed", storage_url: null, severity: "high",   species_id: 0, raw_confidence: 0.942, timestamp: 0 },
  { id: "2", type: "Water Lettuce",  confidence: 87.5, lat: 30.0512, lon: 31.2401, time: "09:11:44", status: "Confirmed", storage_url: null, severity: "high",   species_id: 1, raw_confidence: 0.875, timestamp: 0 },
  { id: "3", type: "Water Hyacinth", confidence: 91.0, lat: 30.0398, lon: 31.2289, time: "10:05:02", status: "Confirmed", storage_url: null, severity: "high",   species_id: 0, raw_confidence: 0.910, timestamp: 0 },
  { id: "4", type: "Water Lettuce",  confidence: 78.3, lat: 30.0601, lon: 31.2451, time: "11:33:27", status: "Review",    storage_url: null, severity: "medium", species_id: 1, raw_confidence: 0.783, timestamp: 0 },
];

export function useDetections(useFirebase = true) {
  const [detections, setDetections] = useState(FALLBACK_DETECTIONS);
  const [isLive, setIsLive]         = useState(false);

  useEffect(() => {
    if (!useFirebase) return;

    let unsubscribe;
    try {
      const q = query(
        collection(db, COLLECTIONS.DETECTIONS),
        orderBy("timestamp", "desc"),
        limit(DETECTIONS_LIMIT),
      );

      unsubscribe = onSnapshot(
        q,
        (snapshot) => {
          if (snapshot.empty) return; // keep fallback until first real data arrives
          const docs = snapshot.docs.map(d => normalise(d.id, d.data()));
          // sort newest first
          docs.sort((a, b) => b.timestamp - a.timestamp);
          setDetections(docs);
          setIsLive(true);
        },
        (error) => {
          console.warn("[useDetections] Firestore error:", error.message);
          setIsLive(false);
        }
      );
    } catch (err) {
      console.warn("[useDetections] Firebase not configured:", err.message);
    }

    return () => unsubscribe?.();
  }, [useFirebase]);

  // ── Derived statistics ──────────────────────────────────────────────────
  const stats = {
    total:          detections.length,
    waterHyacinth:  detections.filter(d => d.species_id === 0).length,
    waterLettuce:   detections.filter(d => d.species_id === 1).length,
    avgConfidence:  detections.length
      ? +(detections.reduce((s, d) => s + d.confidence, 0) / detections.length).toFixed(1)
      : 0,
  };

  return { detections, stats, isLive };
}
