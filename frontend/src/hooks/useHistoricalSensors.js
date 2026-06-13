// src/hooks/useHistoricalSensors.js
// ==================================
// Queries the "sensors" Firestore collection for a date range.
// Used by the HistoryPage and AnalyticsPage for filtered historical data.
//
// Firestore index required (create in Firebase Console or firebase.indexes.json):
//   Collection: sensors
//   Fields: mission_id ASC, timestamp ASC
//
// OUTPUT:
//   {
//     readings:  [ { timestamp, pH, tds, turbidity, temperature, ammonia, source }, ... ],
//     loading:   false,
//     error:     null | "string",
//     stats:     { ph: {min,max,mean,count}, tds: {...}, ... },
//     exportCSV: () => void,   // triggers browser download
//   }

import { useState, useEffect, useCallback, useRef } from "react";
import {
  db,
  collection,
  query,
  orderBy,
  limit,
  getDocs,
  where,
} from "../services/firebase";
import { COLLECTIONS } from "../config/firestore";

const SENSOR_KEYS = ["pH", "tds", "turbidity", "temperature", "ammonia"];
const MAX_ROWS    = 2000;   // cap to prevent OOM on long queries

// ── Statistics calculator ──────────────────────────────────────────────────
function calcStats(readings) {
  const out = {};
  SENSOR_KEYS.forEach(key => {
    const vals = readings.map(r => r[key]).filter(v => v != null && !isNaN(v));
    if (!vals.length) { out[key] = { min: null, max: null, mean: null, count: 0 }; return; }
    const sum = vals.reduce((a, b) => a + b, 0);
    out[key] = {
      min:   +Math.min(...vals).toFixed(4),
      max:   +Math.max(...vals).toFixed(4),
      mean:  +(sum / vals.length).toFixed(4),
      count: vals.length,
    };
  });
  return out;
}

// ── CSV exporter ──────────────────────────────────────────────────────────
function buildCSV(readings) {
  const header = ["timestamp_utc", "unix_ts", "pH", "tds", "turbidity", "temperature", "ammonia", "source"];
  const rows = readings.map(r => {
    const dt = r.timestamp ? new Date(r.timestamp * 1000).toISOString() : "";
    return [dt, r.timestamp ?? "", r.pH ?? "", r.tds ?? "", r.turbidity ?? "",
            r.temperature ?? "", r.ammonia ?? "", r.source ?? ""].join(",");
  });
  return [header.join(","), ...rows].join("\n");
}

function downloadCSV(csv, filename) {
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement("a");
  a.href     = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// ── Hook ──────────────────────────────────────────────────────────────────
export function useHistoricalSensors({
  useFirebase  = true,
  startDate    = null,   // JS Date | null  (null = last 24 h)
  endDate      = null,   // JS Date | null  (null = now)
  missionId    = null,   // filter by mission, null = all
  maxRows      = MAX_ROWS,
} = {}) {
  const [readings, setReadings] = useState([]);
  const [loading,  setLoading]  = useState(false);
  const [error,    setError]    = useState(null);
  const abortRef               = useRef(false);

  // Default range: last 24 hours
  const start = startDate ?? new Date(Date.now() - 24 * 60 * 60 * 1000);
  const end   = endDate   ?? new Date();

  const startTs = Math.floor(start.getTime() / 1000);
  const endTs   = Math.floor(end.getTime()   / 1000);

  const fetchData = useCallback(async () => {
    if (!useFirebase) return;
    abortRef.current = false;
    setLoading(true);
    setError(null);

    try {
      // Build query — Firestore requires a composite index for multiple where clauses
      const constraints = [
        orderBy("timestamp", "asc"),
        where("timestamp", ">=", startTs),
        where("timestamp", "<=", endTs),
        limit(maxRows),
      ];

      if (missionId) {
        constraints.unshift(where("mission_id", "==", missionId));
      }

      const q    = query(collection(db, COLLECTIONS.SENSORS), ...constraints);
      const snap = await getDocs(q);

      if (abortRef.current) return;

      const docs = snap.docs.map(d => {
        const data = d.data();
        return {
          id:          d.id,
          timestamp:   data.timestamp    ?? null,
          pH:          data.pH           ?? null,
          tds:         data.tds          ?? null,
          turbidity:   data.turbidity    ?? null,
          temperature: data.temperature  ?? null,
          ammonia:     data.ammonia      ?? null,
          source:      data.source       ?? "sensor",
          mission_id:  data.mission_id   ?? "",
        };
      });

      setReadings(docs);
    } catch (err) {
      if (!abortRef.current) {
        console.error("[useHistoricalSensors] Query failed:", err.message);
        setError(err.message);
      }
    } finally {
      if (!abortRef.current) setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [useFirebase, startTs, endTs, missionId, maxRows]);

  useEffect(() => {
    fetchData();
    return () => { abortRef.current = true; };
  }, [fetchData]);

  const stats = calcStats(readings);

  const exportCSV = useCallback(() => {
    if (!readings.length) return;
    const dateStr = start.toISOString().slice(0, 10);
    downloadCSV(buildCSV(readings), `smartnile_sensors_${dateStr}.csv`);
  }, [readings, start]);

  const exportJSON = useCallback(() => {
    if (!readings.length) return;
    const json = JSON.stringify({ exported_at: new Date().toISOString(), count: readings.length, readings }, null, 2);
    const blob = new Blob([json], { type: "application/json" });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    a.href     = url;
    a.download = `smartnile_sensors_${start.toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }, [readings, start]);

  return { readings, loading, error, stats, exportCSV, exportJSON, refetch: fetchData };
}
