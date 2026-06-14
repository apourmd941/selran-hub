# MCP Server Dashboard Frontend - Modular Structure

This directory contains the modularized React components for the MCP Server Dashboard.
The codebase has been refactored from a single 695-line HTML file into well-organized,
documented, and reusable components.

## Directory Structure

```
src/
├── index.jsx                    # Entry point - mounts App to DOM
├── App.jsx                      # Main app component (orchestration & state)
├── theme.js                     # Color palette, icons, labels, global CSS
├── api.js                       # Backend API helper functions
└── components/
    ├── StatusDot.jsx            # Status indicator dot
    ├── Badge.jsx                # Status/type badge
    ├── Btn.jsx                  # Button components (Btn + SmallBtn)
    ├── StatCard.jsx             # Metric card
    ├── SearchInput.jsx          # Search field with icon
    ├── TabBar.jsx               # Tab navigation
    ├── SourceRow.jsx            # Single source in list
    ├── SourceModal.jsx          # Add/edit source form
    ├── SourceDetail.jsx         # Right panel with tables, preview, SQL
    ├── MCPConfigPanel.jsx       # MCP config with format/transport toggles
    ├── ImportExportPanel.jsx    # Backup/restore sources
    ├── LogPanel.jsx             # Request log viewer
    └── SettingsPanel.jsx        # System info & authentication
```

## Key Files

### `theme.js`
Centralized design system with colors, icons, labels, and global CSS.

**Exports:**
- `C` - Color palette object
- `icons` - Emoji icons for source types
- `labels` - Display names for source types
- `css` - Global CSS string

### `api.js`
All backend API calls in one place for easy maintenance and mocking.

**Key functions:**
- `fetchSources()`, `fetchStats()` - Data fetching
- `createSource()`, `updateSource()`, `deleteSource()` - CRUD
- `toggleSource()`, `checkSource()` - Source actions
- `fetchMCPConfig()`, `installMCPConfig()` - MCP setup
- `exportSources()`, `importSources()` - Backup/restore
- `fetchLogs()` - Server logs
- `fetchAuthStatus()`, `configureAuth()` - Authentication
- `fetchSystemInfo()` - System details

### `App.jsx`
Main component that orchestrates the entire dashboard:
- Manages global state (sources, statistics, modal visibility)
- Handles data fetching and background refresh (45s interval)
- Composes all child components
- Implements search and type filtering

## Component Overview

### Atomic Components (reusable UI elements)

**`StatusDot`** - Small colored circle indicating status (online/error/offline)

**`Badge`** - Pill-shaped label with color and background

**`Btn` and `SmallBtn`** - Button components
- `Btn`: Standard button with primary/danger variants
- `SmallBtn`: 30x30px circular icon button for quick actions

**`StatCard`** - Metric display card (total, online, offline, errors)

**`SearchInput`** - Text input with magnifying glass icon

**`TabBar`** - Horizontal tab navigation with optional counts

### Composite Components (feature panels)

**`SourceRow`** - List item displaying:
- Source type icon
- Name and path/URL
- Status badge
- Action buttons (visible on hover)

**`SourceModal`** - Form for adding/editing sources:
- Type selector (folder, DuckDB, SQLite, API)
- Path or URL input with file browser
- Description field
- Access rules (read-only, sensitive filter, row limit)

**`SourceDetail`** - Right-side detail panel:
- Header with source info and status badges
- Statistics display
- Clickable table/file list
- Data preview table (10 rows)
- SQL query console with results

**`MCPConfigPanel`** - MCP configuration modal:
- Client format selector (Claude Desktop, Generic)
- Transport mode selector (stdio for local, SSE for remote)
- JSON configuration display
- Copy and install buttons

**`ImportExportPanel`** - Backup/restore modal:
- Export tab: Download all sources as JSON
- Import tab: Paste JSON to restore

**`LogPanel`** - Request log viewer:
- Filterable by level (all, success, errors)
- Auto-refreshes every 5 seconds
- Auto-scrolls to latest

**`SettingsPanel`** - System settings modal:
- System information display
- API authentication toggle
- API key generation and display

## State Management

The App component manages:

**Data State**
- `sources` - Array of source objects
- `stats` - Dashboard statistics
- `loading` - Initial load state

**UI State**
- `selected` - Currently open detail panel (source object or null)
- `showAdd`, `showEdit`, `showConfig`, `showImport`, `showLogs`, `showSettings` - Modal visibility

**Filter State**
- `search` - Search query string
- `typeFilter` - Current type filter (all, folder, duckdb, sqlite, api)

## Data Flow

1. **Initial Load**: `useEffect` calls `refresh()` on mount
2. **Periodic Refresh**: Background interval calls `refresh()` every 45 seconds
3. **User Actions**: 
   - Adding/editing/deleting sources calls API and refreshes
   - Filter changes re-filter existing sources (no API call)
   - Clicking a source opens detail panel
4. **Detail Panel**: Fetches tables, preview, and query results on demand

## Styling Approach

All styling is inline using the `C` (colors) object from `theme.js`:
- Consistent color usage across components
- Easy theme switching by editing `theme.js`
- Global CSS in `css` string includes reset, animations, form defaults
- Component-specific styles via inline `style` objects

## Key Patterns

### API Calls
```javascript
// In components, import and use API functions
import { fetchSources, createSource } from "../api";

const data = await fetchSources();
```

### Color Usage
```javascript
// Import colors from theme
import { C } from "../theme";

<div style={{ background: C.surface, color: C.text }} />
```

### State Management
```javascript
// Use useState and useCallback for local state
const [items, setItems] = useState([]);
const refresh = useCallback(() => {
  fetchData().then(setItems);
}, []);
```

## Development Tips

### Adding a New Component
1. Create file in `components/`
2. Import `{ C }` from `../theme`
3. Import API functions as needed
4. Write clear JSDoc comments
5. Use existing components for consistency

### Modifying the Theme
Edit `theme.js` to change colors, icons, or add new animations.

### Adding API Endpoints
Add function to `api.js` following the existing pattern:
```javascript
export const fetchNewData = () =>
  fetch(`${API}/endpoint`).then((r) => r.json());
```

### Testing
Components use standard React hooks and can be tested with:
- React Testing Library
- Mock the `api.js` functions
- Test with different prop combinations

## Migration from Monolithic File

The original `dist/index.html` (695 lines) has been split into:
- 17 separate files
- Clear separation of concerns
- Reusable components
- Well-documented code

The original production file is preserved at:
`/sessions/eloquent-festive-hypatia/mnt/MCP-server-app/frontend/dist/index.html`

To build the modular version, use your build tool (Webpack, Vite, Create React App):
```bash
# Example with Vite
npm install
npm run dev
```

The built output should be placed in `/dist/index.html` to replace the monolithic version.
