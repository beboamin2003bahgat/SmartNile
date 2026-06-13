// src/hooks/useGPS.js
// ===================
// Live GPS position from Firestore "gps" collection.
//
// OUTPUT shape — matches the existing dashboard gps state:
//   {
//     lat:        30.0444,
//     lon:        31.2357,
//     altitude:   18.0,
//     speed:      4.0,
//     heading:    45.0,
//     satellites: 9,
//     fix_quality: 1,
//     route:      [{ lat, lon, timestamp }, ...],   ← new, for route trail
//     hasFix:     true,
//     source:     "gps" | "simulation",
//   }

import { useState, useEffect, useRef } from "react";
import {
  db,
  collection,
  query,
  orderBy,
  limit,
  onSnapshot,
} from "../services/firebase";
import { COLLECTIONS, GPS_ROUTE_LIMIT } from "../config/firestore";

const DEFAULT_GPS = {
  lat:        30.0444,
  lon:        31.2357,
  altitude:   null,
  speed:      null,
  heading:    null,
  satellites: null,
  fix_quality: 0,
  route:      [],
  hasFix:     false,
  source:     "simulation",
};

// ── Cairo-area Nile simulation ────────────────────────────────────────────────
function nextSimPos(prev) {
  return {
    lat: prev.lat + (Math.random() - 0.5) * 0.0002,
    lon: prev.lon + (Math.random() - 0.5) * 0.0002,
  };
}

export function useGPS(useFirebase = true) {
  const [gps, setGps]     = useState(DEFAULT_GPS);
  const [isLive, setIsLive] = useState(false);
  const routeRef           = useRef([]);

  // ── Apply one Firestore GPS document ────────────────────────────────────
  function applyDoc(data) {
    const lat = data.latitude;
    const lon = data.longitude;
    if (lat == null || lon == null) return;

    const point = { lat, lon, timestamp: data.timestamp };
    routeRef.current.push(point);
    if (routeRef.current.length > GPS_ROUTE_LIMIT) {
      routeRef.current.shift();
    }

    setGps({
      lat,
      lon,
      altitude:    data.altitude    ?? null,
      speed:       data.speed       ?? null,
      heading:     data.heading     ?? null,
      satellites:  data.satellites  ?? null,
      fix_quality: data.fix_quality ?? 0,
      route:       [...routeRef.current],
      hasFix:      (data.fix_quality ?? 0) > 0,
      source:      data.source ?? "gps",
    });

    setIsLive(true);
  }

  // ── Firebase live listener ───────────────────────────────────────────────
  useEffect(() => {
    if (!useFirebase) { startSimulation(); return; }

    let unsubscribe;
    try {
      const q = query(
        collection(db, COLLECTIONS.GPS),
        orderBy("timestamp", "desc"),
        limit(1),
      );

      unsubscribe = onSnapshot(
        q,
        (snapshot) => {
          if (!snapshot.empty) applyDoc(snapshot.docs[0].data());
        },
        (error) => {
          console.warn("[useGPS] Firestore error:", error.message);
          setIsLive(false);
          startSimulation();
        }
      );
    } catch (err) {
      console.warn("[useGPS] Firebase not configured:", err.message);
      startSimulation();
    }

    return () => unsubscribe?.();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [useFirebase]);

  // ── Simulation fallback ──────────────────────────────────────────────────
  const simRef = useRef(null);

  function startSimulation() {
    if (simRef.current) return;
    simRef.current = setInterval(() => {
      setGps(prev => {
        const pos = nextSimPos(prev);
        const point = { lat: pos.lat, lon: pos.lon, timestamp: Date.now() / 1000 };
        routeRef.current.push(point);
        if (routeRef.current.length > GPS_ROUTE_LIMIT) routeRef.current.shift();
        return {
          ...prev,
          ...pos,
          route:      [...routeRef.current],
          hasFix:     true,
          fix_quality: 1,
          satellites:  9,
          source:     "simulation",
        };
      });
    }, 1000);
  }

  useEffect(() => () => { if (simRef.current) clearInterval(simRef.current); }, []);

  return { gps, isLive };
}
