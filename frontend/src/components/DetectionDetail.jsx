// src/components/DetectionDetail.jsx
// ====================================
// Expandable detail panel shown when a user clicks a row in the
// Detection History table. Displays:
//   - Firebase Storage snapshot image (if storage_url is set)
//   - Bounding box overlay drawn on canvas
//   - Confidence bar + severity badge
//   - GPS coordinates with Google Maps deep-link
//   - Species info card
//
// Usage in DetectionPage:
//   import DetectionDetail from "../components/DetectionDetail";
//   ...
//   <DetectionDetail detection={selectedDetection} onClose={() => setSelected(null)} />

import { useEffect, useRef } from "react";

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
};

const SPECIES_INFO = {
  "Water Hyacinth": {
    scientific: "Eichhornia crassipes",
    threat: "critical",
    desc: "Highly invasive floating plant. Doubles in area every 2 weeks under optimal conditions. Depletes dissolved oxygen and blocks sunlight, causing fish kills.",
    color: "#16a34a",
  },
  "Water Lettuce": {
    scientific: "Pistia stratiotes",
    threat: "critical",
    desc: "Dense floating rosettes reduce water oxygen and block navigation. Listed among the world's 100 worst invasive species.",
    color: "#7c3aed",
  },
  "Algae Bloom": {
    scientific: "Cyanobacteria spp.",
    threat: "warning",
    desc: "Dense algal growth indicates eutrophication. Can produce toxins harmful to humans, livestock, and aquatic wildlife.",
    color: COLORS.warning,
  },
  "Unknown Plant": {
    scientific: "Unclassified",
    threat: "warning",
    desc: "Unidentified vegetation detected. Manual review recommended to confirm species and assess threat level.",
    color: COLORS.textMuted,
  },
};

function ConfidenceBar({ value, color }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <div style={{ flex: 1, height: 8, background: COLORS.border, borderRadius: 4, overflow: "hidden" }}>
        <div style={{ width: `${value}%`, height: "100%", background: color, borderRadius: 4, transition: "width 0.4s ease" }} />
      </div>
      <span style={{ fontSize: 13, fontWeight: 600, color, minWidth: 44 }}>{value.toFixed(1)}%</span>
    </div>
  );
}

