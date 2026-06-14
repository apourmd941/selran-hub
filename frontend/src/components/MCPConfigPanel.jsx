/**
 * MCPConfigPanel component - modal for MCP configuration and installation.
 *
 * Displays MCP configuration in JSON format for different clients and transport modes.
 * Supports:
 * - Client format: Claude Desktop or Generic MCP client
 * - Transport mode: stdio (local) or SSE (network)
 *
 * Users can copy the config or install directly to their system (Claude Desktop only).
 *
 * @param {Object} props - Component props
 * @param {Function} props.onClose - Callback to close modal
 * @returns {JSX.Element} Modal dialog
 */

import { useState, useEffect } from "react";
import { C } from "../theme";
import { Btn } from "./Btn";
import { fetchMCPConfig, installMCPConfig } from "../api";

export default function MCPConfigPanel({ onClose }) {
  const [config, setConfig] = useState(null);
  const [format, setFormat] = useState("claude");
  const [transport, setTransport] = useState("stdio");
  const [installResult, setInstallResult] = useState(null);
  const [copied, setCopied] = useState(false);

  // Fetch config whenever format or transport changes
  useEffect(() => {
    fetchMCPConfig(format, transport).then(setConfig);
  }, [format, transport]);

  /**
   * Copy config JSON to clipboard.
   */
  const handleCopy = () => {
    navigator.clipboard.writeText(JSON.stringify(config, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  /**
   * Install config to Claude Desktop config file.
   */
  const handleInstall = () => {
    installMCPConfig(format, transport).then(setInstallResult);
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
        <h2 style={{ fontSize: 19, fontWeight: 700, marginBottom: 6 }}>
          MCP Configuration
        </h2>
        <p style={{ fontSize: 13, color: C.textDim, marginBottom: 18 }}>
          Connect AI clients to your data sources through MCP.
        </p>

        {/* ─── Client Format Selector ─────────────────────────────────── */}
        <div
          style={{
            fontSize: 11,
            fontWeight: 600,
            color: C.textMuted,
            marginBottom: 6,
            letterSpacing: 0.8,
          }}
        >
          CLIENT FORMAT
        </div>
        <div style={{ display: "flex", gap: 6, marginBottom: 14 }}>
          {["claude", "generic"].map((f) => (
            <button
              key={f}
              onClick={() => {
                setFormat(f);
                setInstallResult(null);
              }}
              style={{
                padding: "8px 14px",
                borderRadius: 8,
                fontSize: 13,
                background: format === f ? C.accentBg : C.bgAlt,
                border: `1px solid ${format === f ? C.accent : C.border}`,
                color: format === f ? C.accentHover : C.textDim,
                fontWeight: format === f ? 600 : 400,
              }}
            >
              {f === "claude" ? "Claude Desktop" : "Generic"}
            </button>
          ))}
        </div>

        {/* ─── Transport Mode Selector ────────────────────────────────── */}
        <div
          style={{
            fontSize: 11,
            fontWeight: 600,
            color: C.textMuted,
            marginBottom: 6,
            letterSpacing: 0.8,
          }}
        >
          TRANSPORT MODE
        </div>
        <div style={{ display: "flex", gap: 6, marginBottom: 6 }}>
          {[
            {
              id: "stdio",
              label: "stdio (local)",
              desc: "AI launches the bridge as a child process",
            },
            {
              id: "sse",
              label: "SSE (network)",
              desc: "Bridge runs as an HTTP server — supports remote access",
            },
          ].map((t) => (
            <button
              key={t.id}
              onClick={() => {
                setTransport(t.id);
                setInstallResult(null);
              }}
              style={{
                padding: "8px 14px",
                borderRadius: 8,
                fontSize: 13,
                background: transport === t.id ? C.accentBg : C.bgAlt,
                border: `1px solid ${transport === t.id ? C.accent : C.border}`,
                color: transport === t.id ? C.accentHover : C.textDim,
                fontWeight: transport === t.id ? 600 : 400,
              }}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* Transport mode description */}
        <div style={{ fontSize: 12, color: C.textMuted, marginBottom: 14 }}>
          {transport === "stdio"
            ? "Best for local setups — Claude launches the bridge automatically."
            : "Best for remote or multi-client setups — run the bridge separately with: python mcp_bridge.py --transport sse"}
        </div>

        {/* ─── Config JSON Display ────────────────────────────────────── */}
        <pre
          style={{
            background: C.bgAlt,
            borderRadius: 10,
            padding: 14,
            fontSize: 12,
            lineHeight: 1.6,
            overflow: "auto",
            maxHeight: 280,
            border: `1px solid ${C.border}`,
            fontFamily: "monospace",
          }}
        >
          {config ? JSON.stringify(config, null, 2) : "Loading..."}
        </pre>

        {/* ─── Footer with Actions ────────────────────────────────────── */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginTop: 14,
          }}
        >
          <div>
            {installResult && (
              <span
                style={{
                  fontSize: 12,
                  color: installResult.installed ? C.green : C.red,
                }}
              >
                {installResult.installed
                  ? `Installed to ${installResult.path}`
                  : installResult.error}
              </span>
            )}
          </div>

          <div style={{ display: "flex", gap: 8 }}>
            <Btn onClick={handleCopy}>
              {copied ? "Copied!" : "Copy"}
            </Btn>
            {format === "claude" && (
              <Btn primary onClick={handleInstall}>
                Install
              </Btn>
            )}
            <Btn onClick={onClose}>Close</Btn>
          </div>
        </div>
      </div>
    </div>
  );
}
