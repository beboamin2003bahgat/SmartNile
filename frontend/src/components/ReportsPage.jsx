// src/components/ReportsPage.jsx
// ==============================
// Displays all mission reports written by backend/managers/report_manager.py.
// Each report card shows: generated time, sensor statistics, GPS summary,
// alert counts, detection counts, and a download button for the JSON export.
//
// Plugs into the existing pageMap as key "reports".

import { useState } from "react";
import { useReports } from "../hooks/useReports";

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

function fmtDate(isoStr) {
  if (!isoStr) return "–";
  try {
    return new Date(isoStr).toLocaleString("en-US", {
      year: "numeric", month: "short", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hour12: false,
    });
  } catch {
    return isoStr;
  }
}

function StatRow({ label, value, unit = "", color = COLORS.text }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", padding: "4px 0", borderBottom: `1px solid ${COLORS.border}`, fontSize: 12 }}>
      <span style={{ color: COLORS.textMuted }}>{label}</span>
      <span style={{ fontWeight: 600, color }}>{value ?? "–"}{unit ? " " + unit : ""}</span>
    </div>
  );
}

function SensorStatsCard({ sensorStats }) {
  if (!sensorStats) return null;
  const sensors = [
    { key: "pH",          label: "pH",          unit: "pH",  color: COLORS.nileMid  },
    { key: "tds",         label: "TDS",         unit: "ppm", color: "#7c3aed"       },
    { key: "turbidity",   label: "Turbidity",   unit: "NTU", color: COLORS.turquoise },
    { key: "temperature", label: "Temperature", unit: "°C",  color: COLORS.warning  },
    { key: "ammonia",     label: "Ammonia",     unit: "ppm", color: COLORS.critical },
  ];

  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 8, marginTop: 12 }}>
      {sensors.map(s => {
        const st = sensorStats[s.key];
        if (!st || st.samples === 0) return null;
        return (
          <div key={s.key} style={{ background: COLORS.surface, borderRadius: 8, padding: "10px 12px" }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: s.color, marginBottom: 5 }}>{s.label}</div>
            <div style={{ fontSize: 11, color: COLORS.textMuted, lineHeight: 1.8 }}>
              <div>Mean: <b style={{ color: COLORS.text }}>{st.mean ?? "–"} {s.unit}</b></div>
              <div>Min: {st.min ?? "–"} / Max: {st.max ?? "–"}</div>
              <div>Samples: {st.samples ?? 0}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ReportCard({ report, expanded, onToggle }) {
  const gps  = report.gps_summary         ?? {};
  const alrt = report.alerts_summary      ?? {};
  const det  = report.detections_summary  ?? {};

  function downloadJSON() {
    const json = JSON.stringify(report, null, 2);
    const blob = new Blob([json], { type: "application/json" });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    a.href     = url;
    a.download = `smartnile_report_${report.mission_id}_${(report.generated_at ?? "").slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div style={{ background: COLORS.card, border: `1px solid ${COLORS.border}`, borderRadius: 14, overflow: "hidden" }}>
      {/* Header row */}
      <div
        onClick={onToggle}
        style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "14px 16px", cursor: "pointer", userSelect: "none" }}
      >
        <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
          <span style={{ fontSize: 20 }}>📋</span>
          <div>
            <div style={{ fontSize: 13, fontWeight: 600, color: COLORS.text }}>
              Mission: <span style={{ color: COLORS.nileMid }}>{report.mission_id}</span>
            </div>
            <div style={{ fontSize: 11, color: COLORS.textMuted, marginTop: 2 }}>
              Generated: {fmtDate(report.generated_at)} · {report.period_hours ?? 24}h period
            </div>
          </div>
        </div>
        <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
          {/* Summary pills */}
          {alrt.critical > 0 && (
            <span style={{ fontSize: 11, background: "#fee2e2", color: COLORS.critical, padding: "3px 8px", borderRadius: 5, fontWeight: 600 }}>
              🚨 {alrt.critical} critical
            </span>
          )}
          <span style={{ fontSize: 11, background: "#dcfce7", color: COLORS.success, padding: "3px 8px", borderRadius: 5, fontWeight: 600 }}>
            🌿 {det.total ?? 0} detections
          </span>
          <span style={{ fontSize: 18, color: COLORS.textMuted }}>{expanded ? "▾" : "▸"}</span>
        </div>
      </div>

      {/* Expanded body */}
      {expanded && (
        <div style={{ borderTop: `1px solid ${COLORS.border}`, padding: "14px 16px" }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16 }}>

            {/* GPS summary */}
            <div>
              <div style={{ fontSize: 12, fontWeight: 600, color: COLORS.text, marginBottom: 8 }}>🗺️ GPS Summary</div>
              <StatRow label="Total fixes"    value={gps.total_fixes}  />
              <StatRow label="Valid fixes"    value={gps.valid_fixes}  />
              <StatRow label="Distance"       value={gps.distance_km}  unit="km" color={COLORS.nileMid} />
              {gps.start && <StatRow label="Start lat/lon" value={`${gps.start.lat?.toFixed(4)}, ${gps.start.lon?.toFixed(4)}`} />}
            </div>

            {/* Alert summary */}
            <div>
              <div style={{ fontSize: 12, fontWeight: 600, color: COLORS.text, marginBottom: 8 }}>🚨 Alert Summary</div>
              <StatRow label="Total alerts" value={alrt.total}    />
              <StatRow label="Critical"     value={alrt.critical} color={COLORS.critical} />
              <StatRow label="Warning"      value={alrt.warning}  color={COLORS.warning}  />
              <StatRow label="Info"         value={alrt.info}     color={COLORS.nileMid}  />
            </div>

            {/* Detection summary */}
            <div>
              <div style={{ fontSize: 12, fontWeight: 600, color: COLORS.text, marginBottom: 8 }}>🌿 Detection Summary</div>
              <StatRow label="Total"          value={det.total}          />
              <StatRow label="Water Hyacinth" value={det.water_hyacinth} color={COLORS.success} />
              <StatRow label="Water Lettuce"  value={det.water_lettuce}  color="#7c3aed" />
              <StatRow label="Algae Bloom"    value={det.algae_bloom}    color={COLORS.warning} />
            </div>
          </div>

          {/* Sensor stats */}
          <div style={{ fontSize: 12, fontWeight: 600, color: COLORS.text, marginTop: 16, marginBottom: 4 }}>📡 Sensor Statistics</div>
          <SensorStatsCard sensorStats={report.sensor_stats} />

          {/* Download */}
          <div style={{ marginTop: 14, display: "flex", gap: 10 }}>
            <button onClick={downloadJSON}
              style={{ padding: "7px 16px", borderRadius: 8, border: `1px solid ${COLORS.nileMid}`, background: "white", color: COLORS.nileMid, fontSize: 12, fontWeight: 500, cursor: "pointer" }}>
              ⬇ Download JSON Report
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default function ReportsPage({ useFirebase = true }) {
  const { reports, loading, isLive } = useReports(useFirebase, 20);
  const [expanded, setExpanded]      = useState(null);

  function toggle(id) {
    setExpanded(prev => prev === id ? null : id);
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

      {/* Status header */}
      <div style={{ background: COLORS.card, border: `1px solid ${COLORS.border}`, borderRadius: 14, padding: "1rem 1.25rem", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: COLORS.text }}>Mission Reports</div>
          <div style={{ fontSize: 11, color: COLORS.textMuted, marginTop: 2 }}>
            Auto-generated every 24 hours by the Raspberry Pi 5 backend. Click a report to expand.
          </div>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <span style={{ fontSize: 11, background: isLive ? "#dcfce7" : COLORS.surface, color: isLive ? COLORS.success : COLORS.textMuted, padding: "3px 10px", borderRadius: 5, fontWeight: 600 }}>
            {isLive ? "● Firebase live" : "○ Awaiting connection"}
          </span>
          <span style={{ fontSize: 13, color: COLORS.textMuted }}>{reports.length} report{reports.length !== 1 ? "s" : ""}</span>
        </div>
      </div>

      {/* Loading */}
      {loading && (
        <div style={{ textAlign: "center", padding: "40px 0", color: COLORS.textMuted }}>
          Loading reports…
        </div>
      )}

      {/* No reports */}
      {!loading && reports.length === 0 && (
        <div style={{ background: COLORS.card, border: `1px solid ${COLORS.border}`, borderRadius: 14, padding: "40px", textAlign: "center" }}>
          <div style={{ fontSize: 32, marginBottom: 12 }}>📋</div>
          <div style={{ fontSize: 14, fontWeight: 600, color: COLORS.text }}>No reports yet</div>
          <div style={{ fontSize: 12, color: COLORS.textMuted, marginTop: 6 }}>
            Reports are generated automatically every 24 h when the backend is running,<br />
            or immediately when a mission ends. Start the backend to generate the first report.
          </div>
        </div>
      )}

      {/* Report cards */}
      {reports.map(r => (
        <ReportCard
          key={r.id}
          report={r}
          expanded={expanded === r.id}
          onToggle={() => toggle(r.id)}
        />
      ))}
    </div>
  );
}
