// SmartNileDashboard.jsx  — Firebase-connected edition
// ======================================================
// WHAT CHANGED vs the original:
//   1. Top-level state (sensors, gps, DETECTIONS, ALERTS) now comes from
//      Firebase hooks instead of setInterval simulation.
//   2. The simulation setInterval is removed from the main component —
//      each hook handles its own fallback internally.
//   3. StatusBar "Cloud" cell shows live Firebase sync status.
//   4. StatusBar "Boat" cell shows heartbeat-driven online/offline.
//   5. DetectionPage and MapPage use live detections array.
//   6. AlertsPage uses live alerts array.
//   7. Everything else — layout, colours, components, nav — is unchanged.

import { useState, useEffect, useRef } from "react";
import { useSensors }            from "./hooks/useSensors";
import { useGPS }                from "./hooks/useGPS";
import { useDetections }         from "./hooks/useDetections";
import { useAlerts }             from "./hooks/useAlerts";
import { useHeartbeat }          from "./hooks/useHeartbeat";
import { useReports }            from "./hooks/useReports";
import { useSystemStats }        from "./hooks/useSystemStats";
import HistoryPage               from "./components/HistoryPage";
import ReportsPage               from "./components/ReportsPage";
import DetectionDetail           from "./components/DetectionDetail";

// ── Set to false to force simulation (no Firebase calls) ─────────────────────
const USE_FIREBASE = true;

const COLORS = {
  nileBlue:    "#0a4d7c",
  nileMid:     "#1a6fa3",
  nileLight:   "#2e8bc0",
  turquoise:   "#0eb8a4",
  turquoiseLt: "#4dd9c8",
  gold:        "#d4a017",
  goldLt:      "#f0c040",
  success:     "#16a34a",
  successLt:   "#4ade80",
  warning:     "#d97706",
  warningLt:   "#fbbf24",
  critical:    "#dc2626",
  criticalLt:  "#f87171",
  surface:     "#f0f6fb",
  card:        "#ffffff",
  text:        "#0f2236",
  textMuted:   "#4a6a85",
  border:      "#c8dcea",
};

// ── Helpers ──────────────────────────────────────────────────────────────────
function getSensorStatus(value, sensor) {
  if (value == null) return "offline";
  if (value >= sensor.optimal[0] && value <= sensor.optimal[1]) return "optimal";
  if (value >= sensor.warning[0] && value <= sensor.warning[1]) return "warning";
  return "critical";
}

// ── Mini sparkline ────────────────────────────────────────────────────────────
function Sparkline({ data, color = COLORS.nileLight, height = 40 }) {
  if (!data || data.length < 2) return null;
  const min = Math.min(...data), max = Math.max(...data);
  const range = max - min || 1;
  const w = 120, h = height;
  const pts = data.map((v, i) => `${(i / (data.length - 1)) * w},${h - ((v - min) / range) * h}`).join(" ");
  return (
    <svg width={w} height={h} style={{ display: "block" }}>
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  );
}

// ── Circular gauge ────────────────────────────────────────────────────────────
function CircleGauge({ value, min = 0, max = 14, color = COLORS.nileLight, size = 80 }) {
  const r = size * 0.38, cx = size / 2, cy = size / 2;
  const pct = Math.min(1, Math.max(0, (value - min) / (max - min)));
  const circ = 2 * Math.PI * r;
  const dash = pct * circ * 0.75;
  const gap = circ;
  const rotation = -225;
  return (
    <svg width={size} height={size}>
      <circle cx={cx} cy={cy} r={r} fill="none" stroke={COLORS.border} strokeWidth={size * 0.1} strokeDasharray={`${circ * 0.75} ${circ}`} strokeLinecap="round" transform={`rotate(${rotation} ${cx} ${cy})`} />
      <circle cx={cx} cy={cy} r={r} fill="none" stroke={color} strokeWidth={size * 0.1} strokeDasharray={`${dash} ${gap}`} strokeLinecap="round" transform={`rotate(${rotation} ${cx} ${cy})`} />
      <text x={cx} y={cy + 4} textAnchor="middle" fontSize={size * 0.2} fontWeight="600" fill={color}>{typeof value === "number" ? value.toFixed(1) : value}</text>
    </svg>
  );
}

// ── Status badge ──────────────────────────────────────────────────────────────
function Badge({ status }) {
  const cfg = {
    optimal:  { bg: "#dcfce7", color: COLORS.success,  label: "Optimal" },
    warning:  { bg: "#fef9c3", color: COLORS.warning,  label: "Warning" },
    critical: { bg: "#fee2e2", color: COLORS.critical, label: "Critical" },
    online:   { bg: "#dbeafe", color: COLORS.nileMid,  label: "Online" },
    offline:  { bg: "#f3f4f6", color: "#6b7280",       label: "Offline" },
  }[status] || { bg: "#f3f4f6", color: "#6b7280", label: status };
  return (
    <span style={{ background: cfg.bg, color: cfg.color, borderRadius: 6, padding: "2px 8px", fontSize: 11, fontWeight: 600, letterSpacing: "0.03em" }}>
      {cfg.label}
    </span>
  );
}

// ── Sensor card ───────────────────────────────────────────────────────────────
function SensorCard({ sensorKey, sensor }) {
  const value = sensor.value ?? sensor.base;
  const status = getSensorStatus(value, sensor);
  const gaugeMax = { ph: 14, tds: 1000, turbidity: 20, temperature: 40, ammonia: 2 }[sensorKey] || 100;
  const statusColor = status === "optimal" ? COLORS.turquoise : status === "warning" ? COLORS.warning : COLORS.critical;

  return (
    <div style={{ background: COLORS.card, border: `1px solid ${COLORS.border}`, borderRadius: 14, padding: "1rem 1.25rem", display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 20 }}>{sensor.icon}</span>
          <span style={{ fontSize: 13, fontWeight: 500, color: COLORS.text }}>{sensor.name}</span>
        </div>
        <Badge status={status} />
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <CircleGauge value={value} min={0} max={gaugeMax} color={statusColor} size={72} />
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 24, fontWeight: 600, color: COLORS.text }}>{value.toFixed(2)} <span style={{ fontSize: 13, color: COLORS.textMuted }}>{sensor.unit}</span></div>
          <div style={{ fontSize: 11, color: COLORS.textMuted, marginTop: 4 }}>
            Optimal: {sensor.optimal[0]}–{sensor.optimal[1]} {sensor.unit}
          </div>
          <div style={{ marginTop: 6 }}>
            <Sparkline data={sensor.history.slice(-20).map(h => h.v)} color={statusColor} />
          </div>
        </div>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: COLORS.textMuted }}>
        <span>Min: {sensor.min?.toFixed(2) ?? "—"} {sensor.unit}</span>
        <span>Max: {sensor.max?.toFixed(2) ?? "—"} {sensor.unit}</span>
        <span>Updated {sensor.lastUpdate ?? "just now"}</span>
      </div>
    </div>
  );
}

