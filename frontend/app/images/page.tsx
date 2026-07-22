"use client";

import { useState, useEffect, useCallback } from "react";
import { authHeaders } from "../../lib/supabase";

const API = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

interface ImgRow {
  image_name: string;
  image_url: string;
  image_detail?: string;
  qc_reason?: string;
  human_feedback?: string;
  status: number;
}

function lowres(url: string, name: string) {
  return url ? url.replace(`/${name}`, `/lowres/${name}`) : "";
}

export default function ImagesReview() {
  const [tab, setTab] = useState<2 | 1>(2);          // 2 = to review, 1 = approved
  const [rows, setRows] = useState<ImgRow[]>([]);
  const [total, setTotal] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const [feedbackFor, setFeedbackFor] = useState<string | null>(null);
  const [feedback, setFeedback] = useState("");
  const [note, setNote] = useState("");

  const load = useCallback(async (status: 2 | 1) => {
    const res = await fetch(`${API}/api/images?status=${status}&limit=200`,
                            { headers: await authHeaders() });
    if (res.ok) {
      const data = await res.json();
      setRows(data.rows || []);
      setTotal(data.total || 0);
    }
  }, []);

  useEffect(() => { load(tab); }, [tab, load]);

  async function verdict(filename: string, action: string, fb?: string) {
    setBusy(filename);
    try {
      const res = await fetch(`${API}/api/images/verdict`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ filename, action, feedback: fb || "" }),
      });
      if (res.ok) {
        setRows((prev) => prev.filter((r) => r.image_name !== filename));
        setTotal((t) => t - 1);
        setNote(`${action}: ${filename}` + (fb ? ` — "${fb}"` : ""));
      } else {
        setNote(`failed: ${await res.text()}`);
      }
    } finally {
      setBusy(null);
      setFeedbackFor(null);
      setFeedback("");
    }
  }

  return (
    <main style={{ minHeight: "100vh", padding: "24px 28px" }}>
      <header style={{ display: "flex", alignItems: "baseline", gap: 14, marginBottom: 6 }}>
        <h2 style={{ fontSize: 21 }}>Image review</h2>
        <a href="/" style={{ fontSize: 13, color: "var(--ink-soft)" }}>← App</a>
      </header>
      <p style={{ fontSize: 13, color: "var(--ink-faint)", marginBottom: 16 }}>
        Approve keeps the image (it is already live under its real name). Reject and
        Recreate send it back to the generation queue — the worker picks it up
        automatically; Recreate feedback is enforced by both the prompt and QC.
      </p>

      <div style={{ display: "flex", gap: 6, marginBottom: 16 }}>
        {([[2, "To review"], [1, "Approved"]] as [2 | 1, string][]).map(([s, label]) => (
          <button key={s} onClick={() => setTab(s)} className="btn btn-ghost"
            style={{
              fontWeight: tab === s ? 700 : 400,
              borderColor: tab === s ? "var(--accent)" : "var(--line)",
            }}>
            {label}{tab === s ? ` · ${total}` : ""}
          </button>
        ))}
        {note && <span style={{ fontSize: 12, color: "var(--ink-faint)", alignSelf: "center" }}>{note}</span>}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(210px,1fr))", gap: 14 }}>
        {rows.map((r) => (
          <div key={r.image_name} className="card" style={{ padding: 10 }}>
            <a href={r.image_url} target="_blank" rel="noreferrer">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={lowres(r.image_url, r.image_name)} alt={r.image_name} loading="lazy"
                   style={{ width: "100%", aspectRatio: "1", objectFit: "contain",
                            background: "#fff", borderRadius: 8 }} />
            </a>
            <div style={{ fontFamily: "monospace", fontSize: 12, fontWeight: 600, marginTop: 6 }}>
              {r.image_name}
            </div>
            {r.image_detail && (
              <div style={{ fontSize: 11, color: "var(--ink-faint)" }}>{r.image_detail}</div>
            )}
            {r.qc_reason && (
              <div style={{ fontSize: 11, color: "#b91c1c", marginTop: 4 }}>QC: {r.qc_reason}</div>
            )}
            {r.human_feedback && (
              <div style={{ fontSize: 11, color: "#7c3aed", marginTop: 4 }}>
                feedback: {r.human_feedback}
              </div>
            )}

            {feedbackFor === r.image_name ? (
              <div style={{ marginTop: 8 }}>
                <textarea value={feedback} onChange={(e) => setFeedback(e.target.value)}
                  placeholder="What should change? (art style stays the same)" rows={2} autoFocus
                  style={{ width: "100%", fontSize: 12, padding: 6, borderRadius: 6,
                           border: "1px solid var(--line)", background: "var(--cream)" }} />
                <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
                  <button className="btn btn-accent" disabled={busy === r.image_name}
                    style={{ flex: 1, padding: "6px 0", fontSize: 12 }}
                    onClick={() => verdict(r.image_name, "recreate", feedback)}>
                    Send for recreation
                  </button>
                  <button className="btn btn-ghost" style={{ padding: "6px 10px", fontSize: 12 }}
                    onClick={() => { setFeedbackFor(null); setFeedback(""); }}>
                    ✕
                  </button>
                </div>
              </div>
            ) : (
              <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
                {r.status === 2 && (
                  <>
                    <button disabled={busy === r.image_name}
                      onClick={() => verdict(r.image_name, "approve")}
                      style={{ flex: 1, padding: "6px 0", fontSize: 12, fontWeight: 600,
                               cursor: "pointer", borderRadius: 7, border: "1px solid #16a34a",
                               background: "#dcfce7", color: "#16a34a" }}>
                      ✓ Approve
                    </button>
                    <button disabled={busy === r.image_name}
                      onClick={() => verdict(r.image_name, "reject")}
                      style={{ flex: 1, padding: "6px 0", fontSize: 12, fontWeight: 600,
                               cursor: "pointer", borderRadius: 7, border: "1px solid var(--accent)",
                               background: "var(--accent-soft, #fee2e2)", color: "var(--accent)" }}>
                      ✕ Reject
                    </button>
                  </>
                )}
                <button disabled={busy === r.image_name}
                  onClick={() => setFeedbackFor(r.image_name)}
                  style={{ flex: 1, padding: "6px 0", fontSize: 12, fontWeight: 600,
                           cursor: "pointer", borderRadius: 7, border: "1px solid #7c3aed",
                           background: "#f5f3ff", color: "#7c3aed" }}>
                  ↻ Recreate…
                </button>
              </div>
            )}
          </div>
        ))}
        {rows.length === 0 && (
          <div style={{ color: "var(--ink-faint)", fontSize: 13 }}>
            {tab === 2 ? "Nothing awaiting review 🎉" : "No approved images yet."}
          </div>
        )}
      </div>
    </main>
  );
}
