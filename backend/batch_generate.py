#!/usr/bin/env python3
"""
Overnight batch generator.

Generates a full grid of lessons (every theme x every age) by driving the
LangGraph pipeline directly — no HTTP, so it also bypasses the per-day run cap
that guards the UI endpoint. Built to be left running unattended:

  * Adaptive pacing: a delay between lessons that GROWS after a 429 and slowly
    shrinks after clean runs, so it settles just under the Vertex rate limit
    instead of bursting past it (bursting is what caused the 429s).
  * Run-level 429 backoff: a quota error retries the WHOLE lesson after a wait
    (30s, 60s, 120s, ... capped) rather than losing it.
  * Resume: skips any (theme, age, milestone, theme_code) already saved with a
    non-empty matrix, so you can stop/restart or survive a reboot freely.

Themes live in a registry CSV (themes.csv: theme,theme_code). Add themes there
(code optional — a stable one is auto-assigned and written back) and they get
generated across all ages. Codes never change once assigned.

Run from the backend/ directory:

    python batch_generate.py                 # every theme in themes.csv x ages 3-7
    python batch_generate.py --themes jungle,space --ages 4,5   # subset
    python batch_generate.py --themes dragons,castles           # new themes: auto-registered
    python batch_generate.py --dry-run       # print the queue, generate nothing

On the EC2 box, launch detached and watch the log:

    cd ~/zuno-content-pipeline/backend
    nohup python batch_generate.py > storage/batch.log 2>&1 &
    tail -f storage/batch.log
"""
import argparse
import csv
import logging
import os
import re
import time
from datetime import datetime, timezone

from app.core.config import CONFIG
from app.core.graph import build_graph
from app.core.metrics import init_collector, clear_collector
from app.main import _save_run, _load_runs

log = logging.getLogger("batch")

AGES = [3, 4, 5, 6, 7]

# Persistent theme registry (theme -> stable theme_code). This CSV is the single
# source of truth for the growing catalog: add a theme to it (with or without a
# code) and it gets generated across all ages. A code, once assigned, never
# changes — so already-generated content keeps pointing at the right files.
THEMES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "themes.csv")


def _slugify_theme(theme: str) -> str:
    """Normalize a theme name: lowercase, trimmed, single spaces."""
    return re.sub(r"\s+", " ", str(theme or "").strip().lower())


def load_registry(path: str = THEMES_FILE) -> dict:
    """Read {theme: theme_code} from the CSV. Missing file => empty registry."""
    reg = {}
    if not os.path.exists(path):
        return reg
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            theme = _slugify_theme(row.get("theme", ""))
            code = str(row.get("theme_code", "")).strip().upper()
            if theme and code:
                reg[theme] = code
    return reg


def _next_code(reg: dict) -> str:
    """Lowest unused T-code (T01, T02, …)."""
    used = {int(m.group(1)) for c in reg.values()
            if (m := re.fullmatch(r"T(\d+)", c))}
    n = 1
    while n in used:
        n += 1
    return f"T{n:02d}"


def ensure_codes(reg: dict, themes: list, path: str = THEMES_FILE) -> dict:
    """Assign a stable code to any theme not yet in the registry and persist.
    Returns the (possibly grown) registry."""
    added = False
    for t in themes:
        t = _slugify_theme(t)
        if t and t not in reg:
            reg[t] = _next_code(reg)
            log.info("Registered new theme '%s' -> %s", t, reg[t])
            added = True
    if added:
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["theme", "theme_code"])
            for t, c in sorted(reg.items(), key=lambda kv: int(kv[1][1:])):
                w.writerow([t, c])
    return reg

# Adaptive pacing bounds (seconds between lessons).
PACE_MIN = 5.0
PACE_MAX = 300.0
PACE_START = 15.0
PACE_DECAY = 0.85        # multiply delay by this after a clean lesson
PACE_GROW = 2.0          # multiply delay by this after a 429