// ── Nile map (SVG schematic) ──────────────────────────────────────────────────
function NileMap({ gpsLat, gpsLon, detections }) {
  const boatX = 200 + (gpsLon - 31.2) * 800;
  const boatY = 220 - (gpsLat - 30.02) * 600;

  return (
    <div style={{ background: "#e8f4fb", borderRadius: 12, overflow: "hidden", position: "relative" }}>
      <svg viewBox="0 0 480 320" width="100%" style={{ display: "block" }}>
        <rect width="480" height="320" fill="#e8f4fb" />
        <rect x="0" y="0" width="480" height="320" fill="#f5edd6" />
        <path d="M 200 10 Q 210 80 195 160 Q 185 220 200 300 Q 205 320 210 320" stroke="#2e8bc0" strokeWidth="28" fill="none" strokeLinecap="round" opacity="0.8" />
        <path d="M 200 10 Q 210 80 195 160 Q 185 220 200 300 Q 205 320 210 320" stroke="#4dd9c8" strokeWidth="30" fill="none" strokeLinecap="round" opacity="0.2" />
        <path d="M 200 10 Q 210 80 195 160 Q 185 220 200 300 Q 205 320 210 320" stroke="#86efac" strokeWidth="42" fill="none" strokeLinecap="round" opacity="0.15" />
        <line x1="195" y1="80"  x2="100" y2="80"  stroke="#2e8bc0" strokeWidth="3" opacity="0.4" />
        <line x1="193" y1="130" x2="80"  y2="120" stroke="#2e8bc0" strokeWidth="3" opacity="0.4" />
        <line x1="200" y1="180" x2="310" y2="175" stroke="#2e8bc0" strokeWidth="3" opacity="0.4" />
        <line x1="196" y1="230" x2="90"  y2="240" stroke="#2e8bc0" strokeWidth="3" opacity="0.4" />
        <text x="240" y="175" fontSize="10" fill={COLORS.nileBlue} fontWeight="600" opacity="0.7">Cairo</text>
        <circle cx="228" cy="172" r="4" fill={COLORS.nileBlue} opacity="0.5" />
        <text x="240" y="90" fontSize="9" fill={COLORS.textMuted} opacity="0.8">Zamalek</text>
        {detections.map((d, i) => {
          const mx = 195 + ((d.lon ?? d.longitude ?? 31.235) - 31.235) * 800;
          const my = 172 - ((d.lat ?? d.latitude ?? 30.044) - 30.044) * 600;
          return (
            <g key={d.id}>
              <circle cx={mx} cy={my} r="10" fill={d.type === "Water Hyacinth" ? "#16a34a" : "#7c3aed"} opacity="0.8" />
              <text x={mx} y={my + 4} textAnchor="middle" fontSize="8" fill="white" fontWeight="700">{i + 1}</text>
            </g>
          );
        })}
        <g transform={`translate(${Math.min(250, Math.max(160, boatX))},${Math.min(280, Math.max(30, boatY))})`}>
          <circle r="12" fill={COLORS.nileMid} opacity="0.9" />
          <circle r="12" fill="none" stroke={COLORS.turquoise} strokeWidth="2" opacity="0.6">
            <animate attributeName="r" values="12;20;12" dur="2s" repeatCount="indefinite" />
            <animate attributeName="opacity" values="0.6;0;0.6" dur="2s" repeatCount="indefinite" />
          </circle>
          <text textAnchor="middle" y="4" fontSize="10">🚤</text>
        </g>
        <g transform="translate(320, 20)">
          <rect x="0" y="0" width="150" height="80" rx="6" fill="white" opacity="0.85" />
          <text x="8" y="16" fontSize="9" fontWeight="600" fill={COLORS.text}>Map Legend</text>
          <circle cx="18" cy="30" r="6" fill={COLORS.nileMid} />
          <text x="28" y="34" fontSize="8" fill={COLORS.textMuted}>Boat (live)</text>
          <circle cx="18" cy="48" r="6" fill="#16a34a" />
          <text x="28" y="52" fontSize="8" fill={COLORS.textMuted}>Water Hyacinth</text>
          <circle cx="18" cy="65" r="6" fill="#7c3aed" />
          <text x="28" y="69" fontSize="8" fill={COLORS.textMuted}>Water Lettuce</text>
        </g>
      </svg>
      <div style={{ position: "absolute", bottom: 10, left: 12, background: "rgba(255,255,255,0.9)", borderRadius: 8, padding: "4px 10px", fontSize: 11, color: COLORS.text }}>
        GPS: {gpsLat.toFixed(4)}°N, {gpsLon.toFixed(4)}°E
      </div>
    </div>
  );
}

