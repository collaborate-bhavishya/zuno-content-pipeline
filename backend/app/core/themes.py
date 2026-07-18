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
    """All catalog rows, ordered by code."""
    rows = get_client().table("themes").select("*").execute().data or []
    return sorted(rows, key=lambda r: (len(r["theme_code"]), r["theme_code"]))


def register_themes(names: list) -> dict:
    """Ensure each named theme exists (auto-assigning codes). Returns
    {theme: theme_code}. Used by the batch for --themes with new names."""
    existing = {r["theme"]: r["theme_code"] for r in list_themes()}
    used = set(existing.values())
    new_rows = []
    for name in names:
        t = slugify(name)
        if t and t not in existing:
            code = _next_code(used)
            used.add(code)
            existing[t] = code
            new_rows.append({"theme": t, "theme_code": code})
    if new_rows:
        get_client().table("themes").upsert(
            new_rows, on_conflict="theme", ignore_duplicates=True).execute()
        for r in new_rows:
            log.info("Registered new theme '%s' -> %s", r["theme"], r["theme_code"])
    return existing


def mark_age_done(theme: str, age: int) -> str:
    """Record that one (theme, age) lesson completed. Updates generated_ages
    and derives status: done when every configured age is generated,
    in_progress otherwise. Returns the new status."""
    from datetime import datetime, timezone
    client = get_client()
    row = client.table("themes").select("ages, generated_ages").eq("theme", theme).execute().data
    if not row:
        return "unknown"
    configured = set(parse_ages(row[0].get("ages", "")))
    done_ages = {int(a) for a in str(row[0].get("generated_ages") or "").split(",") if a.strip().isdigit()}
    done_ages.add(int(age))
    status = "done" if configured <= done_ages else "in_progress"
    client.table("themes").update({
        "generated_ages": ",".join(str(a) for a in sorted(done_ages)),
        "status": status,
        "last_generated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("theme", theme).execute()
    return status


def ages_remaining(row: dict) -> list:
    """Configured ages for a catalog row minus the ones already generated."""
    configured = parse_ages(row.get("ages", ""))
    done = {int(a) for a in str(row.get("generated_ages") or "").split(",") if a.strip().isdigit()}
    return [a for a in configured if a not in done]


def upsert_csv(csv_text: str) -> dict:
    """Merge an uploaded CSV into the catalog.

    Rules: existing themes keep their code no matter what the CSV says (ages/
    active/notes are updated); new themes take the provided code if it's free,
    else it's an error row; blank codes are auto-assigned.
    """
    current = {r["theme"]: r for r in list_themes()}
    used_codes = {r["theme_code"] for r in current.values()}
    added, updated, errors, warnings = [], [], [], []

    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    if not reader.fieldnames or "theme" not in [f.strip().lower() for f in reader.fieldnames]:
        return {"error": "CSV must have a header row including a 'theme' column.",
                "expected_columns": "theme,theme_code,ages,active,notes"}

    rows_out = []
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
        ages = ",".join(str(a) for a in parse_ages(row.get("ages", "")))
        active = row.get("active", "true").lower() not in ("false", "0", "no")
        notes = row.get("notes", "")
        fields = {"ages": ages, "milestone_code": milestone or None,
                  "active": active, "notes": notes}

        if theme in current:
            kept = current[theme]["theme_code"]
            if code and code != kept:
                warnings.append(f"line {i}: '{theme}' already has code {kept}; "
                                f"ignored CSV's {code} (codes never change)")
            rows_out.append({"theme": theme, "theme_code": kept, **fields})
            updated.append(theme)
        else:
            if code:
                if code in used_codes:
                    errors.append(f"line {i}: code {code} is already taken; "
                                  f"leave blank to auto-assign")
                    continue
            else:
                code = _next_code(used_codes)
            used_codes.add(code)
            rows_out.append({"theme": theme, "theme_code": code, **fields})
            added.append(f"{theme} -> {code}")

    if rows_out:
        get_client().table("themes").upsert(rows_out, on_conflict="theme").execute()

    return {"added": added, "updated": updated,
            "warnings": warnings, "errors": errors,
            "themes": list_themes()}
