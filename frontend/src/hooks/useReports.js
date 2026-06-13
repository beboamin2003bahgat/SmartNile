// src/hooks/useReports.js
// =======================
// Loads the most recent mission reports from Firestore.
//
// Reports are written by backend/managers/report_manager.py every 24 h
// and at mission end. Each document in "reports/" contains the full
// summary JSON (sensor stats, GPS summary, alert counts, detection counts).
//
// OUTPUT:
//   {
//     reports:    [{ id, generated_at, mission_id, sensor_stats,
//                    gps_summary, alerts_summary, detections_summary }, ...],
//     latest:     { ... } | null,
//     loading:    false,
//     isLive:     true,
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
import { COLLECTIONS } from "../config/firestore";

export function useReports(useFirebase = true, maxReports = 10) {
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(true);
  const [isLive,  setIsLive]  = useState(false);

  useEffect(() => {
    if (!useFirebase) { setLoading(false); return; }

    let unsubscribe;
    try {
      const q = query(
        collection(db, COLLECTIONS.REPORTS),
        orderBy("generated_at_epoch", "desc"),
        limit(maxReports),
      );

      unsubscribe = onSnapshot(
        q,
        (snapshot) => {
          const docs = snapshot.docs.map(d => ({ id: d.id, ...d.data() }));
          setReports(docs);
          setLoading(false);
          setIsLive(true);
        },
        (err) => {
          console.warn("[useReports] Firestore error:", err.message);
          setLoading(false);
          setIsLive(false);
        }
      );
    } catch (err) {
      console.warn("[useReports] Firebase not configured:", err.message);
      setLoading(false);
    }

    return () => unsubscribe?.();
  }, [useFirebase, maxReports]);

  return {
    reports,
    latest:  reports[0] ?? null,
    loading,
    isLive,
  };
}
