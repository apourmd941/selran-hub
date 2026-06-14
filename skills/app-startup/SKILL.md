---
name: app-startup
description: Use this skill when creating or updating start/stop scripts for any app with a backend+frontend, or when the user asks to "start the app", "run the app", "fix port conflicts", "make ports dynamic", or set up app launch scripts. Handles safe process cleanup, dynamic port allocation via the shared port registry service, and verified process identity. Also use when scaffolding a new app's start.sh/stop.sh.
---

# App Startup — Safe Process Management & Port Registry

## ⛔ STRICT RULES — CANNOT BE BYPASSED

These rules apply to EVERY app, EVERY time, with NO exceptions:

1. **ALL ports MUST come from the port registry service at `127.0.0.1:11999`.** No hardcoded ports. No fallback ranges. No "just use 8000". The CLI wrapper `app-port-registry` talks to the same backend.
2. **Never read or write `~/.config/app-ports.json` directly.** The internal SQLite store is a private implementation detail. All access goes through the service or CLI only.
3. **Port range is 12000-14000 ONLY.** No ports outside this range for any app.
4. **Each app gets exactly one stable 5-port block.** Slot 0 = backend, slot 1 = frontend, slots 2-4 = reserved. No ad-hoc fallback ports. No reassignment during routine startup.
5. **Every app MUST use `ensure`** on startup to get its assigned ports. `ensure` is create-if-missing: if the app ID or canonical path is already registered, it returns the existing assignment without allocating a new block.
6. **Start/stop scripts MUST kill stale processes on the app's assigned ports** before starting. Processes on your assigned ports are yours — kill them.
7. **Never use ports outside your assigned range.** Never fall back to arbitrary ports.
8. **These rules are non-negotiable.** No "quick hack", no "temporary workaround", no "just this once".

## Port Registry Service

**Endpoint:** `http://127.0.0.1:11999`
**CLI wrapper:** `app-port-registry` (same backend)

Single source of truth for port assignments across ALL apps and ALL tools (Claude Code, Codex, manual scripts, any AI agent).

### Service API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/v1/report` | List all registered apps |
| `GET` | `/v1/apps/<app_id>` | Get a specific app's registration |
| `GET` | `/v1/lookup?path=/absolute/path` | Look up an app by its canonical path |
| `POST` | `/v1/ensure` | Register (create-if-missing) an app |

### `POST /v1/ensure` — Request Body

```json
{
  "app_id": "my-app",
  "path": "/absolute/path/to/app",
  "description": "My App — what it does"
}
```

**Behavior:** If `app_id` already exists, or if `path` is already registered, returns the existing assignment. Otherwise allocates the next available 5-port block.

### CLI Equivalents

```bash
app-port-registry list --json
app-port-registry get <app-id> --json
app-port-registry lookup <absolute-path> --json
app-port-registry ensure <app-id> <absolute-path> --description "..." --json
```

### Response Format (from `ensure` or `get`)

```json
{
  "app_id": "my-app",
  "range": [12000, 12004],
  "path": "/absolute/path/to/app",
  "description": "My App — what it does"
}
```

## Startup Sequence

### Step 1: Resolve Ports via Registry Service

Call `ensure` to get the app's assigned port block. This is idempotent — safe to call every startup.

```bash
resolve_ports() {
    # Try service first
    RESULT=$(curl -sf http://127.0.0.1:11999/v1/ensure \
        -H "Content-Type: application/json" \
        -d "{\"app_id\": \"$APP_ID\", \"path\": \"$SCRIPT_DIR\", \"description\": \"$APP_DESCRIPTION\"}" 2>/dev/null)

    if [ $? -eq 0 ] && [ -n "$RESULT" ]; then
        PORT_START=$(echo "$RESULT" | python3 -c "import sys,json; r=json.load(sys.stdin); print(r['range'][0])")
        PORT_END=$(echo "$RESULT" | python3 -c "import sys,json; r=json.load(sys.stdin); print(r['range'][1])")
    else
        # Fallback: CLI wrapper
        RESULT=$(app-port-registry ensure "$APP_ID" "$SCRIPT_DIR" --description "$APP_DESCRIPTION" --json 2>/dev/null)
        PORT_START=$(echo "$RESULT" | python3 -c "import sys,json; r=json.load(sys.stdin); print(r['range'][0])")
        PORT_END=$(echo "$RESULT" | python3 -c "import sys,json; r=json.load(sys.stdin); print(r['range'][1])")
    fi

    if [ -z "$PORT_START" ]; then
        echo "ERROR: Could not resolve ports from registry service" >&2
        exit 1
    fi
}
```

### Step 2: Kill Previous Instances

Three layers of cleanup, in order:

#### Layer 1 — PID File
- Read `.app.pid` from the app's root directory
- Kill each saved PID (the file is written by THIS app's start script — trustworthy)

#### Layer 2 — Assigned Ports
- Kill ANY process on ports within the app's assigned range (12000-12004 etc.)
- These ports belong to this app by registry — no further identity check needed

#### Layer 3 — Orphan Search
- `pgrep -f "uvicorn.*app.main:app"` → verify cwd/command contains this app's path
- `pgrep -f "vite"` → verify cwd/command contains this app's path
- Use `lsof -p PID | grep cwd | awk '{for(i=9;i<=NF;i++) printf "%s ", $i}'` for paths with spaces

#### What NOT to do
- Never `pkill -f "uvicorn"` — kills ALL uvicorn instances
- Never `pkill -f "vite"` — kills ALL vite instances
- Never kill based on port number outside your assigned range
- Never use generic patterns like `node`, `python`, `npm`

### Step 3: Start Services on Assigned Ports

Backend always on slot 0 (PORT_START), frontend always on slot 1 (PORT_START + 1). No scanning, no fallback.

```bash
BACKEND_PORT=$PORT_START
FRONTEND_PORT=$((PORT_START + 1))
```

### Step 4: Generate Dynamic Frontend Config

```bash
cat > frontend/vite.config.dynamic.js << EOF
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: $FRONTEND_PORT,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://localhost:$BACKEND_PORT',
        changeOrigin: true,
      }
    }
  }
})
EOF
```

### Step 5: Start Services & Save PIDs

- Start backend with `--port $BACKEND_PORT`
- Start frontend with `--config vite.config.dynamic.js`
- Save PIDs to `.app.pid`
- Print actual URLs with port numbers

### Step 6: Clean Shutdown (trap)

```bash
cleanup() {
    kill $BACKEND_PID $FRONTEND_PID 2>/dev/null
    rm -f "$PID_FILE"
    rm -f frontend/vite.config.dynamic.js
}
trap cleanup INT TERM
wait
```

## File Structure

Every app MUST have:
```
app-root/
├── start.sh          — Smart startup with registry service lookup
├── stop.sh           — Verified shutdown (reads registry for port range)
├── .app.pid          — Runtime PID file (gitignored)
├── .gitignore        — Must include .app.pid and dynamic configs
```

## Gitignore Entries

```
.app.pid
frontend/vite.config.dynamic.js
```

## Cross-Platform Notes

- `lsof` is available on macOS and Linux
- On Windows, use `netstat -ano | findstr :PORT` and `tasklist /FI "PID eq ..."` equivalents
- PID file approach works across all platforms

## Guardrails

- If the registry service is unreachable, fail loudly — do NOT bypass and pick random ports
- Always clean up runtime files on shutdown
- The start script must be idempotent — running it twice safely restarts
- If identity verification fails for orphan search, warn the user — do NOT kill
