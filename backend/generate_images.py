#!/usr/bin/env python3
"""
Image production worker — the external process the image_assets ledger was
built for. Ported from v2_Image_generation.ipynb (same model, same prompts,
same QC layer, same 3-attempt loop), adapted to run unattended against the
Supabase ledger instead of a CSV:

    pick one pending row (status=0)
      -> generate with gemini-2.5-flash-image      (notebook: generation)
      -> audit the pixels with the SAME model      (notebook: vision critic)
      -> on pass: upload PNG to S3, mark status=1  (notebook: img.save)
      -> on 3 failed attempts: leave pending, move on (a rerun retries it)

Production additions the Colab loop didn't need: 429 pacing/backoff (image
quota is per-minute), resumability via the status flags, and a log file.

    python generate_images.py --limit 2      # smoke test on 2 images
    python generate_images.py                # work through the whole queue
    python generate_images.py --dry-run      # show what would be generated
"""
import argparse
import io
import json
import logging
import os
import re
import time

import PIL.Image

from app.core.db import get_client, mark_generated
from app.core.storage import STORAGE

log = logging.getLogger("imgworker")

MODEL = "gemini-2.5-flash-image"
MAX_QC_ATTEMPTS = 3          # same as the notebook
THROTTLE_S = 8.0             # pause before every API call (gen AND audit)
BACKOFF_BASE_S = 30          # 429 backoff: 30s, 60s, 90s... capped
BACKOFF_MAX_S = 300
MAX_429_RETRIES = 6

# Known INANIMATE objects -> rendered with NO face. Everything else (animals,
# people, characters, or anything ambiguous) defaults to friendly eyes — the
# notebook's is_living CSV column, derived from the filename instead.
INANIMATE_WORDS = {
    "ball", "block", "blocks", "cube", "cup", "mug", "plate", "bowl", "spoon",
    "fork", "knife", "box", "bag", "basket", "bottle", "jar", "can",
    "car", "truck", "bus", "train", "plane", "boat", "ship", "bike", "cycle",
    "apple", "banana", "orange", "grape", "grapes", "fruit", "mango", "pear",
    "carrot", "tomato", "potato", "corn", "vegetable", "cake", "bread", "egg",
    "book", "pen", "pencil", "crayon", "paper",
    "cap", "hat", "shoe", "shoes", "sock", "socks", "shirt", "dress", "coat",
    "star", "moon", "sun", "cloud", "circle", "square", "triangle", "heart",
    "tree", "leaf", "leaves", "flower", "plant", "grass", "rock", "stone",
    "house", "home", "door", "window", "wall", "roof",
    "key", "drum", "bell", "kite", "balloon", "clock", "lamp", "light",
    "chair", "table", "bed", "sofa", "brush", "comb", "umbrella", "ring",
    "coin", "phone", "tv", "guitar", "flag", "wheel", "button",
    "tent", "map", "menu", "ticket", "castle", "tower", "bridge", "pyramid",
    "rocket", "robot", "computer", "swing", "slide",
}


def eye_rule(object_name: str) -> str:
    """Whole-word match so 'starfish' isn't caught by 'star'. Ambiguity
    defaults to friendly eyes (an unknown subject is usually a creature)."""
    words = set(object_name.lower().replace("_", " ").split())
    if words & INANIMATE_WORDS:
        return "no eyes and no face"
    return "two simple black circle eyes with a white glimmer"


# ── Gemini client (new google-genai SDK; the notebook's google.generativeai
#    package is deprecated — same model, same calls) ──────────────────────
_client = None


def genai_client():
    global _client
    if _client is None:
        from google import genai
        if os.getenv("GOOGLE_API_KEY"):
            _client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
        else:  # Vertex AI via ADC (how the backend authenticates in prod)
            _client = genai.Client(
                vertexai=True,
                project=os.getenv("GOOGLE_CLOUD_PROJECT"),
                location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
            )
    return _client


def _is_429(e: Exception) -> bool:
    s = str(e).lower()
    return "429" in s or "resource_exhausted" in s or "quota" in s


def _call_model(contents):
    """One paced generate_content call with 429 backoff. Returns the response."""
    from google.genai import types
    for attempt in range(1, MAX_429_RETRIES + 1):
        time.sleep(THROTTLE_S)
        try:
            return genai_client().models.generate_content(
                model=MODEL, contents=contents,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE", "TEXT"]),
            )
        except Exception as e:
            if _is_429(e) and attempt < MAX_429_RETRIES:
                wait = min(BACKOFF_MAX_S, BACKOFF_BASE_S * attempt)
                log.warning("429 from %s — backing off %ds (attempt %d/%d)",
                            MODEL, wait, attempt, MAX_429_RETRIES)
                time.sleep(wait)
                continue
            raise


def _image_from(resp):
    for cand in (resp.candidates or []):
        for part in (cand.content.parts or []):
            inline = getattr(part, "inline_data", None)
            if inline and inline.data:
                return PIL.Image.open(io.BytesIO(inline.data))
    return None


