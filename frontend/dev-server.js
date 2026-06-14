#!/usr/bin/env node

/**
 * MCP Server Dashboard — Development Server
 *
 * Lightweight Node.js dev server that:
 * - Serves files from public/ as static assets
 * - Concatenates all component files into a single Babel script
 * - Proxies /api/* requests to http://127.0.0.1:8420
 * - Watches for file changes and sends reload signals via polling
 * - Runs on port 3000 by default
 *
 * NO npm packages required — uses only Node.js built-ins.
 */

const http = require("http");
const fs = require("fs");
const path = require("path");
const { URL } = require("url");

// ─── Config ──────────────────────────────────────────────────────────────────
const PORT = process.env.PORT || 3000;
const BACKEND_URL = "http://127.0.0.1:8420";

// File concatenation order (strip import/export, combine into single <script>)
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

// ─── File Watchers ───────────────────────────────────────────────────────────
const fileWatchers = [];
let lastChangeTime = Date.now();

function watchFiles() {
  COMPONENT_ORDER.forEach((file) => {
    const fullPath = path.join(__dirname, file);
    if (!fs.existsSync(fullPath)) {
      console.warn(`Warning: ${file} not found, skipping watch`);
      return;
    }

    try {
      fs.watchFile(fullPath, { interval: 500 }, () => {
        console.log(`[CHANGE] ${file}`);
        lastChangeTime = Date.now();
      });
      fileWatchers.push(fullPath);
    } catch (err) {
      console.warn(`Could not watch ${file}: ${err.message}`);
    }
  });
}

// ─── Concatenate Components ──────────────────────────────────────────────────
function stripImportsExports(code) {
  return code
    .replace(/^import\s+.*?from\s+['"][^'"]*['"]\s*;?/gm, "")
    .replace(/^export\s+(default\s+)?/gm, "")
    .trim();
}

function concatenateComponents() {
  let result = "";
  const missing = [];

  COMPONENT_ORDER.forEach((file) => {
    const fullPath = path.join(__dirname, file);
    if (!fs.existsSync(fullPath)) {
      missing.push(file);
      return;
    }

    try {
      const content = fs.readFileSync(fullPath, "utf-8");
      const stripped = stripImportsExports(content);
      result += "\n    // ─── " + path.basename(file) + " ──────────────────────────────────────────\n";
      result += stripped + "\n";
    } catch (err) {
      console.error(`Error reading ${file}:`, err.message);
    }
  });

  if (missing.length > 0) {
    console.warn(`\nWarning: ${missing.length} files not found:`);
    missing.forEach((f) => console.warn(`  - ${f}`));
  }

  return result;
}

// ─── Generate Dev HTML ───────────────────────────────────────────────────────
function readThemeCss() {
  // Shared Selran suite theme — inlined FIRST so the app inherits the shared
  // palette/fonts before its own styles run (mirrors how wake imports it first).
  const themePath = path.join(__dirname, "src/selran-theme.css");
  try {
    return fs.readFileSync(themePath, "utf-8");
  } catch (err) {
    console.warn(`Warning: src/selran-theme.css not found (theme not inlined)`);
    return "";
  }
}

