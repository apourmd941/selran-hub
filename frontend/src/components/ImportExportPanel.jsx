/**
 * ImportExportPanel component - modal for importing/exporting source configurations.
 *
 * Export: Download all sources as a JSON file for backup or migration.
 * Import: Paste previously exported JSON to import sources into this instance.
 *
 * @param {Object} props - Component props
 * @param {Function} props.onClose - Callback to close modal
 * @param {Function} props.onRefresh - Callback to refresh source list after import
 * @returns {JSX.Element} Modal dialog with tabbed interface
 */

import { useState, useEffect } from "react";
import { C } from "../theme";
import { Btn } from "./Btn";
import TabBar from "./TabBar";
import { exportSources, importSources } from "../api";

export default function ImportExportPanel({ onClose, onRefresh }) {
  const [exportData, setExportData] = useState(null);
  const [importText, setImportText] = useState("");
  const [importResult, setImportResult] = useState(null);
  const [tab, setTab] = useState("export");

  // Fetch export data when panel opens
  useEffect(() => {
    exportSources().then(setExportData);
  }, []);

  /**
   * Handle import form submission.
   * Validates JSON and imports sources.
   */
  const handleImport = () => {
    try {
      const data = JSON.parse(importText);
      const sources = data.sources || data;

      importSources(Array.isArray(sources) ? sources : [sources])
        .then((d) => {
          setImportResult(d);
          onRefresh();
        });
    } catch {
      setImportResult({ error: "Invalid JSON" });
    }
  };

  /**
   * Download export data as JSON file.
   */
  const downloadJSON = () => {
    const blob = new Blob([JSON.stringify(exportData, null, 2)], {
      type: "application/json",
    });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "mcp-sources.json";
    a.click();
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
          width: 580,
          maxHeight: "85vh",
          overflow: "auto",
          animation: "fadeIn 0.2s ease",
        }}
      >
        <h2 style={{ fontSize: 19, fontWeight: 700, marginBottom: 16 }}>
          Import / Export
        </h2>

        {/* Tab navigation */}
        <TabBar
          tabs={[
            { id: "export", label: "Export" },
            { id: "import", label: "Import" },
          ]}
          active={tab}
          onChange={setTab}
        />

        {/* ─── Export Tab ─────────────────────────────────────────────── */}
        {tab === "export" ? (
          <div style={{ marginTop: 16 }}>
            <p style={{ fontSize: 13, color: C.textDim, marginBottom: 10 }}>
              Download your source configurations for backup or migration.
            </p>

            {/* Config preview */}
            <pre
              style={{
                background: C.bgAlt,
                borderRadius: 10,
                padding: 14,
                fontSize: 12,
                lineHeight: 1.5,
                overflow: "auto",
                maxHeight: 300,
                border: `1px solid ${C.border}`,
                fontFamily: "monospace",
              }}
            >
              {exportData ? JSON.stringify(exportData, null, 2) : "Loading..."}
            </pre>

            {/* Download button */}
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 12 }}>
              <Btn onClick={downloadJSON}>Download JSON</Btn>
              <Btn onClick={onClose}>Close</Btn>
            </div>
          </div>
        ) : (
          /* ─── Import Tab ─────────────────────────────────────────── */
          <div style={{ marginTop: 16 }}>
            <p style={{ fontSize: 13, color: C.textDim, marginBottom: 10 }}>
              Paste exported JSON to import source configurations.
            </p>

            {/* Import textarea */}
            <textarea
              value={importText}
              onChange={(e) => setImportText(e.target.value)}
              placeholder="Paste JSON here..."
              style={{
                width: "100%",
                minHeight: 140,
                fontFamily: "monospace",
                fontSize: 12,
                marginBottom: 10,
              }}
            />

            {/* Import result message */}
            {importResult && (
              <div
                style={{
                  fontSize: 13,
                  color: importResult.error ? C.red : C.green,
                  marginBottom: 10,
                }}
              >
                {importResult.error ||
                  `Imported ${importResult.imported}, skipped ${importResult.skipped}`}
              </div>
            )}

            {/* Action buttons */}
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
              <Btn onClick={onClose}>Close</Btn>
              <Btn primary onClick={handleImport}>
                Import
              </Btn>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