# Run-level backoff when a lesson dies on a 429.
BACKOFF_BASE = 30
BACKOFF_MAX = 600
MAX_LESSON_ATTEMPTS = 6


def build_queue(themes, reg, ages_by_theme, ages_override=None, milestone_by_theme=None):
    milestone_by_theme = milestone_by_theme or {}
    return [
        {"theme": t, "age": a,
         # catalog override if set, else derived from age (AG03 for age 3, ...)
         "milestone_code": milestone_by_theme.get(t) or f"AG{a:02d}",
         "theme_code": reg[t]}
        for t in themes
        for a in (ages_override or ages_by_theme.get(t, AGES))
    ]


def already_done(combo, runs) -> bool:
    """True if a completed lesson for this combo already exists (non-empty
    matrix, no error)."""
    for r in runs:
        if (r.get("theme") == combo["theme"]
                and int(r.get("age", -1)) == combo["age"]
                and r.get("milestone_code") == combo["milestone_code"]
                and r.get("theme_code") == combo["theme_code"]
                and (r.get("matrix") or []) and not r.get("error")):
            return True
    return False


def _is_quota_error(exc: Exception) -> bool:
    s = str(exc).lower()
    return "429" in s or "resource_exhausted" in s or "quota" in s


# ── LLM error triage ──────────────────────────────────────────────────
# On any non-quota failure, ask the judge model to read the error and decide:
# retry (with an optional hint injected into the next attempt) or hold (a
# problem retrying can't fix — bad credentials, schema mismatch, code bug).
# After DIAG_MAX_TRIALS failed attempts for one lesson, the whole batch puts
# itself ON HOLD (exits with a clear log) rather than burning the night on a
# systemic fault.
DIAG_MAX_TRIALS = 3


def diagnose(error_text: str, combo: dict) -> dict:
    """Returns {cause, action: 'retry'|'hold', hint}. Never raises."""
    import json as _json
    from app.core.llm import get_judge, invoke_with_limit
    prompt = (
        "You are the on-call engineer for an automated lesson-generation batch.\n"
        f"Generating lesson theme='{combo['theme']}' age={combo['age']} failed with:\n\n"
        f"{error_text[:3000]}\n\n"
        "Decide what the batch should do:\n"
        "- 'retry'  if another attempt could plausibly succeed (transient API issue, "
        "malformed model output, validation that a regeneration may pass).\n"
        "- 'hold'   if retrying cannot help (authentication/permission errors, missing "
        "tables or columns, code bugs like ImportError/AttributeError/KeyError in our "
        "own modules, exhausted daily quotas).\n"
        "If retrying, optionally give ONE short hint (<50 words) to steer the next "
        "generation attempt away from the failure. Empty hint is fine.\n\n"
        'Output ONLY raw JSON, no markdown: {"cause": "<one line>", '
        '"action": "retry" | "hold", "hint": "<optional>"}'
    )
    try:
        r = invoke_with_limit(get_judge(), [("user", prompt)])
        clean = r.content.replace("```json", "").replace("```", "").strip()
        d = _json.loads(clean)
        return {"cause": str(d.get("cause", "?"))[:300],
                "action": "hold" if str(d.get("action", "")).lower() == "hold" else "retry",
                "hint": str(d.get("hint", "") or "")[:400]}
    except Exception as e:   # diagnosis must never take the batch down
        return {"cause": f"(diagnosis itself failed: {e})", "action": "retry", "hint": ""}


def hold_batch(reason: str, ok: int, fail: int):
    log.error("=" * 62)
    log.error("SYSTEM ON HOLD: %s", reason)
    log.error("Progress so far: %d lessons succeeded, %d failed.", ok, fail)
    log.error("Fix the issue, then rerun batch_generate.py — completed lessons "
              "are skipped automatically.")
    log.error("=" * 62)
    raise SystemExit(2)


