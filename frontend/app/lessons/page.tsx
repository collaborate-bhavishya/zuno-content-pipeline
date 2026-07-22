"use client";

import { useState, useEffect } from "react";
import { authHeaders } from "../../lib/supabase";

const API = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";
const DASH = "—";

interface Lesson {
  id: string; theme: string; target_age: number;
  milestone_code: string; theme_code: string; eval_grade?: string;
}
interface Asset { url: string; status: number }
interface View {
  questions: any[];
  images: Record<string, Asset>;
  audio: Record<string, Asset>;
}

function low(url: string, name: string) {
  return url ? url.replace(`/${name}`, `/lowres/${name}`) : "";
}

function Aud({ code, audio, label }: { code?: string; audio: Record<string, Asset>; label: string }) {
  if (!code || code === DASH) return null;
  const a = audio[code];
  if (!a?.url) {
    return <div style={{ fontSize: 11, color: "#b91c1c" }}>{label}: audio missing ({code})</div>;
  }
  return (
    <div style={{ margin: "4px 0" }}>
      <div style={{ fontSize: 10, color: "var(--ink-faint)", textTransform: "uppercase" }}>{label}</div>
      <audio controls preload="none" src={a.url} style={{ width: "100%", height: 30 }} />
    </div>
  );
}

function Img({ name, images, label }: { name?: string; images: Record<string, Asset>; label: string }) {
  if (!name || name === DASH) return null;
  const img = images[name];
  return (
    <div style={{ textAlign: "center", width: 110 }}>
      {img?.url ? (
        <a href={img.url} target="_blank" rel="noreferrer">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={low(img.url, name)} alt={name} loading="lazy"
               style={{ width: 100, height: 100, objectFit: "contain", background: "#fff",
                        borderRadius: 8, border: img.status === 2 ? "2px solid #eab308" : "1px solid var(--line)" }} />
        </a>
      ) : (
        <div style={{ width: 100, height: 100, borderRadius: 8, background: "var(--cream-deep)",
                      display: "flex", alignItems: "center", justifyContent: "center",
                      fontSize: 10, color: "var(--ink-faint)" }}>
          in queue
        </div>
      )}
      <div style={{ fontSize: 9, fontFamily: "monospace", color: "var(--ink-faint)", marginTop: 2 }}>
        {label}: {name}
      </div>
    </div>
  );
}