function generateDevHtml() {
  const componentCode = concatenateComponents();
  const themeCss = readThemeCss();

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>MCP Server Dashboard (Dev)</title>
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

  <script>
    // ─── Polling for Live Reload ──────────────────────────────────────────────
    // Check server status every 1s; if it changes, reload the page
    let lastStatus = Date.now();
    setInterval(async () => {
      try {
        const res = await fetch('/dev-status');
        const data = await res.json();
        if (data.changeTime > lastStatus) {
          console.log('[DEV] Files changed, reloading page...');
          window.location.reload();
        }
        lastStatus = data.changeTime;
      } catch (err) {
        // Server error or not reachable (yet)
      }
    }, 1000);
  </script>
</body>
</html>`;
}

// ─── HTTP Server ─────────────────────────────────────────────────────────────
function serveFile(filePath, res) {
  const fullPath = path.resolve(__dirname, filePath);

  // Security: prevent directory traversal
  if (!fullPath.startsWith(path.resolve(__dirname))) {
    res.writeHead(403);
    res.end("Forbidden");
    return;
  }

  if (!fs.existsSync(fullPath)) {
    res.writeHead(404, { "Content-Type": "text/html" });
    res.end("<h1>404 Not Found</h1><p>" + filePath + "</p>");
    return;
  }

  const stat = fs.statSync(fullPath);
  if (stat.isDirectory()) {
    res.writeHead(403);
    res.end("Forbidden");
    return;
  }

  const ext = path.extname(fullPath).toLowerCase();
  const mimeTypes = {
    ".html": "text/html",
    ".css": "text/css",
    ".js": "application/javascript",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
  };

  const mimeType = mimeTypes[ext] || "application/octet-stream";
  res.writeHead(200, {
    "Content-Type": mimeType,
    "Cache-Control": "no-cache",
  });
  res.end(fs.readFileSync(fullPath));
}

function proxyRequest(reqUrl, method, headers, body, res) {
  const target = new URL(reqUrl, BACKEND_URL);
  const options = {
    hostname: target.hostname,
    port: target.port,
    path: target.pathname + target.search,
    method: method,
    headers: {
      ...headers,
      "Host": target.host,
    },
  };

  // Remove hop-by-hop headers
  delete options.headers["connection"];
  delete options.headers["transfer-encoding"];
  delete options.headers["content-length"];

  const proxyReq = http.request(options, (proxyRes) => {
    res.writeHead(proxyRes.statusCode, proxyRes.headers);
    proxyRes.pipe(res);
  });

  proxyReq.on("error", (err) => {
    console.error(`Proxy error:`, err.message);
    res.writeHead(502, { "Content-Type": "text/plain" });
    res.end(`Bad Gateway: ${err.message}`);
  });

  if (body) {
    proxyReq.write(body);
  }
  proxyReq.end();
}

const server = http.createServer((req, res) => {
  const parsedUrl = new URL(req.url, `http://${req.headers.host || "localhost"}`);
  const pathname = parsedUrl.pathname;

  // ─── Dev Status (for hot reload polling) ──────────────────────────────────
  if (pathname === "/dev-status") {
    res.writeHead(200, {
      "Content-Type": "application/json",
      "Cache-Control": "no-cache",
    });
    res.end(JSON.stringify({ changeTime: lastChangeTime }));
    return;
  }

  // ─── API Proxy ───────────────────────────────────────────────────────────
  if (pathname.startsWith("/api/")) {
    console.log(`[API] ${req.method} ${pathname}`);
    let body = "";
    req.on("data", (chunk) => {
      body += chunk;
    });
    req.on("end", () => {
      proxyRequest(pathname + parsedUrl.search, req.method, req.headers, body, res);
    });
    return;
  }

  // ─── Root → Dev HTML ────────────────────────────────────────────────────
  if (pathname === "/" || pathname === "") {
    res.writeHead(200, {
      "Content-Type": "text/html",
      "Cache-Control": "no-cache",
    });
    res.end(generateDevHtml());
    return;
  }

  // ─── Static Files ───────────────────────────────────────────────────────
  if (pathname.startsWith("/public/")) {
    serveFile(pathname.slice(1), res); // Remove /public prefix
    return;
  }

  // Try serving from public/
  const publicFile = path.join(__dirname, "public", pathname);
  if (fs.existsSync(publicFile) && fs.statSync(publicFile).isFile()) {
    serveFile(path.join("public", pathname), res);
    return;
  }

  // ─── 404 ────────────────────────────────────────────────────────────────
  res.writeHead(404, { "Content-Type": "text/html" });
  res.end("<h1>404 Not Found</h1><p>" + pathname + "</p>");
});

// ─── Startup ─────────────────────────────────────────────────────────────────
server.listen(PORT, () => {
  console.log(`
╔════════════════════════════════════════════════════════════════╗
║                  MCP Dashboard Dev Server                      ║
╚════════════════════════════════════════════════════════════════╝

  Local:        http://localhost:${PORT}
  Backend:      ${BACKEND_URL}

  Commands:
    npm run build    Compile to dist/index.html (production)
    npm run dev      Start dev server (you are here)

  Features:
    - Edit files in src/ for hot-reload
    - /api/* proxied to backend on 8420
    - No npm packages needed

  Watching: ${COMPONENT_ORDER.length} files
`);

  watchFiles();
});

// ─── Graceful Shutdown ───────────────────────────────────────────────────────
process.on("SIGINT", () => {
  console.log("\n\nShutting down...");
  fileWatchers.forEach((f) => fs.unwatchFile(f));
  server.close(() => {
    console.log("Dev server stopped.");
    process.exit(0);
  });
});
