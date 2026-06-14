/**
 * SourceDetail component - right-side panel showing detailed information about a source.
 *
 * Displays:
 * - Header with source name, type, status badges
 * - Statistics (row count, size, etc.)
 * - List of tables/files with clickable preview
 * - Data preview table (10 rows)
 * - SQL query console with execute button and results table
 *
 * @param {Object} props - Component props
 * @param {Object} props.source - Source object to display
 * @param {Function} props.onClose - Callback to close the panel
 * @returns {JSX.Element} Right-side panel element
 */

import { useState, useEffect } from "react";
import { C, icons, labels } from "../theme";
import Badge from "./Badge";
import StatusDot from "./StatusDot";
import { Btn, SmallBtn } from "./Btn";
import {
  fetchSourceTables,
  fetchTablePreview,
  executeQuery,
} from "../api";

export default function SourceDetail({ source, onClose }) {
  const [tables, setTables] = useState(null);
  const [preview, setPreview] = useState(null);
  const [loading, setLoading] = useState(false);
  const [querySQL, setQuerySQL] = useState("");
  const [queryResult, setQueryResult] = useState(null);
  const [queryLoading, setQueryLoading] = useState(false);

  // Load tables when source changes
  useEffect(() => {
    if (!source) return;

    setLoading(true);
    setPreview(null);
    setQueryResult(null);
    setQuerySQL("");

    fetchSourceTables(source.id)
      .then((d) => {
        setTables(d.tables || []);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [source?.id]);

  /**
   * Load preview data for a specific table.
   */
  const loadPreview = (name) => {
    setPreview(null);
    fetchTablePreview(source.id, name, 10).then(setPreview);
  };

  /**
   * Execute SQL query and display results.
   */
  const runQuery = () => {
    if (!querySQL.trim()) return;

    setQueryLoading(true);
    executeQuery(source.id, querySQL, 100)
      .then((d) => {
        setQueryResult(d);
        setQueryLoading(false);
      })
      .catch(() => setQueryLoading(false));
  };

  if (!source) return null;

  return (
    <div
      style={{
        position: "fixed",
        top: 0,
        right: 0,
        bottom: 0,
        width: 580,
        background: C.surface,
        borderLeft: `1px solid ${C.border}`,
        overflow: "auto",
        animation: "slideIn 0.2s ease",
        zIndex: 50,
        boxShadow: "-8px 0 30px rgba(0,0,0,.3)",
      }}
    >
      {/* ─── Header ─────────────────────────────────────────────────── */}
      <div style={{ padding: 22, borderBottom: `1px solid ${C.border}` }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
          }}
        >
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span style={{ fontSize: 26 }}>{icons[source.type]}</span>
              <h2 style={{ fontSize: 19, fontWeight: 700 }}>{source.name}</h2>
            </div>
            <div style={{ color: C.textDim, fontSize: 13, marginTop: 4 }}>
              {source.path || source.url}
            </div>
          </div>

          {/* Close button */}
          <button
            onClick={onClose}
            style={{
              width: 34,
              height: 34,
              borderRadius: 9,
              fontSize: 15,
              background: C.bgAlt,
              color: C.textDim,
              border: `1px solid ${C.border}`,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            ✕
          </button>
        </div>

        {/* Status badges */}
        <div style={{ display: "flex", gap: 6, marginTop: 14, flexWrap: "wrap" }}>
          <Badge
            color={source.status === "online" ? C.green : C.red}
            bg={source.status === "online" ? C.greenBg : C.redBg}
          >
            <StatusDot status={source.status} /> {source.status}
          </Badge>
          <Badge color={C.blue} bg={C.blueBg}>
            {labels[source.type]}
          </Badge>
          {source.rules?.read_only && (
            <Badge color={C.amber} bg={C.amberBg}>
              Read-only
            </Badge>
          )}
        </div>
      </div>

      {/* ─── Statistics ─────────────────────────────────────────────── */}
      {source.stats && Object.keys(source.stats).length > 0 && (
        <div style={{ padding: "14px 22px", borderBottom: `1px solid ${C.border}` }}>
          <div
            style={{
              fontSize: 11,
              fontWeight: 600,
              color: C.textMuted,
              marginBottom: 8,
              letterSpacing: 0.8,
            }}
          >
            STATS
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 20px", fontSize: 13 }}>
            {Object.entries(source.stats)
              .filter(([k]) => k !== "error")
              .map(([k, v]) => (
                <div key={k}>
                  <span style={{ color: C.textDim }}>
                    {k.replace(/_/g, " ")}:{" "}
                  </span>
                  <span style={{ fontWeight: 500 }}>
                    {typeof v === "number" ? v.toLocaleString() : String(v)}
                  </span>
                </div>
              ))}
          </div>
        </div>
      )}

      {/* Error message */}
      {source.error && (
        <div
          style={{
            padding: "10px 22px",
            background: C.redBg,
            color: C.red,
            fontSize: 13,
          }}
        >
          Error: {source.error}
        </div>
      )}

      {/* ─── Tables/Files List ──────────────────────────────────────── */}
      <div style={{ padding: 22 }}>
        <div
          style={{
            fontSize: 11,
            fontWeight: 600,
            color: C.textMuted,
            marginBottom: 10,
            letterSpacing: 0.8,
          }}
        >
          {loading ? "LOADING TABLES..." : `TABLES & FILES (${tables?.length || 0})`}
        </div>

        {tables?.map((t) => (
          <div
            key={t.name}
            onClick={() => loadPreview(t.name)}
            style={{
              padding: "11px 14px",
              borderRadius: 8,
              cursor: "pointer",
              border: `1px solid ${C.border}`,
              marginBottom: 6,
              transition: "border-color 0.12s",
            }}
            onMouseEnter={(e) => (e.currentTarget.style.borderColor = C.accent)}
            onMouseLeave={(e) => (e.currentTarget.style.borderColor = C.border)}
          >
            <div style={{ fontWeight: 500, fontSize: 13 }}>{t.name}</div>
            <div style={{ fontSize: 11, color: C.textDim, marginTop: 2 }}>
              {t.row_count != null && `${t.row_count.toLocaleString()} rows`}
              {t.column_count != null && ` · ${t.column_count} cols`}
              {t.size_mb != null && ` · ${t.size_mb} MB`}
              {t.type && ` · ${t.type}`}
            </div>
          </div>
        ))}
      </div>

      {/* ─── Data Preview ───────────────────────────────────────────── */}
      {preview && (
        <div style={{ padding: "0 22px 22px" }}>
          <div
            style={{
              fontSize: 11,
              fontWeight: 600,
              color: C.textMuted,
              marginBottom: 8,
              letterSpacing: 0.8,
            }}
          >
            PREVIEW ({preview.preview_rows} of {preview.total_rows?.toLocaleString()} rows)
          </div>

          {preview.error ? (
            <div style={{ color: C.red, fontSize: 13 }}>{preview.error}</div>
          ) : (
            <div style={{ overflow: "auto", borderRadius: 8, border: `1px solid ${C.border}` }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                <thead>
                  <tr>
                    {preview.columns?.map((col) => (
                      <th
                        key={col}
                        style={{
                          padding: "7px 10px",
                          textAlign: "left",
                          fontWeight: 600,
                          background: C.bgAlt,
                          borderBottom: `1px solid ${C.border}`,
                          whiteSpace: "nowrap",
                          color: C.textDim,
                          fontSize: 11,
                        }}
                      >
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {preview.rows?.map((row, i) => (
                    <tr key={i}>
                      {row.map((cell, j) => (
                        <td
                          key={j}
                          style={{
                            padding: "5px 10px",
                            borderBottom: `1px solid ${C.border}`,
                            whiteSpace: "nowrap",
                            maxWidth: 180,
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                          }}
                        >
                          {cell == null ? (
                            <span style={{ color: C.textMuted }}>null</span>
                          ) : (
                            String(cell)
                          )}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ─── SQL Query Console ──────────────────────────────────────── */}
      <div style={{ padding: "0 22px 22px" }}>
        <div
          style={{
            fontSize: 11,
            fontWeight: 600,
            color: C.textMuted,
            marginBottom: 8,
            letterSpacing: 0.8,
          }}
        >
          SQL QUERY
        </div>

        {/* SQL textarea */}
        <textarea
          value={querySQL}
          onChange={(e) => setQuerySQL(e.target.value)}
          placeholder="SELECT * FROM table_name LIMIT 10"
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              runQuery();
            }
          }}
          style={{
            width: "100%",
            minHeight: 64,
            fontFamily: "monospace",
            fontSize: 13,
            resize: "vertical",
            marginBottom: 8,
          }}
        />

        {/* Run button and shortcut hint */}
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <Btn small primary onClick={runQuery} disabled={queryLoading}>
            {queryLoading ? "Running..." : "Run Query"}
          </Btn>
          <span style={{ fontSize: 11, color: C.textMuted }}>⌘+Enter to run</span>
        </div>

        {/* Query results */}
        {queryResult && (
          <div style={{ marginTop: 12 }}>
            {queryResult.error ? (
              <div
                style={{
                  color: C.red,
                  fontSize: 13,
                  padding: 10,
                  background: C.redBg,
                  borderRadius: 8,
                }}
              >
                {queryResult.error}
              </div>
            ) : (
              <div
                style={{
                  overflow: "auto",
                  borderRadius: 8,
                  border: `1px solid ${C.border}`,
                  maxHeight: 300,
                }}
              >
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                  <thead>
                    <tr>
                      {queryResult.columns?.map((c) => (
                        <th
                          key={c}
                          style={{
                            padding: "6px 10px",
                            textAlign: "left",
                            fontWeight: 600,
                            background: C.bgAlt,
                            borderBottom: `1px solid ${C.border}`,
                            whiteSpace: "nowrap",
                            color: C.textDim,
                            fontSize: 11,
                            position: "sticky",
                            top: 0,
                          }}
                        >
                          {c}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {queryResult.rows?.map((row, i) => (
                      <tr key={i}>
                        {row.map((cell, j) => (
                          <td
                            key={j}
                            style={{
                              padding: "4px 10px",
                              borderBottom: `1px solid ${C.border}`,
                              whiteSpace: "nowrap",
                              maxWidth: 180,
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                            }}
                          >
                            {cell == null ? (
                              <span style={{ color: C.textMuted }}>null</span>
                            ) : (
                              String(cell)
                            )}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div
                  style={{
                    padding: "6px 10px",
                    fontSize: 11,
                    color: C.textDim,
                    borderTop: `1px solid ${C.border}`,
                    background: C.bgAlt,
                  }}
                >
                  {queryResult.row_count} row
                  {queryResult.row_count !== 1 ? "s" : ""}
                  {queryResult.truncated ? " (truncated)" : ""}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
