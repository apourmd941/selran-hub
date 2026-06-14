/**
 * TabBar component - horizontal tab navigation with optional counts.
 *
 * Used to filter sources by type (All, Folder, DuckDB, SQLite, API)
 * and to switch between panels (Export/Import, etc.).
 *
 * @param {Object} props - Component props
 * @param {Array<{id: string, label: string, count?: number}>} props.tabs - Tab definitions
 * @param {string} props.active - ID of the currently active tab
 * @param {Function} props.onChange - Callback when a tab is clicked, receives tab ID
 * @returns {JSX.Element} Tab navigation bar
 */

import { C } from "../theme";

export default function TabBar({ tabs, active, onChange }) {
  return (
    <div
      style={{
        display: "flex",
        gap: 2,
        background: C.bgAlt,
        borderRadius: 10,
        padding: 3,
      }}
    >
      {tabs.map((t) => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          style={{
            padding: "7px 16px",
            borderRadius: 8,
            fontSize: 13,
            fontWeight: active === t.id ? 600 : 400,
            background: active === t.id ? C.surface : "transparent",
            color: active === t.id ? C.text : C.textDim,
            border: active === t.id ? `1px solid ${C.border}` : "1px solid transparent",
          }}
        >
          {t.label}
          {t.count != null && (
            <span style={{ marginLeft: 6, fontSize: 11, color: C.textMuted }}>
              ({t.count})
            </span>
          )}
        </button>
      ))}
    </div>
  );
}
