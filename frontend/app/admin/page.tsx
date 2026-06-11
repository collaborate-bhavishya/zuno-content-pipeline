"use client";

import { useState } from "react";

const API = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

export default function Admin() {
  const [pw, setPw] = useState("");
  const [authed, setAuthed] = useState(false);
  const [config, setConfig] = useState<any>(null);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  async function login() {
    const res = await fetch(`${API}/api/admin/config`, {
      headers: { "x-admin-password": pw },
    });
    if (res.ok) {
      setConfig(await res.json());
      setAuthed(true);
      setError("");
    } else {
      setError("Wrong password");
    }
  }

  async function save() {
    const res = await fetch(`${API}/api/admin/config`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "x-admin-password": pw },
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
      <Section title="Models" subtitle="Generator, judge, and vision-critic roles. Cross-family judging reduces self-preference bias.">
        <ModelRow label="Generator (text)" prefix="generator" config={config} providers={providers} onProvider={setModel} onModel={setModel} onTemp={setModel} />
        <ModelRow label="Blueprint judge" prefix="judge" config={config} providers={providers} onProvider={setModel} onModel={setModel} onTemp={setModel} />
        <ModelRow label="Vision critic" prefix="vision" config={config} providers={providers} onProvider={setModel} onModel={setModel} onTemp={setModel} />
        <div style={{ display: "flex", gap: 12, alignItems: "center", marginTop: 6 }}>
          <span style={{ minWidth: 150, fontSize: 13.5, fontWeight: 500 }}>Image generator</span>
          <input value={config.models.image_model} onChange={(e) => setModel("image_model", e.target.value)} style={inp} />
        </div>
      </Section>

      {/* MODE + LIMITS */}
      <Section title="Run mode & limits" subtitle="Trial mode (default) caps questions and images so test runs stay cheap. Turn it off for a full run where the system decides the count.">
        {/* Trial toggle */}
        <div style={{
          display: "flex", alignItems: "center", gap: 14, marginBottom: 18,
          padding: "14px 16px", borderRadius: 10,
          background: config.limits.trial_mode ? "#fefce8" : "var(--cream)",
          border: `1px solid ${config.limits.trial_mode ? "#fef08a" : "var(--line)"}`,
        }}>
          <label style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer", flex: 1 }}>
            <input
              type="checkbox"
              checked={!!config.limits.trial_mode}
              onChange={(e) => setLimit("trial_mode", e.target.checked ? 1 : 0)}
              style={{ width: 18, height: 18, accentColor: "var(--accent)" }}
            />
            <div>
              <span style={{ fontSize: 14, fontWeight: 600 }}>Trial mode</span>
              <div style={{ fontSize: 12, color: "var(--ink-faint)", marginTop: 1 }}>
                {config.limits.trial_mode
                  ? `Capped to ${config.limits.trial_max_questions} questions & ${config.limits.trial_max_images} images`
                  : "Full mode — system decides count (up to the upper bounds below)"}
              </div>
            </div>
          </label>
          <span style={{
            fontSize: 11, fontWeight: 700, padding: "3px 10px", borderRadius: 4,
            background: config.limits.trial_mode ? "#fef08a" : "#22c55e22",
            color: config.limits.trial_mode ? "#854d0e" : "#22c55e",
          }}>
            {config.limits.trial_mode ? "TRIAL" : "FULL"}
          </span>
        </div>

        {/* Trial caps — active when trial mode is on */}
        {config.limits.trial_mode && (
          <div style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: "var(--ink-soft)", marginBottom: 8 }}>
              Trial caps (active)
            </div>
            {[["trial_max_questions", "max questions"], ["trial_max_images", "max images"]].map(([k, label]) => (
              <div key={k} style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 10 }}>
                <span style={{ minWidth: 150, fontSize: 13.5 }}>{label}</span>
                <input type="number" min={0} value={config.limits[k] ?? 0}
                  onChange={(e) => setLimit(k, Number(e.target.value))} style={{ ...inp, maxWidth: 100 }} />
              </div>
            ))}
          </div>
        )}

        {/* Full-mode upper bounds + retries */}
        <div style={{ fontSize: 12, fontWeight: 700, color: "var(--ink-soft)", marginBottom: 8 }}>
          {config.limits.trial_mode ? "Full-mode upper bounds (used when trial is off)" : "Limits"}
        </div>
        {["max_questions", "max_images", "max_retries"].map((k) => (
          <div key={k} style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 12,
            opacity: config.limits.trial_mode && k !== "max_retries" ? 0.55 : 1 }}>
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
        <PromptEditor label="Vision critic prompt" value={config.prompts.vision_critic_system} onChange={(v: string) => setPrompt("vision_critic_system", v)} hint="Use {object_name} and {eye_rule} placeholders." />
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
