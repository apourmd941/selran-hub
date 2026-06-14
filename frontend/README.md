# MCP Server Dashboard Frontend

A React 18 + Babel standalone frontend for the MCP Server Dashboard.

## Architecture

This project uses a **dual-mode development approach**:

- **Development** (`src/`): Individual component files with hot-reload via dev server
- **Production** (`dist/index.html`): Single-file bundle with React + Babel from CDN

No build step or npm packages are needed — everything runs with Node.js built-ins and browser APIs.

## Quick Start

### Development

```bash
# Start the dev server on port 3000
# API calls proxy to http://127.0.0.1:8420 automatically
node dev-server.js
```

Then open http://localhost:3000 in your browser.

**Features:**
- Hot reload — edit any file in `src/` and the page reloads automatically
- WebSocket-based live reload (no polling)
- API proxy to backend on 8420
- No npm install needed

### Production Build

```bash
# Concatenate all components into dist/index.html
node build.js
```

This creates a single HTML file with all components bundled together, ready for deployment.

## Project Structure

```
frontend/
├── package.json                    # Scripts only (no dependencies)
├── dev-server.js                   # Dev server with hot reload
├── build.js                        # Production builder
├── README.md                        # This file
│
├── public/
│   └── index.html                  # Static HTML template
│
├── src/
│   ├── theme.js                    # Color palette & icons
│   ├── api.js                      # API client utilities
│   ├── components/
│   │   ├── StatusDot.jsx           # Status indicator
│   │   ├── Badge.jsx               # Badge component
│   │   ├── Btn.jsx                 # Button components
│   │   ├── StatCard.jsx            # Stats card
│   │   ├── SearchInput.jsx         # Search bar
│   │   ├── TabBar.jsx              # Tab navigation
│   │   ├── SourceRow.jsx           # Data source row
│   │   ├── SourceModal.jsx         # Add/edit source modal
│   │   ├── SourceDetail.jsx        # Detail panel (sidebar)
│   │   ├── MCPConfigPanel.jsx      # MCP config viewer
│   │   ├── ImportExportPanel.jsx   # Import/export utilities
│   │   ├── LogPanel.jsx            # Activity logs
│   │   └── SettingsPanel.jsx       # Settings
│   └── App.jsx                     # Root component
│
└── dist/
    └── index.html                  # Production bundle (generated)
```

## Adding Components

To add a new component:

1. **Create file** in `src/components/ComponentName.jsx`
2. **Write component** using React hooks (no imports needed in dev)
3. **Update concatenation order** in `dev-server.js` and `build.js` if dependencies exist
4. **Dev server auto-reloads** on save
5. **Run `node build.js`** to include in production bundle

Example component:

```jsx
// src/components/MyComponent.jsx
function MyComponent({ title }) {
  const [count, setCount] = useState(0);
  return (
    <div>
      <h3>{title}</h3>
      <button onClick={() => setCount(count + 1)}>
        Clicks: {count}
      </button>
    </div>
  );
}
```

## Theme & Styling

Colors and icons are centralized in `src/theme.js`:

```javascript
const colors = {
  bg: "#0f1117",
  accent: "#6366f1",
  green: "#22c55e",
  // ... more colors
};
```

Import and use in components (in production, everything is concatenated, so imports are stripped).

## API Integration

The `src/api.js` file provides utilities for calling the backend:

```javascript
const API = "/api";  // Proxied to http://127.0.0.1:8420

// Dev server automatically proxies /api/* requests
fetch(`${API}/sources`).then(r => r.json());
```

## Commands

| Command | Purpose |
|---------|---------|
| `node dev-server.js` | Start development server (port 3000, hot reload) |
| `node build.js` | Build single-file production bundle |

## Browser Support

- Modern Chrome, Firefox, Safari, Edge (ES2018+)
- Uses React 18 from unpkg CDN
- Babel standalone for JSX in the browser

## Deployment

### Option 1: Simple HTTP Server

```bash
# Build the bundle
node build.js

# Serve the file
python3 -m http.server --directory dist 8080
```

Then access at http://localhost:8080

### Option 2: Production Server

Copy `dist/index.html` to your web server (Nginx, Apache, etc.) and serve from any path.

## Troubleshooting

### Dev server won't start

```bash
# Check if port 3000 is in use
lsof -i :3000

# Use a different port
PORT=4000 node dev-server.js
```

### Components not loading in dev

Check that all files in `COMPONENT_ORDER` exist. The dev server logs missing files on startup.

### Hot reload not working

- Check browser console for errors (Ctrl+Shift+J)
- Ensure WebSocket connection is open (DevTools → Network → WS)
- Restart the dev server

### Production build too large

The current build includes React 18 + Babel from CDN, plus all component code. This is intentional for single-file deployment. Minification happens at the CDN level.

## Notes

- No npm packages = no `node_modules`, no lock files, no dependency hell
- All styling is inline (no CSS files) for simplicity
- Components use React hooks (useState, useEffect, useCallback, useRef)
- The dev server uses only Node.js built-ins: `http`, `fs`, `path`, `url`, `ws`
- File concatenation order matters — list dependencies in the correct order in the scripts

## License

Same as parent MCP Server project.
