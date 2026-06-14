/**
 * SourceModal component - modal for creating or editing a data source.
 *
 * Displays form fields based on source type:
 * - Folder: requires path
 * - DuckDB/SQLite: requires path
 * - API: requires URL
 * All: name, description, and access rules (read-only, sensitive filter, row limit)
 *
 * Includes file/folder browser capability and validation.
 *
 * @param {Object} props - Component props
 * @param {Function} props.onClose - Callback to close modal
 * @param {Function} props.onSubmit - Callback when form submitted, receives (formData, id?)
 * @param {Object} props.editing - If provided, source object being edited (else creating new)
 * @returns {JSX.Element} Modal dialog
 */

import { useState } from "react";
import { C, icons, labels } from "../theme";
import { Btn } from "./Btn";
import { browsePath } from "../api";

export default function SourceModal({ onClose, onSubmit, editing }) {
  // Initialize form state - either from editing source or empty defaults
  const [form, setForm] = useState(
    editing
      ? {
          name: editing.name,
          type: editing.type,
          path: editing.path || "",
          url: editing.url || "",
          description: editing.description || "",
          read_only: editing.rules?.read_only ?? true,
          row_limit: editing.rules?.row_limit || 1000,
          sensitive_filter: editing.rules?.sensitive_filter || false,
        }
      : {
          name: "",
          type: "folder",
          path: "",
          url: "",
          description: "",
          read_only: true,
          row_limit: 1000,
          sensitive_filter: false,
        }
  );

  const [browseErr, setBrowseErr] = useState("");

  // Determine which fields are needed based on source type
  const needsPath = ["folder", "duckdb", "sqlite"].includes(form.type);
  const needsUrl = form.type === "api";

  /**
   * Handle form submission with validation.
   */
  const handleSubmit = () => {
    // Validate required fields
    if (!form.name.trim()) return;
    if (needsPath && !form.path.trim()) return;
    if (needsUrl && !form.url.trim()) return;

    // Submit the form
    onSubmit(
      {
        name: form.name,
        type: form.type,
        path: needsPath ? form.path : null,
        url: needsUrl ? form.url : null,
        description: form.description,
        rules: {
          read_only: form.read_only,
          row_limit: form.row_limit,
          sensitive_filter: form.sensitive_filter,
        },
      },
      editing?.id
    );
  };

  /**
   * Open file/folder browser dialog.
   * @param {string} mode - "folder" or "file"
   */
  const browse = (mode) => {
    setBrowseErr("");
    browsePath(mode)
      .then((d) => {
        if (d.headless) {
          setBrowseErr(d.error);
          return;
        }
        if (d.path) {
          setForm((f) => ({ ...f, path: d.path }));
        }
      })
      .catch(() => setBrowseErr("Browse failed"));
  };

  // Common label styling
  const L = {
    display: "block",
    fontSize: 13,
    fontWeight: 500,
    color: C.textDim,
    marginBottom: 6,
  };

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
          width: 520,
          maxHeight: "85vh",
          overflow: "auto",
          animation: "fadeIn 0.2s ease",
        }}
      >
        <h2 style={{ fontSize: 19, fontWeight: 700, marginBottom: 22 }}>
          {editing ? "Edit Source" : "Add Data Source"}
        </h2>

        {/* Name field */}
        <label style={L}>Name</label>
        <input
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          placeholder="e.g. Project Files, Customer DB, Internal API"
          style={{ width: "100%", marginBottom: 14 }}
        />

        {/* Type selector (only for new sources) */}
        {!editing && (
          <>
            <label style={L}>Type</label>
            <div style={{ display: "flex", gap: 6, marginBottom: 14, flexWrap: "wrap" }}>
              {["folder", "duckdb", "sqlite", "api"].map((t) => (
                <button
                  key={t}
                  onClick={() => setForm({ ...form, type: t })}
                  style={{
                    padding: "9px 16px",
                    borderRadius: 9,
                    fontSize: 13,
                    background:
                      form.type === t ? C.accentBg : C.bgAlt,
                    border: `1px solid ${form.type === t ? C.accent : C.border}`,
                    color:
                      form.type === t ? C.accentHover : C.textDim,
                    fontWeight: form.type === t ? 600 : 400,
                  }}
                >
                  {icons[t]} {labels[t]}
                </button>
              ))}
            </div>
          </>
        )}

        {/* Path field (for folder, duckdb, sqlite) */}
        {needsPath && (
          <>
            <label style={L}>Path</label>
            <div style={{ display: "flex", gap: 6, marginBottom: browseErr ? 6 : 14 }}>
              <input
                value={form.path}
                onChange={(e) => setForm({ ...form, path: e.target.value })}
                placeholder={
                  form.type === "folder"
                    ? "/path/to/folder"
                    : "/path/to/database.duckdb"
                }
                style={{ flex: 1 }}
              />
              <button
                onClick={() =>
                  browse(form.type === "folder" ? "folder" : "file")
                }
                style={{
                  padding: "10px 14px",
                  borderRadius: 8,
                  fontSize: 13,
                  fontWeight: 500,
                  background: C.bgAlt,
                  color: C.textDim,
                  border: `1px solid ${C.border}`,
                  whiteSpace: "nowrap",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = C.accent;
                  e.currentTarget.style.color = C.accentHover;
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = C.border;
                  e.currentTarget.style.color = C.textDim;
                }}
              >
                Browse…
              </button>
            </div>
            {browseErr && (
              <div style={{ fontSize: 12, color: C.amber, marginBottom: 14 }}>
                {browseErr}
              </div>
            )}
          </>
        )}

        {/* URL field (for API) */}
        {needsUrl && (
          <>
            <label style={L}>Base URL</label>
            <input
              value={form.url}
              onChange={(e) => setForm({ ...form, url: e.target.value })}
              placeholder="https://api.example.com/v1"
              style={{ width: "100%", marginBottom: 14 }}
            />
          </>
        )}

        {/* Description field */}
        <label style={L}>Description (optional)</label>
        <input
          value={form.description}
          onChange={(e) => setForm({ ...form, description: e.target.value })}
          placeholder="Brief description of this data source"
          style={{ width: "100%", marginBottom: 20 }}
        />

        {/* Access rules section */}
        <div style={{ padding: 14, background: C.bgAlt, borderRadius: 10, marginBottom: 20 }}>
          <div
            style={{
              fontSize: 12,
              fontWeight: 600,
              marginBottom: 10,
              color: C.textMuted,
              letterSpacing: 0.8,
            }}
          >
            ACCESS RULES
          </div>

          <label
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              marginBottom: 8,
              fontSize: 13,
              cursor: "pointer",
            }}
          >
            <input
              type="checkbox"
              checked={form.read_only}
              onChange={(e) => setForm({ ...form, read_only: e.target.checked })}
            />
            Read-only access (recommended)
          </label>

          <label
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              marginBottom: 8,
              fontSize: 13,
              cursor: "pointer",
            }}
          >
            <input
              type="checkbox"
              checked={form.sensitive_filter}
              onChange={(e) =>
                setForm({ ...form, sensitive_filter: e.target.checked })
              }
            />
            Filter sensitive columns (PII, credentials)
          </label>

          <label style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 13 }}>
            Max rows per query:{" "}
            <input
              type="number"
              value={form.row_limit}
              onChange={(e) =>
                setForm({ ...form, row_limit: parseInt(e.target.value) || 1000 })
              }
              style={{ width: 90 }}
            />
          </label>
        </div>

        {/* Footer buttons */}
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <Btn onClick={onClose}>Cancel</Btn>
          <Btn primary onClick={handleSubmit}>
            {editing ? "Save Changes" : "Add Source"}
          </Btn>
        </div>
      </div>
    </div>
  );
}
