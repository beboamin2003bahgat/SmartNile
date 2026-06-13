// src/components/HistoryPage.jsx
// ==============================
// Historical sensor data page.
// Plugs into the existing pageMap as key "history".
//
// Features
// --------
// - Date range picker (last 1h / 6h / 24h / 7d / custom)
// - Per-sensor toggle filter (show/hide individual sensors)
// - Paginated readings table sorted newest-first
// - Per-sensor statistics: min, max, mean, sample count
// - Export CSV and JSON buttons
// - Graceful "no data" states for empty results

import { useState, useMemo } from "react";
import { useHistoricalSensors } from "../hooks/useHistoricalSensors";

const COLORS = {
  nileBlue:  "#0a4d7c",
  nileMid:   "#1a6fa3",
  turquoise: "#0eb8a4",
  success:   "#16a34a",
  warning:   "#d97706",
  critical:  "#dc2626",
  surface:   "#f0f6fb",
  card:      "#ffffff",
  text:      "#0f2236",
  textMuted: "#4a6a85",
  border:    "#c8dcea",
  gold:      "#d4a017",
};

// ── Range presets ─────────────────────────────────────────────────────────────
const PRESETS = [
  { label: "Last 1h",  hours: 1  },
  { label: "Last 6h",  hours: 6  },
  { label: "Last 24h", hours: 24 },
  { label: "Last 7d",  hours: 168 },
];

const SENSOR_COLS = [
  { key: "pH",          label: "pH",          unit: "pH",  color: COLORS.nileMid  },
  { key: "tds",         label: "TDS",         unit: "ppm", color: "#7c3aed"       },
  { key: "turbidity",   label: "Turbidity",   unit: "NTU", color: COLORS.turquoise },
  { key: "temperature", label: "Temperature", unit: "°C",  color: COLORS.warning  },
  { key: "ammonia",     label: "Ammonia",     unit: "ppm", color: COLORS.critical },
];

const PAGE_SIZE = 50;

