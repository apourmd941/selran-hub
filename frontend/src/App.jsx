/**
 * App component - main application root.
 *
 * Orchestrates the entire MCP Server Dashboard:
 * - Manages global state (sources, statistics, UI visibility)
 * - Handles data fetching and refreshing
 * - Composes all child components (panels, modals, list views)
 * - Provides filtering and search across data sources
 *
 * This is the entry point for the application.
 */

import { useState, useEffect, useCallback } from "react";
import { C, css } from "./theme";
import {
  fetchSources,
  fetchStats,
  createSource,
  updateSource,
  deleteSource,
  toggleSource,
  checkSource,
} from "./api";

// Component imports
import StatCard from "./components/StatCard";
import { Btn, SmallBtn } from "./components/Btn";
import SearchInput from "./components/SearchInput";
import TabBar from "./components/TabBar";
import SourceRow from "./components/SourceRow";
import SourceModal from "./components/SourceModal";
import SourceDetail from "./components/SourceDetail";
import MCPConfigPanel from "./components/MCPConfigPanel";
import ImportExportPanel from "./components/ImportExportPanel";
import LogPanel from "./components/LogPanel";
import SettingsPanel from "./components/SettingsPanel";

// Configuration
const POLL_INTERVAL = 45000; // 45 seconds between background refreshes

/**
 * Main App component - dashboard root.
 */
