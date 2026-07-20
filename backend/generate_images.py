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

from app.core.db import get_client, mark_generated, mark_wrong_generation
from app.core.storage import STORAGE

log = logging.getLogger("imgworker")

MODEL = "gemini-2.5-flash-image"
MAX_QC_ATTEMPTS = 3          # same as the notebook

# Every approved (or review-held) image is stored in TWO sizes:
#   {name}.png          1024x1024 native render
#   lowres/{name}.png   512x512 optimized copy (same filename, lowres/ prefix,
#                       so consumers just prepend a path segment)
LOWRES_SIZE = 512
LOWRES_PREFIX = "lowres/"
THROTTLE_S = 8.0             # pause before every API call (gen AND audit)
BACKOFF_BASE_S = 30          # 429 backoff: 30s, 60s, 90s... capped
BACKOFF_MAX_S = 300
MAX_429_RETRIES = 6

# THE EYE RULE (from content review): eyes exist ONLY when a living creature's
# face is shown. Objects/symbols never get faces; an isolated body part (a
# nose, a mouth) is drawn ALONE with no other features added; even a living
# being shown without its face gets no eyes.
#
# Known-inanimate and body-part word lists give a hard, deterministic verdict;
# everything else gets the conditional rule, which the model applies and the
# critic then verifies from the pixels.
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
    "house", "home", "door", "window", "wall", "roof", "barn",
    "key", "drum", "bell", "kite", "balloon", "clock", "lamp", "light",
    "chair", "table", "bed", "sofa", "brush", "comb", "umbrella", "ring",
    "coin", "phone", "tv", "guitar", "flag", "wheel", "button",
    "tent", "map", "menu", "ticket", "castle", "tower", "bridge", "pyramid",
    "rocket", "robot", "computer", "swing", "slide",
    "checkmark", "check", "mark", "tick", "cross", "icon", "sign", "symbol",
    "arrow", "blanket", "pillow", "towel", "soap", "toothbrush",
}

# Body parts are named subjects that must be drawn ALONE — never given eyes,
# a mouth, or composed into a face (review finding: 'small nose' was rendered
# as a whole face; feet were given eyes).
BODY_PART_WORDS = {
    "nose", "mouth", "ear", "ears", "eye", "eyes", "hand", "hands",
    "foot", "feet", "leg", "legs", "arm", "arms", "finger", "fingers",
    "toe", "toes", "tummy", "belly", "hair", "teeth", "tooth", "tongue",
    "chin", "knee", "elbow", "shoulder", "cheek", "lips",
}


