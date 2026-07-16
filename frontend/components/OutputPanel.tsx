"use client";

import { useState } from "react";
import { FeedEvent, EvalDimension, RunMetrics, imageUrl } from "../lib/api";

type Complete = Extract<FeedEvent, { kind: "complete" }>;

export type RerunPhase = "all" | "blueprint" | "questions" | "images";

export default function OutputPanel({
  data,
  onApprove,
  onFeedback,
  onRerun,
  busy,
}: {
  data: Complete;
  onApprove: () => void;
  onFeedback: (text: string, phase?: RerunPhase) => void;
  onRerun: (phase: RerunPhase) => void;
  busy: boolean;
}) {
  const [tab, setTab] = useState<"blueprint" | "questions" | "images" | "eval" | "logs">("blueprint");
  const [showFeedback, setShowFeedback] = useState(false);
  const [feedbackText, setFeedbackText] = useState("");
  const [feedbackPhase, setFeedbackPhase] = useState<RerunPhase>("all");
  const [approved, setApproved] = useState(false);
  const [showRerunMenu, setShowRerunMenu] = useState(false);

  const evalData = data.eval;
  const metrics = (data as any).metrics as RunMetrics | undefined;
  const tabs: [typeof tab, string, string][] = [
    ["blueprint", "Blueprint", ""],
    ["questions", "Questions", data.matrix?.length ? `${data.matrix.length}` : ""],
    ["images", "Images", (() => {
      const imgs = data.images?.length || 0;
      const pending = (data as any).pending_images?.length || 0;
      return pending ? `${pending} pending` : (imgs ? `${imgs}` : "");
    })()],
    ["eval", "Eval", evalData?.grade || ""],
    ["logs", "Logs", data.history?.length ? `${data.history.length}` : ""],
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* header + tabs */}
      <div style={{ padding: "20px 24px 0", borderBottom: "1px solid var(--line)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
          <h2 style={{ fontSize: 21 }}>
            {data.theme} · age {data.age}
          </h2>
          {approved && <span className="tag tag-pass">approved</span>}
        </div>
        {(data as any).play_url && (
          <div style={{
            display: "flex", alignItems: "center", gap: 8, marginTop: 8,
            fontSize: 12.5,
          }}>
            <span style={{ color: "var(--ink-faint)" }}>Player URL:</span>
            <a
              href={(data as any).play_url}
              target="_blank"
              rel="noopener noreferrer"
              style={{ color: "var(--accent)", wordBreak: "break-all" }}
            >
              {(data as any).play_url}
            </a>
            <button
              className="btn btn-ghost"
              style={{ padding: "2px 8px", fontSize: 11 }}
              onClick={() => navigator.clipboard?.writeText((data as any).play_url)}
              title="Copy player URL"
            >
              Copy
            </button>
          </div>
        )}
        {metrics && metrics.total_latency_ms != null && (
          <div style={{
            display: "flex", gap: 16, marginTop: 10, fontSize: 12,
            color: "var(--ink-faint)", flexWrap: "wrap",
          }}>
            <span title="Total latency">
              {((metrics.total_latency_ms ?? 0) / 1000).toFixed(1)}s total
            </span>
            <span title="Total tokens">
              {(((metrics.total_input_tokens ?? 0) + (metrics.total_output_tokens ?? 0)) / 1000).toFixed(1)}k tokens
            </span>
            <span title="LLM calls">
              {metrics.total_llm_calls ?? 0} LLM call{metrics.total_llm_calls !== 1 ? "s" : ""}
            </span>
            {(metrics.total_image_calls ?? 0) > 0 && (
              <span title="Image calls">
                {metrics.total_image_calls} image{metrics.total_image_calls !== 1 ? "s" : ""}
              </span>
            )}
            <span title="Estimated cost" style={{ fontWeight: 600, color: "var(--ink-soft)" }}>
              ~${(metrics.total_cost ?? 0) < 0.01 ? (metrics.total_cost ?? 0).toFixed(4) : (metrics.total_cost ?? 0).toFixed(3)}
            </span>
            {metrics.retries && Object.values(metrics.retries).some(v => v > 0) && (
              <span title="Retries" style={{ color: "var(--accent)" }}>
                {Object.entries(metrics.retries).filter(([,v]) => v > 0).map(([k,v]) => `${k}: ${v}`).join(", ")} retries
              </span>
            )}
          </div>
        )}
        <div style={{ display: "flex", gap: 4, marginTop: 16 }}>
          {tabs.map(([key, label, badge]) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              style={{
                padding: "9px 15px",
                fontSize: 13.5,
                fontWeight: 500,
                color: tab === key ? "var(--ink)" : "var(--ink-faint)",
                borderBottom: tab === key ? "2px solid var(--accent)" : "2px solid transparent",
              }}
            >
              {label}
              {badge && (
                <span style={{
                  color: key === "eval" ? gradeColor(badge) : "var(--ink-faint)",
                  fontWeight: key === "eval" ? 700 : 400,
                  marginLeft: 4,
                }}>{key === "eval" ? badge : `· ${badge}`}</span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* scrollable body */}
      <div style={{ flex: 1, overflowY: "auto", padding: "20px 24px" }}>
        {tab === "blueprint" && (
          <pre
            style={{
              whiteSpace: "pre-wrap",
              fontFamily: "Spline Sans, sans-serif",
              fontSize: 14,
              lineHeight: 1.7,
              color: "var(--ink-soft)",
            }}
          >
            {data.blueprint || "No blueprint produced."}
          </pre>
        )}

        {tab === "questions" && (
          <QuestionTable rows={data.matrix || []} theme={data.theme} age={data.age} />
        )}

        {tab === "images" && (
          <div>
            {/* Images this lesson needs that don't exist yet — registered as
                pending in Supabase for the external generation process. */}
            {(data as any).pending_images?.length > 0 && (
              <div style={{
                padding: "12px 16px", marginBottom: 14, borderRadius: 10,
                background: "#fefce8", border: "1px solid #fef08a",
              }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: "#854d0e" }}>
                  {(data as any).pending_images.length} image{(data as any).pending_images.length > 1 ? "s" : ""} registered for generation
                </div>
                <div style={{ fontSize: 12, color: "#a16207", marginTop: 2 }}>
                  New images this lesson needs — saved as pending in the asset database.
                </div>
                <div style={{ fontSize: 11, color: "#a16207", marginTop: 4 }}>
                  {(data as any).pending_images.map((a: any) => a.object_name || a.filename).join(", ")}
                </div>
              </div>
            )}

            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(140px,1fr))", gap: 14 }}>
              {(data.images || []).map((img) => (
                <div key={img.filename} className="card" style={{ padding: 10, textAlign: "center" }}>
                  <div
                    style={{
                      background: "#fff",
                      borderRadius: 8,
                      aspectRatio: "1",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      overflow: "hidden",
                    }}
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={imageUrl(img.url)} alt={img.object_name} style={{ maxWidth: "100%", maxHeight: "100%" }} />
                  </div>
                  <div style={{ fontSize: 12, marginTop: 7, color: "var(--ink-soft)" }}>{img.object_name}</div>
                </div>
              ))}
              {(!data.images || data.images.length === 0) && !(data as any).pending_images?.length && (
                <div style={{ color: "var(--ink-faint)", fontSize: 13 }}>
                  No new images needed — everything is reused from the asset library.
                </div>
              )}
            </div>
          </div>
        )}

        {tab === "eval" && evalData && (
          <EvalScorecard eval={evalData} />
        )}
        {tab === "eval" && !evalData && !metrics && (
          <div style={{ color: "var(--ink-faint)", fontSize: 13 }}>No eval data available.</div>
        )}
        {tab === "eval" && metrics && (
          <MetricsBreakdown metrics={metrics} />
        )}

        {tab === "logs" && (
          <LogsPanel history={data.history || []} metrics={metrics} />
        )}
      </div>

      {/* action bar */}
      <div style={{ borderTop: "1px solid var(--line)", padding: 18, background: "var(--paper)" }}>
        {!showFeedback ? (
          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <button
              className="btn btn-accent"
              disabled={busy || approved}
              onClick={() => {
                setApproved(true);
                onApprove();
              }}
            >
              ✓ Approve
            </button>
            <button className="btn btn-ghost" disabled={busy} onClick={() => setShowFeedback(true)}>
              Add feedback
            </button>

            {/* Re-run dropdown */}
            <div style={{ position: "relative" }}>
              <button
                className="btn btn-ghost"
                disabled={busy}
                onClick={() => setShowRerunMenu(!showRerunMenu)}
              >
                ↻ Re-run ▾
              </button>
              {showRerunMenu && (
                <div style={{
                  position: "absolute", bottom: "100%", left: 0, marginBottom: 4,
                  background: "var(--paper)", border: "1px solid var(--line)",
                  borderRadius: 10, boxShadow: "0 4px 16px rgba(0,0,0,0.1)",
                  overflow: "hidden", zIndex: 10, minWidth: 220,
                }}>
                  {([
                    ["all", "Re-run everything", "Full pipeline from scratch"],
                    ["blueprint", "Re-run blueprint", "New blueprint → questions → image plan"],
                    ["questions", "Re-run questions", "Keep blueprint, redo questions → image plan"],
                    ["images", "Re-plan images", "Keep questions, redo image plan & eval"],
                  ] as [RerunPhase, string, string][]).map(([phase, label, desc]) => (
                    <button
                      key={phase}
                      onClick={() => {
                        setShowRerunMenu(false);
                        onRerun(phase);
                      }}
                      style={{
                        display: "block", width: "100%", textAlign: "left",
                        padding: "10px 14px", border: "none", background: "none",
                        cursor: "pointer", borderBottom: "1px solid var(--line)",
                      }}
                      onMouseEnter={(e) => (e.currentTarget.style.background = "var(--cream)")}
                      onMouseLeave={(e) => (e.currentTarget.style.background = "none")}
                    >
                      <div style={{ fontSize: 13, fontWeight: 500 }}>{label}</div>
                      <div style={{ fontSize: 11, color: "var(--ink-faint)", marginTop: 1 }}>{desc}</div>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <textarea
              value={feedbackText}
              onChange={(e) => setFeedbackText(e.target.value)}
              placeholder="e.g. Make the tone warmer and add more animal sounds…"
              rows={3}
              style={{
                width: "100%",
                padding: 12,
                borderRadius: 9,
                border: "1px solid var(--line)",
                background: "var(--cream)",
                resize: "vertical",
              }}
            />
            <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
              <select
                value={feedbackPhase}
                onChange={(e) => setFeedbackPhase(e.target.value as RerunPhase)}
                style={{
                  padding: "8px 10px", borderRadius: 8,
                  border: "1px solid var(--line)", background: "var(--cream)",
                  fontSize: 13,
                }}
              >
                <option value="all">Re-run everything</option>
                <option value="blueprint">Re-run from blueprint</option>
                <option value="questions">Re-run from questions</option>
                <option value="images">Re-plan images</option>
              </select>
              <button
                className="btn btn-accent"
                disabled={busy || !feedbackText.trim()}
                onClick={() => {
                  onFeedback(feedbackText.trim(), feedbackPhase);
                  setShowFeedback(false);
                  setFeedbackText("");
                  setFeedbackPhase("all");
                }}
              >
                Re-run with feedback
              </button>
              <button className="btn btn-ghost" onClick={() => { setShowFeedback(false); setFeedbackPhase("all"); }}>
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// All 26 columns in display order, grouped with separators
const ALL_COLUMNS: { key: string; label: string; group: string; isFile?: boolean }[] = [
  // Group 1: Identity & Instruction
  { key: "Playable Code", label: "Playable Code", group: "identity" },
  { key: "Playable Name", label: "Playable Name", group: "identity" },
  { key: "Layer", label: "Layer", group: "identity" },
  { key: "Template", label: "Template", group: "identity" },
  { key: "Instruction Text", label: "Instruction Text", group: "instruction" },
  { key: "Instruction VO", label: "Instruction VO", group: "instruction" },
  { key: "Instruction VO — File", label: "Inst VO File", group: "instruction", isFile: true },
  // Group 2: Question
  { key: "Text in Question", label: "Text in Question", group: "question" },
  { key: "Audio in Question", label: "Audio in Q", group: "question" },
  { key: "Audio in Question — File", label: "Audio Q File", group: "question", isFile: true },
  { key: "VO for Question", label: "VO for Question", group: "question" },
  { key: "VO for Question — File", label: "VO Q File", group: "question", isFile: true },
  { key: "Image in Question — Detail", label: "Image Detail", group: "question" },
  { key: "Image in Question — Name", label: "Image Name", group: "question", isFile: true },
  // Group 3: Answer
  { key: "Correct Answer", label: "Correct Answer", group: "answer" },
  { key: "Correct Answer VO — File", label: "Ans VO File", group: "answer", isFile: true },
  { key: "Correct Answer — Image", label: "Ans Image", group: "answer", isFile: true },
  { key: "Correct Answer — Image Detail", label: "Ans Img Detail", group: "answer" },
  { key: "Other Options", label: "Other Options", group: "answer" },
  { key: "Other Options VO — File", label: "Opts VO File", group: "answer", isFile: true },
  { key: "Other Options — Image", label: "Opts Image", group: "answer", isFile: true },
  { key: "Other Options — Image Detail", label: "Opts Img Detail", group: "answer" },
  // Group 4: Speech
  { key: "STT Expectation", label: "STT Expectation", group: "speech" },
  // Group 5: Meta
  { key: "Concept (bucket / skill)", label: "Concept", group: "meta" },
  { key: "Pattern", label: "Pattern", group: "meta" },
  { key: "Notes", label: "Notes", group: "meta" },
];

const GROUP_COLORS: Record<string, { bg: string; label: string }> = {
  identity: { bg: "#1F3864", label: "Identity" },
  instruction: { bg: "#2E75B6", label: "Instruction" },
  question: { bg: "#1B8A6B", label: "Question" },
  answer: { bg: "#C65911", label: "Answer" },
  speech: { bg: "#6B21A8", label: "Speech" },
  meta: { bg: "#475569", label: "Meta" },
};

const LAYER_ROW_COLORS: Record<string, string> = {
  "1 - Vocabulary": "#FFF9E6",
  "2 - Concept Builder": "#E6F0FF",
  "2.5 - Sentence Comprehension": "#F0E6FF",
  "3 - Sentence Formation": "#E6FFE6",
  "4 - Guided Speaking": "#FFF0E0",
  "5 - Independent Speaking": "#FFE6F0",
};

function QuestionTable({ rows, theme, age }: { rows: any[]; theme: string; age: number }) {
  if (!rows.length) return <div style={{ color: "var(--ink-faint)", fontSize: 13 }}>No questions.</div>;

  const val = (v: any) => (v && v !== "—" && v !== "—") ? String(v) : null;

  const downloadPdf = () => {
    const w = window.open("", "_blank");
    if (!w) return;
    const html = `<!DOCTYPE html>
<html><head><title>${theme} - Age ${age} - Questions</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; padding: 16px; color: #333; font-size: 10px; }
  h1 { font-size: 18px; margin-bottom: 4px; }
  .subtitle { color: #888; font-size: 11px; margin-bottom: 16px; }
  table { border-collapse: collapse; width: 100%; font-size: 9px; }
  th { background: #1F3864; color: white; padding: 4px 6px; text-align: left; font-weight: 600; white-space: nowrap; position: sticky; top: 0; }
  td { padding: 4px 6px; border-bottom: 1px solid #e5e7eb; vertical-align: top; max-width: 180px; overflow: hidden; text-overflow: ellipsis; }
  tr:nth-child(even) td { background: #f9fafb; }
  .na { color: #d1d5db; }
  .file { font-family: monospace; font-size: 8px; color: #6b7280; }
  @media print { body { padding: 8px; } th { position: static; } }
</style></head><body>
<h1>${theme} — Age ${age}</h1>
<div class="subtitle">Generated ${new Date().toLocaleDateString()} · ${rows.length} questions · Zuno SpeakX Pipeline</div>
<table>
<thead><tr>${ALL_COLUMNS.map(c => `<th>${c.label}</th>`).join("")}</tr></thead>
<tbody>
${rows.map((r: any) => {
  const cells = ALL_COLUMNS.map(c => {
    const x = r[c.key];
    const v = (x && x !== "—" && x !== "—") ? String(x) : null;
    if (v) {
      const cls = c.isFile ? "file" : "";
      return "<td class=\"" + cls + "\">" + v + "</td>";
    }
    return '<td class="na">—</td>';
  }).join("");
  return "<tr>" + cells + "</tr>";
}).join("\n")}
</tbody></table>
</body></html>`;
    w.document.write(html);
    w.document.close();
    setTimeout(() => { w.print(); }, 400);
  };

  // Compute group spans for the column group header row
  const groupSpans: { group: string; span: number }[] = [];
  ALL_COLUMNS.forEach((col) => {
    const last = groupSpans[groupSpans.length - 1];
    if (last && last.group === col.group) {
      last.span++;
    } else {
      groupSpans.push({ group: col.group, span: 1 });
    }
  });

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
        <span style={{ fontSize: 13, color: "var(--ink-faint)" }}>
          {rows.length} questions · {theme} · age {age} · 26 columns
        </span>
        <button className="btn btn-ghost" onClick={downloadPdf} style={{ fontSize: 12 }}>
          PDF
        </button>
      </div>
      <div style={{
        overflow: "auto",
        border: "1px solid var(--line)",
        borderRadius: 8,
        maxHeight: "calc(100vh - 280px)",
      }}>
        <table style={{
          borderCollapse: "collapse",
          fontSize: 11,
          whiteSpace: "nowrap",
          minWidth: "100%",
        }}>
          {/* Group header row */}
          <thead>
            <tr>
              {groupSpans.map((gs, gi) => {
                const gc = GROUP_COLORS[gs.group];
                return (
                  <th
                    key={gi}
                    colSpan={gs.span}
                    style={{
                      background: gc.bg,
                      color: "white",
                      padding: "6px 8px",
                      textAlign: "center",
                      fontSize: 10,
                      fontWeight: 700,
                      letterSpacing: "0.5px",
                      textTransform: "uppercase",
                      borderRight: "2px solid rgba(255,255,255,0.3)",
                      position: "sticky",
                      top: 0,
                      zIndex: 3,
                    }}
                  >
                    {gc.label}
                  </th>
                );
              })}
            </tr>
            {/* Column header row */}
            <tr>
              {ALL_COLUMNS.map((col, ci) => {
                const gc = GROUP_COLORS[col.group];
                return (
                  <th
                    key={ci}
                    style={{
                      background: gc.bg,
                      color: "white",
                      padding: "6px 8px",
                      textAlign: "left",
                      fontSize: 10,
                      fontWeight: 600,
                      borderRight: "1px solid rgba(255,255,255,0.15)",
                      borderTop: "1px solid rgba(255,255,255,0.2)",
                      position: "sticky",
                      top: 28,
                      zIndex: 2,
                      whiteSpace: "nowrap",
                    }}
                    title={col.key}
                  >
                    {col.label}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const layer = String(r["Layer"] || "");
              const rowBg = LAYER_ROW_COLORS[layer] || (i % 2 === 0 ? "#ffffff" : "#f9fafb");
              return (
                <tr key={i} style={{ background: rowBg }}>
                  {ALL_COLUMNS.map((col, ci) => {
                    const raw = r[col.key];
                    const v = val(raw);
                    return (
                      <td
                        key={ci}
                        style={{
                          padding: "5px 8px",
                          borderBottom: "1px solid #e5e7eb",
                          borderRight: "1px solid #f0f0f0",
                          verticalAlign: "top",
                          maxWidth: col.isFile ? 200 : 220,
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                          fontSize: col.isFile ? 10 : 11,
                          fontFamily: col.isFile ? "monospace" : "inherit",
                          color: v ? (col.isFile ? "#6b7280" : "#374151") : "#d1d5db",
                          fontStyle: v ? "normal" : "italic",
                        }}
                        title={v || "—"}
                      >
                        {v || "—"}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function QRow({ label, value, isFile }: { label: string; value: string | null; isFile?: boolean }) {
  return (
    <div style={{ display: "flex", gap: 10, fontSize: 13, marginTop: 2 }}>
      <span style={{ color: "var(--ink-faint)", minWidth: 110, fontWeight: 500, flexShrink: 0 }}>{label}</span>
      {value ? (
        <span style={{ color: isFile ? "#2563eb" : "var(--ink-soft)" }}>
          {value}
        </span>
      ) : (
        <span style={{ color: "#d1d5db", fontStyle: "italic" }}>N/A</span>
      )}
    </div>
  );
}


// ── Eval scorecard ──

function gradeColor(grade: string): string {
  const m: Record<string, string> = { A: "#22c55e", B: "#84cc16", C: "#eab308", D: "#f97316", F: "#ef4444" };
  return m[grade] || "#888";
}

function EvalScorecard({ eval: ev }: { eval: { total_score: number; grade: string; dimensions: EvalDimension[]; llm_calls?: number; error?: string } }) {
  const codeDims = (ev.dimensions || []).filter(d => d.lane === "deterministic");
  const llmDims = (ev.dimensions || []).filter(d => d.lane === "llm" || d.lane === "heuristic");

  return (
    <div>
      {/* Header score */}
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 20 }}>
        <div style={{ fontSize: 48, fontWeight: 800, color: gradeColor(ev.grade), lineHeight: 1 }}>
          {ev.grade}
        </div>
        <div>
          <div style={{ fontSize: 28, fontWeight: 700, color: ev.total_score >= 80 ? "#22c55e" : ev.total_score >= 60 ? "#eab308" : "#ef4444" }}>
            {ev.total_score}<span style={{ fontSize: 16, fontWeight: 400 }}>/100</span>
          </div>
          <div style={{ fontSize: 12, color: "var(--ink-faint)" }}>
            {codeDims.length} code checks + {llmDims.length} LLM checks
            {ev.llm_calls !== undefined && ` (${ev.llm_calls} API call${ev.llm_calls !== 1 ? "s" : ""})`}
          </div>
        </div>
      </div>

      {ev.error && (
        <div style={{ padding: 10, background: "#fef2f2", borderRadius: 8, color: "#ef4444", fontSize: 13, marginBottom: 16 }}>
          {ev.error}
        </div>
      )}

      {/* Dimension bars */}
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {(ev.dimensions || []).map((dim) => (
          <DimensionRow key={dim.name} dim={dim} />
        ))}
      </div>
    </div>
  );
}

function MetricsBreakdown({ metrics: m }: { metrics: RunMetrics }) {
  const nodes = Object.entries(m.per_node_summary);
  if (!nodes.length) return null;

  return (
    <div style={{ marginTop: 24 }}>
      <h3 style={{ fontSize: 15, fontWeight: 600, marginBottom: 12 }}>Cost breakdown by node</h3>
      <table style={{ width: "100%", fontSize: 12, borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ borderBottom: "2px solid var(--line)", textAlign: "left" }}>
            <th style={{ padding: "6px 8px", fontWeight: 600 }}>Node</th>
            <th style={{ padding: "6px 8px", fontWeight: 600 }}>Model</th>
            <th style={{ padding: "6px 8px", fontWeight: 600, textAlign: "right" }}>Calls</th>
            <th style={{ padding: "6px 8px", fontWeight: 600, textAlign: "right" }}>Tokens</th>
            <th style={{ padding: "6px 8px", fontWeight: 600, textAlign: "right" }}>Latency</th>
            <th style={{ padding: "6px 8px", fontWeight: 600, textAlign: "right" }}>Cost</th>
          </tr>
        </thead>
        <tbody>
          {nodes.map(([node, s]) => (
            <tr key={node} style={{ borderBottom: "1px solid var(--line)" }}>
              <td style={{ padding: "6px 8px", fontWeight: 500, textTransform: "capitalize" }}>
                {node.replace(/_/g, " ")}
              </td>
              <td style={{ padding: "6px 8px", color: "var(--ink-faint)" }}>
                {s.model?.replace(/^models\//, "").split("-preview")[0] || "—"}
              </td>
              <td style={{ padding: "6px 8px", textAlign: "right" }}>{s.calls}</td>
              <td style={{ padding: "6px 8px", textAlign: "right" }}>
                {((s.input_tokens + s.output_tokens) / 1000).toFixed(1)}k
              </td>
              <td style={{ padding: "6px 8px", textAlign: "right" }}>
                {(s.latency_ms / 1000).toFixed(1)}s
              </td>
              <td style={{ padding: "6px 8px", textAlign: "right", fontWeight: 600 }}>
                ${s.cost < 0.01 ? s.cost.toFixed(4) : s.cost.toFixed(3)}
              </td>
            </tr>
          ))}
          <tr style={{ fontWeight: 700, borderTop: "2px solid var(--line)" }}>
            <td style={{ padding: "6px 8px" }} colSpan={2}>Total</td>
            <td style={{ padding: "6px 8px", textAlign: "right" }}>{m.total_llm_calls}</td>
            <td style={{ padding: "6px 8px", textAlign: "right" }}>
              {((m.total_input_tokens + m.total_output_tokens) / 1000).toFixed(1)}k
            </td>
            <td style={{ padding: "6px 8px", textAlign: "right" }}>
              {(m.total_latency_ms / 1000).toFixed(1)}s
            </td>
            <td style={{ padding: "6px 8px", textAlign: "right" }}>
              ${m.total_cost < 0.01 ? m.total_cost.toFixed(4) : m.total_cost.toFixed(3)}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function LogsPanel({ history, metrics }: { history: string[]; metrics?: RunMetrics }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Evaluator history / critique log */}
      {history.length > 0 && (
        <div>
          <h3 style={{ fontSize: 15, fontWeight: 600, marginBottom: 10 }}>Evaluator history</h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {history.map((entry, i) => {
              const isRetry = /retry|fail|reject/i.test(entry);
              const isPass = /pass|proceed|approve|advance/i.test(entry);
              return (
                <div
                  key={i}
                  style={{
                    padding: "10px 14px",
                    borderRadius: 8,
                    fontSize: 13,
                    lineHeight: 1.6,
                    background: isRetry ? "var(--accent-soft, #fef2f2)" : isPass ? "#f0fdf4" : "var(--cream)",
                    border: `1px solid ${isRetry ? "#fecaca" : isPass ? "#bbf7d0" : "var(--line)"}`,
                    color: "var(--ink-soft)",
                    whiteSpace: "pre-wrap",
                  }}
                >
                  <span style={{
                    display: "inline-block",
                    fontSize: 10,
                    fontWeight: 700,
                    padding: "1px 6px",
                    borderRadius: 3,
                    marginBottom: 6,
                    marginRight: 8,
                    background: isRetry ? "#ef444418" : isPass ? "#22c55e18" : "#6b728018",
                    color: isRetry ? "#ef4444" : isPass ? "#22c55e" : "#6b7280",
                    textTransform: "uppercase",
                    letterSpacing: "0.5px",
                  }}>
                    Round {i + 1}
                  </span>
                  {entry}
                </div>
              );
            })}
          </div>
        </div>
      )}
      {history.length === 0 && (
        <div style={{ color: "var(--ink-faint)", fontSize: 13 }}>
          No evaluator history — blueprint passed on first attempt.
        </div>
      )}

      {/* LLM call log */}
      {metrics && metrics.llm_calls.length > 0 && (
        <div>
          <h3 style={{ fontSize: 15, fontWeight: 600, marginBottom: 10 }}>LLM call log</h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {metrics.llm_calls.map((call, i) => (
              <div
                key={i}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  padding: "8px 12px",
                  borderRadius: 6,
                  background: "var(--cream)",
                  border: "1px solid var(--line)",
                  fontSize: 12,
                }}
              >
                <span style={{ fontWeight: 600, minWidth: 20, color: "var(--ink-faint)" }}>
                  {i + 1}
                </span>
                <span style={{
                  fontSize: 10, fontWeight: 600, padding: "1px 6px", borderRadius: 3,
                  background: call.role === "generator" ? "#3b82f618" : call.role === "judge" ? "#8b5cf618" : call.role === "eval_judge" ? "#f59e0b18" : "#6b728018",
                  color: call.role === "generator" ? "#3b82f6" : call.role === "judge" ? "#8b5cf6" : call.role === "eval_judge" ? "#f59e0b" : "#6b7280",
                  textTransform: "uppercase",
                  letterSpacing: "0.5px",
                  flexShrink: 0,
                }}>
                  {call.role}
                </span>
                <span style={{ color: "var(--ink-soft)", textTransform: "capitalize", flexShrink: 0 }}>
                  {call.node.replace(/_/g, " ")}
                </span>
                <span style={{ flex: 1 }} />
                <span style={{ color: "var(--ink-faint)", flexShrink: 0 }}>
                  {call.model?.replace(/^models\//, "").split("-preview")[0]}
                </span>
                <span style={{ color: "var(--ink-faint)", flexShrink: 0 }}>
                  {((call.input_tokens + call.output_tokens) / 1000).toFixed(1)}k tok
                </span>
                <span style={{ color: "var(--ink-faint)", flexShrink: 0 }}>
                  {(call.latency_ms / 1000).toFixed(1)}s
                </span>
                <span style={{ fontWeight: 600, flexShrink: 0 }}>
                  ${call.cost < 0.01 ? call.cost.toFixed(4) : call.cost.toFixed(3)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Node timings */}
      {metrics && metrics.node_timings.length > 0 && (
        <div>
          <h3 style={{ fontSize: 15, fontWeight: 600, marginBottom: 10 }}>Node timings</h3>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {metrics.node_timings.map((nt, i) => (
              <div
                key={i}
                style={{
                  padding: "6px 12px",
                  borderRadius: 6,
                  background: "var(--cream)",
                  border: "1px solid var(--line)",
                  fontSize: 12,
                }}
              >
                <span style={{ fontWeight: 500, textTransform: "capitalize" }}>
                  {nt.node.replace(/_/g, " ")}
                </span>
                <span style={{ color: "var(--ink-faint)", marginLeft: 8 }}>
                  {(nt.latency_ms / 1000).toFixed(1)}s
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function DimensionRow({ dim }: { dim: EvalDimension }) {
  const [open, setOpen] = useState(false);
  const pct = Math.round(dim.score * 100);
  const color = pct >= 80 ? "#22c55e" : pct >= 60 ? "#eab308" : "#ef4444";
  const laneColor = dim.lane === "llm" ? "#8b5cf6" : dim.lane === "heuristic" ? "#f59e0b" : "#6b7280";
  const laneLabel = dim.lane === "llm" ? "LLM" : dim.lane === "heuristic" ? "Heuristic" : "Code";

  return (
    <div style={{ border: "1px solid var(--line)", borderRadius: 8, overflow: "hidden" }}>
      <div onClick={() => setOpen(!open)} style={{ display: "flex", alignItems: "center", gap: 8, padding: "7px 12px", cursor: "pointer" }}>
        <span style={{ minWidth: 130, fontSize: 12.5, fontWeight: 500, textTransform: "capitalize" }}>
          {dim.name.replace(/_/g, " ")}
        </span>
        <span style={{
          fontSize: 9, fontWeight: 600, padding: "1px 5px", borderRadius: 3,
          background: laneColor + "18", color: laneColor, textTransform: "uppercase",
          letterSpacing: "0.5px",
        }}>{laneLabel}</span>
        <div style={{ flex: 1, height: 7, background: "#e5e7eb", borderRadius: 4, overflow: "hidden" }}>
          <div style={{ height: "100%", width: `${pct}%`, background: color, borderRadius: 4, transition: "width 0.3s" }} />
        </div>
        <span style={{ fontSize: 12.5, fontWeight: 600, minWidth: 36, textAlign: "right", color }}>{pct}%</span>
        <span style={{ fontSize: 11 }}>{open ? "▲" : "▼"}</span>
      </div>
      {open && (
        <div style={{ padding: "4px 12px 8px", background: "var(--cream)", fontSize: 12 }}>
          <div style={{ color: "var(--ink-soft)" }}>{dim.detail}</div>
          {dim.issues.length > 0 && (
            <ul style={{ margin: "4px 0 0 14px", padding: 0, color: "#ef4444", fontSize: 11.5 }}>
              {dim.issues.map((issue, i) => <li key={i} style={{ marginBottom: 2 }}>{issue}</li>)}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