export default function App() {
  // Data state
  const [sources, setSources] = useState([]);
  const [stats, setStats] = useState({});
  const [loading, setLoading] = useState(true);

  // UI state - detail panel
  const [selected, setSelected] = useState(null);

  // UI state - modals
  const [showAdd, setShowAdd] = useState(false);
  const [showEdit, setShowEdit] = useState(null);
  const [showConfig, setShowConfig] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [showLogs, setShowLogs] = useState(false);
  const [showSettings, setShowSettings] = useState(false);

  // UI state - filtering
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("all");

  /**
   * Refresh sources and statistics from the backend.
   * Used on initial load, after mutations, and on interval.
   */
  const refresh = useCallback(() => {
    fetchSources()
      .then((d) => {
        setSources(d);
        setLoading(false);
      })
      .catch(() => setLoading(false));

    fetchStats().then(setStats);
  }, []);

  /**
   * Set up initial load and auto-refresh interval.
   */
  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, POLL_INTERVAL);
    return () => clearInterval(interval);
  }, [refresh]);

  /**
   * Handle adding a new source.
   */
  const handleAddSource = (formData) => {
    createSource(formData).then(() => {
      setShowAdd(false);
      refresh();
    });
  };

  /**
   * Handle editing an existing source.
   */
  const handleEditSource = (formData, sourceId) => {
    updateSource(sourceId, formData).then(() => {
      setShowEdit(null);
      refresh();
    });
  };

  /**
   * Handle deleting a source with confirmation.
   */
  const handleDeleteSource = (sourceId) => {
    if (!confirm("Remove this data source?")) return;

    deleteSource(sourceId).then(() => {
      if (selected?.id === sourceId) {
        setSelected(null);
      }
      refresh();
    });
  };

  /**
   * Filter sources based on type filter and search query.
   */
  const filtered = sources.filter((s) => {
    // Type filter
    if (typeFilter !== "all" && s.type !== typeFilter) {
      return false;
    }

    // Search filter - check name, path, url, and description
    if (search) {
      const q = search.toLowerCase();
      return (
        s.name.toLowerCase().includes(q) ||
        (s.path || "").toLowerCase().includes(q) ||
        (s.url || "").toLowerCase().includes(q) ||
        (s.description || "").toLowerCase().includes(q)
      );
    }

    return true;
  });

  /**
   * Count sources by type for tab labels.
   */
  const typeCounts = { all: sources.length };
  sources.forEach((s) => {
    typeCounts[s.type] = (typeCounts[s.type] || 0) + 1;
  });

  return (
    <>
      {/* Global styles */}
      <style>{css}</style>

      {/* Main layout */}
      <div style={{ maxWidth: 1200, margin: "0 auto", padding: "28px 24px" }}>
        {/* Header */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: 28,
          }}
        >
          {/* Title */}
          <div>
            <h1 style={{ fontSize: 26, fontWeight: 800, letterSpacing: -0.5 }}>
              <span style={{ color: C.accent }}>MCP</span> Server
            </h1>
            <p style={{ fontSize: 13, color: C.textDim, marginTop: 3 }}>
              Manage data sources for AI tools
            </p>
          </div>

          {/* Action buttons */}
          <div style={{ display: "flex", gap: 8 }}>
            <Btn small onClick={() => setShowLogs(true)}>
              📋 Logs
            </Btn>
            <Btn small onClick={() => setShowImport(true)}>
              ↕ Import/Export
            </Btn>
            <Btn small onClick={() => setShowSettings(true)}>
              ⚙ Settings
            </Btn>
            <Btn small onClick={() => setShowConfig(true)}>
              🔌 MCP Config
            </Btn>
            <Btn primary onClick={() => setShowAdd(true)}>
              + Add Source
            </Btn>
          </div>
        </div>

        {/* Statistics Cards */}
        <div
          style={{
            display: "flex",
            gap: 14,
            marginBottom: 24,
            flexWrap: "wrap",
          }}
        >
          <StatCard
            label="Total Sources"
            value={stats.total || 0}
            icon="📊"
            sub={
              stats.types
                ? Object.entries(stats.types)
                    .map(([k, v]) => `${v} ${k}`)
                    .join(", ")
                : null
            }
          />
          <StatCard
            label="Online"
            value={stats.online || 0}
            color={C.green}
            icon="✅"
          />
          <StatCard
            label="Offline"
            value={stats.offline || 0}
            color={C.textMuted}
            icon="⏸️"
          />
          <StatCard
            label="Errors"
            value={stats.error || 0}
            color={stats.error > 0 ? C.red : C.textMuted}
            icon={stats.error > 0 ? "⚠️" : "✔️"}
          />
        </div>

        {/* Source List Container */}
        <div
          style={{
            background: C.surface,
            borderRadius: 14,
            border: `1px solid ${C.border}`,
            overflow: "hidden",
          }}
        >
          {/* Filter and search bar */}
          <div
            style={{
              padding: "12px 18px",
              borderBottom: `1px solid ${C.border}`,
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              gap: 12,
              flexWrap: "wrap",
            }}
          >
            {/* Type filter tabs */}
            <TabBar
              tabs={[
                { id: "all", label: "All", count: typeCounts.all },
                ...["folder", "duckdb", "sqlite", "api"]
                  .filter((t) => typeCounts[t])
                  .map((t) => ({
                    id: t,
                    label:
                      t === "folder"
                        ? "Folder"
                        : t === "duckdb"
                        ? "DuckDB"
                        : t === "sqlite"
                        ? "SQLite"
                        : "REST API",
                    count: typeCounts[t],
                  })),
              ]}
              active={typeFilter}
              onChange={setTypeFilter}
            />

            {/* Search and refresh */}
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <SearchInput
                value={search}
                onChange={setSearch}
                placeholder="Search sources..."
              />
              <SmallBtn onClick={refresh} title="Refresh">
                ↻
              </SmallBtn>
            </div>
          </div>

          {/* Source list or empty state */}
          {loading ? (
            <div style={{ padding: 40, textAlign: "center", color: C.textMuted }}>
              Loading sources...
            </div>
          ) : filtered.length === 0 ? (
            <div style={{ padding: 50, textAlign: "center" }}>
              <div style={{ fontSize: 44, marginBottom: 10 }}>
                {search || typeFilter !== "all" ? "🔍" : "📂"}
              </div>
              <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 4 }}>
                {search || typeFilter !== "all"
                  ? "No matching sources"
                  : "No data sources yet"}
              </div>
              <div style={{ fontSize: 13, color: C.textDim, marginBottom: 18 }}>
                {search || typeFilter !== "all"
                  ? "Try a different filter"
                  : "Connect a folder, database, or API to get started"}
              </div>
              {!search && typeFilter === "all" && (
                <Btn primary onClick={() => setShowAdd(true)}>
                  + Add Your First Source
                </Btn>
              )}
            </div>
          ) : (
            /* Source rows */
            filtered.map((s) => (
              <SourceRow
                key={s.id}
                source={s}
                onSelect={setSelected}
                onToggle={toggleSource}
                onCheck={checkSource}
                onDelete={handleDeleteSource}
                onEdit={(source) => setShowEdit(source)}
              />
            ))
          )}
        </div>
      </div>

      {/* Panels and Modals */}
      {selected && (
        <SourceDetail source={selected} onClose={() => setSelected(null)} />
      )}
      {showAdd && (
        <SourceModal
          onClose={() => setShowAdd(false)}
          onSubmit={handleAddSource}
        />
      )}
      {showEdit && (
        <SourceModal
          onClose={() => setShowEdit(null)}
          onSubmit={handleEditSource}
          editing={showEdit}
        />
      )}
      {showConfig && <MCPConfigPanel onClose={() => setShowConfig(false)} />}
      {showImport && (
        <ImportExportPanel
          onClose={() => setShowImport(false)}
          onRefresh={refresh}
        />
      )}
      {showLogs && <LogPanel onClose={() => setShowLogs(false)} />}
      {showSettings && <SettingsPanel onClose={() => setShowSettings(false)} />}
    </>
  );
}
