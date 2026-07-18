"""One-off verification: planners must check existing DB records before
inserting, and never create duplicate rows. Run inside the backend container."""
from app.core.db import get_client
from app.nodes.graph_nodes import asset_planner_node, audio_planner_node

c = get_client()
TEST_IMG = "zz_dedupe_test.png"
TEST_LINE = "__dedupe_test__ hello little star!"

# pick a real, already-generated image and a real ledger dialogue
img = c.table("image_assets").select("image_name,status").eq("status", 1).limit(1).execute().data[0]
aud = c.table("audio_assets").select("dialogue_text,audio_code").limit(1).execute().data[0]
print(f"existing image: {img['image_name']} (status=1)")
print(f"existing line : {aud['dialogue_text']!r} -> {aud['audio_code']}")

def matrix():
    return [{
        "Playable Code": "AG05T99P01",
        "Concept (bucket / skill)": "test",
        "Image in Question — Name": f"{img['image_name']},{TEST_IMG}",
        "Image in Question — Detail": "x,y",
        "Instruction VO": aud["dialogue_text"],
        "Instruction VO — File": "AG05T99P01Q01_inst.mp3",
        "Audio in Question": TEST_LINE,
        "Audio in Question — File": "AG05T99P01Q01_aud.mp3",
    }]

print("\n--- IMAGES: run 1 ---")
r = asset_planner_node({"raw_question_matrix": matrix(), "milestone_code": "AG05", "theme_code": "T99"})
q = [a["filename"] for a in r["asset_queue"]]
assert img["image_name"] not in q, "existing image must be skipped"
assert TEST_IMG in q, "new image must be queued"
print(f"queue={q}  -> existing skipped, new queued  OK")

print("--- IMAGES: run 2 (repeat) ---")
asset_planner_node({"raw_question_matrix": matrix(), "milestone_code": "AG05", "theme_code": "T99"})
n = len(c.table("image_assets").select("id").eq("image_name", TEST_IMG).execute().data)
assert n == 1, f"expected exactly 1 row for {TEST_IMG}, got {n}"
print(f"rows for {TEST_IMG} after two runs: {n}  (no duplicate)  OK")

print("\n--- AUDIO: run 1 ---")
m = matrix()
r = audio_planner_node({"raw_question_matrix": m, "milestone_code": "AG05", "theme_code": "T99"})
assert m[0]["Instruction VO — File"] == aud["audio_code"], \
    f"existing line must reuse {aud['audio_code']}, got {m[0]['Instruction VO — File']}"
new_regs = {e["dialogue_text"] for e in r["pending_audio"]}
assert TEST_LINE in new_regs and aud["dialogue_text"] not in new_regs
print(f"existing line rewritten to {aud['audio_code']}; only new line registered  OK")

print("--- AUDIO: run 2 (repeat) ---")
m2 = matrix()
r2 = audio_planner_node({"raw_question_matrix": m2, "milestone_code": "AG05", "theme_code": "T99"})
assert m2[0]["Audio in Question — File"] == "AG05T99P01Q01_aud.mp3"  # its first-seen code, from DB now
assert not r2["pending_audio"], f"second run must register nothing, got {r2['pending_audio']}"
n = len(c.table("audio_assets").select("id").eq("dialogue_text", TEST_LINE).execute().data)
assert n == 1, f"expected exactly 1 row for test line, got {n}"
print(f"second run: 0 new registrations, reused from ledger; rows for test line: {n}  OK")

# cleanup
c.table("image_assets").delete().eq("image_name", TEST_IMG).execute()
c.table("audio_assets").delete().eq("dialogue_text", TEST_LINE).execute()
print("\ncleaned up test rows. ALL DEDUPE CHECKS PASS")
