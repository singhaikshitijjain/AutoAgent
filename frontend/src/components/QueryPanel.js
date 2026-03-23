import React, { useState } from "react";

const EXAMPLES = [
  "AI receptionist agent",
  "Python web scraping bot",
  "FastAPI REST API starter",
  "LangChain chatbot",
  "CLI todo app Python",
];

export default function QueryPanel({
  query, setQuery, githubToken, setGithubToken,
  running, onRun, onStop, onClear
}) {
  const [showToken, setShowToken] = useState(false);
  const [tokenVisible, setTokenVisible] = useState(false);

  const handleKey = (e) => {
    if (e.key === "Enter" && !e.shiftKey && !running) {
      e.preventDefault();
      onRun();
    }
  };

  return (
    <div className="query-panel">
      <div className="query-row">
        <input
          className="query-input"
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKey}
          placeholder="Describe what you want to run… e.g. 'AI receptionist agent'"
          disabled={running}
          autoFocus
        />
        <button
          className={`btn-run ${running ? "btn-stop" : ""}`}
          onClick={running ? onStop : onRun}
          disabled={!running && !query.trim()}
        >
          {running ? (
            <><span className="spinner" /> Stop</>
          ) : "▶ Run"}
        </button>
        {!running && (query || githubToken) && (
          <button className="btn-clear" onClick={() => { onClear(); setQuery(""); }}>
            ✕
          </button>
        )}
      </div>

      <div className="examples-row">
        {EXAMPLES.map((ex) => (
          <button
            key={ex}
            className="example-chip"
            onClick={() => setQuery(ex)}
            disabled={running}
          >
            {ex}
          </button>
        ))}
      </div>

      <div className="token-row">
        <button
          className="token-toggle"
          onClick={() => setShowToken((v) => !v)}
        >
          {showToken ? "▲" : "▼"} GitHub Token (optional — higher rate limits)
        </button>
        {showToken && (
          <div className="token-input-wrap">
            <input
              className="token-input"
              type={tokenVisible ? "text" : "password"}
              value={githubToken}
              onChange={(e) => setGithubToken(e.target.value)}
              placeholder="ghp_xxxxxxxxxxxxxxxxxxxx"
            />
            <button className="token-eye" onClick={() => setTokenVisible((v) => !v)}>
              {tokenVisible ? "🙈" : "👁"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
