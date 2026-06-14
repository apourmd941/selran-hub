/**
 * API helper functions for the MCP Server Dashboard.
 *
 * Centralizes all API calls to the backend, making it easy to:
 * - Change the API base URL in one place
 * - Add common headers or authentication
 * - Handle consistent error patterns
 * - Mock API calls during testing
 */

const API = "/api";

/**
 * Fetch all data sources from the backend.
 * @returns {Promise<Array>} Array of source objects
 */
export const fetchSources = () =>
  fetch(`${API}/sources`).then((r) => r.json());

/**
 * Fetch dashboard statistics (total, online, offline, error counts).
 * @returns {Promise<Object>} Statistics object with counts and type breakdown
 */
export const fetchStats = () =>
  fetch(`${API}/stats`).then((r) => r.json());

/**
 * Fetch list of tables/files for a specific data source.
 * @param {string} sourceId - The source ID
 * @returns {Promise<Object>} Object with tables array
 */
export const fetchSourceTables = (sourceId) =>
  fetch(`${API}/sources/${sourceId}/tables`).then((r) => r.json());

/**
 * Fetch preview data from a table/file.
 * @param {string} sourceId - The source ID
 * @param {string} tableName - The table or file name
 * @param {number} limit - Max rows to preview (default: 10)
 * @returns {Promise<Object>} Preview data with columns, rows, and row count
 */
export const fetchTablePreview = (sourceId, tableName, limit = 10) =>
  fetch(
    `${API}/sources/${sourceId}/preview/${encodeURIComponent(tableName)}?limit=${limit}`
  ).then((r) => r.json());

/**
 * Execute a SQL query against a source.
 * @param {string} sourceId - The source ID
 * @param {string} sql - SQL query string
 * @param {number} limit - Max rows to return (default: 100)
 * @returns {Promise<Object>} Query results with columns, rows, row_count, and optional error
 */
export const executeQuery = (sourceId, sql, limit = 100) =>
  fetch(`${API}/sources/${sourceId}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sql, limit }),
  }).then((r) => r.json());

/**
 * Create a new data source.
 * @param {Object} source - Source object with name, type, path/url, description, rules
 * @returns {Promise<Object>} Created source object
 */
export const createSource = (source) =>
  fetch(`${API}/sources`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(source),
  }).then((r) => r.json());

/**
 * Update an existing data source.
 * @param {string} sourceId - The source ID
 * @param {Object} updates - Partial source object with fields to update
 * @returns {Promise<Object>} Updated source object
 */
export const updateSource = (sourceId, updates) =>
  fetch(`${API}/sources/${sourceId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  }).then((r) => r.json());

/**
 * Delete a data source.
 * @param {string} sourceId - The source ID
 * @returns {Promise<void>}
 */
export const deleteSource = (sourceId) =>
  fetch(`${API}/sources/${sourceId}`, {
    method: "DELETE",
  }).then((r) => r.json());

/**
 * Toggle a source's enabled/disabled state.
 * @param {string} sourceId - The source ID
 * @returns {Promise<Object>} Updated source object
 */
export const toggleSource = (sourceId) =>
  fetch(`${API}/sources/${sourceId}/toggle`, {
    method: "POST",
  }).then((r) => r.json());

/**
 * Check the health/status of a source by connecting to it.
 * @param {string} sourceId - The source ID
 * @returns {Promise<Object>} Health check result
 */
export const checkSource = (sourceId) =>
  fetch(`${API}/sources/${sourceId}/check`, {
    method: "POST",
  }).then((r) => r.json());

/**
 * Open a file/folder browser dialog.
 * @param {string} mode - "folder" or "file"
 * @returns {Promise<Object>} Object with path, or headless/error properties
 */
export const browsePath = (mode) =>
  fetch(`${API}/browse?mode=${mode}`).then((r) => r.json());

/**
 * Export all sources as JSON.
 * @returns {Promise<Object>} Object with sources array
 */
export const exportSources = () =>
  fetch(`${API}/sources/export`).then((r) => r.json());

/**
 * Import sources from JSON.
 * @param {Array} sources - Array of source objects
 * @returns {Promise<Object>} Import result with imported and skipped counts
 */
export const importSources = (sources) =>
  fetch(`${API}/sources/import`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sources: Array.isArray(sources) ? sources : [sources] }),
  }).then((r) => r.json());

/**
 * Fetch MCP configuration in the specified format.
 * @param {string} format - "claude" or "generic"
 * @param {string} transport - "stdio" or "sse"
 * @returns {Promise<Object>} MCP config object
 */
export const fetchMCPConfig = (format = "claude", transport = "stdio") =>
  fetch(
    `${API}/mcp-config?format=${format}&transport=${transport}`
  ).then((r) => r.json());

/**
 * Install MCP configuration to the local system.
 * @param {string} format - "claude" or "generic"
 * @param {string} transport - "stdio" or "sse"
 * @returns {Promise<Object>} Installation result
 */
export const installMCPConfig = (format = "claude", transport = "stdio") =>
  fetch(
    `${API}/mcp-config/install?format=${format}&transport=${transport}`,
    { method: "POST" }
  ).then((r) => r.json());

/**
 * Fetch request logs from the server.
 * @param {number} limit - Max logs to return (default: 200)
 * @param {string} level - "all", "success", or "error"
 * @returns {Promise<Object>} Object with logs array
 */
export const fetchLogs = (limit = 200, level = "all") =>
  fetch(`${API}/logs?limit=${limit}&level=${level}`).then((r) => r.json());

/**
 * Fetch authentication status.
 * @returns {Promise<Object>} Object with enabled boolean
 */
export const fetchAuthStatus = () =>
  fetch(`${API}/auth/status`).then((r) => r.json());

/**
 * Configure authentication settings.
 * @param {boolean} enabled - Whether to enable API key authentication
 * @returns {Promise<Object>} Auth config with enabled, api_key, and message
 */
export const configureAuth = (enabled) =>
  fetch(`${API}/auth/configure`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  }).then((r) => r.json());

/**
 * Fetch system information.
 * @returns {Promise<Object>} System info with version, platform, python, headless flag
 */
export const fetchSystemInfo = () =>
  fetch(`${API}/info`).then((r) => r.json());

/**
 * Run installation verification check.
 * @returns {Promise<Object>} Object with checks array and summary
 */
export const fetchSystemCheck = () =>
  fetch(`${API}/system-check`).then((r) => r.json());
