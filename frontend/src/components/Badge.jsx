/**
 * Badge component - displays a small labeled pill with background color.
 *
 * Used for status indicators, type labels, and other metadata display
 * throughout the dashboard. Designed to be compact and visually distinct.
 *
 * @param {Object} props - Component props
 * @param {React.ReactNode} props.children - Content to display (usually text or text + icon)
 * @param {string} props.color - Text color (hex value)
 * @param {string} props.bg - Background color (hex value or rgba)
 * @returns {JSX.Element} Styled badge element
 */

export default function Badge({ children, color, bg }) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "2px 10px",
        borderRadius: 20,
        fontSize: 12,
        fontWeight: 500,
        color: color,
        background: bg,
      }}
    >
      {children}
    </span>
  );
}