function BBoxCanvas({ storageUrl, bbox }) {
  const canvasRef = useRef(null);
  const imgRef    = useRef(null);

  useEffect(() => {
    if (!canvasRef.current || !storageUrl || !bbox) return;
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      imgRef.current = img;
      const canvas = canvasRef.current;
      canvas.width  = img.naturalWidth;
      canvas.height = img.naturalHeight;
      const ctx = canvas.getContext("2d");
      ctx.drawImage(img, 0, 0);
      // draw bounding box
      ctx.strokeStyle = "#16a34a";
      ctx.lineWidth   = Math.max(2, img.naturalWidth / 150);
      ctx.strokeRect(bbox.x, bbox.y, bbox.w, bbox.h);
      // label background
      ctx.fillStyle = "rgba(22,163,74,0.85)";
      const lh = Math.max(18, img.naturalHeight / 25);
      ctx.fillRect(bbox.x, bbox.y - lh, bbox.w, lh);
      ctx.fillStyle = "white";
      ctx.font       = `bold ${lh * 0.7}px system-ui`;
      ctx.fillText("Detection", bbox.x + 4, bbox.y - lh * 0.2);
    };
    img.src = storageUrl;
  }, [storageUrl, bbox]);

  if (!storageUrl) {
    return (
      <div style={{ background: COLORS.surface, borderRadius: 10, height: 200, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", color: COLORS.textMuted, fontSize: 13 }}>
        <span style={{ fontSize: 32, marginBottom: 8 }}>📷</span>
        No snapshot image available
        <span style={{ fontSize: 11, marginTop: 4 }}>Camera snapshot uploads when Firebase Storage is configured</span>
      </div>
    );
  }

  return (
    <div style={{ borderRadius: 10, overflow: "hidden", background: "#000" }}>
      <canvas ref={canvasRef} style={{ width: "100%", display: "block" }} />
    </div>
  );
}

export default function DetectionDetail({ detection, onClose }) {
  if (!detection) return null;

  const info    = SPECIES_INFO[detection.type] ?? SPECIES_INFO["Unknown Plant"];
  const mapsUrl = detection.lat && detection.lon
    ? `https://www.google.com/maps?q=${detection.lat},${detection.lon}`
    : null;

  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(10,30,50,0.55)",
      display: "flex", alignItems: "center", justifyContent: "center",
      zIndex: 1000, padding: 20,
    }}
      onClick={e => e.target === e.currentTarget && onClose()}
    >
      <div style={{
        background: COLORS.card, borderRadius: 16, width: "100%", maxWidth: 680,
        maxHeight: "90vh", overflowY: "auto",
        boxShadow: "0 20px 60px rgba(0,0,0,0.3)",
      }}>
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "16px 20px", borderBottom: `1px solid ${COLORS.border}` }}>
          <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
            <div style={{ width: 12, height: 12, borderRadius: "50%", background: info.color }} />
            <div>
              <div style={{ fontSize: 15, fontWeight: 700, color: COLORS.text }}>{detection.type}</div>
              <div style={{ fontSize: 11, color: COLORS.textMuted, fontStyle: "italic" }}>{info.scientific}</div>
            </div>
          </div>
          <button onClick={onClose}
            style={{ background: COLORS.surface, border: `1px solid ${COLORS.border}`, borderRadius: 8, padding: "6px 12px", cursor: "pointer", fontSize: 13, color: COLORS.textMuted }}>
            ✕ Close
          </button>
        </div>

        <div style={{ padding: "16px 20px", display: "flex", flexDirection: "column", gap: 16 }}>

          {/* Snapshot */}
          <BBoxCanvas storageUrl={detection.storage_url} bbox={detection.bounding_box} />

          {/* Confidence + severity */}
          <div style={{ background: COLORS.surface, borderRadius: 10, padding: "12px 14px" }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: COLORS.text, marginBottom: 8 }}>Detection Confidence</div>
            <ConfidenceBar value={detection.confidence} color={info.color} />
            <div style={{ marginTop: 8, display: "flex", gap: 10 }}>
              <span style={{ fontSize: 11, background: info.threat === "critical" ? "#fee2e2" : "#fef9c3", color: info.threat === "critical" ? COLORS.critical : COLORS.warning, padding: "3px 9px", borderRadius: 5, fontWeight: 600 }}>
                {info.threat === "critical" ? "🚨 Critical Invasive" : "⚠️ Monitor"}
              </span>
              <span style={{ fontSize: 11, background: "#f0f6fb", color: COLORS.textMuted, padding: "3px 9px", borderRadius: 5 }}>
                {detection.time}
              </span>
              <span style={{ fontSize: 11, background: "#f0f6fb", color: COLORS.textMuted, padding: "3px 9px", borderRadius: 5 }}>
                {detection.status}
              </span>
            </div>
          </div>

          {/* Species info */}
          <div style={{ background: `${info.color}0d`, border: `1px solid ${info.color}30`, borderRadius: 10, padding: "12px 14px" }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: info.color, marginBottom: 6 }}>Species Information</div>
            <div style={{ fontSize: 12, color: COLORS.text, lineHeight: 1.7 }}>{info.desc}</div>
          </div>

          {/* Location */}
          <div style={{ background: COLORS.surface, borderRadius: 10, padding: "12px 14px" }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: COLORS.text, marginBottom: 8 }}>📍 Detection Location</div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div style={{ fontSize: 12, color: COLORS.textMuted }}>
                {detection.lat != null ? `${detection.lat.toFixed(6)}°N` : "–"},{" "}
                {detection.lon != null ? `${detection.lon.toFixed(6)}°E` : "–"}
              </div>
              {mapsUrl && (
                <a href={mapsUrl} target="_blank" rel="noopener noreferrer"
                  style={{ fontSize: 12, color: COLORS.nileMid, textDecoration: "none", fontWeight: 500, border: `1px solid ${COLORS.border}`, padding: "4px 10px", borderRadius: 6 }}>
                  Open in Google Maps ↗
                </a>
              )}
            </div>
          </div>

          {/* Raw data */}
          <details>
            <summary style={{ fontSize: 12, color: COLORS.textMuted, cursor: "pointer", userSelect: "none" }}>Raw detection data</summary>
            <pre style={{ marginTop: 8, fontSize: 11, color: COLORS.textMuted, background: COLORS.surface, padding: "10px 14px", borderRadius: 8, overflowX: "auto" }}>
              {JSON.stringify(detection, null, 2)}
            </pre>
          </details>
        </div>
      </div>
    </div>
  );
}
