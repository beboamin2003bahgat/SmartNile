// src/hooks/useSensors.js
// =======================
// Subscribes to the "sensors" Firestore collection and continuously updates
// the sensor state that the existing dashboard components consume.
//
// OUTPUT shape — identical to the dashboard's initialSensors() so every
// SensorCard, Sparkline, CircleGauge, and AnalyticsChart works without
// any component modification:
//
//   {
//     ph:          { name, unit, icon, optimal, warning, value, min, max,
//                    history: [{t, v}, ...], lastUpdate, source },
//     tds:         { ... },
//     turbidity:   { ... },
//     temperature: { ... },
//     ammonia:     { ... },
//   }
//
// FALLBACK — when Firebase is unavailable (offline / not yet configured)
// the hook returns the original simulated data so the UI never breaks.

import { useState, useEffect, useRef, useCallback } from "react";
import {
  db,
  collection,
  query,
  orderBy,
  limit,
  onSnapshot,
} from "../services/firebase";
import { COLLECTIONS, HISTORY_LIMIT } from "../config/firestore";

// ── Static metadata (sensor display config — never changes) ──────────────────
const SENSOR_META = {
  ph: {
    name: "pH", unit: "pH", icon: "🧪",
    optimal: [6.5, 7.5], warning: [6.0, 8.0],
    base: 7.2, range: 0.3,
  },
  tds: {
    name: "TDS", unit: "ppm", icon: "💧",
    optimal: [0, 500], warning: [0, 800],
    base: 320, range: 40,
  },
  turbidity: {
    name: "Turbidity", unit: "NTU", icon: "🌊",
    optimal: [0, 5], warning: [0, 10],
    base: 3.5, range: 1.5,
  },
  temperature: {
    name: "Temperature", unit: "°C", icon: "🌡️",
    optimal: [20, 25], warning: [18, 28],
    base: 22, range: 2,
  },
  ammonia: {
    name: "Ammonia (NH₃)", unit: "ppm", icon: "⚗️",
    optimal: [0, 0.5], warning: [0, 1.0],
    base: 0.2, range: 0.15,
  },
};

// ── Simulation fallback (keeps UI alive if Firebase isn't connected) ──────────
function simVal(base, range) {
  return +(base + (Math.random() - 0.5) * range * 2).toFixed(2);
}

function buildSimReading() {
  const result = {};
  Object.entries(SENSOR_META).forEach(([key, meta]) => {
    const v = simVal(meta.base, meta.range);
    result[key] = v;
  });
  return result;
}

// ── Initial state builder ─────────────────────────────────────────────────────
function buildInitialState() {
  const state = {};
  Object.entries(SENSOR_META).forEach(([key, meta]) => {
    state[key] = {
      ...meta,
      value:      meta.base,
      min:        meta.base,
      max:        meta.base,
      history:    [],
      lastUpdate: "–",
      source:     "simulation",
      online:     false,
    };
  });
  return state;
}

// ── Field name map: Firestore key → local state key ──────────────────────────
const FIELD_MAP = {
  pH:          "ph",
  tds:         "tds",
  turbidity:   "turbidity",
  temperature: "temperature",
  ammonia:     "ammonia",
};

// ── Hook ─────────────────────────────────────────────────────────────────────
export function useSensors(useFirebase = true) {
  const [sensors, setSensors] = useState(buildInitialState);
  const [isLive, setIsLive]   = useState(false);
  const [lastDoc, setLastDoc]  = useState(null);
  const historyRef             = useRef({}); // persists history across renders without re-render

  // Initialise history accumulator
  useEffect(() => {
    Object.keys(SENSOR_META).forEach(k => { historyRef.current[k] = []; });
  }, []);

  // ── Apply one Firestore document to state ────────────────────────────────
  const applyDoc = useCallback((doc) => {
    const data = doc.data ? doc.data() : doc; // handle both snapshot and plain object
    const ts   = data.timestamp ? data.timestamp * 1000 : Date.now();
    const when = new Date(ts).toLocaleTimeString();

    setSensors(prev => {
      const next = { ...prev };

      Object.entries(FIELD_MAP).forEach(([firestoreKey, localKey]) => {
        const rawVal = data[firestoreKey];
        if (rawVal == null || typeof rawVal !== "number") return;

        const val  = +rawVal.toFixed(4);
        const prev_sensor = next[localKey];

        // append to in-memory history (cap at HISTORY_LIMIT)
        const hist = historyRef.current[localKey] || [];
        hist.push({ t: ts, v: val });
        if (hist.length > HISTORY_LIMIT) hist.shift();
        historyRef.current[localKey] = hist;

        next[localKey] = {
          ...prev_sensor,
          value:      val,
          min:        Math.min(prev_sensor.min ?? val, val),
          max:        Math.max(prev_sensor.max ?? val, val),
          history:    [...hist],
          lastUpdate: when,
          source:     data.source || "sensor",
          online:     true,
        };
      });

      return next;
    });

    setLastDoc(data);
    setIsLive(true);
  }, []);

  // ── Firebase live listener ───────────────────────────────────────────────
  useEffect(() => {
    if (!useFirebase) return;

    let unsubscribe;
    try {
      const q = query(
        collection(db, COLLECTIONS.SENSORS),
        orderBy("timestamp", "desc"),
        limit(1),
      );

      unsubscribe = onSnapshot(
        q,
        (snapshot) => {
          if (!snapshot.empty) {
            applyDoc(snapshot.docs[0]);
          }
        },
        (error) => {
          console.warn("[useSensors] Firestore error — falling back to simulation:", error.message);
          setIsLive(false);
          startSimulation();
        }
      );
    } catch (err) {
      console.warn("[useSensors] Firebase not configured — using simulation:", err.message);
      startSimulation();
    }

    return () => unsubscribe?.();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [useFirebase]);

  // ── Simulation fallback ──────────────────────────────────────────────────
  const simRef = useRef(null);

  function startSimulation() {
    if (simRef.current) return; // already running
    simRef.current = setInterval(() => {
      const reading = buildSimReading();
      const ts      = Date.now();
      const when    = new Date(ts).toLocaleTimeString();

      setSensors(prev => {
        const next = { ...prev };
        Object.entries(FIELD_MAP).forEach(([, localKey]) => {
          const val        = reading[localKey];
          const prev_sensor = next[localKey];
          const hist       = historyRef.current[localKey] || [];
          hist.push({ t: ts, v: val });
          if (hist.length > HISTORY_LIMIT) hist.shift();
          historyRef.current[localKey] = hist;

          next[localKey] = {
            ...prev_sensor,
            value:      val,
            min:        Math.min(prev_sensor.min ?? val, val),
            max:        Math.max(prev_sensor.max ?? val, val),
            history:    [...hist],
            lastUpdate: when,
            source:     "simulation",
          };
        });
        return next;
      });
    }, 2000);
  }

  useEffect(() => {
    return () => {
      if (simRef.current) clearInterval(simRef.current);
    };
  }, []);

  return { sensors, isLive, lastDoc };
}
