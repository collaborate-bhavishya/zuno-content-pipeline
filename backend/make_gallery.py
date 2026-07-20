#!/usr/bin/env python3
"""Build the static review gallery of all generated images and upload it to
the image bucket (same origin as the images, so it renders anywhere).

    https://zuno-auto-images.s3.ap-south-1.amazonaws.com/review_gallery.html
"""
import os
from datetime import datetime, timezone

from app.core.db import get_client


def main():
    c = get_client()
    rows, page = [], 0
    while True:
        b = (c.table("image_assets")
             .select("image_name,image_url,status,qc_reason,image_detail")
             .in_("status", [1, 2]).order("status", desc=True).order("image_name")
             .range(page * 1000, page * 1000 + 999).execute().data)
        rows += b
        if len(b) < 1000:
            break
        page += 1
    pending = (c.table("image_assets").select("*", count="exact", head=True)
               .eq("status", 0).execute().count)

    cards = []
    for r in rows:
        name = r["image_name"]
        url = r.get("image_url") or ""
        if not url.startswith("http"):
            continue
        low = url.replace(f"/{name}", f"/lowres/{name}")
        badge = ("<span style='background:#fef08a;color:#854d0e;padding:2px 8px;"
                 "border-radius:4px;font-size:11px;font-weight:700'>REVIEW</span>"
                 if r["status"] == 2 else
                 "<span style='background:#dcfce7;color:#166534;padding:2px 8px;"
                 "border-radius:4px;font-size:11px;font-weight:700'>APPROVED</span>")
        reason = (f"<div style='font-size:11px;color:#b91c1c;margin-top:4px'>"
                  f"{r.get('qc_reason') or ''}</div>" if r["status"] == 2 else "")
        detail = f"<div style='font-size:11px;color:#6b7280'>{r.get('image_detail') or ''}</div>"
        cards.append(f"""
        <div style="border:1px solid #e5e7eb;border-radius:10px;padding:10px;background:#fff">
          <a href="{url}" target="_blank"><img src="{low}" loading="lazy"
             style="width:100%;aspect-ratio:1;object-fit:contain;background:#fafafa;border-radius:6px"></a>
          <div style="font-family:monospace;font-size:12px;font-weight:600;margin-top:6px">{name} {badge}</div>
          {detail}{reason}
        </div>""")

    n1 = sum(1 for r in rows if r["status"] == 1)
    n2 = sum(1 for r in rows if r["status"] == 2)
    total = n1 + n2 + pending
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Zuno image review — {n1 + n2}/{total}</title>
<meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="font-family:-apple-system,sans-serif;background:#f6f5f2;margin:0;padding:24px">
<h2 style="margin:0 0 4px">Zuno image review</h2>
<p style="color:#6b7280;margin:0 0 6px">
  <b>{n1}</b> approved &nbsp;·&nbsp; <b>{n2}</b> awaiting review (yellow)
  &nbsp;·&nbsp; <b>{pending}</b> still in the generation queue
  &nbsp;·&nbsp; progress {n1 + n2}/{total} ({(n1 + n2) * 100 // max(total, 1)}%)</p>
<p style="color:#9ca3af;font-size:12px;margin:0 0 20px">refreshed {stamp} —
  updated automatically after every 250-image batch. Click any image for full-size 1024.</p>
<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:14px">
{''.join(cards)}
</div></body></html>"""

    import boto3
    s3 = boto3.session.Session(region_name=os.getenv("AWS_REGION", "ap-south-1")).client("s3")
    bucket = os.getenv("S3_IMAGE_BUCKET", "zuno-auto-images")
    s3.put_object(Bucket=bucket, Key="review_gallery.html", Body=html.encode(),
                  ContentType="text/html")
    print(f"gallery refreshed: {n1} approved, {n2} review, {pending} pending "
          f"-> https://{bucket}.s3.ap-south-1.amazonaws.com/review_gallery.html")


if __name__ == "__main__":
    main()
