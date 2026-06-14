# Understanding MCP Servers — A Plain-Language Guide

**Audience**: Anyone — no programming experience required  
**Last Updated**: April 2026  
**Version**: 1.0

---

## What Is This Guide?

This guide explains everything you need to know about:

1. **What an MCP server is** and why it matters
2. **What a management app (dashboard) does** for it
3. **All the requirements** that make one robust and production-ready

We use pictures, diagrams, and tables — no code, no jargon.

---

## Table of Contents

1. [The Big Picture — What Problem Does This Solve?](#1-the-big-picture)
2. [How the Pieces Fit Together](#2-how-the-pieces-fit-together)
3. [The MCP Server — Your Data Translator](#3-the-mcp-server)
4. [The Dashboard App — Your Control Center](#4-the-dashboard-app)
5. [All Requirements at a Glance](#5-all-requirements-at-a-glance)
6. [Deep Dive: MCP Server Requirements](#6-deep-dive-mcp-server-requirements)
7. [Deep Dive: Dashboard App Requirements](#7-deep-dive-dashboard-app-requirements)
8. [Security — Keeping Everything Safe](#8-security)
9. [Cross-Platform — Works Everywhere](#9-cross-platform)
10. [Common Questions](#10-common-questions)
11. [Glossary](#11-glossary)

---

## 1. The Big Picture

### The Problem

Imagine you have research data spread across many places:

```
Your Data World
═══════════════════════════════════════════════════════

  📁 A folder full of CSV spreadsheets
  🗄️ A SQLite database from your lab software
  🦆 A DuckDB file with processed results
  🌐 A web API that serves live data

═══════════════════════════════════════════════════════
```

Now you want an AI assistant (like Claude) to help you analyze that data. But the AI has no idea where your files live, what format they're in, or how to open them.

### The Solution

You put a **translator** between the AI and your data. That translator is the **MCP Server**.

```
┌─────────────┐          ┌─────────────┐          ┌─────────────┐
│             │          │             │          │             │
│  AI Client  │◄────────►│  MCP Server │◄────────►│  Your Data  │
│  (Claude)   │ Standard │ (Translator)│  Knows   │  (Files,    │
│             │ Language  │             │  How To  │  Databases, │
│             │  (MCP)    │             │  Read    │  APIs)      │
└─────────────┘          └─────────────┘          └─────────────┘
```

The AI speaks **MCP** (Model Context Protocol) — a standard language. The server translates that into whatever your data needs.

---

## 2. How the Pieces Fit Together

Here's the full system with all three parts:

```
┌─────────────────────────────────────────────────────────────────────┐
│                        YOUR COMPUTER                                │
│                                                                     │
│  ┌──────────┐    stdio     ┌──────────────┐    HTTP     ┌────────┐ │
│  │          │◄────────────►│              │◄───────────►│        │ │
│  │    AI    │  (messages   │  MCP Bridge  │  (requests  │ Dash-  │ │
│  │  Client  │   back and   │  (thin pipe) │   to the    │ board  │ │
│  │          │   forth)     │              │   server)   │  App   │ │
│  └──────────┘              └──────────────┘             └───┬────┘ │
│                                                             │      │
│                                    ┌────────────────────────┘      │
│                                    │ manages                       │
│                                    ▼                               │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                     DATA SOURCES                            │   │
│  │                                                             │   │
│  │   📁 Folders     🗄️ SQLite     🦆 DuckDB     🌐 APIs      │   │
│  │   (CSV, Excel,   (databases)   (analytics    (web          │   │
│  │    JSON, etc.)                  databases)    services)     │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

**Three distinct parts:**

| Part | What It Is | Analogy |
|------|-----------|---------|
| **MCP Bridge** | A thin pipe that speaks the AI's language and passes requests to the dashboard | A phone interpreter on a conference call |
| **Dashboard App** | The brain — manages sources, runs queries, shows a web interface | The restaurant manager's office |
| **Connectors** | Adapters that know how to read each type of data | Different plug adapters for different countries |

---

## 3. The MCP Server

### What Does "MCP" Even Mean?

**MCP = Model Context Protocol**

Think of it like USB. Before USB, every device had its own cable — printers, cameras, phones all needed different plugs. USB created one standard plug that works with everything.

MCP does the same thing for AI + data:

```
BEFORE MCP                              AFTER MCP
══════════                              ═════════

AI ──special code──► CSV files          AI ──── MCP ────► Any data source
AI ──special code──► Databases                            (one standard
AI ──special code──► APIs                                  language)
AI ──special code──► Spreadsheets

(Every data type needs custom work)     (Write once, works with everything)
```

### The 9 Data Tools the AI Can Use

The MCP server gives the AI a specific set of **tools** — like buttons it can press. Each tool does one thing:

```
┌─────────────────────────────────────────────────────────────┐
│                    MCP TOOL BELT                            │
│                                                             │
│  ┌───────────────┐  ┌───────────────┐  ┌────────────────┐  │
│  │ 🔍 list       │  │ ℹ️ source     │  │ 📋 list        │  │
│  │    sources    │  │    info       │  │    tables      │  │
│  │               │  │               │  │                │  │
│  │ "What data    │  │ "Tell me      │  │ "What tables   │  │
│  │  sources      │  │  about this   │  │  are inside    │  │
│  │  exist?"      │  │  source"      │  │  this source?" │  │
│  └───────────────┘  └───────────────┘  └────────────────┘  │
│                                                             │
│  ┌───────────────┐  ┌───────────────┐  ┌────────────────┐  │
│  │ 👀 preview    │  │ 📊 table      │  │ 🔎 query       │  │
│  │    data       │  │    schema     │  │    source      │  │
│  │               │  │               │  │                │  │
│  │ "Show me the  │  │ "What are     │  │ "Run this SQL  │  │
│  │  first few    │  │  the column   │  │  question on   │  │
│  │  rows"        │  │  names/types?"│  │  the data"     │  │
│  └───────────────┘  └───────────────┘  └────────────────┘  │
│                                                             │
│  ┌───────────────┐  ┌───────────────┐  ┌────────────────┐  │
│  │ 📈 describe   │  │ 📉 dashboard  │  │ ❤️ check       │  │
│  │    source     │  │    stats      │  │    source      │  │
│  │               │  │               │  │                │  │
│  │ "Give me      │  │ "How is the   │  │ "Is this       │  │
│  │  statistics   │  │  overall      │  │  source still   │  │
│  │  for a table" │  │  system?"     │  │  working?"     │  │
│  └───────────────┘  └───────────────┘  └────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### The Typical AI Workflow

When an AI assistant uses your MCP server, it follows a natural discovery flow:

```
Step 1          Step 2          Step 3          Step 4          Step 5
───────         ───────         ───────         ───────         ───────
"What           "What's         "What           "Show me        "Run
sources         in this         tables          the first       this
do I            source?"        are in          20 rows"        query"
have?"                          there?"

list_sources → source_info → list_tables → preview_data → query_source
     │              │              │              │              │
     ▼              ▼              ▼              ▼              ▼
 Returns a      Returns         Returns        Returns a      Returns
 list of all    health,         table names    sample of      full
 registered     type,           and sizes      the data       results
 sources        stats
```

### Two interactive UI tools (MCP Apps / SEP-1865)

Beyond the nine data tools, the bridge ships two **MCP Apps** tools that render
an interactive panel *inline in the chat* (in hosts that support SEP-1865):

- `design_picker` — the seven Design Director directions as clickable cards; the
  user's pick is sent straight back to the conversation.
- `data_sources_panel` — your connected sources as a clickable table.

Each is a `ui://` HTML resource (mimeType `text/html;profile=mcp-app`) linked
from the tool via `_meta.ui.resourceUri`. Both also return a complete text +
`structuredContent` result, so an assistant whose client does **not** render MCP
Apps (Claude does not yet — it falls back to the text) still gets everything it
needs to present the options. Renders today in Goose, VS Code, and ChatGPT.

---

## 4. The Dashboard App

The dashboard is a **web page** that runs in your browser. It's the control center where you manage everything without needing to type commands.

### What the Dashboard Looks Like (Conceptually)

```
┌─────────────────────────────────────────────────────────────────┐
│  MCP Server Dashboard                    🔍 Search sources...   │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────┬──────────┬──────────┬──────────┬─────────────────┐ │
│  │   All   │  Folder  │  DuckDB  │  SQLite  │      API        │ │
│  │  (12)   │   (5)    │   (3)    │   (2)    │      (2)        │ │
│  └─────────┴──────────┴──────────┴──────────┴─────────────────┘ │
│                                                                 │
│  ┌──────────────────────────────────┐  ┌────────────────────┐   │
│  │  🟢 Patient Demographics         │  │  Source Details     │   │
│  │     Folder · 4 tables · Online   │  │                    │   │
│  ├──────────────────────────────────┤  │  Type: Folder      │   │
│  │  🟢 Lab Results 2024             │  │  Tables: 4         │   │
│  │     DuckDB · 12 tables · Online  │  │  Rows: 15,420      │   │
│  ├──────────────────────────────────┤  │  Size: 2.3 MB      │   │
│  │  🔴 Old Archive                  │  │  Status: 🟢 Online │   │
│  │     SQLite · Error: file moved   │  │                    │   │
│  ├──────────────────────────────────┤  │  ┌──────────────┐  │   │
│  │  ⚫ Disabled Source              │  │  │ SQL Console  │  │   │
│  │     API · Offline (disabled)     │  │  │              │  │   │
│  └──────────────────────────────────┘  │  │ SELECT *     │  │   │
│                                        │  │ FROM patients│  │   │
│  ┌─ + Add Source ───────────────────┐  │  │ LIMIT 10     │  │   │
│  │  Name: ___________               │  │  │              │  │   │
│  │  Type: [Folder ▼]               │  │  │  [▶ Run]    │  │   │
│  │  Path: ___________               │  │  └──────────────┘  │   │
│  └──────────────────────────────────┘  └────────────────────┘   │
│                                                                 │
│  ┌─ Logs ─────────────────────────────────────────────────────┐ │
│  │  10:23:05  GET /api/sources         200  OK     12ms       │ │
│  │  10:23:08  POST /api/sources/q      200  OK     145ms      │ │
│  │  10:23:15  GET /api/sources/abc     404  Error  3ms        │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### Dashboard Panels

| Panel | What It Does | Why You Need It |
|-------|-------------|-----------------|
| **Source List** | Shows all your registered data sources with status indicators (green = working, red = error, gray = disabled) | See the health of all your data at a glance |
| **Source Detail** | Shows stats, tables, and a SQL console for the selected source | Explore and verify data without other tools |
| **Search & Filter** | Search by name, filter by type (Folder, DuckDB, SQLite, API) | Find what you need quickly when you have many sources |
| **Log Viewer** | Shows every request to the server — what happened, when, success or failure | Troubleshoot issues and see what the AI is doing |
| **Settings** | Enable/disable authentication, view system info | Control who can access the server |
| **Import/Export** | Download your source configs as a file, or upload configs from another machine | Move your setup between computers |

---

## 5. All Requirements at a Glance

Here's every requirement in one table, organized by category. Green items are about the MCP server, blue items are about the dashboard app, and orange items apply to both.

### Requirements Summary Table

| # | Requirement | Category | Why It Matters |
|---|------------|----------|---------------|
| **MCP SERVER** | | | |
| 1 | Connect to multiple data types | Data Access | Your data lives in different formats |
| 2 | Read-only enforcement | Safety | AI must never accidentally change your data |
| 3 | Clear set of AI tools | AI Integration | AI needs specific, predictable commands |
| 4 | Standard communication | Compatibility | Must work with any AI client that supports MCP |
| 5 | Graceful error handling | Reliability | Problems should be reported clearly, not crash |
| 6 | SQL query engine | Data Access | The universal language for asking data questions |
| 7 | Descriptive statistics | Analysis | Quick min/max/avg/count without writing queries |
| **DASHBOARD APP** | | | |
| 8 | Source management (CRUD) | Management | Add, edit, remove, enable/disable data sources |
| 9 | Health monitoring | Monitoring | Know immediately if a source goes down |
| 10 | Data exploration UI | Usability | Browse tables, preview rows, see schemas |
| 11 | SQL console | Power Users | Run custom queries from the browser |
| 12 | Full REST API | Automation | Every action available programmatically |
| 13 | Import/export configs | Portability | Move your setup between machines |
| 14 | Request logging | Troubleshooting | See what happened and when |
| 15 | Background health polling | Awareness | Auto-refresh status without manual clicking |
| 16 | No build step frontend | Simplicity | Works immediately, no extra tools needed |
| **BOTH** | | | |
| 17 | Authentication (API key) | Security | Lock access to authorized users only |
| 18 | Rate limiting | Protection | Prevent runaway requests from overwhelming system |
| 19 | Cross-platform support | Compatibility | Works on Mac, Windows, and Linux |
| 20 | Background service mode | Convenience | Runs without keeping a terminal window open |
| 21 | Headless detection | Robustness | Knows when there's no screen (server mode) |
| 22 | Auto-registration with AI clients | Setup | AI clients discover the server automatically |
| 23 | Structured error codes | Consistency | Standard error format across everything |

---

## 6. Deep Dive: MCP Server Requirements

### Requirement 1 — Connect to Multiple Data Types

Your data comes in many shapes. The server needs a **connector** for each type:

```
DATA TYPE           CONNECTOR           HOW IT WORKS
═════════           ═════════           ════════════

📁 CSV files    ──► Folder          ──► Scans the folder, treats each
📁 Excel files      Connector           file as a virtual database table
📁 JSON files                           using DuckDB as the engine
📁 Parquet files

🦆 .duckdb     ──► DuckDB          ──► Opens the database file directly
   files            Connector           in read-only mode

🗄️ .db or      ──► SQLite          ──► Opens with a special read-only
   .sqlite          Connector           connection string
   files

🌐 REST APIs   ──► API             ──► Fetches data from web URLs,
   (web URLs)       Connector           loads into temporary tables
                                        for querying
```

**Why it's pluggable:** The connector system is designed so new types can be added later without changing existing code. Think of it like apps on a phone — you can install new ones without replacing the phone.

```
┌────────────────────────────────────────────────────────┐
│              CONNECTOR PLUGIN SYSTEM                   │
│                                                        │
│   Every connector must do these 4 things:              │
│                                                        │
│   ┌──────────────────────────────────────────────┐     │
│   │  1. Health Check     "Am I still connected?" │     │
│   │  2. Get Stats        "How big is this data?" │     │
│   │  3. List Tables      "What tables exist?"    │     │
│   │  4. Preview Data     "Show me sample rows"   │     │
│   └──────────────────────────────────────────────┘     │
│                                                        │
│   And optionally:                                      │
│                                                        │
│   ┌──────────────────────────────────────────────┐     │
│   │  5. Query   (run SQL)                        │     │
│   │  6. Describe (column-level statistics)        │     │
│   └──────────────────────────────────────────────┘     │
│                                                        │
│   New connector types follow this same template.       │
└────────────────────────────────────────────────────────┘
```

---

### Requirement 2 — Read-Only Enforcement (Safety)

This is one of the most critical requirements. Your data must be **protected from accidental changes**.

The server enforces this at **two separate levels** — like having both a lock on the door and a security guard:

```
                    YOUR DATA
                    ─────────

Level 1: SQL Keyword Blocking (the security guard)
══════════════════════════════════════════════════

   Incoming query: "DELETE FROM patients WHERE id = 5"
                          │
                          ▼
                ┌───────────────────┐
                │  BLOCKED WORDS:   │
                │                   │
                │  ✗ INSERT         │
                │  ✗ UPDATE         │──► "Sorry, write
                │  ✗ DELETE         │    operations are
                │  ✗ DROP           │    not allowed"
                │  ✗ CREATE         │
                │  ✗ ALTER          │
                │  ✗ TRUNCATE       │
                └───────────────────┘


Level 2: Driver-Level Read-Only (the locked door)
═══════════════════════════════════════════════════

   Even if something slips past Level 1:

   SQLite  ──► Opened with "?mode=ro" (read-only at the database level)
   DuckDB  ──► Opened with read_only=True
   Folders ──► DuckDB views are inherently read-only
   APIs    ──► Only GET requests, no POST/PUT/DELETE
```

**Why two levels?** Defense in depth. If a clever query somehow sneaks past the keyword blocker, the database itself refuses to make changes. No single failure can compromise your data.

---

### Requirement 3 — Clear AI Tools

The AI can't just "figure things out." It needs a specific menu of actions:

| Tool | What the AI Asks | What It Gets Back |
|------|-----------------|-------------------|
| `list_sources` | "What data sources are available?" | Names, types, and status of all sources |
| `source_info` | "Tell me about source X" | Type, health, table count, row count, size |
| `list_tables` | "What tables are in source X?" | Table names with row counts and columns |
| `preview_data` | "Show me the first 20 rows of table Y" | Column headers + sample data |
| `table_schema` | "What columns does table Y have?" | Column names, data types, nullable |
| `query_source` | "Run this SQL on source X" | Query results (up to 1,000 rows) |
| `describe_source` | "Give me statistics for table Y" | Min, max, average, std deviation, null count |
| `dashboard_stats` | "How's the overall system?" | Total sources, online count, error count |
| `check_source` | "Is source X still healthy?" | Current status + any error messages |

---

### Requirement 4 — Standard Communication (stdio)

The AI and server need a way to send messages back and forth. There are two main options:

```
Option A: stdio (what we use)
═════════════════════════════

   AI Client ◄──── text messages via stdin/stdout ────► MCP Server

   ✅ Works everywhere (Mac, Windows, Linux)
   ✅ Works with every AI client
   ✅ Simple — no network configuration needed
   ✅ Secure — no open ports


Option B: SSE (Server-Sent Events)
══════════════════════════════════

   AI Client ◄──── HTTP connection over network ────► MCP Server

   ✅ Can work over network (remote servers)
   ❌ Requires port configuration
   ❌ Firewall issues possible
   ❌ Not all AI clients support it yet
```

We chose **stdio** because it just works without any setup.

---

### Requirement 5 — Graceful Error Handling

When something goes wrong, the server should explain what happened clearly, not crash or return gibberish:

```
BAD (without structured errors):
════════════════════════════════
   Traceback (most recent call last):
     File "/usr/lib/python3.10/json/decoder.py", line 355
       raise JSONDecodeError("Expecting value", s, err.value)
   json.decoder.JSONDecodeError: Expecting value: line 1 column 1

   ...what? 😵


GOOD (with structured errors):
══════════════════════════════
   {
     "code": "NOT_FOUND",
     "message": "Source 'patient_data' does not exist",
     "detail": "Available sources: lab_results, demographics"
   }

   ...clear! I know exactly what went wrong and what to do. ✅
```

**The five error categories:**

| Error Code | When It Happens | Example |
|-----------|----------------|---------|
| `NOT_FOUND` | You asked for something that doesn't exist | "Source 'xyz' not found" |
| `BAD_REQUEST` | Your request was formatted wrong | "Missing required field: name" |
| `UNAUTHORIZED` | Auth is on and you didn't provide a key | "API key required" |
| `RATE_LIMITED` | Too many requests too fast | "Limit exceeded, try again in 30s" |
| `INTERNAL_ERROR` | Something unexpected broke | "Database connection failed" |

---

### Requirement 6 — SQL Query Engine

SQL is the universal language for asking questions about data. Even non-database sources (like CSV files) become queryable through DuckDB:

```
Your CSV file "patients.csv":                 You can now ask:
═══════════════════════════                   ════════════════

  id, name,    age, diagnosis                 SELECT AVG(age)
  1,  Alice,   34,  FAI                       FROM patients
  2,  Bob,     28,  FAI                       WHERE diagnosis = 'FAI'
  3,  Carol,   41,  Labral tear
  4,  Dave,    55,  OA                              │
                                                    ▼
       │                                       Result: 31.0
       │ loaded as virtual table
       ▼
  ┌──────────────┐
  │    DuckDB    │ ◄── Treats the CSV as if it were
  │  (in memory) │     a real database table
  └──────────────┘
```

---

### Requirement 7 — Descriptive Statistics

For any table, you should be able to get a quick statistical summary without writing SQL:

```
describe("patients", "age")

┌─────────────────────────────────────────────┐
│  Column: age                                │
│  Type:   numeric                            │
│                                             │
│  Count:      150        (non-null values)   │
│  Nulls:        3        (missing values)    │
│  Min:         18                            │
│  Max:         82                            │
│  Average:    43.7                           │
│  Std Dev:    15.2       (how spread out)    │
│                                             │
│  Column: name                               │
│  Type:   text                               │
│                                             │
│  Count:      153                            │
│  Nulls:        0                            │
│  Distinct:   148        (unique values)     │
│  Top Value:  "Smith"    (most common)       │
└─────────────────────────────────────────────┘
```

This is especially useful for research data where you need to quickly sanity-check datasets — "Does the age range look reasonable? How many missing values are there?"

---

## 7. Deep Dive: Dashboard App Requirements

### Requirement 8 — Source Management (CRUD)

CRUD stands for Create, Read, Update, Delete — the four basic operations:

```
┌──────────────────────────────────────────────────────────────┐
│                    SOURCE LIFECYCLE                           │
│                                                              │
│  ➕ CREATE                                                   │
│  "I want to add my lab data folder as a source"              │
│   → Give it a name, pick type, point to location             │
│   → System checks health immediately                         │
│                                                              │
│  👁️ READ                                                     │
│  "Show me all my sources and their status"                   │
│   → List view with green/red status dots                     │
│                                                              │
│  ✏️ UPDATE                                                    │
│  "The folder moved, I need to change the path"              │
│   → Edit name, path, URL, rules, or description              │
│   → System re-checks health after path changes               │
│                                                              │
│  🗑️ DELETE                                                    │
│  "I don't need this source anymore"                          │
│   → Removes registration (never touches the actual data!)    │
│                                                              │
│  ⏸️ TOGGLE                                                    │
│  "Temporarily disable this without deleting it"              │
│   → Source stays registered but AI won't see it              │
└──────────────────────────────────────────────────────────────┘
```

**Important:** Deleting a source from the dashboard only removes the *registration*. It never touches, moves, or deletes the actual data files.

---

### Requirement 9 — Health Monitoring

```
Automatic Health Check (every 45 seconds)
═════════════════════════════════════════

   Time 0:00    Dashboard checks all sources
                   📁 Lab Data ──► folder exists? ──► 🟢 Online
                   🗄️ Archive  ──► file exists?  ──► 🟢 Online
                   🌐 NIH API  ──► responds?     ──► 🟢 Online

   Time 0:45    Dashboard checks again
                   📁 Lab Data ──► folder exists? ──► 🟢 Online
                   🗄️ Archive  ──► file moved!   ──► 🔴 Error: file not found
                   🌐 NIH API  ──► responds?     ──► 🟢 Online

   You see the red dot immediately — no surprises
   when the AI tries to use that source later.
```

---

### Requirement 10 — Data Exploration UI

You should be able to browse your data visually:

```
Step 1: Click a source          Step 2: See its tables       Step 3: Preview any table
─────────────────────           ─────────────────────        ────────────────────────

┌─────────────────┐            Tables in "Lab Data":        Table: "blood_work.csv"
│ 🟢 Lab Data     │  ──►                                    ──►
│    Folder        │            ┌──────────┬──────┐          ┌────┬───────┬─────┐
│    4 tables      │            │ Name     │ Rows │          │ id │ name  │ WBC │
└─────────────────┘            ├──────────┼──────┤          ├────┼───────┼─────┤
                               │ blood    │ 150  │          │ 1  │ Alice │ 7.2 │
                               │ vitals   │ 150  │          │ 2  │ Bob   │ 6.8 │
                               │ imaging  │  45  │          │ 3  │ Carol │ 8.1 │
                               │ outcomes │ 150  │          │ .. │ ...   │ ... │
                               └──────────┴──────┘          └────┴───────┴─────┘
```

---

### Requirement 12 — Full REST API

Behind the dashboard's visual interface, there's a complete **API** (Application Programming Interface). Think of the dashboard as a TV remote — the API is the infrared signals it sends.

**Why does the API matter?** Three reasons:

```
Reason 1: The MCP Bridge uses it
════════════════════════════════
   AI tool call → MCP Bridge → HTTP request to API → Response → AI

Reason 2: Scripts can automate tasks
════════════════════════════════════
   A script can add 50 sources at once through the API
   instead of clicking through the dashboard 50 times

Reason 3: Other apps can integrate
═══════════════════════════════════
   A lab management system could check source health
   via the API without opening the dashboard
```

**All 22 API endpoints:**

| Endpoint | What It Does |
|----------|-------------|
| **System** | |
| `GET /api/health` | "Is the server alive?" |
| `GET /api/info` | Server version, OS, Python version |
| `GET /api/stats` | Total sources, online/error/offline counts |
| `GET /api/logs` | Recent request log entries |
| **Source Management** | |
| `POST /api/sources` | Register a new data source |
| `GET /api/sources` | List all sources with status |
| `GET /api/sources/{id}` | Get details for one source |
| `PATCH /api/sources/{id}` | Update a source's settings |
| `DELETE /api/sources/{id}` | Remove a source |
| `POST /api/sources/{id}/toggle` | Enable/disable a source |
| `POST /api/sources/{id}/check` | Force a health re-check |
| **Data Exploration** | |
| `GET /api/sources/{id}/tables` | List tables in a source |
| `GET /api/sources/{id}/tables/{table}/preview` | Preview rows from a table |
| `POST /api/sources/{id}/query` | Run a SQL query |
| `GET /api/sources/{id}/tables/{table}/describe` | Get statistics for a table |
| **Authentication** | |
| `GET /api/auth/status` | Is auth enabled? |
| `POST /api/auth/configure` | Turn auth on/off, set key |
| **MCP Configuration** | |
| `GET /api/mcp/config` | Generate MCP config for AI clients |
| `POST /api/mcp/install` | Auto-register with Claude Desktop |
| **Import/Export** | |
| `GET /api/sources/export` | Download all source configs as JSON |
| `POST /api/sources/import` | Upload source configs from JSON |

---

### Requirement 13 — Import/Export

```
EXPORT (backup or transfer)
═══════════════════════════

   Your Dashboard                     JSON File
   ┌──────────────┐                  ┌──────────────┐
   │ 🟢 Lab Data  │                  │ {            │
   │ 🟢 Archive   │ ──── Export ──── │   sources: [ │
   │ 🟢 NIH API   │                  │     {...},   │
   └──────────────┘                  │     {...},   │
                                     │     {...}    │
                                     │   ]          │
                                     │ }            │
                                     └──────────────┘

IMPORT (restore or set up new machine)
══════════════════════════════════════

   JSON File                         New Dashboard
   ┌──────────────┐                  ┌──────────────┐
   │ {            │                  │ 🟢 Lab Data  │
   │   sources: [ │ ──── Import ──── │ 🟢 Archive   │
   │     {...},   │                  │ 🟢 NIH API   │
   │     {...}    │                  └──────────────┘
   │   ]          │
   │ }            │                  Duplicates are
   └──────────────┘                  automatically skipped!
```

---

## 8. Security

### Requirement 17 — Authentication

```
WITHOUT AUTH (default):                WITH AUTH (optional):
═══════════════════════                ══════════════════════

   Anyone on the machine               Only requests with
   can use the API                      the correct API key
                                        can use the API

   Request ──────► Server               Request + Key ──► Server
                   ✅ OK                    │
                                            ▼
                                        ┌──────────┐
                                        │ Key      │
                                        │ matches? │
                                        └────┬─────┘
                                          ┌──┴──┐
                                         Yes    No
                                          │      │
                                         ✅    🚫 401
                                         OK    Unauthorized
```

The API key is stored in your system's config directory (not in the code), generated randomly, and can be turned on/off through the settings panel.

---

### Requirement 18 — Rate Limiting

Prevents the system from being overwhelmed — like a "maximum occupancy" sign:

```
Rate Limit: 120 requests per 60 seconds (per user/IP)

   Requests:  ||||| ||||| ||||| |||||  (normal traffic — ✅ all pass)

   Requests:  ||||||||||||||||||||||||||||||||||||||||||||||||||||
              ||||||||||||||||||||||||||||||||||||||||||||||||||||
              ||||||||||||||||||||||||||||||||||||||||||||
              ▲
              120th request
              ──────────────────────────────────────────────
              Request 121+ → "RATE_LIMITED: Too many requests.
                              Try again in X seconds."
```

---

## 9. Cross-Platform

### Requirement 19 & 20 — Works on Every OS as a Background Service

```
┌─────────────────┬──────────────────┬──────────────────┐
│     macOS        │     Linux         │     Windows       │
├─────────────────┼──────────────────┼──────────────────┤
│                 │                  │                  │
│  LaunchAgent    │  systemd user    │  Task Scheduler  │
│  (runs at       │  service (runs   │  (runs at        │
│   login,        │   at login,      │   login,         │
│   auto-restart) │   auto-restart)  │   auto-restart)  │
│                 │                  │                  │
│  Config stored  │  Config stored   │  Config stored   │
│  in:            │  in:             │  in:             │
│  ~/Library/     │  ~/.config/      │  %APPDATA%/      │
│  Application    │  mcp-server/     │  MCP-Server/     │
│  Support/       │                  │                  │
│  MCP-Server/    │                  │                  │
│                 │                  │                  │
│  Claude config: │  Claude config:  │  Claude config:  │
│  ~/Library/     │  ~/.config/      │  %APPDATA%/      │
│  Application    │  claude/         │  Claude/         │
│  Support/       │                  │                  │
│  Claude/        │                  │                  │
└─────────────────┴──────────────────┴──────────────────┘

All three install with one command: python install.py install
```

---

### Requirement 21 — Headless Detection

When the server runs as a background service, there's no screen, no browser, no window. The system needs to detect this:

```
NORMAL MODE (you're at the computer):
═════════════════════════════════════
   Server starts → Opens browser to dashboard → ✅

HEADLESS MODE (running as background service):
═════════════════════════════════════════════
   Server starts → Detects no display → Skips browser open → ✅

   Without headless detection:
   Server starts → Tries to open browser → 💥 CRASH
```

---

## 10. Common Questions

**Q: Can the AI change my data?**  
No. The server enforces read-only access at two levels. Even if a bug somehow bypassed the first check, the database connection itself refuses write operations.

**Q: Do I need to keep a terminal window open?**  
No. Install the service with `python install.py install` and it runs in the background, starting automatically when you log in.

**Q: What if I move a data folder?**  
The dashboard will show a red error indicator. Edit the source through the dashboard to update the path, and it re-checks health automatically.

**Q: Can I use this on a remote server?**  
Yes. Run in headless mode (the system detects this automatically). The dashboard is accessible on port 8420.

**Q: Is my data sent anywhere?**  
No. Everything runs locally on your machine. The MCP server talks to the AI client through stdio (standard input/output) — there are no external network connections for your data.

**Q: What happens if the server crashes?**  
The background service (LaunchAgent on Mac, systemd on Linux, Task Scheduler on Windows) automatically restarts it.

**Q: Can I add my own data source type?**  
Yes. The connector system is pluggable. See CONTRIBUTING.md for a step-by-step guide to creating a new connector.

---

## 11. Glossary

| Term | Plain English Definition |
|------|------------------------|
| **MCP** | Model Context Protocol — a shared language that lets AI assistants talk to data sources. Like USB but for AI + data. |
| **Connector** | An adapter that knows how to read one type of data. Each data format has its own connector, like how different countries have different electrical plugs. |
| **Source** | A registered data connection — a folder, database file, or web API that you've told the server about. |
| **Dashboard** | The web page (control center) where you manage sources, run queries, and view logs. |
| **Bridge** | The thin layer that translates between the AI's MCP language and the dashboard's HTTP API. |
| **DuckDB** | A fast, lightweight database engine used behind the scenes to query your files (CSV, Excel, etc.) as if they were database tables. |
| **SQLite** | A simple file-based database. Many apps and lab instruments store data in SQLite format. |
| **REST API** | A standardized way for software to communicate over HTTP. The dashboard has 22 API endpoints. |
| **stdio** | Standard input/output — the simplest way for two programs to talk to each other by passing text back and forth. |
| **CRUD** | Create, Read, Update, Delete — the four basic operations you can do with data sources. |
| **Rate Limiting** | A safety valve that limits how many requests can be processed per minute to prevent overload. |
| **Headless** | Running without a screen — like a server in a closet. The system detects this and avoids trying to open browser windows. |
| **Auth / API Key** | A password-like string that proves you're allowed to use the server. Optional — off by default. |
| **Query** | A question you ask the data using SQL language, like "show me all patients over age 40." |
| **Schema** | The structure of a table — what columns it has and what type of data each column holds (text, number, date, etc.). |
| **Endpoint** | A specific URL path on the server that does one thing (like `/api/health` checks if the server is alive). |

---

*This guide is part of the MCP Server project. For technical details, see [REQUIREMENTS.md](REQUIREMENTS.md), [AGENTS.md](AGENTS.md), and [MASTER_JOURNAL.md](MASTER_JOURNAL.md).*