// ── AI Advisor ─────────────────────────────────────────────────────────────────
function AIAdvisor({ sensors, alerts }) {
  const [messages, setMessages] = useState([
    { role: "assistant", content: "Hello! I'm the Smart Nile AI Advisor. I have live access to all sensor readings and detection events. Ask me about water quality, sensor trends, or environmental conditions." }
  ]);
  const [input, setInput]   = useState("");
  const [loading, setLoading] = useState(false);
  const scrollRef             = useRef(null);

  useEffect(() => { scrollRef.current?.scrollTo({ top: 9999, behavior: "smooth" }); }, [messages]);

  const buildContext = () => {
    const s = sensors;
    return `You are SMART NILE AI ADVISOR integrated into a real-time Nile River monitoring system.\n\nLive Sensor Data:\n- pH: ${s.ph?.value?.toFixed(2)} ${getSensorStatus(s.ph?.value, s.ph)} (optimal 6.5–7.5)\n- TDS: ${s.tds?.value?.toFixed(0)} ppm ${getSensorStatus(s.tds?.value, s.tds)} (optimal <500)\n- Turbidity: ${s.turbidity?.value?.toFixed(1)} NTU ${getSensorStatus(s.turbidity?.value, s.turbidity)} (optimal <5)\n- Temperature: ${s.temperature?.value?.toFixed(1)}°C ${getSensorStatus(s.temperature?.value, s.temperature)} (optimal 20–25°C)\n- Ammonia: ${s.ammonia?.value?.toFixed(3)} ppm ${getSensorStatus(s.ammonia?.value, s.ammonia)} (safe <0.5)\n\nRecent Alerts: ${alerts.map(a => a.message).join("; ")}\n\nAnswer as a water quality expert. Be concise and actionable.`;
  };

  const send = async (text) => {
    if (!text.trim() || loading) return;
    const userMsg = { role: "user", content: text };
    setMessages(prev => [...prev, userMsg]);
    setInput("");
    setLoading(true);
    try {
      const res = await fetch("https://api.anthropic.com/v1/messages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model: "claude-sonnet-4-6",
          max_tokens: 1000,
          system: buildContext(),
          messages: [...messages, userMsg].map(m => ({ role: m.role, content: m.content }))
        })
      });
      const data = await res.json();
      const reply = data.content?.[0]?.text || "Unable to respond at this time.";
      setMessages(prev => [...prev, { role: "assistant", content: reply }]);
    } catch {
      setMessages(prev => [...prev, { role: "assistant", content: "Connection error. Please try again." }]);
    }
    setLoading(false);
  };

  const quickQ = ["Current water quality?", "pH trend analysis", "Ammonia risk level", "Recommend calibration"];

  return (
    <div style={{ display: "flex", flexDirection: "column", height: 480, background: COLORS.card, border: `1px solid ${COLORS.border}`, borderRadius: 14, overflow: "hidden" }}>
      <div style={{ padding: "12px 16px", borderBottom: `1px solid ${COLORS.border}`, background: COLORS.surface, display: "flex", alignItems: "center", gap: 10 }}>
        <div style={{ width: 32, height: 32, borderRadius: "50%", background: `linear-gradient(135deg, ${COLORS.nileMid}, ${COLORS.turquoise})`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16 }}>🤖</div>
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: COLORS.text }}>Smart Nile AI Advisor</div>
          <div style={{ fontSize: 11, color: COLORS.turquoise }}>● Live sensor context enabled</div>
        </div>
      </div>
      <div ref={scrollRef} style={{ flex: 1, overflowY: "auto", padding: 12, display: "flex", flexDirection: "column", gap: 10 }}>
        {messages.map((m, i) => (
          <div key={i} style={{ display: "flex", justifyContent: m.role === "user" ? "flex-end" : "flex-start" }}>
            <div style={{
              maxWidth: "82%", padding: "10px 14px", borderRadius: m.role === "user" ? "14px 14px 4px 14px" : "14px 14px 14px 4px",
              background: m.role === "user" ? COLORS.nileMid : COLORS.surface,
              color: m.role === "user" ? "white" : COLORS.text,
              fontSize: 13, lineHeight: 1.6, border: m.role === "assistant" ? `1px solid ${COLORS.border}` : "none"
            }}>{m.content}</div>
          </div>
        ))}
        {loading && (
          <div style={{ display: "flex" }}>
            <div style={{ background: COLORS.surface, border: `1px solid ${COLORS.border}`, borderRadius: "14px 14px 14px 4px", padding: "10px 14px", fontSize: 13, color: COLORS.textMuted }}>
              Analyzing sensor data…
            </div>
          </div>
        )}
      </div>
      <div style={{ borderTop: `1px solid ${COLORS.border}`, padding: 10 }}>
        <div style={{ display: "flex", gap: 6, marginBottom: 8, flexWrap: "wrap" }}>
          {quickQ.map(q => (
            <button key={q} onClick={() => send(q)} style={{ fontSize: 11, padding: "4px 10px", borderRadius: 6, border: `1px solid ${COLORS.border}`, background: COLORS.surface, color: COLORS.nileMid, cursor: "pointer" }}>{q}</button>
          ))}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <input value={input} onChange={e => setInput(e.target.value)} onKeyDown={e => e.key === "Enter" && send(input)}
            placeholder="Ask about water quality, sensors, or the Nile…"
            style={{ flex: 1, padding: "8px 12px", borderRadius: 8, border: `1px solid ${COLORS.border}`, fontSize: 13, outline: "none" }} />
          <button onClick={() => send(input)} disabled={loading}
            style={{ padding: "8px 16px", borderRadius: 8, background: COLORS.nileMid, color: "white", border: "none", cursor: "pointer", fontSize: 13, fontWeight: 500 }}>
            Send
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Analytics Chart ───────────────────────────────────────────────────────────
function AnalyticsChart({ sensors }) {
  const canvasRef = useRef(null);
  const chartRef  = useRef(null);
  const [selected, setSelected] = useState("ph");

  useEffect(() => {
    if (!canvasRef.current) return;
    const sensor = sensors[selected];
    const hist   = sensor?.history?.slice(-30) || [];
    const labels = hist.map((_, i) => `T-${hist.length - i}`);
    const data   = hist.map(h => h.v);
    const color  = selected === "ph" ? "#1a6fa3" : selected === "temperature" ? "#d97706" : selected === "ammonia" ? "#dc2626" : selected === "tds" ? "#7c3aed" : "#0eb8a4";

    if (chartRef.current) { chartRef.current.destroy(); chartRef.current = null; }
    if (typeof window.Chart === "undefined" || !hist.length) return;
    chartRef.current = new window.Chart(canvasRef.current, {
      type: "line",
      data: { labels, datasets: [{ label: sensor.name, data, borderColor: color, backgroundColor: color + "18", fill: true, tension: 0.4, pointRadius: 2, pointHoverRadius: 5 }] },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { font: { size: 10 }, color: "#4a6a85", maxRotation: 0 }, grid: { color: "#e2ecf4" } },
          y: { ticks: { font: { size: 10 }, color: "#4a6a85" }, grid: { color: "#e2ecf4" } }
        }
      }
    });
  }, [selected, sensors]);

  const tabs = [
    { key: "ph",          label: "pH" },
    { key: "temperature", label: "Temp" },
    { key: "tds",         label: "TDS" },
    { key: "turbidity",   label: "Turbidity" },
    { key: "ammonia",     label: "Ammonia" },
  ];

  return (
    <div style={{ background: COLORS.card, border: `1px solid ${COLORS.border}`, borderRadius: 14, padding: "1rem 1.25rem" }}>
      <div style={{ fontSize: 13, fontWeight: 600, color: COLORS.text, marginBottom: 12 }}>Sensor Trend Analysis</div>
      <div style={{ display: "flex", gap: 6, marginBottom: 12, flexWrap: "wrap" }}>
        {tabs.map(t => (
          <button key={t.key} onClick={() => setSelected(t.key)}
            style={{ padding: "4px 12px", borderRadius: 6, border: `1px solid ${selected === t.key ? COLORS.nileMid : COLORS.border}`, background: selected === t.key ? COLORS.nileMid : COLORS.surface, color: selected === t.key ? "white" : COLORS.textMuted, cursor: "pointer", fontSize: 12 }}>
            {t.label}
          </button>
        ))}
      </div>
      <div style={{ position: "relative", height: 200 }}>
        <canvas ref={canvasRef} role="img" aria-label={`${selected} sensor trend over time`}>Sensor trend data</canvas>
      </div>
    </div>
  );
}

