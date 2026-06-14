/**
 * Btn and SmallBtn components - primary UI buttons.
 *
 * Btn: Standard-sized button for major actions (add, save, submit).
 * SmallBtn: Compact circular buttons for icon-only actions (edit, delete, refresh).
 *
 * Both components support hover states and can be disabled.
 */

import { useState } from "react";
import { C } from "../theme";

/**
 * Standard button component with optional primary or danger styling.
 *
 * @param {Object} props - Component props
 * @param {React.ReactNode} props.children - Button label or content
 * @param {Function} props.onClick - Click handler
 * @param {boolean} props.primary - If true, use accent color and filled style
 * @param {boolean} props.danger - If true, use red color for destructive actions
 * @param {boolean} props.small - If true, use smaller padding/font size
 * @param {boolean} props.disabled - If true, button is non-interactive
 * @param {Object} props.style - Additional inline styles
 * @returns {JSX.Element} Button element
 */
export function Btn({
  children,
  onClick,
  primary,
  danger,
  small,
  disabled,
  style: xs,
}) {
  const [h, setH] = useState(false);

  let bg = "transparent";
  let fg = C.text;
  let bd = C.border;

  if (primary) {
    bg = C.accent;
    fg = C.accentContrast;
    bd = C.accent;
  }

  if (danger) {
    bg = h ? C.redBg : "transparent";
    fg = C.red;
    bd = C.red;
  }

  if (h && primary) {
    bg = C.accentHover;
  }

  return (
    <button
      onClick={onClick}
      disabled={disabled}
      onMouseEnter={() => setH(true)}
      onMouseLeave={() => setH(false)}
      style={{
        padding: small ? "6px 14px" : "10px 20px",
        borderRadius: 8,
        fontSize: small ? 13 : 14,
        fontWeight: 500,
        background: bg,
        color: fg,
        border: `1px solid ${bd}`,
        opacity: disabled ? 0.5 : 1,
        ...xs,
      }}
    >
      {children}
    </button>
  );
}

/**
 * Small circular button component for icon-only actions.
 *
 * Used in source rows and detail panels for quick actions like
 * edit, delete, toggle, and refresh.
 *
 * @param {Object} props - Component props
 * @param {React.ReactNode} props.children - Icon/emoji to display
 * @param {Function} props.onClick - Click handler
 * @param {string} props.title - Tooltip text on hover
 * @param {boolean} props.danger - If true, icon turns red on hover
 * @returns {JSX.Element} Circular button element
 */
export function SmallBtn({ children, onClick, title, danger }) {
  const [h, setH] = useState(false);

  return (
    <button
      onClick={onClick}
      title={title}
      onMouseEnter={() => setH(true)}
      onMouseLeave={() => setH(false)}
      style={{
        width: 30,
        height: 30,
        borderRadius: 7,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontSize: 13,
        color: danger && h ? C.red : C.textDim,
        background: h ? C.bgAlt : "transparent",
        border: `1px solid ${h ? C.borderLight : "transparent"}`,
      }}
    >
      {children}
    </button>
  );
}
