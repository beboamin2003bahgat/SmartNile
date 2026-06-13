// src/hooks/useSystemStats.js
// ===========================
// Reads system health metrics from the heartbeat/boat Firestore document.
// The Python SystemMonitor appends cpu_pct, ram_pct, cpu_temp_c, battery_pct,
// uptime_s, ram_used_mb, ram_total_mb into the heartbeat extra fields.
//
// OUTPUT:
//   {
//     cpuPct:      34.2,
//     ramPct:      26.1,
//     ramUsedMb:   2150,
//     ramTotalMb:  8192,
//     cpuTempC:    52.4,
//     batteryPct:  87,
//     uptimeS:     11520,
//     uptimeLabel: "3h 12m",
//     diskPct:     18.3,
//     ready:       true,    // false while waiting for first document
//   }
//
// Falls back to static demo values when Firebase is unavailable so
// BoatPage always renders correctly.

import { useState, useEffect } from "react";
import { db, onSnapshot, doc } from "../services/firebase";
import { COLLECTIONS }    from "../config/firestore";

function formatUptime(seconds) {
  if (!seconds) return "–";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

const DEMO = {
  cpuPct:      34,
  ramPct:      26,
  ramUsedMb:   2150,
  ramTotalMb:  8192,
  cpuTempC:    51.2,
  batteryPct:  87,
  uptimeS:     11520,
  uptimeLabel: "3h 12m",
  diskPct:     18,
  ready:       false,
};

export function useSystemStats(useFirebase = true) {
  const [stats, setStats] = useState(DEMO);

  useEffect(() => {
    if (!useFirebase) return;

    let unsubscribe;
    try {
      const docRef = doc(db, COLLECTIONS.HEARTBEAT, "boat");
      unsubscribe  = onSnapshot(
        docRef,
        (snap) => {
          if (!snap.exists()) return;
          const d = snap.data();
          setStats({
            cpuPct:      d.cpu_pct      ?? DEMO.cpuPct,
            ramPct:      d.ram_pct      ?? DEMO.ramPct,
            ramUsedMb:   d.ram_used_mb  ?? DEMO.ramUsedMb,
            ramTotalMb:  d.ram_total_mb ?? DEMO.ramTotalMb,
            cpuTempC:    d.cpu_temp_c   ?? DEMO.cpuTempC,
            batteryPct:  d.battery_pct  ?? DEMO.batteryPct,
            uptimeS:     d.uptime_s     ?? DEMO.uptimeS,
            uptimeLabel: formatUptime(d.uptime_s ?? DEMO.uptimeS),
            diskPct:     d.disk_pct     ?? DEMO.diskPct,
            ready:       true,
          });
        },
        (err) => {
          console.warn("[useSystemStats] Firestore error:", err.message);
        }
      );
    } catch (err) {
      console.warn("[useSystemStats] Firebase not configured:", err.message);
    }

    return () => unsubscribe?.();
  }, [useFirebase]);

  return stats;
}
