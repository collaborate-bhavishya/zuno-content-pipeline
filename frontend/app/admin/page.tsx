"use client";

import { useState } from "react";
import { authHeaders } from "../../lib/supabase";

const API = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

export default function Admin() {
  const [pw, setPw] = useState("");
  const [authed, setAuthed] = useState(false);
  const [config, setConfig] = useState<any>(null);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [themes, setThemes] = useState<any[]>([]);
  const [themeUpload, setThemeUpload] = useState<any>(null); // last upload result

  async function login() {
    const res = await fetch(`${API}/api/admin/config`, {
      headers: { "x-admin-password": pw, ...(await authHeaders()) },
    });
    if (res.ok) {
      setConfig(await res.json());
      setAuthed(true);
      setError("");
      loadThemes();
    } else {
      setError("Wrong password");
    }
  }

  async function loadThemes() {
    try {
      const res = await fetch(`${API}/api/themes`, { headers: await authHeaders() });
      if (res.ok) setThemes(await res.json());
    } catch {}
  }

  async function uploadThemesCsv(file: File) {
    const csv_text = await file.text();
    const res = await fetch(`${API}/api/themes/upload`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(await authHeaders()) },
      body: JSON.stringify({ csv_text }),
    });
    const data = await res.json();
    setThemeUpload(data);
    if (data.themes) setThemes(data.themes);
  }

  async function save() {
    const res = await fetch(`${API}/api/admin/config`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "x-admin-password": pw, ...(await authHeaders()) },
      body: JSON.stringify({
        models: config.models,
        prompts: config.prompts,
        keys: config._newKeys || {},
        limits: config.limits,
        output: config.output,
      }),
    });
    if (res.ok) {
      setConfig({ ...(await res.json()), _newKeys: {} });
      setSaved(true);
      setTimeout(() => setSaved(false), 1800);
    }
  }

  const setModel = (k: string, v: any) =>
    setConfig((c: any) => ({ ...c, models: { ...c.models, [k]: v } }));
  const setPrompt = (k: string, v: string) =>
    setConfig((c: any) => ({ ...c, prompts: { ...c.prompts, [k]: v } }));
  const setKey = (k: string, v: string) =>
    setConfig((c: any) => ({ ...c, _newKeys: { ...(c._newKeys || {}), [k]: v } }));
  const setLimit = (k: string, v: number) =>
    setConfig((c: any) => ({ ...c, limits: { ...c.limits, [k]: v } }));
  const setColumns = (cols: string[]) =>
    setConfig((c: any) => ({ ...c, output: { ...c.output, matrix_columns: cols } }));
  const setAgeGuideline = (age: string, field: string, value: any) =>
    setConfig((c: any) => ({
      ...c,
      output: {
        ...c.output,
        age_guidelines: {
          ...c.output.age_guidelines,
          [age]: { ...c.output.age_guidelines[age], [field]: value },
        },
      },
    }));

  if (!authed) {
    return (
      <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <div className="card" style={{ padding: 30, width: 340 }}>
          <h1 style={{ fontSize: 24, marginBottom: 6 }}>Admin</h1>
          <p style={{ color: "var(--ink-soft)", fontSize: 14, marginBottom: 20 }}>
            Manage models, keys, and prompts.
          </p>
          <input
            type="password"
            value={pw}
            onChange={(e) => setPw(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && login()}
            placeholder="Admin password"
            autoFocus
            style={{ width: "100%", padding: 12, borderRadius: 9, border: "1px solid var(--line)", background: "var(--cream)" }}
          />
          {error && <div style={{ color: "var(--accent)", fontSize: 13, marginTop: 8 }}>{error}</div>}
          <button className="btn btn-accent" onClick={login} style={{ width: "100%", justifyContent: "center", marginTop: 16 }}>
            Unlock
          </button>
          <a href="/" style={{ display: "block", textAlign: "center", marginTop: 16, fontSize: 13, color: "var(--ink-soft)" }}>
            ← Back to app
          </a>
        </div>
      </div>
    );
  }

  const providers = ["google", "anthropic", "openai"];

  return (
    <div style={{ maxWidth: 860, margin: "0 auto", padding: "32px 24px 80px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 28 }}>
        <h1 style={{ fontSize: 28 }}>Admin panel</h1>
        <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
          {saved && <span className="tag tag-pass">saved</span>}
          <a href="/" style={{ fontSize: 13, color: "var(--ink-soft)" }}>← App</a>
          <button className="btn btn-primary" onClick={save}>Save changes</button>
        </div>
      </div>

      {/* MODELS */}
      <Section title="Models" subtitle="Generator and judge roles. Cross-family judging reduces self-preference bias.">
        <ModelRow label="Generator (text)" prefix="generator" config={config} providers={providers} onProvider={setModel} onModel={setModel} onTemp={setModel} />
        <ModelRow label="Blueprint judge" prefix="judge" config={config} providers={providers} onProvider={setModel} onModel={setModel} onTemp={setModel} />
      </Section>

      {/* THEMES */}
      <Section title="Theme catalog" subtitle="The themes the batch generator produces lessons for. Upload a CSV to add or update — columns: theme (required), theme_code (blank = auto-assigned, never changes once set), ages (e.g. 3-7 or 4,5), active, notes.">
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 14 }}>
          <input
            type="file"
            accept=".csv,text/csv"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) uploadThemesCsv(f);
              e.target.value = "";
            }}
          />
          <span style={{ fontSize: 12, color: "var(--ink-faint)" }}>
            {themes.length} theme{themes.length !== 1 ? "s" : ""} registered
          </span>
        </div>

        {themeUpload && (
          <div style={{
            padding: "10px 14px", borderRadius: 9, marginBottom: 14, fontSize: 12.5,
            background: themeUpload.error || themeUpload.errors?.length ? "#fef2f2" : "#f0fdf4",
            border: `1px solid ${themeUpload.error || themeUpload.errors?.length ? "#fecaca" : "#bbf7d0"}`,
          }}>
            {themeUpload.error && <div style={{ color: "#b91c1c" }}>{themeUpload.error}</div>}
            {themeUpload.added?.length > 0 && <div>Added: {themeUpload.added.join(", ")}</div>}
            {themeUpload.updated?.length > 0 && <div>Updated: {themeUpload.updated.join(", ")}</div>}
            {themeUpload.warnings?.map((w: string, i: number) => (
              <div key={i} style={{ color: "#a16207" }}>{w}</div>
            ))}
            {themeUpload.errors?.map((e2: string, i: number) => (
              <div key={i} style={{ color: "#b91c1c" }}>{e2}</div>
            ))}
          </div>
        )}

        {themes.length > 0 && (
          <table style={{ width: "100%", fontSize: 12.5, borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: "2px solid var(--line)", textAlign: "left" }}>
                {["Code", "Theme", "Ages", "Active", "Notes"].map((h) => (
                  <th key={h} style={{ padding: "6px 8px", fontWeight: 600 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {themes.map((t) => (
                <tr key={t.theme} style={{ borderBottom: "1px solid var(--line)",
                  opacity: t.active ? 1 : 0.45 }}>
                  <td style={{ padding: "5px 8px", fontFamily: "monospace" }}>{t.theme_code}</td>
                  <td style={{ padding: "5px 8px", fontWeight: 500 }}>{t.theme}</td>
                  <td style={{ padding: "5px 8px" }}>{t.ages}</td>
                  <td style={{ padding: "5px 8px" }}>{t.active ? "✓" : "—"}</td>
                  <td style={{ padding: "5px 8px", color: "var(--ink-faint)" }}>{t.notes || ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      {/* LIMITS */}
      <Section title="Limits" subtitle="The system decides how many questions the lesson needs, up to these upper bounds.">
        {/* Daily hard stop */}
        <div style={{
          display: "flex", alignItems: "center", gap: 12, marginBottom: 18,
          padding: "12px 16px", borderRadius: 10, background: "#fdecea", border: "1px solid #f5c6c0",
        }}>
          <span style={{ minWidth: 150, fontSize: 13.5, fontWeight: 600, color: "#a01b15" }}>
            Max runs per day
          </span>
          <input type="number" min={0} value={config.limits.max_runs_per_day ?? 10}
            onChange={(e) => setLimit("max_runs_per_day", Number(e.target.value))}
            style={{ ...inp, maxWidth: 100 }} />
          <span style={{ fontSize: 11.5, color: "#a16207" }}>
            hard stop — pipeline refuses new runs once this many complete in a (UTC) day
          </span>
        </div>

        {["max_questions", "max_images", "max_retries"].map((k) => (
          <div key={k} style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 12 }}>
            <span style={{ minWidth: 150, fontSize: 13.5 }}>{k.replace(/_/g, " ")}</span>
            <input type="number" value={config.limits[k]} onChange={(e) => setLimit(k, Number(e.target.value))} style={{ ...inp, maxWidth: 100 }} />
          </div>
        ))}
      </Section>

      {/* OUTPUT COLUMNS */}
      {config.output && (
        <Section title="Output columns" subtitle="Required columns in the question matrix. The fabricator prompt uses this list. Drag to reorder or edit inline.">
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {(config.output.matrix_columns || []).map((col: string, i: number) => (
              <div key={i} style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <span style={{ color: "var(--ink-faint)", fontSize: 12, minWidth: 22 }}>{i + 1}</span>
                <input
                  value={col}
                  onChange={(e) => {
                    const cols = [...config.output.matrix_columns];
                    cols[i] = e.target.value;
                    setColumns(cols);
                  }}
                  style={{ ...inp, flex: 1 }}
                />
                <button
                  onClick={() => {
                    const cols = config.output.matrix_columns.filter((_: any, j: number) => j !== i);
                    setColumns(cols);
                  }}
                  style={{ color: "var(--accent)", fontSize: 18, padding: "0 6px", cursor: "pointer", background: "none", border: "none" }}
                  title="Remove column"
                >×</button>
              </div>
            ))}
            <button
              className="btn btn-ghost"
              onClick={() => setColumns([...config.output.matrix_columns, "New Column"])}
              style={{ alignSelf: "flex-start", marginTop: 6 }}
            >+ Add column</button>
          </div>
        </Section>
      )}

      {/* AGE GUIDELINES */}
      {config.output?.age_guidelines && (
        <Section title="Age guidelines" subtitle="Per-age rules for text length, vocabulary, complexity, and allowed templates. These are injected into the planner and fabricator prompts.">
          <AgeGuidelinesEditor guidelines={config.output.age_guidelines} onChange={setAgeGuideline} />
        </Section>
      )}

      {/* PROMPTS */}
      <Section title="Prompts" subtitle="Edit and save — changes apply to the next run, no restart.">
        <PromptEditor label="Generator system prompt" value={config.prompts.generator_system} onChange={(v: string) => setPrompt("generator_system", v)} />
        <PromptEditor label="Blueprint judge prompt" value={config.prompts.blueprint_judge_system} onChange={(v: string) => setPrompt("blueprint_judge_system", v)} />
      </Section>
    </div>
  );
}

const inp: React.CSSProperties = {
  flex: 1,
  padding: "9px 11px",
  borderRadius: 8,
  border: "1px solid var(--line)",
  background: "var(--cream)",
  fontSize: 13.5,
};

function Section({ title, subtitle, children }: any) {
  return (
    <div className="card" style={{ padding: 24, marginBottom: 20 }}>
      <h2 style={{ fontSize: 18 }}>{title}</h2>
      {subtitle && <p style={{ color: "var(--ink-faint)", fontSize: 13, marginTop: 3, marginBottom: 18 }}>{subtitle}</p>}
      {children}
    </div>
  );
}

function ModelRow({ label, prefix, config, providers, onProvider, onModel, onTemp }: any) {
  return (
    <div style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 12 }}>
      <span style={{ minWidth: 150, fontSize: 13.5, fontWeight: 500 }}>{label}</span>
      <select value={config.models[`${prefix}_provider`]} onChange={(e) => onProvider(`${prefix}_provider`, e.target.value)} style={{ ...inp, flex: "0 0 120px" }}>
        {providers.map((p: string) => (
          <option key={p} value={p}>{p}</option>
        ))}
      </select>
      <input value={config.models[`${prefix}_model`]} onChange={(e) => onModel(`${prefix}_model`, e.target.value)} style={inp} />
      <input
        type="number"
        step="0.1"
        min="0"
        max="2"
        value={config.models[`${prefix}_temperature`]}
        onChange={(e) => onTemp(`${prefix}_temperature`, Number(e.target.value))}
        style={{ ...inp, flex: "0 0 70px" }}
      />
    </div>
  );
}

function AgeGuidelinesEditor({ guidelines, onChange }: { guidelines: Record<string, any>; onChange: (age: string, field: string, value: any) => void }) {
  const [openAge, setOpenAge] = useState<string | null>(null);
  const ages = Object.keys(guidelines).sort((a, b) => Number(a) - Number(b));

  const fields: [string, string, string][] = [
    ["max_words_per_sentence", "Max words/sentence", "number"],
    ["vocabulary_level", "Vocabulary level", "text"],
    ["text_complexity", "Text complexity", "text"],
    ["tone", "Tone", "text"],
    ["stt_expectation", "STT expectation", "text"],
    ["vocab_gate", "Vocab gate", "text"],
    ["concept_gate", "Concept gate", "text"],
    ["sentence_gate", "Sentence gate", "text"],
    ["forbidden_structures", "Forbidden structures", "text"],
    ["notes", "Notes", "text"],
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {ages.map((age) => {
        const g = guidelines[age];
        const isOpen = openAge === age;
        return (
          <div key={age} style={{ border: "1px solid var(--line)", borderRadius: 10, overflow: "hidden" }}>
            <button
              onClick={() => setOpenAge(isOpen ? null : age)}
              style={{
                width: "100%",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                padding: "12px 16px",
                background: isOpen ? "var(--cream)" : "var(--paper)",
                cursor: "pointer",
                border: "none",
                textAlign: "left",
              }}
            >
              <span style={{ fontWeight: 600, fontSize: 14 }}>Age {age}</span>
              <span style={{ fontSize: 12, color: "var(--ink-faint)" }}>
                {g.max_words_per_sentence} words · {(g.allowed_templates || []).length} templates · {isOpen ? "▲" : "▼"}
              </span>
            </button>
            {isOpen && (
              <div style={{ padding: "12px 16px", display: "flex", flexDirection: "column", gap: 10 }}>
                {fields.map(([key, label, type]) => (
                  <div key={key} style={{ display: "flex", gap: 10, alignItems: "center" }}>
                    <span style={{ minWidth: 140, fontSize: 13, color: "var(--ink-soft)" }}>{label}</span>
                    {type === "number" ? (
                      <input
                        type="number"
                        value={g[key] || 0}
                        onChange={(e) => onChange(age, key, Number(e.target.value))}
                        style={{ ...inp, maxWidth: 80 }}
                      />
                    ) : (
                      <input
                        value={g[key] || ""}
                        onChange={(e) => onChange(age, key, e.target.value)}
                        style={inp}
                      />
                    )}
                  </div>
                ))}
                <div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
                  <span style={{ minWidth: 140, fontSize: 13, color: "var(--ink-soft)", paddingTop: 6 }}>Allowed templates</span>
                  <input
                    value={(g.allowed_templates || []).join(", ")}
                    onChange={(e) => onChange(age, "allowed_templates", e.target.value.split(",").map((s: string) => s.trim()).filter(Boolean))}
                    style={inp}
                    placeholder="T1, T3, F1, F2, ..."
                  />
                </div>
                <div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
                  <span style={{ minWidth: 140, fontSize: 13, color: "var(--ink-soft)", paddingTop: 6 }}>Forbidden templates</span>
                  <input
                    value={(g.forbidden_templates || []).join(", ")}
                    onChange={(e) => onChange(age, "forbidden_templates", e.target.value.split(",").map((s: string) => s.trim()).filter(Boolean))}
                    style={inp}
                    placeholder="T2, T5, T7, ..."
                  />
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function PromptEditor({ label, value, onChange, hint }: any) {
  return (
    <div style={{ marginBottom: 18 }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
        <span style={{ fontSize: 13.5, fontWeight: 500 }}>{label}</span>
        {hint && <span style={{ fontSize: 12, color: "var(--ink-faint)" }}>{hint}</span>}
      </div>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={6}
        style={{
          width: "100%",
          padding: 12,
          borderRadius: 9,
          border: "1px solid var(--line)",
          background: "var(--cream)",
          fontFamily: "ui-monospace, monospace",
          fontSize: 12.5,
          lineHeight: 1.55,
          resize: "vertical",
        }}
      />
    </div>
  );
}
