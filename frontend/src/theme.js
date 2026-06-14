/**
 * Theme configuration for the MCP Server Dashboard.
 *
 * Centralizes all color constants, icons, labels, and global CSS styles.
 * This makes it easy to maintain consistent branding and quickly adjust colors
 * across the entire application.
 */

/**
 * Color palette for the dashboard.
 *
 * Remapped onto the shared Selran suite theme (see src/selran-theme.css and
 * Selran-Launchpad-V3/theme/selran-theme.css). These keys keep their original
 * names so existing components are unchanged — only the values are repointed to
 * the shared palette so the hub matches the rest of the Selran suite.
 * @type {Object}
 */
export const C = {
  // Background colors  →  --bg / --bg-subtle
  bg: "#0B1220",           // Primary background
  bgAlt: "#0E1626",        // Secondary background (slightly lighter)

  // Surface colors (cards, panels)  →  --surface / --surface-2
  surface: "#131C2E",      // Main surface color
  surfaceHover: "#1A2438", // Hover state for surfaces

  // Border colors  →  --border / --border-strong
  border: "#26324A",       // Standard border
  borderLight: "#33425F",  // Lighter border for subtle separators

  // Text colors  →  --fg / --fg-muted / --fg-subtle
  text: "#E8EEF7",         // Primary text
  textDim: "#9FB0C9",      // Dimmed text (secondary information)
  textMuted: "#6E7E98",    // Muted text (tertiary/disabled)

  // Accent colors (primary UI interactions)  →  --accent / --accent-hover
  accent: "#4F9CF0",       // Primary accent (shared Selran blue)
  accentHover: "#6FB0F5",  // Accent hover state
  accentContrast: "#07101F", // Readable text/icon color on the accent fill
  accentBg: "rgba(79,156,240,0.10)", // Accent background (--accent-soft tint)

  // Status colors  →  --success / --danger / --warning / --info
  green: "#46C08A",        // Success/online status
  greenBg: "rgba(70,192,138,0.10)", // Green background

  red: "#F0726F",          // Error/offline status
  redBg: "rgba(240,114,111,0.10)",  // Red background

  amber: "#E6B450",        // Warning/read-only status
  amberBg: "rgba(230,180,80,0.10)", // Amber background

  blue: "#4F9CF0",         // Info color (shared --info)
  blueBg: "rgba(79,156,240,0.10)",  // Blue background
};

/**
 * Icon emojis for different data source types.
 * @type {Object}
 */
export const icons = {
  folder: "📁",      // Local folder/file system
  duckdb: "🦆",      // DuckDB database
  sqlite: "🗃️",      // SQLite database
  api: "🌐",         // REST API endpoint
};

/**
 * Display labels for different data source types.
 * @type {Object}
 */
export const labels = {
  folder: "Folder",
  duckdb: "DuckDB",
  sqlite: "SQLite",
  api: "REST API",
};

/**
 * Global CSS styles for the application.
 * Includes reset styles, animations, and component styling.
 * Injected into a <style> tag in the HTML head.
 */
export const css = `
  * {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
  }

  body {
    font-family: "Geist", -apple-system, "SF Pro Text", "Segoe UI", system-ui, sans-serif;
    background: ${C.bg};
    color: ${C.text};
    line-height: 1.5;
  }

  ::selection {
    background: ${C.accent}40;
  }

  /* Scrollbar styling */
  ::-webkit-scrollbar {
    width: 5px;
    height: 5px;
  }

  ::-webkit-scrollbar-track {
    background: transparent;
  }

  ::-webkit-scrollbar-thumb {
    background: ${C.border};
    border-radius: 3px;
  }

  /* Form inputs — scoped under .selran-theme so these keep the hub's own
     padding/radius (matching the shared theme's specificity, later source order
     wins) while using the shared palette via C. */
  .selran-theme input,
  .selran-theme select,
  .selran-theme textarea {
    font-family: inherit;
    font-size: 14px;
    background: ${C.bgAlt};
    color: ${C.text};
    border: 1px solid ${C.border};
    border-radius: 8px;
    padding: 10px 14px;
    outline: none;
    transition: border-color 0.2s;
  }

  .selran-theme input:focus,
  .selran-theme select:focus,
  .selran-theme textarea:focus {
    border-color: ${C.accent};
  }

  /* Buttons */
  button {
    font-family: inherit;
    cursor: pointer;
    border: none;
    outline: none;
    transition: all 0.15s;
  }

  /* Animations */
  @keyframes fadeIn {
    from {
      opacity: 0;
      transform: translateY(6px);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }

  @keyframes slideIn {
    from {
      opacity: 0;
      transform: translateX(16px);
    }
    to {
      opacity: 1;
      transform: translateX(0);
    }
  }

  @keyframes spin {
    from {
      transform: rotate(0deg);
    }
    to {
      transform: rotate(360deg);
    }
  }

  .spin {
    animation: spin 0.8s linear infinite;
  }
`;
