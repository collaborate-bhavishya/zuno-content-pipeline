"use client";

import { FeedEvent, NodeMetrics } from "../lib/api";

// One entry per node execution, in order. Retries show as repeated stages.
export interface FeedItem {
  id: number;
  label: string;
  action: string;
  decision?: string;
  critique?: string;
  note?: string;
  status: "running" | "pass" | "fail" | "info";
  metrics?: NodeMetrics;
}

export function eventToItem(e: Extract<FeedEvent, { kind: "node" }>, id: number): FeedItem {
  const d = e.detail || {};
  let status: FeedItem["status"] = "info";
  let note = "";

  if (d.decision) {
    const ok = ["proceed_to_questions", "trigger_assets", "advance", "all_done"].includes(
      d.decision
    );
    const bad = d.decision === "fail" || d.decision === "retry";
    status = ok ? "pass" : bad ? "fail" : "info";
  }
  if (d.rows !== undefined) note = `${d.rows} questions built`;
  if (d.completed?.length) note = `${d.completed.length} image${d.completed.length > 1 ? "s" : ""} approved`;
  if (d.preview) note = d.preview;
  if ((d as any).quota_exhausted) {
    status = "fail";
    note = `Image quota exhausted (429). ${(d as any).pending_count || 0} images queued for retry when quota resets.`;
  }

  return {
    id,
    label: e.label,
    action: e.action,
    decision: d.decision,
    critique: d.critique,
    note,
    status,
    metrics: (d as any).metrics,
  };
}

const STATUS_TAG: Record<string, string> = {
  pass: "tag tag-pass",
  fail: "tag tag-fail",
  running: "tag tag-run",
};

export default function ProcessFeed({
  items,
  running,
}: {
  items: FeedItem[];
  running: boolean;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
      {items.map((it, i) => (
        <div
          key={it.id}
          style={{
            display: "flex",
            gap: 14,
            padding: "14px 0",
            borderBottom: i < items.length - 1 ? "1px solid var(--line)" : "none",
            animation: "fadeUp .25s ease",
          }}
        >
          {/* rail */}
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", paddingTop: 3 }}>
            <Dot status={it.status} />
            {i < items.length - 1 && (
              <div style={{ width: 2, flex: 1, background: "var(--line)", marginTop: 4 }} />
            )}
          </div>

          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
              <span style={{ fontWeight: 600, fontSize: 14 }}>{it.label}</span>
              {it.decision && (
                <span className={it.status === "fail" ? "tag tag-muted" : (STATUS_TAG[it.status] || "tag")}>
                  {it.status === "fail" ? "retry triggered" : it.decision.replace(/_/g, " ")}
                </span>
              )}
            </div>
            <div style={{ color: "var(--ink-soft)", fontSize: 13, marginTop: 2 }}>{it.action}</div>

            {it.note && (
              <div
                style={{
                  marginTop: 8,
                  fontSize: 12.5,
                  color: "var(--ink-soft)",
                  background: "var(--cream)",
                  border: "1px solid var(--line)",
                  borderRadius: 8,
                  padding: "8px 11px",
                  fontStyle: it.note.length > 60 ? "italic" : "normal",
                }}
              >
                {it.note}
              </div>
            )}

            {it.critique && it.status === "fail" && (
              <div
                style={{
                  marginTop: 8,
                  fontSize: 12.5,
                  color: "var(--ink-soft)",
                  background: "var(--cream-deep)",
                  borderLeft: "3px solid var(--ink-faint)",
                  borderRadius: 8,
                  padding: "8px 11px",
                }}
              >
                <strong style={{ fontWeight: 600 }}>Critique fed back to generator:</strong>{" "}
                {it.critique}
              </div>
            )}

            {it.metrics && it.metrics.tokens_in > 0 && (
              <div style={{
                marginTop: 6,
                display: "flex",
                gap: 12,
                fontSize: 11,
                color: "var(--ink-faint)",
              }}>
                <span title="Input + output tokens">
                  {formatTokens(it.metrics.tokens_in + it.metrics.tokens_out)} tok
                </span>
                <span title="Latency">
                  {formatLatency(it.metrics.latency_ms)}
                </span>
                <span title="Estimated cost">
                  ${it.metrics.cost_usd < 0.01 ? it.metrics.cost_usd.toFixed(4) : it.metrics.cost_usd.toFixed(3)}
                </span>
                <span title="Model" style={{ opacity: 0.7 }}>
                  {it.metrics.model?.replace(/^models\//, "").split("-preview")[0]}
                </span>
              </div>
            )}
          </div>
        </div>
      ))}

      {running && (
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "16px 0", color: "var(--ink-faint)" }}>
          <div className="spinner" />
          <span style={{ fontSize: 13 }}>Pipeline running…</span>
        </div>
      )}
    </div>
  );
}

function formatTokens(n: number): string {
  if (n >= 1000) return (n / 1000).toFixed(1) + "k";
  return String(n);
}

function formatLatency(ms: number): string {
  if (ms >= 1000) return (ms / 1000).toFixed(1) + "s";
  return ms + "ms";
}

function Dot({ status }: { status: FeedItem["status"] }) {
  const color =
    status === "pass" ? "var(--green)" : status === "fail" ? "var(--ink-faint)" : "var(--ink-faint)";
  return (
    <div
      style={{
        width: 12,
        height: 12,
        borderRadius: "50%",
        background: status === "info" ? "var(--paper)" : color,
        border: `2px solid ${color}`,
      }}
    />
  );
}
