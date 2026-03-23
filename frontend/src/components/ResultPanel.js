import React, { useState } from "react";

const STATUS_META = {
  success: { icon: "✅", label: "Success", cls: "result-success" },
  failed: { icon: "❌", label: "Failed", cls: "result-failed" },
  needs_credentials: { icon: "🔑", label: "Credentials Required", cls: "result-creds" },
};

export default function ResultPanel({ result }) {
  const [logsExpanded, setLogsExpanded] = useState(false);
  const meta = STATUS_META[result.status] || { icon: "•", label: result.status, cls: "" };

  return (
    <div className={`result-panel ${meta.cls}`}>
      <div className="result-header">
        <span className="result-icon">{meta.icon}</span>
        <div>
          <h3 className="result-title">{meta.label}</h3>
          {result.selected_repo && (
            <span className="result-repo">{result.selected_repo}</span>
          )}
        </div>
      </div>

      {result.error_summary && (
        <div className="result-section">
          <div className="result-label">Error Summary</div>
          <p className="result-summary">{result.error_summary}</p>
        </div>
      )}

      {result.actions_taken?.length > 0 && (
        <div className="result-section">
          <div className="result-label">Actions Taken</div>
          <ol className="result-list">
            {result.actions_taken.map((a, i) => <li key={i}>{a}</li>)}
          </ol>
        </div>
      )}

      {result.fixes_applied?.length > 0 && (
        <div className="result-section">
          <div className="result-label">🔧 Fixes Applied</div>
          <ul className="result-list result-fixes">
            {result.fixes_applied.map((f, i) => <li key={i}>{f}</li>)}
          </ul>
        </div>
      )}

      {result.status === "needs_credentials" && (
        <div className="result-creds-note">
          <p>This repository requires API keys or authentication credentials to run.</p>
          <p>Check the repo's README for setup instructions.</p>
        </div>
      )}

      {result.logs && (
        <div className="result-section">
          <button className="logs-toggle" onClick={() => setLogsExpanded((v) => !v)}>
            {logsExpanded ? "▲ Hide" : "▼ Show"} Execution Logs
          </button>
          {logsExpanded && (
            <pre className="result-logs">{result.logs}</pre>
          )}
        </div>
      )}

      <div className="result-json-section">
        <details>
          <summary className="json-toggle">View Raw JSON Output</summary>
          <pre className="result-json">{JSON.stringify(result, null, 2)}</pre>
        </details>
      </div>
    </div>
  );
}
