/**
 * SearchInput component - search field with magnifying glass icon.
 *
 * Used to filter the source list by name, path, URL, or description.
 * Simple wrapper around a standard input with a left-aligned icon.
 *
 * @param {Object} props - Component props
 * @param {string} props.value - Current search query text
 * @param {Function} props.onChange - Callback when text changes, receives new value
 * @param {string} props.placeholder - Placeholder text when empty
 * @returns {JSX.Element} Search input element with icon
 */

import { C } from "../theme";

export default function SearchInput({ value, onChange, placeholder }) {
  return (
    <div style={{ position: "relative" }}>
      {/* Magnifying glass icon */}
      <span
        style={{
          position: "absolute",
          left: 12,
          top: "50%",
          transform: "translateY(-50%)",
          fontSize: 14,
          color: C.textMuted,
        }}
      >
        🔍
      </span>

      {/* Input field with extra left padding for icon */}
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        style={{
          width: "100%",
          paddingLeft: 36,
          background: C.bgAlt,
        }}
      />
    </div>
  );
}