// ── Main App ──────────────────────────────────────────────────────────────────
export default function SmartNileDashboard() {
  const [activePage,   setActivePage]   = useState("dashboard");
  const [time,         setTime]         = useState(new Date());
  const [sidebarOpen,  setSidebarOpen]  = useState(true);

  // ── Live Firebase data ──────────────────────────────────────────────────
  const { sensors, isLive: sensorsLive }         = useSensors(USE_FIREBASE);
  const { gps,     isLive: gpsLive }             = useGPS(USE_FIREBASE);
  const { detections, stats: detStats }          = useDetections(USE_FIREBASE);
  const { alerts } = useAlerts(USE_FIREBASE);  
  const heartbeat                                = useHeartbeat(USE_FIREBASE);
  const { latest: latestReport }                 = useReports(USE_FIREBASE);
  const sysStats                                 = useSystemStats(USE_FIREBASE);

  // ── Detection detail modal state ────────────────────────────────────────
  const [selectedDetection, setSelectedDetection] = useState(null);

  // ── Clock tick ──────────────────────────────────────────────────────────
  useEffect(() => {
    const t = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  // ── Load Chart.js ────────────────────────────────────────────────────────
  useEffect(() => {
    if (typeof window.Chart !== "undefined") return;
    const s = document.createElement("script");
    s.src = "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js";
    document.head.appendChild(s);
  }, []);

  // ── Derived ──────────────────────────────────────────────────────────────
  const overallStatus = Object.keys(sensors).some(k => getSensorStatus(sensors[k].value, sensors[k]) === "critical") ? "critical"
    : Object.keys(sensors).some(k => getSensorStatus(sensors[k].value, sensors[k]) === "warning") ? "warning" : "optimal";

  const envScore = Math.round(Object.keys(sensors).reduce((acc, k) => {
    const s = sensors[k]; const st = getSensorStatus(s.value, s);
    return acc + (st === "optimal" ? 100 : st === "warning" ? 60 : 20);
  }, 0) / Object.keys(sensors).length);

  const navItems = [
    { key: "dashboard",  label: "Command Center",  icon: "🎛️" },
    { key: "sensors",    label: "Sensor Array",    icon: "📡" },
    { key: "detection",  label: "AI Detection",    icon: "🌿" },
    { key: "map",        label: "GPS Tracking",    icon: "🗺️" },
    { key: "analytics",  label: "Analytics",       icon: "📊" },
    { key: "history",    label: "History",         icon: "🕐" },
    { key: "alerts",     label: "Alert Center",    icon: "🚨" },
    { key: "reports",    label: "Reports",         icon: "📋" },
    { key: "advisor",    label: "AI Advisor",      icon: "🤖" },
    { key: "boat",       label: "Boat Operations", icon: "🚤" },
    { key: "roadmap",    label: "Roadmap",         icon: "🛣️" },
  ];

  const statusBg    = overallStatus === "critical" ? "#fee2e2" : overallStatus === "warning" ? "#fef9c3" : "#dcfce7";
  const statusColor = overallStatus === "critical" ? COLORS.critical : overallStatus === "warning" ? COLORS.warning : COLORS.success;

  // ── Header ────────────────────────────────────────────────────────────────
  const Header = () => (
    <div style={{ padding: "12px 20px", background: COLORS.nileBlue, display: "flex", alignItems: "center", justifyContent: "space-between", color: "white" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <button onClick={() => setSidebarOpen(o => !o)} style={{ background: "rgba(255,255,255,0.15)", border: "none", borderRadius: 6, padding: "4px 8px", color: "white", cursor: "pointer", fontSize: 16 }}>☰</button>
        <span style={{ fontSize: 18, fontWeight: 700, letterSpacing: "0.02em" }}>🌊 SMART NILE</span>
        <span style={{ fontSize: 11, opacity: 0.7, fontWeight: 400 }}>AI-Powered Water Monitoring System · Class of 2026</span>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 11, opacity: 0.7 }}>Environmental Score</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: envScore > 70 ? COLORS.turquoiseLt : envScore > 40 ? COLORS.goldLt : COLORS.criticalLt }}>{envScore}/100</div>
        </div>
        <div style={{ fontSize: 11, opacity: 0.7 }}>{time.toLocaleTimeString()}</div>
      </div>
    </div>
  );

  // ── Status Bar — now uses live heartbeat + Firebase sync status ───────────
  const StatusBar = () => (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: 1, background: COLORS.nileBlue, padding: "0 1px 1px" }}>
      {[
        { label: "Boat",    val: heartbeat.boatOnline ? "Online" : "Offline",  icon: "🚤", ok: heartbeat.boatOnline },
        { label: "GPS",     val: `${gps.lat.toFixed(3)}°N`,                    icon: "📍", ok: gpsLive },
        { label: "AI",      val: "Active",                                      icon: "🧠", ok: true },
        { label: "Cloud",   val: sensorsLive ? "Synced" : "Sim",               icon: "☁️", ok: sensorsLive },
        { label: "Battery", val: sysStats.batteryPct != null ? `${sysStats.batteryPct}%` : "87%", icon: "🔋", ok: (sysStats.batteryPct ?? 87) > 20 },
        { label: "Temp",    val: sysStats.cpuTempC   != null ? `${sysStats.cpuTempC}°C` : "–",   icon: "🌡️", ok: (sysStats.cpuTempC ?? 50) < 80 },
        { label: "System",  val: overallStatus.charAt(0).toUpperCase() + overallStatus.slice(1), icon: "💻", ok: overallStatus === "optimal" },
      ].map(item => (
        <div key={item.label} style={{ background: item.ok ? "#0a3a5e" : "#7f1d1d", padding: "6px 10px", textAlign: "center" }}>
          <div style={{ fontSize: 13 }}>{item.icon}</div>
          <div style={{ fontSize: 10, color: "rgba(255,255,255,0.6)", marginTop: 1 }}>{item.label}</div>
          <div style={{ fontSize: 11, color: item.ok ? COLORS.turquoiseLt : COLORS.criticalLt, fontWeight: 600 }}>{item.val}</div>
        </div>
      ))}
    </div>
  );

  // ── Pages ─────────────────────────────────────────────────────────────────
  const DashboardPage = () => (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
        {[
          { label: "Active Sensors",   val: "5 / 5",                            color: COLORS.turquoise, icon: "📡" },
          { label: "AI Detections",    val: `${detStats.total} Events`,          color: COLORS.gold,     icon: "🌿" },
          { label: "Survey Distance",  val: latestReport?.gps_summary?.distance_km ? `${latestReport.gps_summary.distance_km} km` : "4.7 km", color: COLORS.nileMid, icon: "🗺️" },
          { label: "Mission Duration", val: sysStats.uptimeLabel,                  color: COLORS.success,  icon: "⏱️" },
        ].map(card => (
          <div key={card.label} style={{ background: COLORS.card, border: `1px solid ${COLORS.border}`, borderRadius: 12, padding: "14px 16px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
              <span style={{ fontSize: 20 }}>{card.icon}</span>
              <span style={{ fontSize: 11, color: COLORS.textMuted }}>{card.label}</span>
            </div>
            <div style={{ fontSize: 22, fontWeight: 600, color: card.color }}>{card.val}</div>
          </div>
        ))}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          {Object.entries(sensors).slice(0, 4).map(([k, s]) => (
            <SensorCard key={k} sensorKey={k} sensor={s} />
          ))}
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div style={{ background: COLORS.card, border: `1px solid ${COLORS.border}`, borderRadius: 14, padding: "1rem", flex: 1 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: COLORS.text, marginBottom: 10 }}>🗺️ Live GPS — Nile River, Egypt</div>
            <NileMap gpsLat={gps.lat} gpsLon={gps.lon} detections={detections.slice(0, 6)} />
          </div>
          <div style={{ background: COLORS.card, border: `1px solid ${COLORS.border}`, borderRadius: 14, padding: "1rem" }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: COLORS.text, marginBottom: 10 }}>🚨 Recent Alerts</div>
            {alerts.slice(0, 3).map(a => (
              <div key={a.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 0", borderBottom: `1px solid ${COLORS.border}`, fontSize: 12 }}>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <Badge status={a.type === "critical" ? "critical" : a.type === "warning" ? "warning" : "online"} />
                  <span style={{ color: COLORS.text }}>{a.message}</span>
                </div>
                <span style={{ color: COLORS.textMuted, fontSize: 11 }}>{a.time}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );

  const SensorsPage = () => (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ background: statusBg, borderRadius: 12, padding: "12px 16px", display: "flex", alignItems: "center", gap: 12 }}>
        <span style={{ fontSize: 20 }}>{overallStatus === "optimal" ? "✅" : overallStatus === "warning" ? "⚠️" : "🚨"}</span>
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: statusColor }}>Overall System Status: {overallStatus.toUpperCase()}</div>
          <div style={{ fontSize: 11, color: COLORS.textMuted }}>All 5 sensors are active and reporting. Last sync: {time.toLocaleTimeString()}</div>
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 14 }}>
        {Object.entries(sensors).map(([k, s]) => <SensorCard key={k} sensorKey={k} sensor={s} />)}
      </div>
      <div style={{ background: COLORS.card, border: `1px solid ${COLORS.border}`, borderRadius: 14, padding: "1rem 1.25rem" }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: COLORS.text, marginBottom: 12 }}>Pollution Reference Thresholds</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, fontSize: 12 }}>
          {[{ label: "pH < 6.5", note: "Acidic — danger", color: COLORS.critical }, { label: "TDS > 1000 ppm", note: "Heavy contamination", color: COLORS.critical }, { label: "NH₃ > 0.5 ppm", note: "Toxic to fish", color: COLORS.critical }, { label: "Turbidity > 100 NTU", note: "Severely cloudy", color: COLORS.warning }].map(t => (
            <div key={t.label} style={{ background: "#fff5f5", border: `1px solid ${t.color}30`, borderRadius: 8, padding: "10px 12px" }}>
              <div style={{ color: t.color, fontWeight: 600 }}>{t.label}</div>
              <div style={{ color: COLORS.textMuted, marginTop: 3 }}>{t.note}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );

  const DetectionPage = () => (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
        {[
          { label: "Total Detections", val: detStats.total,           icon: "🌿" },
          { label: "Water Hyacinth",   val: detStats.waterHyacinth,   icon: "🌱" },
          { label: "Avg Confidence",   val: detStats.avgConfidence + "%", icon: "🎯" },
        ].map(m => (
          <div key={m.label} style={{ background: COLORS.card, border: `1px solid ${COLORS.border}`, borderRadius: 12, padding: "14px 16px" }}>
            <span style={{ fontSize: 22 }}>{m.icon}</span>
            <div style={{ fontSize: 22, fontWeight: 600, color: COLORS.nileBlue, marginTop: 6 }}>{m.val}</div>
            <div style={{ fontSize: 12, color: COLORS.textMuted }}>{m.label}</div>
          </div>
        ))}
      </div>
      <div style={{ background: COLORS.card, border: `1px solid ${COLORS.border}`, borderRadius: 14, padding: "1rem 1.25rem" }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: COLORS.text, marginBottom: 14 }}>Detection History — AI Computer Vision (TFLite on Raspberry Pi 5)</div>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr style={{ background: COLORS.surface }}>
              {["#", "Plant Type", "Confidence", "Latitude", "Longitude", "Time", "Status"].map(h => (
                <th key={h} style={{ padding: "8px 12px", textAlign: "left", fontWeight: 600, color: COLORS.textMuted, borderBottom: `1px solid ${COLORS.border}` }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {detections.map((d, i) => (
              <tr key={d.id}
                onClick={() => setSelectedDetection(d)}
                style={{ borderBottom: `1px solid ${COLORS.border}`, cursor: "pointer" }}
                onMouseEnter={e => e.currentTarget.style.background = COLORS.surface}
                onMouseLeave={e => e.currentTarget.style.background = ""}
              >
                <td style={{ padding: "10px 12px", color: COLORS.textMuted }}>{i + 1}</td>
                <td style={{ padding: "10px 12px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <div style={{ width: 10, height: 10, borderRadius: "50%", background: d.type === "Water Hyacinth" ? "#16a34a" : "#7c3aed" }} />
                    <span style={{ color: COLORS.text, fontWeight: 500 }}>{d.type}</span>
                  </div>
                </td>
                <td style={{ padding: "10px 12px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <div style={{ height: 6, width: Math.round(d.confidence), background: d.confidence > 90 ? COLORS.success : COLORS.warning, borderRadius: 3 }} />
                    <span style={{ color: COLORS.text }}>{d.confidence}%</span>
                  </div>
                </td>
                <td style={{ padding: "10px 12px", color: COLORS.textMuted }}>{d.lat ?? "–"}</td>
                <td style={{ padding: "10px 12px", color: COLORS.textMuted }}>{d.lon ?? "–"}</td>
                <td style={{ padding: "10px 12px", color: COLORS.textMuted }}>{d.time}</td>
                <td style={{ padding: "10px 12px" }}><Badge status={d.status === "Confirmed" ? "optimal" : "warning"} /></td>
              </tr>
            ))}
          </tbody>
        </table>
        <div style={{ fontSize: 11, color: COLORS.textMuted, marginTop: 8, textAlign: "right" }}>Click any row for detection details</div>
      </div>
      {/* Detection detail modal */}
      <DetectionDetail detection={selectedDetection} onClose={() => setSelectedDetection(null)} />
      <div style={{ background: COLORS.card, border: `1px solid ${COLORS.border}`, borderRadius: 14, padding: "1rem 1.25rem" }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: COLORS.text, marginBottom: 10 }}>AI Model Performance Metrics</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
          {[{ label: "Detection Precision", val: "92%", note: "Real Nile conditions" }, { label: "Inference Speed", val: "~55ms", note: "Per frame on Pi 5" }, { label: "Cloud Sync Latency", val: "< 1 sec", note: "Firebase realtime DB" }, { label: "Training Images", val: "1,800+", note: "Annotated Nile dataset" }].map(m => (
            <div key={m.label} style={{ background: COLORS.surface, borderRadius: 10, padding: "12px 14px" }}>
              <div style={{ fontSize: 20, fontWeight: 600, color: COLORS.nileBlue }}>{m.val}</div>
              <div style={{ fontSize: 12, fontWeight: 500, color: COLORS.text, marginTop: 4 }}>{m.label}</div>
              <div style={{ fontSize: 11, color: COLORS.textMuted }}>{m.note}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );

  const MapPage = () => (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 16 }}>
        <div style={{ background: COLORS.card, border: `1px solid ${COLORS.border}`, borderRadius: 14, padding: "1rem" }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: COLORS.text, marginBottom: 12 }}>Live GPS Tracking — Nile River, Egypt</div>
          <div style={{ marginBottom: 10, display: "flex", gap: 16, fontSize: 12 }}>
            {[
              { label: "Latitude",    val: gps.lat.toFixed(4) + "°N" },
              { label: "Longitude",   val: gps.lon.toFixed(4) + "°E" },
              { label: "GPS Accuracy", val: "≈ 2.5m" },
              { label: "Satellites",  val: gps.satellites ?? "–" },
            ].map(info => (
              <div key={info.label}>
                <span style={{ color: COLORS.textMuted }}>{info.label}: </span>
                <span style={{ fontWeight: 600, color: COLORS.nileBlue }}>{info.val}</span>
              </div>
            ))}
          </div>
          <NileMap gpsLat={gps.lat} gpsLon={gps.lon} detections={detections} />
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div style={{ background: COLORS.card, border: `1px solid ${COLORS.border}`, borderRadius: 14, padding: "1rem" }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: COLORS.text, marginBottom: 12 }}>GPS Module — NEO-6M</div>
            {[
              { label: "Protocol",    val: "UART / NMEA 0183" },
              { label: "Accuracy",    val: "≈ 2.5m open sky" },
              { label: "Speed",       val: gps.speed ? `${gps.speed.toFixed(1)} km/h` : "–" },
              { label: "Fix Quality", val: gps.fix_quality > 0 ? "Active" : "No fix" },
            ].map(info => (
              <div key={info.label} style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", borderBottom: `1px solid ${COLORS.border}`, fontSize: 12 }}>
                <span style={{ color: COLORS.textMuted }}>{info.label}</span>
                <span style={{ fontWeight: 500, color: COLORS.text }}>{info.val}</span>
              </div>
            ))}
          </div>
          <div style={{ background: COLORS.card, border: `1px solid ${COLORS.border}`, borderRadius: 14, padding: "1rem" }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: COLORS.text, marginBottom: 10 }}>Detection Map Markers</div>
            {detections.slice(0, 8).map((d, i) => (
              <div key={d.id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 0", borderBottom: `1px solid ${COLORS.border}`, fontSize: 12 }}>
                <div style={{ width: 16, height: 16, borderRadius: "50%", background: d.type === "Water Hyacinth" ? "#16a34a" : "#7c3aed", display: "flex", alignItems: "center", justifyContent: "center", color: "white", fontSize: 9, fontWeight: 700 }}>{i + 1}</div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 500, color: COLORS.text }}>{d.type}</div>
                  <div style={{ color: COLORS.textMuted }}>{d.lat ?? "–"}, {d.lon ?? "–"}</div>
                </div>
                <span style={{ color: COLORS.textMuted }}>{d.time}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );

  const AnalyticsPage = () => (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <AnalyticsChart sensors={sensors} />
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 14 }}>
        {[
          { label: "pH Status",    sensor: sensors.ph,          icon: "🧪" },
          { label: "Temperature",  sensor: sensors.temperature, icon: "🌡️" },
          { label: "Ammonia Risk", sensor: sensors.ammonia,     icon: "⚗️" },
        ].map(item => {
          const status = getSensorStatus(item.sensor.value, item.sensor);
          return (
            <div key={item.label} style={{ background: COLORS.card, border: `1px solid ${COLORS.border}`, borderRadius: 14, padding: "1rem" }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: COLORS.text }}>{item.icon} {item.label}</span>
                <Badge status={status} />
              </div>
              <Sparkline data={item.sensor.history.slice(-30).map(h => h.v)} color={status === "optimal" ? COLORS.turquoise : status === "warning" ? COLORS.warning : COLORS.critical} height={60} />
              <div style={{ marginTop: 8, fontSize: 12, color: COLORS.textMuted }}>
                Current: <b style={{ color: COLORS.text }}>{item.sensor.value?.toFixed(2)} {item.sensor.unit}</b> · Min: {item.sensor.min?.toFixed(2)} · Max: {item.sensor.max?.toFixed(2)}
              </div>
            </div>
          );
        })}
      </div>
      <div style={{ background: COLORS.card, border: `1px solid ${COLORS.border}`, borderRadius: 14, padding: "1rem 1.25rem" }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: COLORS.text, marginBottom: 12 }}>System Performance Summary</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
          {[{ label: "Detection Precision", val: "92%", sub: "Field validated" }, { label: "Sensor Drift", val: "< 2%", sub: "Per month" }, { label: "Battery Endurance", val: "4.5h", sub: "Continuous ops" }, { label: "Pi 5 Inference", val: "15–18 FPS", sub: "3× faster than Pi 4" }].map(m => (
            <div key={m.label} style={{ background: COLORS.surface, borderRadius: 10, padding: "12px 14px" }}>
              <div style={{ fontSize: 20, fontWeight: 600, color: COLORS.nileBlue }}>{m.val}</div>
              <div style={{ fontSize: 12, fontWeight: 500, color: COLORS.text, marginTop: 4 }}>{m.label}</div>
              <div style={{ fontSize: 11, color: COLORS.textMuted }}>{m.sub}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );

  const AlertsPage = () => (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {alerts.map(a => {
        const cfg = a.type === "critical" ? { bg: "#fee2e2", border: COLORS.critical, label: "🚨 Critical" } : a.type === "warning" ? { bg: "#fef9c3", border: COLORS.warning, label: "⚠️ Warning" } : { bg: "#dbeafe", border: COLORS.nileMid, label: "ℹ️ Info" };
        return (
          <div key={a.id} style={{ background: cfg.bg, border: `1px solid ${cfg.border}40`, borderLeft: `4px solid ${cfg.border}`, borderRadius: 10, padding: "14px 16px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
              <div>
                <div style={{ fontSize: 12, fontWeight: 600, color: cfg.border, marginBottom: 4 }}>{cfg.label} · {a.sensor}</div>
                <div style={{ fontSize: 14, color: COLORS.text, fontWeight: 500 }}>{a.message}</div>
                <div style={{ fontSize: 12, color: COLORS.textMuted, marginTop: 4 }}>Location: {a.location}</div>
              </div>
              <span style={{ fontSize: 12, color: COLORS.textMuted }}>{a.time}</span>
            </div>
          </div>
        );
      })}
      <div style={{ background: COLORS.card, border: `1px solid ${COLORS.border}`, borderRadius: 14, padding: "1rem 1.25rem" }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: COLORS.text, marginBottom: 10 }}>Alert Thresholds</div>
        <div style={{ fontSize: 12, color: COLORS.textMuted, lineHeight: 2 }}>
          pH: &lt;6.0 or &gt;8.5 → Critical · TDS: &gt;1000 ppm → Critical · Ammonia: &gt;0.5 ppm → Critical · Turbidity: &gt;100 NTU → Warning
        </div>
      </div>
    </div>
  );

  const BoatPage = () => (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 14 }}>
        {[
          { label: "Battery",          val: sysStats.batteryPct != null ? `${sysStats.batteryPct}%` : "87%",                                  icon: "🔋", color: COLORS.success },
          { label: "Speed",            val: gps.speed ? `${gps.speed.toFixed(1)} km/h` : "1.5 m/s",                                           icon: "⚡", color: COLORS.nileMid },
          { label: "CPU Usage",        val: sysStats.cpuPct     != null ? `${sysStats.cpuPct}%` : "–",                                         icon: "💻", color: COLORS.turquoise },
          { label: "RAM Usage",        val: sysStats.ramUsedMb  != null ? `${(sysStats.ramUsedMb/1024).toFixed(1)} GB / ${(sysStats.ramTotalMb/1024).toFixed(0)} GB` : "–", icon: "🧠", color: COLORS.warning },
          { label: "Mission Duration", val: sysStats.uptimeLabel,                                                                              icon: "⏱️", color: COLORS.nileBlue },
          { label: "Distance Covered", val: latestReport?.gps_summary?.distance_km ? `${latestReport.gps_summary.distance_km} km` : "4.7 km", icon: "🗺️", color: COLORS.gold },
        ].map(m => (
          <div key={m.label} style={{ background: COLORS.card, border: `1px solid ${COLORS.border}`, borderRadius: 12, padding: "14px 16px" }}>
            <span style={{ fontSize: 24 }}>{m.icon}</span>
            <div style={{ fontSize: 20, fontWeight: 600, color: m.color, marginTop: 6 }}>{m.val}</div>
            <div style={{ fontSize: 12, color: COLORS.textMuted }}>{m.label}</div>
          </div>
        ))}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <div style={{ background: COLORS.card, border: `1px solid ${COLORS.border}`, borderRadius: 14, padding: "1rem 1.25rem" }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: COLORS.text, marginBottom: 12 }}>Boat Specifications</div>
          {[["Hull Material", "3D-Printed PETG"], ["Propulsion", "Twin Brushed DC Motors"], ["Motor Driver", "L298N"], ["Control", "Bluetooth HC-05 + Arduino Nano"], ["Speed", "~1.5 m/s cruise"], ["Weight", "4.2 kg (fully loaded)"], ["Buoyancy", "8.5 kg displacement"], ["Endurance", "~4.5 hours"], ["Power", "XL4015 Buck Converters 5V/5A"]].map(([k, v]) => (
            <div key={k} style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", borderBottom: `1px solid ${COLORS.border}`, fontSize: 12 }}>
              <span style={{ color: COLORS.textMuted }}>{k}</span>
              <span style={{ fontWeight: 500, color: COLORS.text }}>{v}</span>
            </div>
          ))}
        </div>
        <div style={{ background: COLORS.card, border: `1px solid ${COLORS.border}`, borderRadius: 14, padding: "1rem 1.25rem" }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: COLORS.text, marginBottom: 12 }}>Processing Core — Raspberry Pi 5</div>
          {[["CPU", "2.4 GHz Quad-core Cortex-A76"], ["RAM", "8GB LPDDR4X"], ["Connectivity", "Wi-Fi 5 & Bluetooth 5.0"], ["GPIO", "40-pin (all sensors)"], ["AI Inference", "15–18 FPS (TFLite)"], ["Idle Draw", "3.5 W"], ["AI Load", "8.5 W"], ["Battery", "10 Ah Li-ion"], ["OS", "Raspberry Pi OS (64-bit)"]].map(([k, v]) => (
            <div key={k} style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", borderBottom: `1px solid ${COLORS.border}`, fontSize: 12 }}>
              <span style={{ color: COLORS.textMuted }}>{k}</span>
              <span style={{ fontWeight: 500, color: COLORS.text }}>{v}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );

  const RoadmapPage = () => (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ background: COLORS.surface, borderRadius: 12, padding: "14px 18px", fontSize: 13, color: COLORS.textMuted }}>
        Smart Nile is designed as an evolving platform. Below is the planned development roadmap approved by the team.
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        {[
          { icon: "☀️", title: "Solar Power Deck",      status: "Planned", color: COLORS.gold,       desc: "Integrate photovoltaic panels for 24/7 autonomous operation. Eliminates battery swap cycles and enables continuous multi-day river surveys." },
          { icon: "🚤", title: "Swarm Fleet Mode",      status: "Planned", color: COLORS.nileMid,    desc: "Deploy 5+ coordinated boats simultaneously covering entire river stretches. Each boat runs its own AI and syncs to a shared cloud layer." },
          { icon: "🦾", title: "Auto Weed Cleanup",     status: "Concept", color: COLORS.turquoise,  desc: "Mechanical arm system for automated aquatic weed collection during patrol missions. Combining detection with active remediation." },
          { icon: "🔬", title: "Heavy Metal Detection", status: "Concept", color: COLORS.warning,    desc: "Expand sensor array to include Chromium (Cr) and Lead (Pb) detection probes — critical for industrial discharge monitoring." },
          { icon: "🤖", title: "Autonomous Navigation", status: "Concept", color: COLORS.success,    desc: "Full SLAM-based autonomous waypoint navigation without manual Bluetooth control. GPS-fused path planning with obstacle avoidance." },
          { icon: "📱", title: "Mobile Dashboard App",  status: "In Dev",  color: COLORS.nileBlue,   desc: "Native Android/iOS application for field operators. Real-time sensor view, boat control, detection alerts and PDF report generation." },
        ].map(item => (
          <div key={item.title} style={{ background: COLORS.card, border: `1px solid ${COLORS.border}`, borderRadius: 14, padding: "1rem 1.25rem" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
              <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <span style={{ fontSize: 26 }}>{item.icon}</span>
                <span style={{ fontSize: 13, fontWeight: 600, color: COLORS.text }}>{item.title}</span>
              </div>
              <span style={{ fontSize: 11, padding: "3px 10px", borderRadius: 6, background: `${item.color}18`, color: item.color, fontWeight: 600 }}>{item.status}</span>
            </div>
            <p style={{ fontSize: 13, color: COLORS.textMuted, lineHeight: 1.6, margin: 0 }}>{item.desc}</p>
          </div>
        ))}
      </div>
    </div>
  );

  const pageMap = {
    dashboard: { title: "Command Center",      sub: "Real-time overview of all systems",                   component: <DashboardPage /> },
    sensors:   { title: "Sensor Array",        sub: "5-parameter water quality monitoring",                component: <SensorsPage /> },
    detection: { title: "AI Detection Center", sub: "Water Hyacinth & Water Lettuce via TFLite",           component: <DetectionPage /> },
    map:       { title: "GPS Tracking",        sub: "NEO-6M geo-tagged telemetry",                        component: <MapPage /> },
    analytics: { title: "Analytics",           sub: "Historical trends and performance",                   component: <AnalyticsPage /> },
    history:   { title: "Sensor History",      sub: "Date-range filter · CSV & JSON export",              component: <HistoryPage useFirebase={USE_FIREBASE} /> },
    alerts:    { title: "Alert Center",        sub: "Automated threshold monitoring",                      component: <AlertsPage /> },
    reports:   { title: "Mission Reports",     sub: "Auto-generated daily summaries from the backend",    component: <ReportsPage useFirebase={USE_FIREBASE} /> },
    advisor:   { title: "AI Advisor",          sub: "SMART NILE AI — sensor-aware assistant",              component: <AIAdvisor sensors={sensors} alerts={alerts} /> },
    boat:      { title: "Boat Operations",     sub: "Raspberry Pi 5 · PETG hull · L298N",                 component: <BoatPage /> },
    roadmap:   { title: "Future Roadmap",      sub: "Planned evolution of the Smart Nile platform",        component: <RoadmapPage /> },
  };

  const page = pageMap[activePage];

  return (
    <div style={{ fontFamily: "system-ui, -apple-system, sans-serif", background: COLORS.surface, minHeight: "100vh", color: COLORS.text }}>
      <h2 className="sr-only">Smart Nile — AI-Powered Nile River Monitoring System Dashboard</h2>
      <Header />
      <StatusBar />
      <div style={{ display: "flex" }}>
        {sidebarOpen && (
          <div style={{ width: 220, background: "white", borderRight: `1px solid ${COLORS.border}`, minHeight: "calc(100vh - 98px)", padding: "12px 0", flexShrink: 0 }}>
            {navItems.map(item => (
              <button key={item.key} onClick={() => setActivePage(item.key)}
                style={{ display: "flex", alignItems: "center", gap: 10, width: "100%", padding: "10px 16px", border: "none", background: activePage === item.key ? `${COLORS.nileBlue}10` : "transparent", color: activePage === item.key ? COLORS.nileBlue : COLORS.textMuted, cursor: "pointer", fontSize: 13, fontWeight: activePage === item.key ? 600 : 400, borderLeft: activePage === item.key ? `3px solid ${COLORS.nileBlue}` : "3px solid transparent", textAlign: "left" }}>
                <span style={{ fontSize: 16 }}>{item.icon}</span>
                {item.label}
              </button>
            ))}
            <div style={{ margin: "16px 12px 0", padding: "12px", background: COLORS.surface, borderRadius: 10, fontSize: 11 }}>
              <div style={{ fontWeight: 600, color: COLORS.text, marginBottom: 6 }}>Project Info</div>
              <div style={{ color: COLORS.textMuted, lineHeight: 1.7 }}>
                Class of 2026<br />
                Electrical & Communications Eng.<br />
                Supervised by Prof. Hazem Ali
              </div>
            </div>
          </div>
        )}
        <div style={{ flex: 1, padding: 20, overflowY: "auto" }}>
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 18, fontWeight: 700, color: COLORS.text }}>{page.title}</div>
            <div style={{ fontSize: 12, color: COLORS.textMuted }}>{page.sub}</div>
          </div>
          {page.component}
        </div>
      </div>
    </div>
  );
}
