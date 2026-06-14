/**
 * LogPanel component - modal for viewing server request logs.
 *
 * Displays recent API requests with timestamps, HTTP status, method, path, and elapsed time.
 * Supports filtering by log level (all, success, errors).
 * Auto-refreshes every 5 seconds and auto-scrolls to latest logs.
 *
 * @param {Object} props - Component props
 * @param {Function} props.onClose - Callback to close modal
 * @returns {JSX.Element} Modal dialog
 */

import { useState, useEffect, useRef } from "react";
import { C } from "../theme";
import { Btn } from "./Btn";
import TabBar from "./TabBar";
import { fetchLogs } from "../api";

export default function LogPanel({ onClose }) {
  const [logs, setLogs] = useState([]);
  const [filter, setFilter] = useState("all");
  const bottomRef = useRef(null);

  /**
   * Load logs from the server.
   */
  const loadLogs = () =>
    fetchLogs(200, filter).then((d) => setLogs(d.logs || []));

  // Initial load and set up auto-refresh
  useEffect(() => {
    loadLogs();
    const i = setInterval(loadLogs, 5000);
    return () => clearInterval(i);
  }, [filter]);

  // Auto-scroll to bottom when new logs arrive
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs.length]);

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,.55)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 100,
      }}
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: C.surface,
          borderRadius: 16,
          border: `1px solid ${C.border}`,
          padding: 28,
          width: 700,
          maxHeight: "85vh",
          overflow: "auto",
          animation: "fadeIn 0.2s ease",
        }}
      >
        {/* Header with filter tabs */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: 16,
          }}
        >
          <h2 style={{ fontSize: 19, fontWeight: 700 }}>Request Logs</h2>
          <TabBar
            tabs={[
              { id: "all", label: "All" },
              { id: "success", label: "OK" },
              { id: "error", label: "Errors" },
            ]}
            active={filter}
            onChange={setFilter}
          />
        </div>

        {/* Log entries */}
        <div
          style={{
            background: C.bgAlt,
            borderRadius: 10,
            border: `1px solid ${C.border}`,
            maxHeight: 400,
            overflow: "auto",
            fontFamily: "monospace",
            fontSize: 12,
            lineHeight: 1.8,
          }}
        >
          {logs.length === 0 ? (
            <div
              style={{
                padding: 20,
                textAlign: "center",
                color: C.textMuted,
              }}
            >
              No logs yet
            </div>
          ) : (
            logs.map((l, i) => (
              <div
                key={i}
                style={{
                  padding: "4px 12px",
                  borderBottom: `1px solid ${C.border}`,
                  display: "flex",
                  gap: 12,
                }}
              >
                {/* Timestamp */}
                <span
                  style={{
                    color: C.textMuted,
                    minWidth: 170,
                  }}
                >
                  {new Date(l.timestamp).toLocaleTimeString()}
                </span>

                {/* HTTP Status code */}
                <span
                  style={{
                    color: l.status < 400 ? C.green : C.red,
                    minWidth: 36,
                  }}
                >
                  {l.status}
                </span>

                {/* HTTP Method */}
                <span
                  style={{
                    color: C.blue,
                    minWidth: 40,
                  }}
                >
                  {l.method}
                </span>

                {/* Request path */}
                <span
                  style={{
                    color: C.text,
                    flex: 1,
                  }}
                >
                  {l.path}
                </span>

                {/* Elapsed time */}
                <span style={{ color: C.textMuted }}>{l.elapsed_ms}ms</span>
              </div>
            ))
          )}
          <div ref={bottomRef} />
        </div>

        {/* Close button */}
        <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 12 }}>
          <Btn onClick={onClose}>Close</Btn>
        </div>
      </div>
    </div>
  );
}
