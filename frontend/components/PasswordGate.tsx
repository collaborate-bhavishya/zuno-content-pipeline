"use client";

import { useState, useEffect } from "react";

const APP_PASSWORD = "Zuno@zuno";
const STORAGE_KEY = "zuno_app_auth";

export default function PasswordGate({ children }: { children: React.ReactNode }) {
  const [authed, setAuthed] = useState(false);
  const [ready, setReady] = useState(false);
  const [val, setVal] = useState("");
  const [err, setErr] = useState(false);

  useEffect(() => {
    setAuthed(typeof window !== "undefined" && localStorage.getItem(STORAGE_KEY) === "1");
    setReady(true);
  }, []);

  if (!ready) return null;          // avoid SSR/hydration flash
  if (authed) return <>{children}</>;

  const submit = () => {
    if (val === APP_PASSWORD) {
      localStorage.setItem(STORAGE_KEY, "1");
      setAuthed(true);
    } else {
      setErr(true);
    }
  };

  return (
    <div style={{
      minHeight: "100vh", display: "flex", alignItems: "center",
      justifyContent: "center", background: "var(--cream)", padding: 24,
    }}>
      <div className="card" style={{ maxWidth: 380, width: "100%", padding: 30, textAlign: "center" }}>
        <div className="display" style={{ fontSize: 26, fontWeight: 700, marginBottom: 6 }}>Zuno</div>
        <div style={{ fontSize: 13, color: "var(--ink-soft)", marginBottom: 22 }}>
          SpeakX lesson pipeline — enter password to continue
        </div>
        <input
          type="password"
          value={val}
          autoFocus
          onChange={(e) => { setVal(e.target.value); setErr(false); }}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          placeholder="Password"
          style={{
            width: "100%", padding: "12px 14px", borderRadius: 9,
            border: `1px solid ${err ? "var(--accent)" : "var(--line)"}`,
            background: "var(--cream)", marginBottom: err ? 8 : 18, fontSize: 14,
          }}
        />
        {err && (
          <div style={{ color: "var(--accent)", fontSize: 12.5, marginBottom: 14 }}>
            Incorrect password
          </div>
        )}
        <button
          className="btn btn-accent"
          onClick={submit}
          style={{ width: "100%", justifyContent: "center", padding: 12 }}
        >
          Enter →
        </button>
      </div>
    </div>
  );
}
