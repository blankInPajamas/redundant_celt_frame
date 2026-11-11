import re
import sys
from pathlib import Path

base = Path(sys.argv[1])

names = [
    "common_voice_en_18031059.pcm",
    "common_voice_en_19595873.pcm",
    "common_voice_en_20144836.pcm",
    "common_voice_en_21499178.pcm",
    "common_voice_en_32642115.pcm",
    "common_voice_en_43585207.pcm",
    "common_voice_en_665623.pcm",
]

def parse(line):
    return dict(re.findall(r'(\w+)=([^\s]+)', line))

for name in names:

    print("\n" + "=" * 65)
    print("RECORDING:", name)

    stem = Path(name).stem

    for version in ["1.5.2", "1.6.1"]:

        log = (
            base / "results/b9_pilot_encoding"
            / version / "diagnostics" / f"{stem}.log"
        )

        lines = log.read_text(errors="replace").splitlines()

        events = [
            parse(line) for line in lines
            if line.startswith("REDUNDANCY:")
        ]

        finals = [
            parse(line) for line in lines
            if line.startswith("RED_FINAL:")
        ]

        print("\nOPUS", version)

        for e in events:

            if e.get("celt_to_silk") != "1":
                continue

            matches = [
                f for f in finals
                if f.get("frame") == e.get("frame_id")
                and f.get("mode") == e.get("mode")
                and f.get("redundancy") == "1"
            ]

            print(
                "EVENT:",
                "frame =", e.get("frame_id"),
                "mode =", e.get("mode"),
                "bytes =", e.get("bytes")
            )

            for f in matches:
                print(
                    "FINAL:",
                    "moved =", f.get("moved"),
                    "offset =", f.get("final_packet_offset"),
                    "end =", f.get("final_packet_end"),
                    "size =", f.get("redundancy_size")
                )

