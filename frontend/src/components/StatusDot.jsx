/**
 * StatusDot component - displays a small colored circle indicating status.
 *
 * Used in badges and status indicators throughout the dashboard to show
 * whether a data source is online, offline, or in error state.
 *
 * @param {Object} props - Component props
 * @param {string} props.status - Status value: "online", "error", or other
 * @returns {JSX.Element} Styled status dot element
 */

import { C } from "../theme";

export default function StatusDot({ status }) {
  // Color changes based on status
  const color =
    status === "online" ? C.green : status === "error" ? C.red : C.textMuted;

  // Online status gets a glow effect for visibility
  const boxShadow =
    status === "online" ? `0 0 6px ${color}` : "none";

  return (
    <span
      style={{
        display: "inline-block",
        width: 8,
        height: 8,
        borderRadius: "50%",
        background: color,
        boxShadow: boxShadow,
      }}
    />
  );
}