export default function HistoryPage({ useFirebase = true }) {
  const [presetHours, setPresetHours] = useState(24);
  const [activeSensors, setActiveSensors] = useState(
    Object.fromEntries(SENSOR_COLS.map(s => [s.key, true]))
  );
  const [page, setPage] = useState(0);

  const startDate = useMemo(
    () => new Date(Date.now() - presetHours * 3600 * 1000),
    [presetHours]
  );

  const { readings, loading, error, stats, exportCSV, exportJSON } =
    useHistoricalSensors({ useFirebase, startDate });

  // Sort newest-first for table display
  const sorted = useMemo(
    () => [...readings].sort((a, b) => (b.timestamp ?? 0) - (a.timestamp ?? 0)),
    [readings]
  );

  const totalPages = Math.ceil(sorted.length / PAGE_SIZE);
  const pageRows   = sorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  function toggleSensor(key) {
    setActiveSensors(prev => ({ ...prev, [key]: !prev[key] }));
    setPage(0);
  }

  function fmtTime(ts) {
    if (!ts) return "–";
    return new Date(ts * 1000).toLocaleString("en-US", {
      month: "short", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
    });
  }

  function fmtVal(val, decimals = 3) {
    return val != null ? val.toFixed(decimals) : "–";
  }

  const visibleCols = SENSOR_COLS.filter(s => activeSensors[s.key]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

      {/* ── Controls ─────────────────────────────────────────────────────── */}
      <div style={{ background: COLORS.card, border: `1px solid ${COLORS.border}`, borderRadius: 14, padding: "1rem 1.25rem" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>

          {/* Range presets */}
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <span style={{ fontSize: 12, color: COLORS.textMuted, marginRight: 4 }}>Range:</span>
            {PRESETS.map(p => (
              <button key={p.hours} onClick={() => { setPresetHours(p.hours); setPage(0); }}
                style={{ padding: "5px 12px", borderRadius: 6, fontSize: 12, cursor: "pointer", border: `1px solid ${presetHours === p.hours ? COLORS.nileMid : COLORS.border}`, background: presetHours === p.hours ? COLORS.nileMid : COLORS.surface, color: presetHours === p.hours ? "white" : COLORS.textMuted, fontWeight: presetHours === p.hours ? 600 : 400 }}>
                {p.label}
              </button>
            ))}
          </div>

          {/* Export buttons */}
          <div style={{ display: "flex", gap: 8 }}>
            <button onClick={exportCSV} disabled={!readings.length}
              style={{ padding: "5px 14px", borderRadius: 6, fontSize: 12, cursor: readings.length ? "pointer" : "not-allowed", border: `1px solid ${COLORS.success}`, background: "white", color: COLORS.success, fontWeight: 500, opacity: readings.length ? 1 : 0.5 }}>
              ⬇ Export CSV
            </button>
            <button onClick={exportJSON} disabled={!readings.length}
              style={{ padding: "5px 14px", borderRadius: 6, fontSize: 12, cursor: readings.length ? "pointer" : "not-allowed", border: `1px solid ${COLORS.nileMid}`, background: "white", color: COLORS.nileMid, fontWeight: 500, opacity: readings.length ? 1 : 0.5 }}>
              ⬇ Export JSON
            </button>
          </div>
        </div>

        {/* Sensor toggles */}
        <div style={{ display: "flex", gap: 6, marginTop: 12, flexWrap: "wrap" }}>
          <span style={{ fontSize: 12, color: COLORS.textMuted, alignSelf: "center" }}>Sensors:</span>
          {SENSOR_COLS.map(s => (
            <button key={s.key} onClick={() => toggleSensor(s.key)}
              style={{ padding: "4px 10px", borderRadius: 6, fontSize: 12, cursor: "pointer", border: `1px solid ${activeSensors[s.key] ? s.color : COLORS.border}`, background: activeSensors[s.key] ? s.color + "18" : COLORS.surface, color: activeSensors[s.key] ? s.color : COLORS.textMuted, fontWeight: activeSensors[s.key] ? 600 : 400 }}>
              {s.label}
            </button>
          ))}
        </div>
      </div>

      {/* ── Stats cards ───────────────────────────────────────────────────── */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 10 }}>
        {SENSOR_COLS.map(s => {
          const st = stats[s.key];
          return (
            <div key={s.key} style={{ background: COLORS.card, border: `1px solid ${COLORS.border}`, borderRadius: 12, padding: "12px 14px" }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: s.color, marginBottom: 6 }}>{s.label}</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: 11 }}>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: COLORS.textMuted }}>Mean</span>
                  <span style={{ fontWeight: 600, color: COLORS.text }}>{fmtVal(st?.mean)} {s.unit}</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: COLORS.textMuted }}>Min</span>
                  <span style={{ color: COLORS.text }}>{fmtVal(st?.min)}</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: COLORS.textMuted }}>Max</span>
                  <span style={{ color: COLORS.text }}>{fmtVal(st?.max)}</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: COLORS.textMuted }}>Samples</span>
                  <span style={{ color: COLORS.text }}>{st?.count ?? 0}</span>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* ── Data table ────────────────────────────────────────────────────── */}
      <div style={{ background: COLORS.card, border: `1px solid ${COLORS.border}`, borderRadius: 14, padding: "1rem 1.25rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: COLORS.text }}>
            Sensor Readings
            {!loading && <span style={{ fontSize: 11, color: COLORS.textMuted, fontWeight: 400, marginLeft: 8 }}>({readings.length.toLocaleString()} rows in range)</span>}
          </div>
          {totalPages > 1 && (
            <div style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 12 }}>
              <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0}
                style={{ padding: "3px 10px", borderRadius: 5, border: `1px solid ${COLORS.border}`, background: COLORS.surface, cursor: "pointer", opacity: page === 0 ? 0.4 : 1 }}>
                ‹
              </button>
              <span style={{ color: COLORS.textMuted }}>Page {page + 1} / {totalPages}</span>
              <button onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))} disabled={page === totalPages - 1}
                style={{ padding: "3px 10px", borderRadius: 5, border: `1px solid ${COLORS.border}`, background: COLORS.surface, cursor: "pointer", opacity: page === totalPages - 1 ? 0.4 : 1 }}>
                ›
              </button>
            </div>
          )}
        </div>

        {loading && (
          <div style={{ textAlign: "center", padding: "32px 0", color: COLORS.textMuted, fontSize: 13 }}>
            Loading historical data…
          </div>
        )}

        {error && (
          <div style={{ textAlign: "center", padding: "24px 0", color: COLORS.critical, fontSize: 13 }}>
            ⚠ {error}
            <div style={{ fontSize: 11, color: COLORS.textMuted, marginTop: 6 }}>
              Ensure a Firestore composite index exists on (timestamp ASC).
            </div>
          </div>
        )}

        {!loading && !error && readings.length === 0 && (
          <div style={{ textAlign: "center", padding: "32px 0", color: COLORS.textMuted, fontSize: 13 }}>
            No readings found in the selected time range.
            <div style={{ fontSize: 11, marginTop: 4 }}>The backend must be running and writing to Firebase.</div>
          </div>
        )}

        {!loading && pageRows.length > 0 && (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr style={{ background: COLORS.surface }}>
                  <th style={{ padding: "8px 12px", textAlign: "left", fontWeight: 600, color: COLORS.textMuted, borderBottom: `1px solid ${COLORS.border}`, whiteSpace: "nowrap" }}>Timestamp</th>
                  {visibleCols.map(s => (
                    <th key={s.key} style={{ padding: "8px 12px", textAlign: "right", fontWeight: 600, color: s.color, borderBottom: `1px solid ${COLORS.border}` }}>
                      {s.label} <span style={{ color: COLORS.textMuted, fontWeight: 400 }}>({s.unit})</span>
                    </th>
                  ))}
                  <th style={{ padding: "8px 12px", textAlign: "left", fontWeight: 600, color: COLORS.textMuted, borderBottom: `1px solid ${COLORS.border}` }}>Source</th>
                </tr>
              </thead>
              <tbody>
                {pageRows.map((r, i) => (
                  <tr key={r.id ?? i} style={{ borderBottom: `1px solid ${COLORS.border}`, background: i % 2 === 0 ? "white" : COLORS.surface }}>
                    <td style={{ padding: "8px 12px", color: COLORS.textMuted, whiteSpace: "nowrap" }}>{fmtTime(r.timestamp)}</td>
                    {visibleCols.map(s => (
                      <td key={s.key} style={{ padding: "8px 12px", textAlign: "right", color: r[s.key] != null ? COLORS.text : COLORS.border }}>
                        {fmtVal(r[s.key])}
                      </td>
                    ))}
                    <td style={{ padding: "8px 12px", color: COLORS.textMuted, fontSize: 11 }}>
                      <span style={{ background: r.source === "sensor" ? "#dcfce7" : "#f0f6fb", color: r.source === "sensor" ? COLORS.success : COLORS.textMuted, padding: "2px 7px", borderRadius: 5 }}>
                        {r.source ?? "–"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
