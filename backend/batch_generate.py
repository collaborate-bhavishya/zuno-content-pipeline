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


def build_queue(themes, ages, reg):
    return [
        {"theme": t, "age": a, "milestone_code": f"AG{a:02d}", "theme_code": reg[t]}
        for t in themes for a in ages
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


def run_one(combo) -> dict:
    """Drive the graph once for a single combo and return the saved run dict.
    Raises on a quota error so the caller can back off and retry the lesson."""
    mc = init_collector()
    graph = build_graph()
    inputs = {"theme": combo["theme"], "target_age": combo["age"],
              "milestone_code": combo["milestone_code"], "theme_code": combo["theme_code"]}
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

    reg = load_registry(args.themes_file)
    if args.themes:
        themes = [_slugify_theme(t) for t in args.themes.split(",") if t.strip()]
    else:
        themes = list(reg.keys())          # whole catalog
    reg = ensure_codes(reg, themes, args.themes_file)   # register + persist any new ones
    ages = [int(a) for a in args.ages.split(",")] if args.ages else AGES
    queue = build_queue(themes, ages, reg)

    runs = _load_runs()
    pending = [c for c in queue if not already_done(c, runs)]
    done = len(queue) - len(pending)
    log.info("Grid: %d lessons (%d themes x %d ages). %d already done, %d to generate.",
             len(queue), len(themes), len(ages), done, len(pending))

    if args.dry_run:
        for c in pending:
            log.info("  QUEUED: %(theme)s age %(age)s [%(milestone_code)s %(theme_code)s]", c)
        return

    pace = PACE_START
    ok = fail = 0
    for i, combo in enumerate(pending, 1):
        label = f"{combo['theme']} age {combo['age']}"
        log.info("[%d/%d] %s — starting", i, len(pending), label)

        for attempt in range(1, MAX_LESSON_ATTEMPTS + 1):
            try:
                run = run_one(combo)
                rows = len(run.get("matrix") or [])
                grade = (run.get("eval") or {}).get("grade", "?")
                cost = (run.get("metrics") or {}).get("total_cost", 0)
                if rows:
                    ok += 1
                    log.info("[%d/%d] %s — DONE: %d rows, grade %s, ~$%.4f",
                             i, len(pending), label, rows, grade, cost)
                else:
                    fail += 1
                    log.warning("[%d/%d] %s — completed but EMPTY matrix (saved for review)",
                                i, len(pending), label)
                pace = max(PACE_MIN, pace * PACE_DECAY)   # speed up after a clean run
                break
            except Exception as e:
                if _is_quota_error(e):
                    wait = min(BACKOFF_MAX, BACKOFF_BASE * (2 ** (attempt - 1)))
                    pace = min(PACE_MAX, pace * PACE_GROW)   # slow the whole batch down
                    log.warning("[%d/%d] %s — 429 quota (attempt %d/%d). Backing off %ds; "
                                "inter-lesson pace now %ds.",
                                i, len(pending), label, attempt, MAX_LESSON_ATTEMPTS, wait, int(pace))
                    time.sleep(wait)
                    continue
                fail += 1
                log.exception("[%d/%d] %s — FAILED (non-quota): %s", i, len(pending), label, e)
                break
        else:
            fail += 1
            log.error("[%d/%d] %s — gave up after %d quota retries.",
                      i, len(pending), label, MAX_LESSON_ATTEMPTS)

        if i < len(pending):
            log.info("Pacing %ds before next lesson…", int(pace))
            time.sleep(pace)

    log.info("Batch finished. %d succeeded, %d failed/empty, %d skipped (already done).",
             ok, fail, done)


if __name__ == "__main__":
    main()
