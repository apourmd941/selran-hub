/**
 * StatCard component - displays a single statistic metric.
 *
 * Used in the dashboard header to show key metrics like total sources,
 * online/offline counts, and error counts.
 *
 * @param {Object} props - Component props
 * @param {string} props.label - Metric label (e.g., "Total Sources")
 * @param {number|string} props.value - The metric value to display
 * @param {string} props.color - Text color for the value (hex value)
 * @param {string} props.icon - Emoji icon to display next to the value
 * @param {string} props.sub - Optional subtitle/metadata below the value
 * @returns {JSX.Element} Styled stat card element
 */

import { C } from "../theme";

export default function StatCard({ label, value, color, icon, sub }) {
  return (
    <div
      style={{
        background: C.surface,
        borderRadius: 12,
        padding: "18px 22px",
        border: `1px solid ${C.border}`,
        flex: "1 1 0",
        minWidth: 140,
      }}
    >
      {/* Label - small text at top */}
      <div
        style={{
          fontSize: 12,
          color: C.textDim,
          marginBottom: 6,
          fontWeight: 500,
          letterSpacing: 0.5,
          textTransform: "uppercase",
        }}
      >
        {label}
      </div>

      {/* Main value with icon */}
      <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <span style={{ fontSize: 28, fontWeight: 700, color: color || C.text }}>
          {value}
        </span>
        {icon && <span style={{ fontSize: 18 }}>{icon}</span>}
      </div>

      {/* Optional subtitle */}
      {sub && (
        <div style={{ fontSize: 12, color: C.textMuted, marginTop: 4 }}>
          {sub}
        </div>
      )}
    </div>
  );
}
