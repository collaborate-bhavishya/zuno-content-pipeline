"""Supabase image-asset DB layer.

Tracks every image the pipeline has ever generated so repeat requests
skip already-generated assets.  Table: `image_assets`.

Columns:
  image_name      TEXT UNIQUE   — canonical filename (e.g. red_apple.png)
  image_detail    TEXT           — generation prompt / subject description
  image_url       TEXT           — public URL or local path after generation
  status          SMALLINT       — 0 = pending, 1 = generated
  milestone_code  TEXT
  theme_code      TEXT
  playable_code   TEXT
"""

import os, logging
from typing import Optional
from supabase import create_client, Client

log = logging.getLogger(__name__)

_client: Optional[Client] = None


def _get_client() -> Client:
    global _client
    if _client is None:
        url = os.getenv("SUPABASE_URL", "")
        key = os.getenv("SUPABASE_KEY", "")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set in .env")
        _client = create_client(url, key)
    return _client


# ── queries ──────────────────────────────────────────────────────────

def lookup_existing(image_names: list[str]) -> dict[str, dict]:
    """Return {image_name: row_dict} for every name already in the DB with status=1."""
    if not image_names:
        return {}
    client = _get_client()
    # Supabase 'in' filter
    result = client.table("image_assets").select("*").in_("image_name", image_names).eq("status", 1).execute()
    return {row["image_name"]: row for row in (result.data or [])}


def upsert_pending(assets: list[dict]):
    """Insert new image rows as status=0 (pending).  Skip if name already exists."""
    if not assets:
        return
    client = _get_client()
    rows = [
        {
            "image_name": a["filename"],
            "image_detail": a.get("detail", ""),
            "status": 0,
            "milestone_code": a.get("milestone_code", ""),
            "theme_code": a.get("theme_code", ""),
            "playable_code": a.get("playable_code", ""),
        }
        for a in assets
    ]
    # on_conflict: if image_name already exists, don't overwrite
    try:
        client.table("image_assets").upsert(
            rows, on_conflict="image_name", ignore_duplicates=True
        ).execute()
    except Exception as e:
        log.warning("upsert_pending: %s", e)


def mark_generated(image_name: str, image_url: str = ""):
    """Set status=1 and optionally store the URL/path."""
    client = _get_client()
    try:
        client.table("image_assets").update(
            {"status": 1, "image_url": image_url}
        ).eq("image_name", image_name).execute()
    except Exception as e:
        log.warning("mark_generated(%s): %s", image_name, e)


def mark_failed(image_name: str):
    """Keep status=0 so next run retries it."""
    # Nothing to change — status is already 0.
    # But we log it for observability.
    log.info("Image stayed pending (will retry next run): %s", image_name)


def mark_wrong_generation(image_name: str, image_url: str = ""):
    """Image was generated but REJECTED by the vision critic. Status 2 =
    wrong_generation; image_url points to the stored (rejected) image for review."""
    client = _get_client()
    try:
        client.table("image_assets").update(
            {"status": 2, "image_url": image_url}
        ).eq("image_name", image_name).execute()
    except Exception as e:
        log.warning("mark_wrong_generation(%s): %s", image_name, e)


def get_all_assets(milestone_code: str = "", theme_code: str = "") -> list[dict]:
    """Fetch all rows, optionally filtered by milestone/theme."""
    client = _get_client()
    q = client.table("image_assets").select("*")
    if milestone_code:
        q = q.eq("milestone_code", milestone_code)
    if theme_code:
        q = q.eq("theme_code", theme_code)
    result = q.order("created_at").execute()
    return result.data or []