def face_rule(object_name: str) -> str:
    """Deterministic verdict for known words; conditional rule otherwise."""
    words = set(object_name.lower().replace("_", " ").split())
    if words & BODY_PART_WORDS:
        return (f"This is an ISOLATED BODY PART illustration. Draw ONLY the "
                f"{object_name} by itself — do NOT add eyes, a mouth, a face, "
                f"or any other body part or feature to it.")
    if words & INANIMATE_WORDS:
        return ("This is an OBJECT, not a living creature: absolutely NO eyes, "
                "NO face, NO facial features anywhere in the image.")
    return (f"Apply this rule: IF the {object_name} is a living creature "
            f"(animal, person, character) depicted with its face visible, give "
            f"it two simple black circle eyes with a white glimmer on its face. "
            f"OTHERWISE — if it is an object, symbol, food, plant, building, or "
            f"a living being shown without its face — add NO eyes and NO facial "
            f"features at all. Eyes may ONLY ever appear on a living creature's "
            f"face — never on feet, hands, body, clothing, objects, or anywhere "
            f"else.")


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
    """Generate + audit one asset.

    Returns (passed, last_img, last_reason): passed=True with the approved
    image, or passed=False with the LAST rejected render (for the status=2
    manual-review path) and the QC reason it failed on.

    Each retry is a REPAIR, not a blind re-roll: the critic's rejection
    reason is fed back into the next generation prompt so the model fixes
    the specific QC parameter that failed.
    """
    object_name = asset["image_name"][:-4].replace("_", " ") \
        if asset["image_name"].endswith(".png") else asset["image_name"]
    detail = (asset.get("image_detail") or "").strip()
    eye = face_rule(object_name)
    color_style = "bright colors"          # notebook default

    base_prompt = f"""
    Generate a flat 2D cartoon illustration of a {object_name}.
    Style: soft rounded shapes, no outlines, {color_style}.
    Face Rule: {eye}
    Composition: Centered on a solid white background. Show ONLY the
    {object_name} itself — no extra objects, characters, props, or added
    features beyond what is named and described.
    Lighting: 100% flat, no shading, no gradients.
    """
    if detail and detail != "—":
        base_prompt += f"    Appearance: {detail}.\n"

    last_reason = "no attempts"
    last_img = None
    for attempt in range(1, MAX_QC_ATTEMPTS + 1):
        prompt = base_prompt
        if last_img is not None or last_reason != "no attempts":
            # Feed the failed QC parameter back so this attempt fixes THAT.
            prompt += (
                f"    REPAIR: the previous attempt was rejected by quality "
                f"control for exactly this reason: \"{last_reason}\". Fix that "
                f"specific issue while keeping the same subject and style.\n"
            )
        log.info("  generating '%s' (attempt %d/%d)…", object_name, attempt, MAX_QC_ATTEMPTS)
        resp = _call_model(prompt)
        img = _image_from(resp)
        if img is None:
            last_reason = "no image data in response"
            log.warning("  no image data returned")
            continue
        last_img = img

        # Vision critic — the notebook's criteria plus the eye-placement law
        # and only-the-named-subject check from content review.
        if detail and detail != "—":
            color_check = f"- Does the image match this description: {detail}?"
        else:
            color_check = f"- Does the {object_name} use bright colors?"
        critic_prompt = f"""
        Inspect this image for a preschool app.
        Criteria:
        - Is the background 100% white?
        - Are there ANY outlines? (Should be NO)
        - EYE PLACEMENT LAW: eyes are allowed ONLY on the face of a living
          creature. FAIL if there are eyes or facial features on any object,
          symbol, building, food, body part, clothing, feet, hands, or
          anywhere that is not a living creature's face.
        - Subject rule for this image: {eye}
        - Does the image show ONLY the {object_name} (plus nothing extra)?
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
            return True, img, "ok"
        last_reason = str(result.get("reason", "rejected"))[:300]
        log.info("  ❌ rejected: %s", last_reason)

    return False, last_img, last_reason


def save_both_sizes(img, name: str) -> str:
    """Upload the native 1024 render at {name} and a 512 copy at lowres/{name}.
    Returns the full-size URL (the one stored in the ledger)."""
    url = STORAGE.save_image(img, name)
    try:
        small = img.resize((LOWRES_SIZE, LOWRES_SIZE), PIL.Image.LANCZOS)
        STORAGE.save_image(small, f"{LOWRES_PREFIX}{name}")
    except Exception as e:
        log.warning("  lowres save failed for %s (non-fatal): %s", name, e)
    return url


def backfill_lowres():
    """Create lowres/ copies for already-generated images that lack one.
    Pure download+resize — no model calls."""
    import urllib.request
    c = get_client()
    rows, page = [], 0
    while True:
        batch = (c.table("image_assets").select("image_name,image_url,status")
                 .in_("status", [1, 2]).order("created_at")
                 .range(page * 1000, page * 1000 + 999).execute().data)
        rows += batch
        if len(batch) < 1000:
            break
        page += 1
    made = skipped = failed = 0
    for r in rows:
        name, url = r["image_name"], r.get("image_url") or ""
        if not url.startswith("http"):
            continue
        if STORAGE.exists(f"{LOWRES_PREFIX}{name}"):
            skipped += 1
            continue
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                img = PIL.Image.open(io.BytesIO(resp.read()))
            small = img.resize((LOWRES_SIZE, LOWRES_SIZE), PIL.Image.LANCZOS)
            STORAGE.save_image(small, f"{LOWRES_PREFIX}{name}")
            made += 1
            log.info("  lowres created: %s", name)
        except Exception as e:
            failed += 1
            log.warning("  lowres backfill failed for %s: %s", name, e)
    log.info("Backfill done: %d created, %d already had one, %d failed.",
             made, skipped, failed)


def fetch_pending(limit=None, names=None):
    c = get_client()
    out, page = [], 0
    while True:
        q = (c.table("image_assets").select("image_name,image_detail")
             .eq("status", 0).order("created_at"))
        if names:
            q = q.in_("image_name", names)
        batch = q.range(page * 1000, page * 1000 + 999).execute().data
        out += batch
        if len(batch) < 1000:
            break
        page += 1
    return out[:limit] if limit else out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="only process this many (smoke test)")
    ap.add_argument("--names", help="comma-separated filenames to process (targeted rerun)")
    ap.add_argument("--throttle", type=float, help="seconds before each API call")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--backfill-lowres", action="store_true",
                    help="create 512px lowres/ copies for already-generated images")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)-9s %(levelname)s  %(message)s")
    if args.backfill_lowres:
        backfill_lowres()
        return
    if args.throttle:
        global THROTTLE_S
        THROTTLE_S = args.throttle

    names = [n.strip() for n in args.names.split(",")] if args.names else None
    pending = fetch_pending(args.limit, names)
    log.info("Image queue: %d pending%s", len(pending),
             f" (limited to {args.limit})" if args.limit else "")
    if args.dry_run:
        for a in pending[:30]:
            log.info("  WOULD GENERATE: %-28s %s", a["image_name"],
                     (a.get("image_detail") or "")[:60])
        return

    ok = review = failed = 0
    t0 = time.time()
    for i, asset in enumerate(pending, 1):
        name = asset["image_name"]
        log.info("[%d/%d] %s", i, len(pending), name)
        try:
            passed, img, reason = produce(asset)
        except Exception as e:
            log.exception("[%d/%d] %s — unrecoverable error: %s", i, len(pending), name, e)
            failed += 1
            continue

        if passed:
            url = save_both_sizes(img, name)
            mark_generated(name, image_url=url)
            ok += 1
            elapsed = time.time() - t0
            rate = elapsed / max(i, 1)
            log.info("[%d/%d] %s — DONE -> %s  (avg %.0fs/img, ~%.1fh for the rest)",
                     i, len(pending), name, url, rate, rate * (len(pending) - i) / 3600)
        elif img is not None:
            # QC rejected all attempts but we HAVE a render: upload it under
            # its REAL name (there is no approved asset to shadow) and tag the
            # row status=2. Approval is then just a status flip — no file
            # renaming; rejection flips back to 0 and a rerun overwrites the key.
            try:
                url = save_both_sizes(img, name)
            except Exception as e:
                url = ""
                log.warning("  could not store %s: %s", name, e)
            mark_wrong_generation(name, image_url=url, reason=reason)
            review += 1
            log.warning("[%d/%d] %s — QC failed %d attempts -> status=2 for review "
                        "(%s) reason: %s", i, len(pending), name, MAX_QC_ATTEMPTS,
                        url or "no upload", reason)
        else:
            # nothing rendered at all — leave status=0 so a rerun retries
            failed += 1
            log.warning("[%d/%d] %s — no render produced (%s); left pending",
                        i, len(pending), name, reason)

    log.info("Worker finished: %d approved+uploaded, %d sent to manual review "
             "(status=2), %d left pending.", ok, review, failed)


if __name__ == "__main__":
    main()
