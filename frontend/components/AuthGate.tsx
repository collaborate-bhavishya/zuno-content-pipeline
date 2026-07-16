"use client";

import { useState, useEffect } from "react";
import type { Session } from "@supabase/supabase-js";
import { supabase } from "../lib/supabase";

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setReady(true);
    });
    const { data: sub } = supabase.auth.onAuthStateChange((_event, s) => setSession(s));
    return () => sub.subscription.unsubscribe();
  }, []);

  if (!ready) return null; // avoid SSR/hydration flash

  if (!session) {
    const submit = async () => {
      setBusy(true);
      setErr("");
      const { error } = await supabase.auth.signInWithPassword({ email, password });
      if (error) setErr(error.message);
      setBusy(false);
    };

    return (
      <div style={{
        minHeight: "100vh", display: "flex", alignItems: "center",
        justifyContent: "center", background: "var(--cream)", padding: 24,
      }}>
        <div className="card" style={{ maxWidth: 380, width: "100%", padding: 30, textAlign: "center" }}>
          <div className="display" style={{ fontSize: 26, fontWeight: 700, marginBottom: 6 }}>Zuno</div>
          <div style={{ fontSize: 13, color: "var(--ink-soft)", marginBottom: 22 }}>
            SpeakX lesson pipeline — sign in to continue
          </div>
          <input
            type="email"
            value={email}
            autoFocus
            onChange={(e) => { setEmail(e.target.value); setErr(""); }}
            onKeyDown={(e) => e.key === "Enter" && submit()}
            placeholder="Email"
            style={{
              width: "100%", padding: "12px 14px", borderRadius: 9,
              border: "1px solid var(--line)",
              background: "var(--cream)", marginBottom: 10, fontSize: 14,
            }}
          />
          <input
            type="password"
            value={password}
            onChange={(e) => { setPassword(e.target.value); setErr(""); }}
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
              {err}
            </div>
          )}
          <button
            className="btn btn-accent"
            onClick={submit}
            disabled={busy}
            style={{ width: "100%", justifyContent: "center", padding: 12 }}
          >
            {busy ? "Signing in…" : "Sign in →"}
          </button>
        </div>
      </div>
    );
  }

  return (
    <>
      <div style={{
        display: "flex", justifyContent: "flex-end", alignItems: "center",
        gap: 10, padding: "8px 16px", fontSize: 12.5, color: "var(--ink-soft)",
      }}>
        <span>{session.user.email}</span>
        <button
          className="btn btn-ghost"
          onClick={() => supabase.auth.signOut()}
          style={{ padding: "4px 10px", fontSize: 12 }}
        >
          Sign out
        </button>
      </div>
      {children}
    </>
  );
}
