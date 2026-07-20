"""Theme catalog (Supabase `themes` table — see supabase/themes.sql).

The catalog is the single source of truth for which themes exist, their stable
theme_codes, and which ages each generates for. The admin UI uploads a CSV
here; the batch runner reads it. Codes are assigned once and never change.

CSV format (only `theme` is required):
    theme,theme_code,ages,milestone_code,active,notes
    dinosaurs,,4-6,,true,friendly dinos only

milestone_code is an optional override (e.g. AG05) used for EVERY lesson of the
theme; blank derives it per age (age 3 -> AG03, ...), matching the app form's
default behavior.
"""
import csv
import io
import logging
import re

from app.core.db import get_client

log = logging.getLogger(__name__)

AGE_MIN, AGE_MAX = 3, 7
DEFAULT_AGES = list(range(AGE_MIN, AGE_MAX + 1))


def slugify(theme: str) -> str:
    """Normalize a theme name: lowercase, trimmed, single spaces."""
    return re.sub(r"\s+", " ", str(theme or "").strip().lower())


def parse_ages(spec: str) -> list:
    """'3-7' | '4,5' | '' -> sorted list of valid ages (default: all)."""
    s = str(spec or "").strip()
    if not s:
        return list(DEFAULT_AGES)
    ages = set()
    for part in s.split(","):
        part = part.strip()
        m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", part)
        if m:
            ages.update(range(int(m.group(1)), int(m.group(2)) + 1))
        elif part.isdigit():
            ages.add(int(part))
    ages = {a for a in ages if AGE_MIN <= a <= AGE_MAX}
    return sorted(ages) or list(DEFAULT_AGES)


def _next_code(used: set) -> str:
    nums = {int(m.group(1)) for c in used if (m := re.fullmatch(r"T(\d+)", c))}
    n = 1
    while n in nums:
        n += 1
    return f"T{n:02d}"


def list_themes() -> list:
    """All catalog rows (ONE per theme+age), ordered by code then milestone."""
    rows = get_client().table("themes").select("*").execute().data or []
    return sorted(rows, key=lambda r: (len(r["theme_code"]), r["theme_code"],
                                       r.get("milestone_code") or ""))


def row_age(row: dict) -> int:
    """The single age a catalog row represents."""
    ages = parse_ages(row.get("ages", ""))
    return ages[0] if ages else AGE_MIN


def register_themes(names: list, ages: list = None) -> dict:
    """Ensure each named theme exists, one row per age (auto-assigning a
    theme_code shared by all its rows). Returns {theme: theme_code}."""
    current = list_themes()
    code_by_theme = {r["theme"]: r["theme_code"] for r in current}
    have_keys = {(r["theme"], r["milestone_code"]) for r in current}
    used = set(code_by_theme.values())
    ages = ages or list(DEFAULT_AGES)
    new_rows = []
    for name in names:
        t = slugify(name)
        if not t:
            continue
        if t not in code_by_theme:
            code_by_theme[t] = _next_code(used)
            used.add(code_by_theme[t])
            log.info("Registered new theme '%s' -> %s", t, code_by_theme[t])
        for a in ages:
            ms = f"AG{a:02d}"
            if (t, ms) not in have_keys:
                new_rows.append({"theme": t, "theme_code": code_by_theme[t],
                                 "ages": str(a), "milestone_code": ms,
                                 "active": True, "status": "pending",
                                 "generated_ages": ""})
    if new_rows:
        get_client().table("themes").insert(new_rows).execute()
    return code_by_theme


def mark_row_done(theme: str, milestone_code: str, age: int = None) -> str:
    """Mark the single (theme, milestone_code) row as generated."""
    from datetime import datetime, timezone
    upd = {"status": "done",
           "last_generated_at": datetime.now(timezone.utc).isoformat()}
    if age is not None:
        upd["generated_ages"] = str(age)
    (get_client().table("themes").update(upd)
     .eq("theme", theme).eq("milestone_code", milestone_code).execute())
    return "done"


