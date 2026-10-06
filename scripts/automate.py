import re
import sys

logfile = sys.argv[1] if len(sys.argv) > 1 else "logs/encode_test01_audio32k.log"
with open(logfile) as f:
    lines = f.readlines()

final_by_id = {}
redundancy = []

# NOTE: requires patch 0002-fix-frame-correlation.patch to be applied —
# it adds a `frame_id` shared between the REDUNDANCY and FINAL packet log
# lines. Without that patch, REDUNDANCY's `frame=` field is a count of
# redundancy EVENTS, not a real frame index, and cannot be safely joined
# against FINAL packet lines by position (see README changelog / commit
# notes for why the old version of this script was unreliable beyond a
# single redundancy event per file).

for line in lines:
    m = re.search(r"FINAL packet: frame_id=(\d+) ret=(\d+), mode=(\d+)", line)
    if m:
        frame_id = int(m.group(1))
        final_by_id[frame_id] = (int(m.group(2)), int(m.group(3)))
        continue
    m = re.search(
        r"REDUNDANCY: event=(\d+) frame_id=(\d+) mode=(\d+) celt_to_silk=(\d+) bytes=(\d+)",
        line,
    )
    if m:
        redundancy.append({
            "event": int(m.group(1)),
            "frame_id": int(m.group(2)),
            "mode": int(m.group(3)),
            "celt_to_silk": int(m.group(4)),
            "bytes": int(m.group(5)),
        })

if not redundancy:
    print("No REDUNDANCY events found in this log.")
    sys.exit(0)

survived_count = 0
for r in redundancy:
    fid = r["frame_id"]
    if fid in final_by_id:
        final_size, mode = final_by_id[fid]
        survived = final_size >= r["bytes"]
        survived_count += survived
        print(f"Event {r['event']} (frame_id={fid}): redundancy_bytes={r['bytes']}, "
              f"final_packet={final_size}, survived={survived}, mode={mode}")
    else:
        print(f"Event {r['event']} (frame_id={fid}): no matching FINAL packet log "
              f"— check that the log wasn't truncated mid-frame")

print(f"\n{survived_count}/{len(redundancy)} redundancy events survived packetization.")
