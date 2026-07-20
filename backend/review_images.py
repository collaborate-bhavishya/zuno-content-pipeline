#!/usr/bin/env python3
"""
Manual review of QC-rejected images (image_assets status=2).

The worker already uploaded each rejected render under its REAL filename, so:
  approve = flip status to 1 (the file is already live at image_url)
  reject  = flip status to 0 (+ clear url/reason); the next worker run
            regenerates and overwrites the same S3 key.

    python review_images.py --list
    python review_images.py --approve small_doll.png,red_kite.png
    python review_images.py --reject small_doll.png
    python review_images.py --approve-all          # accept everything pending review
"""
import argparse

from app.core.db import get_client


def pending_review():
    c = get_client()
    out, page = [], 0
    while True:
        batch = (c.table("image_assets").select("image_name,image_url,qc_reason")
                 .eq("status", 2).order("created_at")
                 .range(page * 1000, page * 1000 + 999).execute().data)
        out += batch
        if len(batch) < 1000:
            break
        page += 1
    return out


def approve(names):
    c = get_client()
    for n in names:
        c.table("image_assets").update({"status": 1, "qc_reason": None}
                                       ).eq("image_name", n).eq("status", 2).execute()
        print(f"  approved: {n}")


def reject(names):
    c = get_client()
    for n in names:
        c.table("image_assets").update({"status": 0, "image_url": "", "qc_reason": None}
                                       ).eq("image_name", n).eq("status", 2).execute()
        print(f"  rejected -> will regenerate: {n}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--approve", help="comma-separated filenames")
    ap.add_argument("--reject", help="comma-separated filenames")
    ap.add_argument("--approve-all", action="store_true")
    args = ap.parse_args()

    rows = pending_review()
    if args.list or not any([args.approve, args.reject, args.approve_all]):
        print(f"{len(rows)} image(s) awaiting review:")
        for r in rows:
            print(f"  {r['image_name']:<30} {r.get('qc_reason') or ''}")
            print(f"    {r.get('image_url') or '(no url)'}")
        return
    if args.approve:
        approve([n.strip() for n in args.approve.split(",") if n.strip()])
    if args.approve_all:
        approve([r["image_name"] for r in rows])
    if args.reject:
        reject([n.strip() for n in args.reject.split(",") if n.strip()])


if __name__ == "__main__":
    main()
