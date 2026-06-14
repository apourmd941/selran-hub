/**
 * SourceRow component - displays a single data source in the list.
 *
 * Shows source icon, name, path/URL, status badge, and action buttons.
 * Action buttons (check, edit, toggle, delete) only appear on hover.
 *
 * @param {Object} props - Component props
 * @param {Object} props.source - Source object with id, name, type, path, url, status, enabled, etc.
 * @param {Function} props.onSelect - Callback when row is clicked, receives source object
 * @param {Function} props.onToggle - Callback to enable/disable source, receives source ID
 * @param {Function} props.onCheck - Callback to check source health, receives source ID
 * @param {Function} props.onDelete - Callback to delete source, receives source ID
 * @param {Function} props.onEdit - Callback to edit source, receives source object
 * @returns {JSX.Element} Styled source row element
 */

import { useState } from "react";
import { C, icons, labels } from "../theme";
import Badge from "./Badge";
import StatusDot from "./StatusDot";
import { SmallBtn } from "./Btn";

export default function SourceRow({
  source,
  onSelect,
  onToggle,
  onCheck,
  onDelete,
  onEdit,
}) {
  const [h, setH] = useState(false);

  return (
    <div
      onMouseEnter={() => setH(true)}
      onMouseLeave={() => setH(false)}
      onClick={() => onSelect(source)}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 14,
        padding: "14px 18px",
        cursor: "pointer",
        background: h ? C.surfaceHover : "transparent",
        borderBottom: `1px solid ${C.border}`,
        transition: "background 0.12s",
      }}
    >
      {/* Source type icon */}
      <span style={{ fontSize: 22, width: 32, textAlign: "center" }}>
        {icons[source.type] || "📦"}
      </span>

      {/* Source name and path/URL */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 600, fontSize: 14 }}>{source.name}</div>
        <div
          style={{
            fontSize: 12,
            color: C.textDim,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {source.path ||
            source.url ||
            source.description ||
            labels[source.type]}
        </div>
      </div>

      {/* Status badge */}
      <Badge
        color={
          source.status === "online"
            ? C.green
            : source.status === "error"
            ? C.red
            : C.textMuted
        }
        bg={
          source.status === "online"
            ? C.greenBg
            : source.status === "error"
            ? C.redBg
            : `${C.textMuted}18`
        }
      >
        <StatusDot status={source.status} /> {source.status}
      </Badge>

      {/* Action buttons (visible on hover) */}
      <div
        style={{
          display: "flex",
          gap: 4,
          opacity: h ? 1 : 0,
          transition: "opacity 0.12s",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <SmallBtn onClick={() => onCheck(source.id)} title="Check health">
          ↻
        </SmallBtn>
        <SmallBtn onClick={() => onEdit(source)} title="Edit">
          ✎
        </SmallBtn>
        <SmallBtn
          onClick={() => onToggle(source.id)}
          title={source.enabled ? "Disable" : "Enable"}
        >
          {source.enabled ? "⏸" : "▶"}
        </SmallBtn>
        <SmallBtn
          onClick={() => onDelete(source.id)}
          title="Remove"
          danger
        >
          ✕
        </SmallBtn>
      </div>
    </div>
  );
}
