#!/usr/bin/env python3
"""
Rate-limit probe. Fires tiny back-to-back LLM calls against the SAME model the
pipeline uses (CONFIG judge/generator = gemini-2.5-flash on Vertex) to find the
empirical ceiling before a 429, so we can design call spacing that never trips it.

Reports, per call: seconds since start, ok/429, and how many calls succeeded in
the trailing 60s window (that trailing count at the moment of the first 429 IS
the effective per-minute limit).

    python probe_rate.py            # burst 40 calls, no spacing
    python probe_rate.py --n 25 --gap 6   # 25 calls, 6s apart (verify a spacing holds)
"""
import argparse
import time
from collections import deque

from app.core.llm import get_judge


def is_429(e: Exception) -> bool:
    s = str(e).lower()
    return "429" in s or "resource_exhausted" in s or "quota" in s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--gap", type=float, default=0.0, help="seconds between calls")
    args = ap.parse_args()

    llm = get_judge()
    msg = [("user", "Reply with the single word: ok")]
    t0 = time.time()
    ok_times = deque()          # timestamps of successful calls (for 60s window)
    first_429 = None
    ok = fail = 0

    print(f"Firing {args.n} calls, gap={args.gap}s, model=judge (gemini-2.5-flash)\n")
    print(f"{'call':>4} {'t(s)':>7} {'result':>8} {'ok/60s':>7}")
    for i in range(1, args.n + 1):
        t = time.time()
        try:
            llm.invoke(msg)
            ok += 1
            ok_times.append(time.time())
            while ok_times and ok_times[0] < time.time() - 60:
                ok_times.popleft()
            print(f"{i:>4} {t - t0:>7.1f} {'ok':>8} {len(ok_times):>7}")
        except Exception as e:
            fail += 1
            tag = "429" if is_429(e) else type(e).__name__
            if is_429(e) and first_429 is None:
                first_429 = (i, t - t0, len(ok_times))
            print(f"{i:>4} {t - t0:>7.1f} {tag:>8} {len(ok_times):>7}"
                  + ("   <-- FIRST 429" if (is_429(e) and first_429 and first_429[0] == i) else ""))
        if args.gap:
            time.sleep(args.gap)

    print(f"\n{ok} ok, {fail} failed.")
    if first_429:
        i, ts, window = first_429
        print(f"First 429 on call #{i} at {ts:.1f}s — {window} calls had succeeded "
              f"in the trailing 60s. => effective limit ~{window} req/min.")
        print(f"   Safe spacing to stay under it: ~{60.0 / max(window, 1):.1f}s between calls "
              f"(add margin).")
    else:
        print("No 429 hit — the ceiling is above this burst. Raise --n to push harder.")


if __name__ == "__main__":
    main()