def _text_from(resp) -> str:
    out = []
    for cand in (resp.candidates or []):
        for part in (cand.content.parts or []):
            if getattr(part, "text", None):
                out.append(part.text)
    return "\n".join(out)


# ── The notebook's preschool_agent, fed from the ledger row ──────────────

def produce(asset: dict):
    """Generate + audit one asset. Returns (PIL image | None, last_reason)."""
    object_name = asset["image_name"][:-4].replace("_", " ") \
        if asset["image_name"].endswith(".png") else asset["image_name"]
    detail = (asset.get("image_detail") or "").strip()
    eye = eye_rule(object_name)
    color_style = "bright colors"          # notebook default

    prompt = f"""
    Generate a flat 2D cartoon illustration of a {object_name}.
    Style: soft rounded shapes, no outlines, {color_style}.
    Face Rule: {eye}.
    Composition: Centered on a solid white background.
    Lighting: 100% flat, no shading, no gradients.
    """
    if detail and detail != "—":
        prompt += f"    Appearance: {detail}.\n"

    last_reason = "no attempts"
    for attempt in range(1, MAX_QC_ATTEMPTS + 1):
        log.info("  generating '%s' (attempt %d/%d)…", object_name, attempt, MAX_QC_ATTEMPTS)
        resp = _call_model(prompt)
        img = _image_from(resp)
        if img is None:
            last_reason = "no image data in response"
            log.warning("  no image data returned")
            continue

        # Vision critic — same criteria as the notebook, plus the ledger's
        # own description as the color/appearance check.
        if detail and detail != "—":
            color_check = f"- Does the image match this description: {detail}?"
        else:
            color_check = f"- Does the {object_name} use bright colors?"
        critic_prompt = f"""
        Inspect this image for a preschool app.
        Criteria:
        - Is the background 100% white?
        - Are there ANY outlines? (Should be NO)
        - If it's a {object_name}, does it follow the rule: {eye}?
        {color_check}

        Return ONLY a JSON object: {{"pass": true/false, "reason": "string"}}
        """
        audit = _call_model([critic_prompt, img])
        raw = _text_from(audit)
        try:
            m = re.search(r"```json\n(.*?)```", raw, re.DOTALL)
            result = json.loads(m.group(1).strip() if m else raw.strip())
        except Exception as e:
            last_reason = f"audit JSON parse error: {e} (raw: {raw[:120]!r})"
            log.warning("  %s", last_reason)
            continue

        if result.get("pass"):
            log.info("  ✅ passed QC")
            return img, "ok"
        last_reason = str(result.get("reason", "rejected"))[:300]
        log.info("  ❌ rejected: %s", last_reason)

    return None, last_reason


def fetch_pending(limit=None):
    c = get_client()
    out, page = [], 0
    while True:
        batch = (c.table("image_assets").select("image_name,image_detail")
                 .eq("status", 0).order("created_at")
                 .range(page * 1000, page * 1000 + 999).execute().data)
        out += batch
        if len(batch) < 1000:
            break
        page += 1
    return out[:limit] if limit else out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="only process this many (smoke test)")
    ap.add_argument("--throttle", type=float, help="seconds before each API call")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)-9s %(levelname)s  %(message)s")
    if args.throttle:
        global THROTTLE_S
        THROTTLE_S = args.throttle

    pending = fetch_pending(args.limit)
    log.info("Image queue: %d pending%s", len(pending),
             f" (limited to {args.limit})" if args.limit else "")
    if args.dry_run:
        for a in pending[:30]:
            log.info("  WOULD GENERATE: %-28s %s", a["image_name"],
                     (a.get("image_detail") or "")[:60])
        return

    ok = failed = 0
    t0 = time.time()
    for i, asset in enumerate(pending, 1):
        name = asset["image_name"]
        log.info("[%d/%d] %s", i, len(pending), name)
        try:
            img, reason = produce(asset)
        except Exception as e:
            log.exception("[%d/%d] %s — unrecoverable error: %s", i, len(pending), name, e)
            failed += 1
            continue
        if img is None:
            failed += 1
            log.warning("[%d/%d] %s — FAILED QC after %d attempts (%s); left pending",
                        i, len(pending), name, MAX_QC_ATTEMPTS, reason)
            continue
        url = STORAGE.save_image(img, name)
        mark_generated(name, image_url=url)
        ok += 1
        elapsed = time.time() - t0
        rate = elapsed / max(ok + failed, 1)
        log.info("[%d/%d] %s — DONE -> %s  (avg %.0fs/img, ~%.1fh for the rest)",
                 i, len(pending), name, url, rate, rate * (len(pending) - i) / 3600)

    log.info("Worker finished: %d generated+uploaded, %d left pending (rerun retries them).",
             ok, failed)


if __name__ == "__main__":
    main()
