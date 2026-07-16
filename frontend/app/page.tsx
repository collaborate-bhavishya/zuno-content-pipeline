"use client";

import { useState, useRef, useEffect } from "react";
import { streamPost, FeedEvent, fetchRuns, RunRecord } from "../lib/api";
import { authHeaders } from "../lib/supabase";
import ProcessFeed, { FeedItem, eventToItem } from "../components/ProcessFeed";
import OutputPanel from "../components/OutputPanel";

type Complete = Extract<FeedEvent, { kind: "complete" }>;

export default function Home() {
  const [theme, setTheme] = useState("");
  const [age, setAge] = useState(5);
  const [milestoneCode, setMilestoneCode] = useState("AG05");
  const [themeCode, setThemeCode] = useState("T01");
  const [items, setItems] = useState<FeedItem[]>([]);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<Complete | null>(null);
  const [started, setStarted] = useState(false);
  const [history, setHistory] = useState<RunRecord[]>([]);
  const [currentRunId, setCurrentRunId] = useState<string | null>(null);
  const [finishingUp, setFinishingUp] = useState(false); // questions shown, eval still running
  const idRef = useRef(0);

  useEffect(() => {
    fetchRuns().then(setHistory);
  }, []);

  async function run(path: string, body: any) {
    setItems([]);
    setResult(null);
    setRunning(true);
    setStarted(true);
    setFinishingUp(false);
    idRef.current = 0;

    try {
      await streamPost(path, body, (e: FeedEvent) => {
        if (e.kind === "node") {
          setItems((prev) => [...prev, eventToItem(e, idRef.current++)]);
        } else if ((e as any).kind === "error") {
          setItems((prev) => [...prev, {
            id: idRef.current++, label: "Run stopped",
            action: (e as any).message || "The run was stopped.", status: "fail" as const,
          }]);
        } else if (e.kind === "questions_ready") {
          // Questions are finalized — show them for review while eval finishes.
          setFinishingUp(true);
          setResult({
            kind: "complete",
            theme, age,
            blueprint: (e as any).blueprint,
            matrix: (e as any).matrix,
            images: [], failed: [], history: [],
            eval: undefined, metrics: undefined, pending_images: [],
          } as any);
        } else if (e.kind === "complete") {
          setFinishingUp(false);
          setResult(e);
          const m = (e as any).metrics;
          const costStr = m ? ` · $${m.total_cost < 0.01 ? m.total_cost.toFixed(4) : m.total_cost.toFixed(3)}` : "";
          const timeStr = m ? ` · ${(m.total_latency_ms / 1000).toFixed(1)}s` : "";
          setItems((prev) => [
            ...prev,
            {
              id: idRef.current++,
              label: "Generation complete",
              action: `${e.matrix?.length || 0} questions · ${(e as any).pending_images?.length || 0} images registered${timeStr}${costStr}`,
              status: "pass" as const,
            },
          ]);
        }
      });
    } catch (err) {
      setItems((prev) => [
        ...prev,
        { id: idRef.current++, label: "Error", action: String(err), status: "fail" },
      ]);
    } finally {
      setRunning(false);
      fetchRuns().then((runs) => {
        setHistory(runs);
        if (runs.length > 0) setCurrentRunId(runs[0].id);
      });
    }
  }

  function viewRun(run: RunRecord) {
    setResult({
      kind: "complete",
      theme: run.theme,
      age: run.age,
      blueprint: run.blueprint,
      matrix: run.matrix,
      images: run.images,
      failed: run.failed,
      history: run.history,
      eval: run.eval,
      metrics: run.metrics,
      pending_images: (run as any).pending_images,
      play_url: (run as any).play_url,
      s3_uri: (run as any).s3_uri,
    } as any);
    setCurrentRunId(run.id);
    setTheme(run.theme);
    setAge(run.age);
    setMilestoneCode(run.milestone_code || `AG0${run.age}`);
    setThemeCode(run.theme_code || "T01");
    // Restore the saved process log so it persists across viewing past runs.
    const savedFeed = (run as any).feed as
      | { node: string; label: string; action: string; detail: any }[]
      | undefined;
    if (savedFeed && savedFeed.length) {
      setItems(
        savedFeed.map((e, i) =>
          eventToItem({ kind: "node", ...e } as any, i)
        )
      );
    } else {
      setItems([]);
    }
    setFinishingUp(false);
    setRunning(false);
    setStarted(true);
  }

  const start = () => {
    if (!theme.trim()) return;
    run("/api/generate", {
      theme: theme.trim(), age, milestone_code: milestoneCode, theme_code: themeCode,
    });
  };
  const approve = async () => fetch(`${process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000"}/api/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify({ action: "approve", theme, age, milestone_code: milestoneCode, theme_code: themeCode }),
  });
  const rerun = (phase: string = "all") =>
    run("/api/feedback", { action: "rerun", theme, age, phase, run_id: currentRunId,
      milestone_code: milestoneCode, theme_code: themeCode });
  const sendFeedback = (text: string, phase: string = "all") =>
    run("/api/feedback", { action: "feedback", theme, age, feedback: text, phase, run_id: currentRunId,
      milestone_code: milestoneCode, theme_code: themeCode });

  return (
    <main style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      {/* top bar */}
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "16px 28px",
          borderBottom: "1px solid var(--line)",
        }}
      >
        <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
          <span
            className="display"
            style={{ fontSize: 22, fontWeight: 600, cursor: "pointer" }}
            onClick={() => { setStarted(false); setResult(null); setItems([]); setRunning(false); }}
          >
            Zuno
          </span>
          <span style={{ fontSize: 13, color: "var(--ink-faint)" }}>SpeakX lesson pipeline</span>
        </div>
        <div style={{ display: "flex", gap: 16 }}>
          <a href="/eval" style={{ fontSize: 13, color: "var(--ink-soft)" }}>
            Eval Dashboard
          </a>
          <a href="/admin" style={{ fontSize: 13, color: "var(--ink-soft)" }}>
            Admin →
          </a>
        </div>
      </header>

      {!started ? (
        <Landing
          theme={theme} setTheme={setTheme} age={age} setAge={(a) => { setAge(a); setMilestoneCode(`AG0${a}`); }}
          milestoneCode={milestoneCode} setMilestoneCode={setMilestoneCode}
          themeCode={themeCode} setThemeCode={setThemeCode}
          onStart={start} history={history} onViewRun={viewRun}
        />
      ) : (
        <>
        {/* Questions ready, eval still scoring */}
        {running && finishingUp && (
          <div style={{
            display: "flex", alignItems: "center", gap: 12,
            padding: "12px 28px", fontSize: 13.5,
            background: "var(--cream-deep)", borderBottom: "1px solid var(--line)",
            color: "var(--ink-soft)",
          }}>
            <div className="spinner" style={{ flexShrink: 0 }} />
            <span>
              <strong style={{ fontWeight: 600 }}>Scoring the lesson…</strong>{" "}
              Your questions are ready below — feel free to review them now.
            </span>
          </div>
        )}
        <div style={{ flex: 1, display: "grid", gridTemplateColumns: result ? "1fr 1fr" : "1fr", overflow: "hidden" }}>
          {/* LEFT — live feed */}
          <section
            style={{
              padding: "24px 28px",
              overflowY: "auto",
              borderRight: result ? "1px solid var(--line)" : "none",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18 }}>
              <h2 style={{ fontSize: 19 }}>
                {running ? "Generating" : "Process log"}
                <span style={{ color: "var(--ink-faint)", fontWeight: 400, fontSize: 15 }}>
                  {" "}· {theme} · age {age}
                </span>
              </h2>
              {!running && (
                <button className="btn btn-ghost" onClick={() => setStarted(false)}>
                  New lesson
                </button>
              )}
            </div>
            <ProcessFeed items={items} running={running} />
          </section>

          {/* RIGHT — output (appears on complete) */}
          {result && (
            <section style={{ overflow: "hidden", animation: "fadeUp .3s ease" }}>
              <OutputPanel
                data={result}
                busy={running}
                onApprove={approve}
                onFeedback={sendFeedback}
                onRerun={rerun}
              />
            </section>
          )}
        </div>
        </>
      )}

    </main>
  );
}

function Landing({
  theme,
  setTheme,
  age,
  setAge,
  milestoneCode,
  setMilestoneCode,
  themeCode,
  setThemeCode,
  onStart,
  history,
  onViewRun,
}: {
  theme: string;
  setTheme: (s: string) => void;
  age: number;
  setAge: (n: number) => void;
  milestoneCode: string;
  setMilestoneCode: (s: string) => void;
  themeCode: string;
  setThemeCode: (s: string) => void;
  onStart: () => void;
  history: RunRecord[];
  onViewRun: (run: RunRecord) => void;
}) {
  return (
    <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}>
      <div style={{ maxWidth: 540, width: "100%", textAlign: "center" }}>
        <h1 style={{ fontSize: 38, lineHeight: 1.1, marginBottom: 12 }}>
          Generate a speaking lesson
        </h1>
        <p style={{ color: "var(--ink-soft)", marginBottom: 32 }}>
          A theme and an age is all it needs. Watch four agents plan, critique, and
          self-correct their way to a finished, illustrated lesson.
        </p>

        <div className="card" style={{ padding: 24, textAlign: "left" }}>
          <label style={{ fontSize: 13, fontWeight: 600, color: "var(--ink-soft)" }}>Theme</label>
          <input
            value={theme}
            onChange={(e) => setTheme(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onStart()}
            placeholder="Trucks, Jungle, Farm…"
            autoFocus
            style={{
              width: "100%",
              padding: "12px 14px",
              marginTop: 6,
              marginBottom: 18,
              borderRadius: 9,
              border: "1px solid var(--line)",
              background: "var(--cream)",
            }}
          />

          <div style={{ display: "flex", gap: 12, marginBottom: 18 }}>
            <div style={{ flex: 1 }}>
              <label style={{ fontSize: 13, fontWeight: 600, color: "var(--ink-soft)" }}>Milestone Code</label>
              <input
                value={milestoneCode}
                onChange={(e) => setMilestoneCode(e.target.value.toUpperCase())}
                placeholder="AG05"
                style={{
                  width: "100%",
                  padding: "10px 12px",
                  marginTop: 6,
                  borderRadius: 9,
                  border: "1px solid var(--line)",
                  background: "var(--cream)",
                  fontSize: 13,
                  fontFamily: "monospace",
                }}
              />
            </div>
            <div style={{ flex: 1 }}>
              <label style={{ fontSize: 13, fontWeight: 600, color: "var(--ink-soft)" }}>Theme Code</label>
              <input
                value={themeCode}
                onChange={(e) => setThemeCode(e.target.value.toUpperCase())}
                placeholder="T01"
                style={{
                  width: "100%",
                  padding: "10px 12px",
                  marginTop: 6,
                  borderRadius: 9,
                  border: "1px solid var(--line)",
                  background: "var(--cream)",
                  fontSize: 13,
                  fontFamily: "monospace",
                }}
              />
            </div>
          </div>

          <label style={{ fontSize: 13, fontWeight: 600, color: "var(--ink-soft)" }}>
            Age · {age}
          </label>
          <input
            type="range"
            min={3}
            max={8}
            value={age}
            onChange={(e) => setAge(Number(e.target.value))}
            style={{ width: "100%", marginTop: 10, accentColor: "var(--accent)" }}
          />
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "var(--ink-faint)" }}>
            <span>3</span>
            <span>8</span>
          </div>

          <button
            className="btn btn-accent"
            disabled={!theme.trim()}
            onClick={onStart}
            style={{ width: "100%", justifyContent: "center", marginTop: 22, padding: 13 }}
          >
            Generate lesson →
          </button>
        </div>

        {history.length > 0 && (
          <div style={{ marginTop: 36, textAlign: "left" }}>
            <h2 style={{ fontSize: 20, marginBottom: 14 }}>Previous runs</h2>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {history.map((run) => (
                <button
                  key={run.id}
                  className="card"
                  onClick={() => onViewRun(run)}
                  style={{
                    padding: "14px 18px",
                    textAlign: "left",
                    cursor: "pointer",
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    transition: "background .15s ease",
                  }}
                >
                  <div>
                    <span style={{ fontWeight: 600, fontSize: 15 }}>{run.theme}</span>
                    <span style={{ color: "var(--ink-faint)", fontSize: 13, marginLeft: 10 }}>
                      age {run.age}
                    </span>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    {run.eval && (
                      <span style={{
                        display: "inline-block",
                        padding: "2px 8px",
                        borderRadius: 4,
                        fontSize: 12,
                        fontWeight: 700,
                        background: run.eval.grade === "A" ? "#22c55e22" : run.eval.grade === "B" ? "#84cc1622" : run.eval.grade === "C" ? "#eab30822" : "#ef444422",
                        color: run.eval.grade === "A" ? "#22c55e" : run.eval.grade === "B" ? "#84cc16" : run.eval.grade === "C" ? "#eab308" : "#ef4444",
                      }}>
                        {run.eval.grade} {run.eval.total_score}
                      </span>
                    )}
                    <span style={{ fontSize: 12, color: "var(--ink-faint)" }}>
                      {run.matrix?.length || 0}Q · {run.images?.length || 0} img
                    </span>
                    {(run as any).pending_images?.length > 0 && (
                      <span style={{
                        fontSize: 11, fontWeight: 600, padding: "1px 6px",
                        borderRadius: 3, background: "#fef08a", color: "#854d0e",
                      }}>
                        {(run as any).pending_images.length} pending
                      </span>
                    )}
                    {run.metrics && (
                      <span style={{ fontSize: 11, color: "var(--ink-faint)", opacity: 0.7 }}>
                        ${run.metrics.total_cost < 0.01 ? run.metrics.total_cost.toFixed(4) : run.metrics.total_cost.toFixed(3)}
                        {" · "}
                        {(run.metrics.total_latency_ms / 1000).toFixed(1)}s
                      </span>
                    )}
                    <span style={{ fontSize: 12, color: "var(--ink-faint)" }}>
                      {new Date(run.timestamp).toLocaleDateString()}
                    </span>
                    <span style={{ color: "var(--ink-faint)", fontSize: 13 }}>→</span>
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
