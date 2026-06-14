# Selran Hub — Audit Log

## Audit run: 2026-06-13, categories [3 Security, 4 Error-handling, 5 Concurrency, 6 Resource-bounds, 7 Spec-compliance]

**Profile:** standard. **Scope (code):** whole codebase, focus on the H1–H9 surface
(`process_inspect.py`, `service_manager.py`, `secrets_store.py`, `mcp_bridge.py`,
`policy.py`, `updater.py`, `hub_router.py`, `app.py`) + the data-source connectors.
**Auditor:** greenloop app-audit. First audit of this repo (no prior codemap / audit infra).

**Pre-commit baseline at start:**
- Tests: 126 passed (full suite; 1 process-timing test in test_hub_h1 is flaky under
  load — passes in isolation and under the same env, confirmed not a regression).
- gitleaks: clean across 33 commits + working tree (run this session).
- Lint/typecheck: ruff / mypy not configured (no lint tier) — noted, not blocking.
- Git: clean working tree at dev `569e389`.

**Detectors (Step 3.0):**
- semgrep: LIVE — bundled greenloop.yml (offline) + registry p/python, p/security-audit.
- gitleaks: LIVE — clean.
- osv-scanner: **installed during this round (v2.3.8) and run** → dependency-CVE tier is
  now LIVE, not judgement-only. Scan of the installed dependency set (49 packages):
  **0 vulnerabilities (0 Critical/High/Medium/Low)**. osv-scanner is greenloop-doctor's
  default dep-CVE detector, so future rounds run it automatically.
- type-checkers: MISSING → schema/data-flow grounding is judgement-only.

**Note:** the security-critical H-series modules (H0 orphan-PID reaper, H5 keychain
secrets, H8 remote bearer auth) were each adversarially reviewed via a 3-lens subagent
workflow during the build this session; H9 policy enforcement was self-audited for
bypasses. This audit re-checks them with detectors + the cross-cutting categories and
found **no new Critical/High**.

### Remediation (applied same round)

- **[Low] health-probe scheme** → FIXED: `_probe_health` now refuses any non-`http(s)`
  URL (returns `unreachable` without opening it). Test added
  (`tests/test_hub_m2.py::test_health_probe_rejects_non_http_schemes`).
- **[Low] SQL identifier interpolation** → VERIFIED CLEAN, no change needed: the SQLite
  `describe` path already guards `table_name not in tables`
  (`sqlite_connector.py:146`), matching `preview` and the DuckDB connector — so the
  "parity" residual was already satisfied. Combined with read-only connections +
  schema-derived `cname`, there is no reachable injection.
- **dependency-CVE gap** → CLOSED: osv-scanner installed + scan clean (above).

### Findings

**[Low] SQL identifier interpolation in the data-source stats/describe path**
- Category: 3 — Security · Type: safety · Source: detector:semgrep
  (python-subprocess… → `python.lang.security…`) + static-review · Provenance: pre-existing
  (connector layer, predates the H-series) · Confidence: 0.6
- Location: `selran_hub/connectors/sqlite_connector.py:170–196`,
  `selran_hub/connectors/duckdb_connector.py` (describe/stats)
- Description: descriptive-stats SQL interpolates `{table_name}` / `{cname}` / `{mean}`
  via f-strings rather than parameters.
- Why bounded (challenge survived → demoted to Low): **both connections are read-only**
  (`sqlite: file:…?mode=ro`, `duckdb: read_only=True`), so identifier injection cannot
  write/drop. `cname` is read from the schema (`PRAGMA table_info` / DESCRIBE), not user
  input. `table_name` is guarded (`if table_name not in tables`) in `preview` and the
  DuckDB `describe`. Residual impact is read access the local user already has (the
  `query_source` tool runs arbitrary read-only SQL on their own DB).
- Suggested fix: add the same `table_name not in tables` guard to the SQLite `describe`
  path for parity; longer term, quote identifiers via a helper. Defense-in-depth.
- Effort: small

**[Low] Service health probe accepts any URL scheme**
- Category: 3 — Security · Type: safety · Source: detector:semgrep (dynamic-urllib) ·
  Provenance: pre-existing · Confidence: 0.55
- Location: `selran_hub/service_manager.py:244` (`_probe_health`)
- Description: a service's `health_url` is registered by the local user and passed to
  `urllib.request.urlopen`; a `file://` value would be opened during the health probe.