def ages_remaining(row: dict) -> list:
    """[] once the row is generated, else its single age."""
    return [] if row.get("status") == "done" else [row_age(row)]


def upsert_csv(csv_text: str) -> dict:
    """Merge an uploaded CSV into the catalog.

    The catalog holds ONE ROW PER (theme, age), each with an explicit
    milestone_code — so a CSV line listing several ages expands into one row
    per age (colors, ages 3-4 -> a row at AG03 and a row at AG04). Rules:
    a theme keeps one theme_code across all its rows; an existing row keeps
    its code and its generated status; a milestone may only be given
    explicitly for a single-age line.
    """
    current = list_themes()
    by_key = {(r["theme"], r["milestone_code"]): r for r in current}
    code_by_theme = {r["theme"]: r["theme_code"] for r in current}
    used_codes = set(code_by_theme.values())
    added, updated, errors, warnings = [], [], [], []

    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    if not reader.fieldnames or "theme" not in [f.strip().lower() for f in reader.fieldnames]:
        return {"error": "CSV must have a header row including a 'theme' column.",
                "expected_columns": "theme,theme_code,ages,milestone_code,active,notes"}

    to_insert, to_update = [], []
    for i, raw in enumerate(reader, 2):   # 2 = first data line in the file
        row = {str(k).strip().lower(): str(v or "").strip() for k, v in raw.items() if k}
        theme = slugify(row.get("theme", ""))
        if not theme:
            continue
        code = row.get("theme_code", "").upper()
        if code and not re.fullmatch(r"T\d{1,4}", code):
            errors.append(f"line {i}: '{theme}' has invalid theme_code '{code}' (expected T<number>)")
            continue
        milestone = row.get("milestone_code", "").upper()
        if milestone and not re.fullmatch(r"AG\d{1,4}", milestone):
            errors.append(f"line {i}: '{theme}' has invalid milestone_code "
                          f"'{milestone}' (expected AG<number>, or blank to derive from age)")
            continue
        ages_list = parse_ages(row.get("ages", ""))
        if milestone and len(ages_list) > 1:
            errors.append(f"line {i}: '{theme}' lists {len(ages_list)} ages with a single "
                          f"milestone_code {milestone}; use one line per age, or leave "
                          f"milestone blank to derive it from each age")
            continue
        active = row.get("active", "true").lower() not in ("false", "0", "no")
        notes = row.get("notes", "")

        # One theme_code per theme, shared by all its age rows.
        if theme in code_by_theme:
            kept = code_by_theme[theme]
            if code and code != kept:
                warnings.append(f"line {i}: '{theme}' already has code {kept}; "
                                f"ignored CSV's {code} (codes never change)")
            code = kept
        else:
            if code and code in used_codes:
                errors.append(f"line {i}: code {code} is already taken; leave blank to auto-assign")
                continue
            code = code or _next_code(used_codes)
            used_codes.add(code)
            code_by_theme[theme] = code

        for a in ages_list:
            ms = milestone or f"AG{a:02d}"
            fields = {"theme": theme, "theme_code": code, "ages": str(a),
                      "milestone_code": ms, "active": active, "notes": notes}
            if (theme, ms) in by_key:
                to_update.append(fields)          # progress columns preserved
                updated.append(f"{theme} {ms}")
            else:
                to_insert.append({**fields, "status": "pending", "generated_ages": ""})
                added.append(f"{theme} {ms} -> {code}")

    client = get_client()
    if to_insert:
        client.table("themes").insert(to_insert).execute()
    for f in to_update:
        (client.table("themes")
         .update({k: v for k, v in f.items() if k not in ("theme", "milestone_code")})
         .eq("theme", f["theme"]).eq("milestone_code", f["milestone_code"]).execute())

    return {"added": added, "updated": updated,
            "warnings": warnings, "errors": errors,
            "themes": list_themes()}
