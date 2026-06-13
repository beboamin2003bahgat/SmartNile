// src/hooks/useHeartbeat.js
// =========================
// Watches the single "heartbeat/boat" document that the Python backend
// writes every 15 seconds to indicate the boat is alive.
//
// OUTPUT:
//   {
//     boatOnline:  true | false,
//     missionId:   "mission_001",
//     lastSeen:    Date,
//     status:      "online" | "offline",
//     lastSeenAgo: 12,       ← seconds since last heartbeat
//   }

import { useState, useEffect, useRef } from "react";
import { db, onSnapshot, doc } from "../services/firebase";
import { COLLECTIONS, HEARTBEAT_TIMEOUT_S } from "../config/firestore";

export function useHeartbeat(useFirebase = true) {
  const [heartbeat, setHeartbeat] = useState({
    boatOnline:  true,   // optimistic default so UI shows "Online" initially
    missionId:   "–",
    lastSeen:    null,
    status:      "online",
    lastSeenAgo: 0,
  });

  const lastTsRef  = useRef(null);
  const timerRef   = useRef(null);

  // ── Poll lastSeenAgo every second ───────────────────────────────────────
  useEffect(() => {
    timerRef.current = setInterval(() => {
      if (!lastTsRef.current) return;
      const ago = Math.floor((Date.now() - lastTsRef.current) / 1000);
      const online = ago < HEARTBEAT_TIMEOUT_S;
      setHeartbeat(prev => ({
        ...prev,
        lastSeenAgo: ago,
        boatOnline:  online,
        status:      online ? "online" : "offline",
      }));
    }, 1000);
    return () => clearInterval(timerRef.current);
  }, []);

  // ── Firestore listener ───────────────────────────────────────────────────
  useEffect(() => {
    if (!useFirebase) return;

    let unsubscribe;
    try {
      const docRef = doc(db, COLLECTIONS.HEARTBEAT, "boat");
      unsubscribe  = onSnapshot(
        docRef,
        (snap) => {
          if (!snap.exists()) return;
          const data = snap.data();
          const ts   = data.timestamp ? data.timestamp * 1000 : Date.now();
          lastTsRef.current = ts;
          setHeartbeat({
            boatOnline:  true,
            missionId:   data.mission_id ?? "–",
            lastSeen:    new Date(ts),
            status:      "online",
            lastSeenAgo: 0,
          });
        },
        (err) => {
          console.warn("[useHeartbeat] Firestore error:", err.message);
        }
      );
    } catch (err) {
      console.warn("[useHeartbeat] Firebase not configured:", err.message);
    }

    return () => unsubscribe?.();
  }, [useFirebase]);

  return heartbeat;
}