def run_one(combo, hint: str = "") -> dict:
    """Drive the graph once for a single combo and return the saved run dict.
    Raises on a quota error so the caller can back off and retry the lesson.
    A non-empty hint is injected the same way human reviewer feedback is."""
    mc = init_collector()
    graph = build_graph()
    inputs = {"theme": combo["theme"], "target_age": combo["age"],
              "milestone_code": combo["milestone_code"], "theme_code": combo["theme_code"]}
    if hint:
        inputs["blueprint_error_log"] = f"Human reviewer feedback: {hint}"
    final = {}
    try:
        for step in graph.stream(inputs, {"recursion_limit": 100}, stream_mode="updates"):
            for _node, update in step.items():
                final.update(update)
    finally:
        pass

    retries = {
        "blueprint": max(0, final.get("blueprint_retry_count", 1) - 1),
        "matrix": max(0, final.get("matrix_retry_count", 1) - 1),
    }
    metrics = mc.finalize(retries).to_dict()
    clear_collector()

    run_data = {
        "id": datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "theme": combo["theme"],
        "age": combo["age"],
        "milestone_code": combo["milestone_code"],
        "theme_code": combo["theme_code"],
        "blueprint": final.get("blueprint_text", ""),
        "matrix": final.get("raw_question_matrix", []) or [],
        "images": final.get("completed_assets", []),
        "failed": final.get("failed_assets", []),
        "pending_images": final.get("asset_queue", []),
        "pending_audio": final.get("pending_audio", []),
        "history": final.get("evaluator_history", []),
        "eval": final.get("eval_result") or {},
        "metrics": metrics,
    }
    _save_run(run_data)
    return run_data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--themes", help="comma-separated subset (default: every theme in the registry)")
    ap.add_argument("--themes-file", default=THEMES_FILE,
                    help=f"theme registry CSV (default: {THEMES_FILE})")
    ap.add_argument("--ages", help="comma-separated (default: 3,4,5,6,7)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)-8s %(levelname)s  %(message)s")

    # Registry: Supabase `themes` table is the source of truth (survives
    # container rebuilds and is fed by the admin CSV upload). The local CSV is
    # only a fallback if the table is missing/empty.
    reg, ages_by_theme, milestone_by_theme = {}, {}, {}
    catalog_live = False
    try:
        from app.core.themes import (list_themes, register_themes, parse_ages,
                                     slugify, ages_remaining)
        rows = list_themes()
        reg = {r["theme"]: r["theme_code"] for r in rows if r.get("active", True)}
        # Only ages NOT already marked done in the catalog (durable resume —
        # survives container rebuilds, unlike local runs.json).
        ages_by_theme = {r["theme"]: ages_remaining(r) for r in rows}
        milestone_by_theme = {r["theme"]: r.get("milestone_code") for r in rows
                              if r.get("milestone_code")}
        if args.themes:
            themes = [slugify(t) for t in args.themes.split(",") if t.strip()]
            reg.update(register_themes(themes))   # auto-register any new names
        else:
            themes = list(reg.keys())
        n_done = sum(1 for r in rows if r.get("status") == "done")
        log.info("Theme catalog: Supabase (%d themes, %d active, %d already done)",
                 len(rows), len(reg), n_done)
        catalog_live = True
    except Exception as e:
        log.warning("Supabase theme catalog unavailable (%s) — falling back to %s",
                    e, args.themes_file)
        reg = load_registry(args.themes_file)
        themes = ([_slugify_theme(t) for t in args.themes.split(",") if t.strip()]
                  if args.themes else list(reg.keys()))
        reg = ensure_codes(reg, themes, args.themes_file)

    ages_override = [int(a) for a in args.ages.split(",")] if args.ages else None
    queue = build_queue(themes, reg, ages_by_theme, ages_override, milestone_by_theme)

    runs = _load_runs()
    pending = [c for c in queue if not already_done(c, runs)]
    done = len(queue) - len(pending)
    log.info("Grid: %d lessons across %d themes. %d already done, %d to generate.",
             len(queue), len(themes), done, len(pending))

    if args.dry_run:
        for c in pending:
            log.info("  QUEUED: %(theme)s age %(age)s [%(milestone_code)s %(theme_code)s]", c)
        return

    pace = PACE_START
    ok = fail = 0
    for i, combo in enumerate(pending, 1):
        label = f"{combo['theme']} age {combo['age']}"
        log.info("[%d/%d] %s — starting", i, len(pending), label)

        quota_attempts = 0
        trials = 0            # non-quota failures for THIS lesson (LLM-triaged)
        hint = ""
        while True:
            try:
                run = run_one(combo, hint)
                rows = len(run.get("matrix") or [])
                if not rows:
                    raise RuntimeError(
                        "pipeline completed but produced an EMPTY question matrix "
                        f"(history: {(run.get('history') or ['none'])[-1]})")
                grade = (run.get("eval") or {}).get("grade", "?")
                cost = (run.get("metrics") or {}).get("total_cost", 0)
                ok += 1
                log.info("[%d/%d] %s — DONE: %d rows, grade %s, ~$%.4f",
                         i, len(pending), label, rows, grade, cost)
                if catalog_live:
                    try:
                        from app.core.themes import mark_age_done
                        status = mark_age_done(combo["theme"], combo["age"])
                        log.info("  catalog: '%s' age %d marked done (theme status: %s)",
                                 combo["theme"], combo["age"], status)
                    except Exception as e2:
                        log.warning("  catalog progress update failed (non-fatal): %s", e2)
                pace = max(PACE_MIN, pace * PACE_DECAY)   # speed up after a clean run
                break
            except Exception as e:
                if _is_quota_error(e):
                    quota_attempts += 1
                    if quota_attempts >= MAX_LESSON_ATTEMPTS:
                        hold_batch(f"quota still exhausted after {quota_attempts} "
                                   f"backoffs on '{label}'", ok, fail)
                    wait = min(BACKOFF_MAX, BACKOFF_BASE * (2 ** (quota_attempts - 1)))
                    pace = min(PACE_MAX, pace * PACE_GROW)   # slow the whole batch down
                    log.warning("[%d/%d] %s — 429 quota (attempt %d/%d). Backing off %ds; "
                                "inter-lesson pace now %ds.", i, len(pending), label,
                                quota_attempts, MAX_LESSON_ATTEMPTS, wait, int(pace))
                    time.sleep(wait)
                    continue

                # Non-quota failure: let the LLM read the error and decide.
                # (No 'fail' tally here — a lesson either eventually succeeds
                # or the whole batch holds; nothing is silently skipped.)
                trials += 1
                import traceback as _tb
                err_text = f"{type(e).__name__}: {e}\n{_tb.format_exc()[-2000:]}"
                diag = diagnose(err_text, combo)
                log.warning("[%d/%d] %s — trial %d/%d failed. LLM diagnosis: %s "
                            "(action=%s%s)", i, len(pending), label, trials,
                            DIAG_MAX_TRIALS, diag["cause"], diag["action"],
                            f", hint={diag['hint']!r}" if diag["hint"] else "")
                if diag["action"] == "hold":
                    hold_batch(f"'{label}' failed and the diagnosis says retrying "
                               f"can't fix it: {diag['cause']}", ok, fail)
                if trials >= DIAG_MAX_TRIALS:
                    hold_batch(f"'{label}' failed {trials} trials in a row "
                               f"(last cause: {diag['cause']})", ok, fail)
                hint = diag["hint"]
                log.info("[%d/%d] %s — re-running (trial %d)…",
                         i, len(pending), label, trials + 1)

        if i < len(pending):
            log.info("Pacing %ds before next lesson…", int(pace))
            time.sleep(pace)

    log.info("Batch finished. %d succeeded, %d failed/empty, %d skipped (already done).",
             ok, fail, done)


if __name__ == "__main__":
    main()
