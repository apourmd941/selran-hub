#!/usr/bin/env node

/**
 * MCP Server Dashboard — Production Build Script
 *
 * Reads component files, strips imports/exports, and bundles into
 * a single dist/index.html file with React 18 + Babel standalone.
 *
 * Usage: node build.js
 */

const fs = require("fs");
const path = require("path");

// ─── Config ──────────────────────────────────────────────────────────────────
const COMPONENT_ORDER = [
  "src/theme.js",
  "src/api.js",
  "src/components/StatusDot.jsx",
  "src/components/Badge.jsx",
  "src/components/Btn.jsx",
  "src/components/StatCard.jsx",
  "src/components/SearchInput.jsx",
  "src/components/TabBar.jsx",
  "src/components/SourceRow.jsx",
  "src/components/SourceModal.jsx",
  "src/components/SourceDetail.jsx",
  "src/components/MCPConfigPanel.jsx",
  "src/components/ImportExportPanel.jsx",
  "src/components/LogPanel.jsx",
  "src/components/SettingsPanel.jsx",
  "src/App.jsx",
];

const OUTPUT_FILE = "dist/index.html";

// ─── Utilities ───────────────────────────────────────────────────────────────
function log(msg) {
  console.log(`[BUILD] ${msg}`);
}

function error(msg) {
  console.error(`[ERROR] ${msg}`);
  process.exit(1);
}

function stripImportsExports(code) {
  return code
    .replace(/^import\s+.*?from\s+['"][^'"]*['"]\s*;?/gm, "")
    .replace(/^export\s+(default\s+)?/gm, "")
    .trim();
}

// ─── Build ───────────────────────────────────────────────────────────────────
function build() {
  log("Starting build...");

  // Ensure dist/ directory exists
  const distDir = path.join(__dirname, "dist");
  if (!fs.existsSync(distDir)) {
    fs.mkdirSync(distDir, { recursive: true });
    log("Created dist/ directory");
  }

  // Concatenate all component files
  log(`Concatenating ${COMPONENT_ORDER.length} files...`);
  let componentCode = "";
  const missing = [];

  COMPONENT_ORDER.forEach((file, idx) => {
    const fullPath = path.join(__dirname, file);

    if (!fs.existsSync(fullPath)) {
      missing.push(file);
      log(`⚠️  Skipping ${file} (not found)`);
      return;
    }

    try {
      const content = fs.readFileSync(fullPath, "utf-8");
      const stripped = stripImportsExports(content);
      const lineCount = stripped.split("\n").length;

      componentCode += "\n    // ─── " + path.basename(file) + " ──────────────────────────────────────────\n";
      componentCode += stripped + "\n";

      log(`✓ ${file} (${lineCount} lines)`);
    } catch (err) {
      error(`Failed to read ${file}: ${err.message}`);
    }
  });

  // Report missing files
  if (missing.length > 0) {
    log(`Warning: ${missing.length} files not found (concatenation will continue)`);
  }

  // Shared Selran suite theme — inlined FIRST so the app inherits the shared
  // palette/fonts before its own styles run (mirrors how wake imports it first).
  let themeCss = "";
  const themePath = path.join(__dirname, "src/selran-theme.css");
  if (fs.existsSync(themePath)) {
    themeCss = fs.readFileSync(themePath, "utf-8");
    log("✓ src/selran-theme.css (inlined first)");
  } else {
    log("⚠️  src/selran-theme.css not found (theme not inlined)");
  }

  // Generate HTML
  log("Generating HTML...");
  const html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>MCP Server Dashboard</title>
  <!-- Shared Selran suite theme — must come first -->
  <style>${themeCss}</style>
  <style>html, body, #root { margin: 0; background: #0B1220; }</style>
  <script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
  <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
  <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
</head>
<body class="selran-theme">
  <div id="root"></div>

  <script type="text/babel">
    const { useState, useEffect, useCallback, useRef } = React;
${componentCode}

    // ─── Render Root ──────────────────────────────────────────────────────────
    ReactDOM.createRoot(document.getElementById('root')).render(<App />);
  </script>
</body>
</html>`;

  // Write output
  log(`Writing to ${OUTPUT_FILE}...`);
  const outputPath = path.join(__dirname, OUTPUT_FILE);
  fs.writeFileSync(outputPath, html, "utf-8");

  const sizeKb = (html.length / 1024).toFixed(1);
  log(`✓ Build complete: ${sizeKb} KB`);

  console.log(`
╔════════════════════════════════════════════════════════════════╗
║                 Build Successful                              ║
╚════════════════════════════════════════════════════════════════╝

  Output:  ${OUTPUT_FILE}
  Size:    ${sizeKb} KB

  Next steps:
    - Copy dist/index.html to your production server
    - Or serve via: python3 -m http.server --directory dist 8080
`);
}

// ─── Entry Point ─────────────────────────────────────────────────────────────
try {
  build();
} catch (err) {
  error(`Build failed: ${err.message}`);
}
