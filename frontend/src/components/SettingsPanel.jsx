/**
 * SettingsPanel component - modal for system settings, installation check,
 * and authentication.
 *
 * Displays:
 * - System information (version, platform, Python version, headless mode)
 * - Installation check (server, service, AI clients, data sources)
 * - API authentication toggle and key display
 *
 * @param {Object} props - Component props
 * @param {Function} props.onClose - Callback to close modal
 * @returns {JSX.Element} Modal dialog
 */

import { useState, useEffect } from "react";
import { C } from "../theme";
import { Btn } from "./Btn";
import { fetchAuthStatus, configureAuth, fetchSystemInfo, fetchSystemCheck } from "../api";

export default function SettingsPanel({ onClose }) {
  const [authEnabled, setAuthEnabled] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [info, setInfo] = useState(null);
  const [msg, setMsg] = useState("");
  const [checks, setChecks] = useState(null);
  const [checkLoading, setCheckLoading] = useState(false);
  const [summary, setSummary] = useState(null);

  // Load auth status and system info on mount
  useEffect(() => {
    fetchAuthStatus().then((d) => setAuthEnabled(d.enabled));
    fetchSystemInfo().then(setInfo);
  }, []);

  /**
   * Toggle API authentication on/off.
   */
  const toggleAuth = () => {
    const enabling = !authEnabled;
    configureAuth(enabling).then((d) => {
      setAuthEnabled(d.enabled);
      if (d.api_key) {
        setApiKey(d.api_key);
      }
      setMsg(d.message);
    });
  };

  /**
   * Run full system installation check.
   */
  const runSystemCheck = () => {
    setCheckLoading(true);
    fetchSystemCheck()
      .then((d) => {
        setChecks(d.checks);
        setSummary(d.summary);
        setCheckLoading(false);
      })
      .catch(() => setCheckLoading(false));
  };

  const statusIcon = (s) =>
    s === "pass" ? "\u2705" : s === "fail" ? "\u274C" : s === "warn" ? "\u26A0\uFE0F" : "\u23ED\uFE0F";
  const statusColor = (s) =>
    s === "pass" ? C.green : s === "fail" ? C.red : s === "warn" ? C.amber : C.textMuted;

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
          width: 560,
          maxHeight: "85vh",
          overflowY: "auto",
          animation: "fadeIn 0.2s ease",
        }}
      >
        <h2 style={{ fontSize: 19, fontWeight: 700, marginBottom: 18 }}>
          Settings
        </h2>

        {/* ─── System Info Section ────────────────────────────────────── */}
        {info && (
          <div
            style={{
              padding: 14,
              background: C.bgAlt,
              borderRadius: 10,
              marginBottom: 16,
              fontSize: 13,
            }}
          >
            <div
              style={{
                fontSize: 11,
                fontWeight: 600,
                color: C.textMuted,
                marginBottom: 8,
                letterSpacing: 0.8,
              }}
            >
              SYSTEM INFO
            </div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "auto 1fr",
                gap: "4px 16px",
              }}
            >
              <span style={{ color: C.textDim }}>Version</span>
              <span>{info.version}</span>

              <span style={{ color: C.textDim }}>Platform</span>
              <span>{info.platform}</span>

              <span style={{ color: C.textDim }}>Python</span>
              <span>{info.python}</span>

              <span style={{ color: C.textDim }}>Mode</span>
              <span>{info.headless ? "Headless (service)" : "Interactive"}</span>
            </div>
          </div>
        )}

        {/* ─── Installation Check Section ─────────────────────────────── */}
        <div
          style={{
            padding: 14,
            background: C.bgAlt,
            borderRadius: 10,
            marginBottom: 16,
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              marginBottom: 10,
            }}
          >
            <div
              style={{
                fontSize: 11,
                fontWeight: 600,
                color: C.textMuted,
                letterSpacing: 0.8,
              }}
            >
              INSTALLATION CHECK
            </div>
            <button
              onClick={runSystemCheck}
              disabled={checkLoading}
              style={{
                background: C.accent,
                color: C.accentContrast,
                border: "none",
                borderRadius: 8,
                padding: "6px 14px",
                fontSize: 12,
                fontWeight: 600,
                opacity: checkLoading ? 0.6 : 1,
                cursor: checkLoading ? "wait" : "pointer",
              }}
            >
              {checkLoading ? "Checking..." : "Run System Check"}
            </button>
          </div>

          {!checks && !checkLoading && (
            <div style={{ fontSize: 13, color: C.textDim }}>
              Verifies server, background service, AI client registrations, and data
              sources.
            </div>
          )}

          {checks && (
            <div>
              {summary && (
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    marginBottom: 12,
                    padding: "8px 12px",
                    borderRadius: 8,
                    fontSize: 13,
                    fontWeight: 600,
                    background: summary.all_pass ? C.greenBg : C.amberBg,
                    color: summary.all_pass ? C.green : C.amber,
                  }}
                >
                  {summary.all_pass
                    ? "\u2705 All checks passed"
                    : `\u26A0\uFE0F ${summary.passed} of ${summary.total} checks passed`}
                </div>
              )}

              {checks.map((c, i) => (
                <div
                  key={i}
                  style={{
                    display: "flex",
                    alignItems: "flex-start",
                    gap: 10,
                    padding: "6px 0",
                    borderBottom:
                      i < checks.length - 1
                        ? `1px solid ${C.border}`
                        : "none",
                  }}
                >
                  <span
                    style={{ fontSize: 14, lineHeight: "20px", flexShrink: 0 }}
                  >
                    {statusIcon(c.status)}
                  </span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div
                      style={{
                        fontSize: 13,
                        fontWeight: 600,
                        color: statusColor(c.status),
                      }}
                    >
                      {c.name}
                    </div>
                    <div
                      style={{
                        fontSize: 12,
                        color: C.textDim,
                        wordBreak: "break-word",
                      }}
                    >
                      {c.detail}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* ─── API Authentication Section ─────────────────────────────── */}
        <div
          style={{
            padding: 14,
            background: C.bgAlt,
            borderRadius: 10,
            marginBottom: 16,
          }}
        >
          <div
            style={{
              fontSize: 11,
              fontWeight: 600,
              color: C.textMuted,
              marginBottom: 10,
              letterSpacing: 0.8,
            }}
          >
            API AUTHENTICATION
          </div>

          {/* Auth toggle */}
          <label
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              fontSize: 14,
              cursor: "pointer",
              marginBottom: 8,
            }}
          >
            <input
              type="checkbox"
              checked={authEnabled}
              onChange={toggleAuth}
            />
            Require API key for requests
          </label>

          {/* Display API key after generation */}
          {apiKey && (
            <div style={{ marginTop: 8 }}>
              <div
                style={{
                  fontSize: 12,
                  color: C.textDim,
                  marginBottom: 4,
                }}
              >
                Your API key (save this — it won't be shown again):
              </div>
              <div
                style={{
                  fontFamily: "monospace",
                  fontSize: 13,
                  padding: 10,
                  background: C.bg,
                  borderRadius: 8,
                  border: `1px solid ${C.border}`,
                  wordBreak: "break-all",
                }}
              >
                {apiKey}
              </div>
            </div>
          )}

          {/* Success message */}
          {msg && (
            <div
              style={{
                fontSize: 12,
                color: C.green,
                marginTop: 8,
              }}
            >
              {msg}
            </div>
          )}
        </div>

        {/* Close button */}
        <div style={{ display: "flex", justifyContent: "flex-end" }}>
          <Btn onClick={onClose}>Close</Btn>
        </div>
      </div>
    </div>
  );
}