- Why bounded: the probe returns only a status string (`ok` / `unreachable` / `http-NNN`),
  never the body, and the registrant is a loopback + CSRF-gated local caller acting on
  their own Hub. The other dynamic-urllib hits (`updater.py:59`, `tray.py:28`) use fixed
  `https://api.github.com` / `http://127.0.0.1` schemes and are not findings.
- Suggested fix: restrict `_probe_health` to `http`/`https` schemes.
- Effort: trivial

**[Info — accepted by design] `subprocess` `shell=True` in service start**
- Category: 3 — Security · Source: detector:semgrep (subprocess-shell-true)
- Location: `selran_hub/service_manager.py:273`
- This is the documented, intentional process-supervisor design (a `start_cmd` is a
  shell line the user registered, like systemd ExecStart / pm2). The trust boundary is
  REGISTRATION, which `app.py`'s loopback + CSRF (`X-Selran-Local`) guard restricts to
  local same-origin callers — established in the prior RCE remediation. Recorded as
  accepted; no action. (If a `.greenloopignore` is added later, this is the canonical
  entry with this reason.)

**[Info] ServiceManager shares one SQLite connection across threads**
- Category: 5 — Concurrency · Confidence: 0.5
- Location: `selran_hub/service_manager.py:58`
  (`sqlite3.connect(..., check_same_thread=False, isolation_level=None)`)
- FastAPI runs sync handlers in a threadpool, so concurrent `/v1/services` requests can
  touch the one shared connection. Safe on a serialized SQLite build (CPython's default
  on macOS/Linux) where the module serializes access; noted as a dependency on that
  build property, not a confirmed defect. No app-level lock. Low likelihood (a
  single-user local daemon with light concurrency).

### Verified clean (0 findings)

- **Category 4 — Error handling.** The broad `try/except` blocks in `secrets_store.py`,
  `policy.py`, `updater.py` are intentional fail-safe degradation (→ file fallback / None
  / no-policy), not error-swallowing. The one write path that mattered (keychain write
  during load-migration) was hardened in the H5 review (crash-safe). No new findings.
- **Category 6 — Resource bounds.** All in-memory stores are capped + TTL'd: studio
  (MAX_SESSIONS=50, 4h), audit panel (MAX_RUNS=20, 12h), request log (`deque` maxlen 500).
  The H8 network transport added `uvicorn` `limit_concurrency`/`timeout_keep_alive`. The
  process-scan helpers (`ps_command_map`, `pids_with_marker_prefix`) are per-request and
  bounded by process count. No unbounded growth found.
- **Category 7 — Spec compliance** (vs `SELRAN_HUB_DESIGN.md`). §2.2 loopback-only: the
  daemon binds `127.0.0.1` (`cli.py:38`) ✓. §8 no telemetry without opt-in: the update
  check is opt-in and is the only egress (H6) ✓. §8 secrets in keychain (H5) ✓. §8/§2.2
  remote transport authenticated + daemon stays loopback (H8) ✓. No drift found.

### Coverage declaration

- **Scope this round:** Categories 3, 4, 5, 6, 7.
- **Could not fully verify:** dependency CVEs (no osv-scanner/pip-audit installed —
  judgement-only this round); SQLite-build thread-serialization (assumed from CPython
  defaults, not probed at runtime).
- **Confidence:** Critical — HIGH confidence none. High — HIGH confidence none. The
  findings are Low/Info, well-bounded by the read-only + loopback + CSRF trust model.
- **Out of scope (no claims):** Categories 1 (schema), 2 (data flow), 8 (operational),
  9 (test coverage — though the suite is 128 tests green), 10 (diagnosability).
- **Recommended next round:** install `osv-scanner` for a real dependency-CVE pass before
  the public release; otherwise the security-relevant surface is in good shape.

**Adversarial challenge:** 3 candidate Critical/High from the SAST pass were challenged
and all demoted — the SQL-injection pattern is neutralized by read-only connections +
schema-derived identifiers (→ Low), `shell=True` is accepted-by-design (→ Info), the
dynamic-urllib hits use fixed schemes except the bounded health probe (→ Low). A healthy
round: the detectors fired, the trust model held, nothing survived as Critical/High.
