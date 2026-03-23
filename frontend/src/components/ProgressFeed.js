import React, { useEffect, useRef } from "react";

const STEP_LABELS = {
  0: "Environment Check",
  1: "Query Understanding",
  2: "GitHub Search",
  3: "System Analysis",
  5: "Clone Repository",
  6: "Setup & Dependencies",
  8: "Execute",
  10: "Error Classification",
  11: "Self-Healing",
  12: "Retry",
};

const TYPE_ICONS = {
  status: "⏳",
  env_check: "🖥",
  keywords: "🔍",
  github_results: "📦",
  system_info: "💻",
  ranked_repos: "🏆",
  repo_selected: "✅",
  repo_skipped: "⏭",
  cloned: "📂",
  deps_installed: "📥",
  entry_point: "🎯",
  execution_result: "⚙️",
  error_classified: "🔬",
  self_heal: "🔧",
  retry_result: "🔄",
  warning: "⚠️",
  error: "❌",
  fatal: "💥",
  success: "🎉",
  done: "📋",
};

function EventRow({ event }) {
  const icon = TYPE_ICONS[event.type] || "•";
  const isError = ["error", "fatal"].includes(event.type);
  const isSuccess = event.type === "success" || (event.type === "done" && event.status === "success");
  const isWarning = event.type === "warning";
  const isSelfHeal = event.type === "self_heal";
  const isCode = ["execution_result", "retry_result"].includes(event.type);

  return (
    <div className={`event-row ${isError ? "event-error" : ""} ${isSuccess ? "event-success" : ""} ${isWarning ? "event-warning" : ""} ${isSelfHeal ? "event-heal" : ""}`}>
      <span className="event-icon">{icon}</span>
      <div className="event-body">
        <span className="event-msg">{event.message || event.type}</span>

        {event.type === "ranked_repos" && event.repos && (
          <div className="repo-list">
            {event.repos.map((r, i) => (
              <div key={r.name} className="repo-item">
                <span className="repo-rank">#{i + 1}</span>
                <span className="repo-name">{r.name}</span>
                <span className="repo-lang">{r.language || "?"}</span>
                <span className="repo-stars">⭐{r.stars}</span>
                <span className="repo-score">score: {r.score}</span>
              </div>
            ))}
          </div>
        )}

        {event.type === "system_info" && (
          <div className="sys-info">
            <span>{event.os}</span>
            <span>RAM: {event.ram_gb}GB</span>
            <span>{event.python}</span>
            <span>{event.node ? `Node ${event.node}` : "No Node"}</span>
          </div>
        )}

        {isCode && (event.stdout || event.stderr) && (
          <div className="log-block">
            {event.stdout && <pre className="log-out">{event.stdout.slice(0, 800)}</pre>}
            {event.stderr && <pre className="log-err">{event.stderr.slice(0, 600)}</pre>}
          </div>
        )}

        {event.type === "self_heal" && event.actions && (
          <ul className="heal-actions">
            {event.actions.map((a, i) => <li key={i}>{a}</li>)}
          </ul>
        )}

        {event.type === "error_classified" && event.classification && (
          <div className={`classify-badge classify-${event.classification.type.toLowerCase()}`}>
            {event.classification.type} · {event.classification.reason}
          </div>
        )}
      </div>
    </div>
  );
}

export default function ProgressFeed({ events, running }) {
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events]);

  if (events.length === 0 && !running) {
    return (
      <div className="feed-empty">
        <div className="feed-empty-icon">🤖</div>
        <p>Enter a query and click <strong>Run</strong> to start the agent.</p>
        <p className="feed-empty-sub">The agent will search GitHub, clone the best repo, and execute it — fixing small errors automatically.</p>
      </div>
    );
  }

  return (
    <div className="progress-feed">
      <div className="feed-header">
        <span>Agent Log</span>
        {running && <span className="live-badge">● LIVE</span>}
      </div>
      <div className="feed-body">
        {events.map((ev, i) => <EventRow key={i} event={ev} />)}
        {running && (
          <div className="event-row event-thinking">
            <span className="event-icon">⏳</span>
            <span className="thinking-dots">Working<span className="dot-1">.</span><span className="dot-2">.</span><span className="dot-3">.</span></span>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
