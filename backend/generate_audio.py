#!/usr/bin/env python3
"""
Audio production worker — renders pending audio_assets rows (status=0) with
Google Cloud Text-to-Speech and uploads MP3s to S3.

THE VOICE (locked by content review — one voice forever, per the dedupe
design): en-US-Neural2-F, pitch +5 semitones, speaking rate 0.8 — the
cheerful, slow, clear "bird mascot" voice.

    pick one pending dialogue -> synthesize -> upload audio/{audio_code}
    -> mark_audio_generated (status 0 -> 1, URL stored)

    python generate_audio.py --limit 20     # smoke test
    python generate_audio.py                # work the whole queue
    python generate_audio.py --dry-run
"""
import argparse
import logging
import os
import time

import boto3
from google.cloud import texttospeech

from app.core.db import get_client, mark_audio_generated

log = logging.getLogger("audworker")

VOICE_NAME = "en-US-Neural2-F"
PITCH = 5.0
RATE = 0.8
AUDIO_PREFIX = "audio/"            # inside the image bucket; URL stored per row
THROTTLE_S = 0.25                  # TTS quotas are generous; tiny pacing only

_tts = None
_s3 = None


def tts():
    global _tts
    if _tts is None:
        _tts = texttospeech.TextToSpeechClient()
    return _tts


def s3():
    global _s3
    if _s3 is None:
        _s3 = boto3.session.Session(
            region_name=os.getenv("AWS_REGION", "ap-south-1")).client("s3")
    return _s3


def synthesize(text: str) -> bytes:
    resp = tts().synthesize_speech(
        input=texttospeech.SynthesisInput(text=text),
        voice=texttospeech.VoiceSelectionParams(language_code="en-US", name=VOICE_NAME),
        audio_config=texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=RATE, pitch=PITCH),
    )
    return resp.audio_content


def fetch_pending(limit=None):
    c = get_client()
    out, page = [], 0
    while True:
        batch = (c.table("audio_assets").select("dialogue_text,audio_code")
                 .eq("status", 0).order("created_at")
                 .range(page * 1000, page * 1000 + 999).execute().data)
        out += batch
        if len(batch) < 1000:
            break
        page += 1
    return out[:limit] if limit else out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)-9s %(levelname)s  %(message)s")

    bucket = os.getenv("S3_IMAGE_BUCKET", "zuno-auto-images")
    pending = fetch_pending(args.limit)
    log.info("Audio queue: %d pending (voice %s, pitch +%s, rate %s)",
             len(pending), VOICE_NAME, PITCH, RATE)
    if args.dry_run:
        for a in pending[:20]:
            log.info("  WOULD SYNTHESIZE: %-32s %r", a["audio_code"], a["dialogue_text"][:60])
        return

    ok = failed = 0
    t0 = time.time()
    for i, row in enumerate(pending, 1):
        code, text = row["audio_code"], row["dialogue_text"]
        try:
            time.sleep(THROTTLE_S)
            audio = synthesize(text)
            key = f"{AUDIO_PREFIX}{code}"
            s3().put_object(Bucket=bucket, Key=key, Body=audio, ContentType="audio/mpeg")
            url = f"https://{bucket}.s3.{os.getenv('AWS_REGION', 'ap-south-1')}.amazonaws.com/{key}"
            mark_audio_generated(text, audio_url=url)
            ok += 1
            if i % 100 == 0 or i == len(pending):
                rate = (time.time() - t0) / max(i, 1)
                log.info("[%d/%d] %s  (%.1fs/line, ~%.1fh left)",
                         i, len(pending), code, rate, rate * (len(pending) - i) / 3600)
        except Exception as e:
            failed += 1
            log.warning("[%d/%d] %s FAILED (%s) — left pending", i, len(pending), code,
                        str(e)[:150])
            if failed > 20 and failed > ok:
                log.error("Too many consecutive failures — stopping so a human can look.")
                break

    log.info("Audio worker finished: %d synthesized+uploaded, %d left pending.", ok, failed)


if __name__ == "__main__":
    main()
