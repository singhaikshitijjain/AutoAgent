import React, { useState, useRef, useEffect, useCallback } from "react";
import QueryPanel from "./components/QueryPanel";
import ProgressFeed from "./components/ProgressFeed";
import ResultPanel from "./components/ResultPanel";
import "./App.css";

const API_BASE = process.env.REACT_APP_API_URL || "http://localhost:8000";

function App() {
  const [query, setQuery] = useState("");
  const [githubToken, setGithubToken] = useState("");
  const [running, setRunning] = useState(false);
  const [events, setEvents] = useState([]);
  const [finalResult, setFinalResult] = useState(null);
  const abortRef = useRef(null);

  const reset = () => {
    setEvents([]);
    setFinalResult(null);
  };

  const handleRun = useCallback(async () => {
    if (!query.trim() || running) return;
    reset();
    setRunning(true);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const resp = await fetch(`${API_BASE}/api/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: query.trim(), github_token: githubToken || null }),
        signal: controller.signal,
      });

      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: "Unknown error" }));
        setEvents((e) => [...e, { type: "error", message: err.detail || "Request failed" }]);
        setRunning(false);
        return;
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop();
        for (const line of lines) {
          if (!line.trim()) continue;
          try {
            const event = JSON.parse(line);
            setEvents((prev) => [...prev, event]);
            if (event.type === "done" || event.type === "success" || event.type === "fatal") {
              setFinalResult(event);
            }
          } catch (_) {}
        }
      }
    } catch (err) {
      if (err.name !== "AbortError") {
        setEvents((e) => [...e, { type: "error", message: err.message }]);
      }
    } finally {
      setRunning(false);
    }
  }, [query, githubToken, running]);

  const handleStop = () => {
    abortRef.current?.abort();
    setRunning(false);
    setEvents((e) => [...e, { type: "status", message: "⛔ Execution stopped by user" }]);
  };

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-inner">
          <div className="logo">
            <span className="logo-icon">⚡</span>
            <div>
              <h1>AutoAgent</h1>
              <span className="logo-sub">Autonomous AI Code Execution</span>
            </div>
          </div>
          <div className="header-badges">
            <span className="badge">Ollama</span>
            <span className="badge">GitHub</span>
            <span className="badge">Self-Healing</span>
          </div>
        </div>
      </header>

      <main className="app-main">
        <QueryPanel
          query={query}
          setQuery={setQuery}
          githubToken={githubToken}
          setGithubToken={setGithubToken}
          running={running}
          onRun={handleRun}
          onStop={handleStop}
          onClear={reset}
        />

        <div className="panels">
          <ProgressFeed events={events} running={running} />
          {finalResult && <ResultPanel result={finalResult} />}
        </div>
      </main>

      <footer className="app-footer">
        <span>AutoAgent MVP · LLM: Ollama (llama3.1:8b) · No Docker · Venv sandbox</span>
      </footer>
    </div>
  );
}

export default App;
