"use client";

import { useState, useEffect, useRef } from "react";

const API = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

interface Dimension {
  name: string;
  score: number;
  weight: number;
  passed: number;
  total: number;
  issues: string[];
  detail: string;
}

interface CaseScore {
  case_id: string;
  theme: string;
  age: number;
  total_score: number;
  grade: string;
  row_count: number;
  dimensions: Dimension[];
  duration_seconds?: number;
  retries?: Record<string, number>;
  error?: string;
}

interface EvalRun {
  id: string;
  timestamp: string;
  prompt_version: string;
  model: string;
  total_cases: number;
  completed_cases: number;
  avg_score: number;
  grade_distribution: Record<string, number>;
  duration_seconds: number;
  scores?: CaseScore[];
}

const GRADE_COLORS: Record<string, string> = {
  A: "#22c55e",
  B: "#84cc16",
  C: "#eab308",
  D: "#f97316",
  F: "#ef4444",
};

export default function EvalPage() {
  const [runs, setRuns] = useState<EvalRun[]>([]);
  const [selectedRun, setSelectedRun] = useState<EvalRun | null>(null);
  const [selectedCase, setSelectedCase] = useState<CaseScore | null>(null);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState<string[]>([]);
  const [promptVersion, setPromptVersion] = useState("v1");
  const [skipImages, setSkipImages] = useState(true);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetchRuns();
  }, []);

  async function fetchRuns() {
    try {
      const res = await fetch(`${API}/api/eval/results`);
      if (res.ok) setRuns(await res.json());
    } catch {}
  }

  async function loadRunDetail(id: string) {
    try {
      const res = await fetch(`${API}/api/eval/results/${id}`);
      if (res.ok) {
        const data = await res.json();
        setSelectedRun(data);
        setSelectedCase(null);
      }
    } catch {}
  }

  async function startEval() {
    setRunning(true);
    setProgress([]);
    setSelectedRun(null);
    setSelectedCase(null);

    try {
      const res = await fetch(`${API}/api/eval/run/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt_version: promptVersion,
          skip_images: skipImages,
        }),
      });

      const reader = res.body?.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (reader) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const evt = JSON.parse(line.slice(6));
            if (evt.kind === "eval_start") {
              setProgress((p) => [...p, `Starting eval: ${evt.total_cases} cases`]);
            } else if (evt.kind === "eval_case_start") {
              setProgress((p) => [
                ...p,
                `[${evt.index + 1}] Running: ${evt.theme} (age ${evt.age})...`,
              ]);
            } else if (evt.kind === "eval_case_done") {
              setProgress((p) => [
                ...p,
                `[${evt.index + 1}] ${evt.case_id}: ${evt.grade} (${evt.score}) in ${evt.duration}s`,
              ]);
            } else if (evt.kind === "eval_complete") {
              setProgress((p) => [
                ...p,
                `\nDone! Avg: ${evt.avg_score} | Grades: ${JSON.stringify(evt.grades)} | ${evt.duration}s`,
              ]);
              // Reload the run detail
              if (evt.run_id) loadRunDetail(evt.run_id);
              fetchRuns();
            }
          } catch {}
        }

        if (logRef.current) {
          logRef.current.scrollTop = logRef.current.scrollHeight;
        }
      }
    } catch (e: any) {
      setProgress((p) => [...p, `Error: ${e.message}`]);
    }
    setRunning(false);
  }

  return (
    <div style={{ maxWidth: 1100, margin: "0 auto", padding: "32px 24px 80px" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 24,
        }}
      >
        <div>
          <h1 style={{ fontSize: 28, margin: 0 }}>Eval Dashboard</h1>
          <p style={{ color: "var(--ink-faint)", fontSize: 14, marginTop: 4 }}>
            Automated scoring against the SpeakX pedagogical rubric
          </p>
        </div>
        <a href="/" style={{ fontSize: 13, color: "var(--ink-soft)" }}>
          &larr; App
        </a>
      </div>

      {/* Run controls */}
      <div className="card" style={{ padding: 20, marginBottom: 20 }}>
        <h2 style={{ fontSize: 17, marginBottom: 12 }}>Run Evaluation</h2>
        <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <label style={{ fontSize: 13 }}>
            Prompt version:
            <input
              value={promptVersion}
              onChange={(e) => setPromptVersion(e.target.value)}
              style={{ ...inp, width: 100, marginLeft: 6 }}
            />
          </label>
          <label style={{ fontSize: 13, display: "flex", alignItems: "center", gap: 4 }}>
            <input
              type="checkbox"
              checked={skipImages}
              onChange={(e) => setSkipImages(e.target.checked)}
            />
            Skip images (faster)
          </label>
          <button
            className="btn btn-accent"
            onClick={startEval}
            disabled={running}
            style={{ marginLeft: "auto" }}
          >
            {running ? "Running..." : "Run All Cases"}
          </button>
        </div>
        {progress.length > 0 && (
          <div
            ref={logRef}
            style={{
              marginTop: 12,
              padding: 12,
              background: "#1a1a2e",
              color: "#a0d0a0",
              borderRadius: 8,
              fontFamily: "ui-monospace, monospace",
              fontSize: 12,
              maxHeight: 200,
              overflow: "auto",
              whiteSpace: "pre-wrap",
            }}
          >
            {progress.map((line, i) => (
              <div key={i}>{line}</div>
            ))}
          </div>
        )}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "320px 1fr", gap: 20 }}>
        {/* Left: run history */}
        <div>
          <h3 style={{ fontSize: 15, marginBottom: 10, color: "var(--ink-soft)" }}>
            Past Runs
          </h3>
          {runs.length === 0 && (
            <p style={{ color: "var(--ink-faint)", fontSize: 13 }}>
              No eval runs yet. Click "Run All Cases" to start.
            </p>
          )}
          {runs.map((run) => (
            <div
              key={run.id}
              onClick={() => loadRunDetail(run.id)}
              className="card"
              style={{
                padding: 14,
                marginBottom: 8,
                cursor: "pointer",
                border:
                  selectedRun?.id === run.id
                    ? "2px solid var(--accent)"
                    : "1px solid var(--line)",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ fontWeight: 600, fontSize: 14 }}>
                  {run.prompt_version}
                </span>
                <span
                  style={{
                    fontSize: 22,
                    fontWeight: 700,
                    color:
                      run.avg_score >= 80
                        ? "#22c55e"
                        : run.avg_score >= 60
                          ? "#eab308"
                          : "#ef4444",
                  }}
                >
                  {run.avg_score}
                </span>
              </div>
              <div style={{ fontSize: 12, color: "var(--ink-faint)", marginTop: 4 }}>
                {run.model} &middot; {run.total_cases} cases &middot;{" "}
                {run.duration_seconds}s
              </div>
              <div style={{ display: "flex", gap: 4, marginTop: 6 }}>
                {Object.entries(run.grade_distribution || {}).map(([g, n]) => (
                  <span
                    key={g}
                    style={{
                      display: "inline-block",
                      padding: "2px 8px",
                      borderRadius: 4,
                      fontSize: 11,
                      fontWeight: 600,
                      background: GRADE_COLORS[g] + "22",
                      color: GRADE_COLORS[g],
                    }}
                  >
                    {g}: {n as number}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>

        {/* Right: detail */}
        <div>
          {selectedRun && !selectedCase && (
            <>
              <h3 style={{ fontSize: 15, marginBottom: 10 }}>
                Run: {selectedRun.prompt_version} &mdash; Avg {selectedRun.avg_score}/100
              </h3>

              {/* Score cards grid */}
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
                  gap: 10,
                }}
              >
                {(selectedRun.scores || []).map((cs) => (
                  <div
                    key={cs.case_id}
                    onClick={() => setSelectedCase(cs)}
                    className="card"
                    style={{ padding: 14, cursor: "pointer" }}
                  >
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                      }}
                    >
                      <div>
                        <div style={{ fontWeight: 600, fontSize: 14 }}>
                          {cs.theme}
                        </div>
                        <div
                          style={{ fontSize: 12, color: "var(--ink-faint)" }}
                        >
                          Age {cs.age} &middot; {cs.row_count} rows
                        </div>
                      </div>
                      <div
                        style={{
                          fontSize: 28,
                          fontWeight: 800,
                          color: GRADE_COLORS[cs.grade] || "#888",
                        }}
                      >
                        {cs.grade}
                      </div>
                    </div>
                    <div
                      style={{
                        marginTop: 8,
                        height: 6,
                        background: "#e5e5e5",
                        borderRadius: 3,
                        overflow: "hidden",
                      }}
                    >
                      <div
                        style={{
                          height: "100%",
                          width: `${cs.total_score}%`,
                          background: GRADE_COLORS[cs.grade] || "#888",
                          borderRadius: 3,
                        }}
                      />
                    </div>
                    <div
                      style={{
                        fontSize: 12,
                        color: "var(--ink-faint)",
                        marginTop: 4,
                        textAlign: "right",
                      }}
                    >
                      {cs.total_score}/100
                    </div>
                    {cs.error && (
                      <div
                        style={{ fontSize: 11, color: "#ef4444", marginTop: 4 }}
                      >
                        {cs.error}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </>
          )}

          {/* Case detail view */}
          {selectedCase && (
            <div>
              <button
                className="btn btn-ghost"
                onClick={() => setSelectedCase(null)}
                style={{ marginBottom: 12, fontSize: 13 }}
              >
                &larr; Back to run
              </button>
              <div className="card" style={{ padding: 20 }}>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                  }}
                >
                  <div>
                    <h3 style={{ fontSize: 20, margin: 0 }}>
                      {selectedCase.theme} (Age {selectedCase.age})
                    </h3>
                    <p style={{ color: "var(--ink-faint)", fontSize: 13 }}>
                      {selectedCase.case_id} &middot; {selectedCase.row_count}{" "}
                      rows &middot; {selectedCase.duration_seconds}s
                    </p>
                  </div>
                  <div
                    style={{
                      fontSize: 42,
                      fontWeight: 800,
                      color: GRADE_COLORS[selectedCase.grade],
                    }}
                  >
                    {selectedCase.grade}
                  </div>
                </div>

                <div
                  style={{
                    fontSize: 32,
                    fontWeight: 700,
                    marginTop: 8,
                    color:
                      selectedCase.total_score >= 80
                        ? "#22c55e"
                        : selectedCase.total_score >= 60
                          ? "#eab308"
                          : "#ef4444",
                  }}
                >
                  {selectedCase.total_score}/100
                </div>

                {/* Dimension breakdown */}
                <h4
                  style={{
                    fontSize: 14,
                    marginTop: 20,
                    marginBottom: 10,
                    color: "var(--ink-soft)",
                  }}
                >
                  Scoring Dimensions
                </h4>
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {(selectedCase.dimensions || []).map((dim) => (
                    <DimensionBar key={dim.name} dim={dim} />
                  ))}
                </div>

                {/* Retries */}
                {selectedCase.retries && (
                  <div style={{ marginTop: 16 }}>
                    <h4
                      style={{
                        fontSize: 13,
                        color: "var(--ink-soft)",
                        marginBottom: 6,
                      }}
                    >
                      Retries
                    </h4>
                    <div style={{ display: "flex", gap: 12, fontSize: 13 }}>
                      {Object.entries(selectedCase.retries).map(([k, v]) => (
                        <span key={k}>
                          {k}: <strong>{v as number}</strong>
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {!selectedRun && !selectedCase && (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                height: 200,
                color: "var(--ink-faint)",
                fontSize: 14,
              }}
            >
              Select an eval run or start a new one
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function DimensionBar({ dim }: { dim: Dimension }) {
  const pct = Math.round(dim.score * 100);
  const color = pct >= 80 ? "#22c55e" : pct >= 60 ? "#eab308" : "#ef4444";
  const [expanded, setExpanded] = useState(false);

  return (
    <div
      style={{
        border: "1px solid var(--line)",
        borderRadius: 8,
        overflow: "hidden",
      }}
    >
      <div
        onClick={() => setExpanded(!expanded)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "8px 12px",
          cursor: "pointer",
        }}
      >
        <span
          style={{
            minWidth: 170,
            fontSize: 13,
            fontWeight: 500,
            textTransform: "capitalize",
          }}
        >
          {dim.name.replace(/_/g, " ")}
        </span>
        <div
          style={{
            flex: 1,
            height: 8,
            background: "#e5e5e5",
            borderRadius: 4,
            overflow: "hidden",
          }}
        >
          <div
            style={{
              height: "100%",
              width: `${pct}%`,
              background: color,
              borderRadius: 4,
              transition: "width 0.3s",
            }}
          />
        </div>
        <span style={{ fontSize: 13, fontWeight: 600, minWidth: 40, textAlign: "right" }}>
          {pct}%
        </span>
        <span
          style={{ fontSize: 11, color: "var(--ink-faint)", minWidth: 50 }}
        >
          w:{dim.weight}
        </span>
        <span style={{ fontSize: 12 }}>{expanded ? "▲" : "▼"}</span>
      </div>
      {expanded && (
        <div
          style={{
            padding: "6px 12px 10px",
            background: "var(--cream)",
            fontSize: 12,
          }}
        >
          <div style={{ color: "var(--ink-soft)", marginBottom: 4 }}>
            {dim.detail} ({dim.passed}/{dim.total} checks)
          </div>
          {dim.issues.length > 0 && (
            <ul
              style={{
                margin: "4px 0 0 16px",
                padding: 0,
                color: "#ef4444",
                fontSize: 11.5,
              }}
            >
              {dim.issues.map((issue, i) => (
                <li key={i} style={{ marginBottom: 2 }}>
                  {issue}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

const inp: React.CSSProperties = {
  padding: "7px 10px",
  borderRadius: 7,
  border: "1px solid var(--line)",
  background: "var(--cream)",
  fontSize: 13,
};