export default function Lessons() {
  const [lessons, setLessons] = useState<Lesson[]>([]);
  const [selected, setSelected] = useState<Lesson | null>(null);
  const [view, setView] = useState<View | null>(null);
  const [loading, setLoading] = useState(false);
  const [ageFilter, setAgeFilter] = useState<number | 0>(0);

  useEffect(() => {
    (async () => {
      const res = await fetch(`${API}/api/lessons`, { headers: await authHeaders() });
      if (res.ok) setLessons(await res.json());
    })();
  }, []);

  async function open(l: Lesson) {
    setSelected(l);
    setView(null);
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/lessons/${l.id}/view`, { headers: await authHeaders() });
      if (res.ok) setView(await res.json());
    } finally {
      setLoading(false);
    }
  }

  const shown = lessons.filter((l) => !ageFilter || l.target_age === ageFilter);

  return (
    <main style={{ minHeight: "100vh", display: "flex" }}>
      {/* lesson list */}
      <aside style={{ width: 290, borderRight: "1px solid var(--line)", padding: 16,
                      overflowY: "auto", height: "100vh", position: "sticky", top: 0 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 10 }}>
          <h2 style={{ fontSize: 17 }}>Lessons</h2>
          <a href="/" style={{ fontSize: 12, color: "var(--ink-soft)" }}>← App</a>
        </div>
        <div style={{ display: "flex", gap: 4, marginBottom: 10, flexWrap: "wrap" }}>
          {[0, 3, 4, 5, 6, 7].map((a) => (
            <button key={a} onClick={() => setAgeFilter(a as any)} className="btn btn-ghost"
              style={{ padding: "3px 10px", fontSize: 12,
                       fontWeight: ageFilter === a ? 700 : 400,
                       borderColor: ageFilter === a ? "var(--accent)" : "var(--line)" }}>
              {a === 0 ? "all" : `age ${a}`}
            </button>
          ))}
        </div>
        {shown.map((l) => (
          <div key={l.id} onClick={() => open(l)}
            style={{ padding: "8px 10px", borderRadius: 8, cursor: "pointer", marginBottom: 4,
                     background: selected?.id === l.id ? "var(--cream-deep)" : "transparent" }}>
            <div style={{ fontSize: 13.5, fontWeight: 600 }}>{l.theme}</div>
            <div style={{ fontSize: 11, color: "var(--ink-faint)" }}>
              age {l.target_age} · {l.milestone_code}{l.theme_code}
              {l.eval_grade ? ` · grade ${l.eval_grade}` : ""}
            </div>
          </div>
        ))}
      </aside>

      {/* playable view */}
      <section style={{ flex: 1, padding: "20px 26px", overflowY: "auto" }}>
        {!selected && <div style={{ color: "var(--ink-faint)", fontSize: 14 }}>
          Pick a lesson to see its questions with images and playable audio.</div>}
        {loading && <div className="spinner" />}
        {selected && view && (
          <>
            <h2 style={{ fontSize: 19, marginBottom: 2 }}>
              {selected.theme} · age {selected.target_age}
            </h2>
            <div style={{ fontSize: 12, color: "var(--ink-faint)", marginBottom: 18 }}>
              {view.questions.length} questions ·{" "}
              {Object.values(view.images).filter((i) => i.url).length}/{Object.keys(view.images).length} images ready ·{" "}
              {Object.values(view.audio).filter((a) => a.url).length}/{Object.keys(view.audio).length} audio ready
            </div>
            {view.questions.map((q, i) => (
              <div key={i} className="card" style={{ padding: 14, marginBottom: 12 }}>
                <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6, flexWrap: "wrap" }}>
                  <span className="tag tag-muted" style={{ fontFamily: "monospace" }}>
                    Q{q.row_index + 1} · {q.playable_code} · {q.template}
                  </span>
                  <span style={{ fontSize: 11, color: "var(--ink-faint)" }}>{q.layer}</span>
                </div>
                {q.instruction_text && q.instruction_text !== DASH && (
                  <div style={{ fontSize: 15, fontWeight: 600 }}>{q.instruction_text}</div>
                )}
                {q.text_in_question && q.text_in_question !== DASH && (
                  <div style={{ fontSize: 14, color: "var(--ink-soft)" }}>{q.text_in_question}</div>
                )}
                <div style={{ display: "flex", gap: 14, marginTop: 8, flexWrap: "wrap" }}>
                  <Img name={q.image_in_question_name} images={view.images} label="Q" />
                  <Img name={q.correct_answer_image} images={view.images} label="✓" />
                  {(q.other_options_image || []).map((n: string, j: number) => (
                    <Img key={j} name={n} images={view.images} label={`opt${j + 1}`} />
                  ))}
                </div>
                <div style={{ maxWidth: 420 }}>
                  <Aud code={q.instruction_vo_file} audio={view.audio} label={`Instruction VO — "${q.instruction_vo}"`} />
                  <Aud code={q.audio_in_question_file} audio={view.audio} label={`Audio in Q — "${q.audio_in_question}"`} />
                  <Aud code={q.vo_for_question_file} audio={view.audio} label={`Question VO — "${q.vo_for_question}"`} />
                  <Aud code={q.correct_answer_vo_file} audio={view.audio} label={`Answer — "${q.correct_answer}"`} />
                  {(q.other_options_vo_file || []).map((code: string, j: number) => (
                    <Aud key={j} code={code} audio={view.audio}
                         label={`Option ${j + 1} — "${(q.other_options || [])[j] || ""}"`} />
                  ))}
                </div>
                {q.stt_expectation && q.stt_expectation !== DASH && (
                  <div style={{ fontSize: 11, color: "#7c3aed", marginTop: 6 }}>
                    child says: “{q.stt_expectation}”
                  </div>
                )}
              </div>
            ))}
          </>
        )}
      </section>
    </main>
  );
}
