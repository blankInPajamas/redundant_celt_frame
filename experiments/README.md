# Experiments — Reproducible Record

This directory records every experiment conducted for the paper
"Reserved-Space Leakage in Opus Hybrid Frames". Each subdirectory contains
a self-contained record:

- `README.md` — what the experiment is, why it exists, what it found
- `reproduce.sh` — exact script to regenerate the results
- `analyze.py` — analysis applied to the raw output
- `results.csv` — observed numbers (small, safe to commit)
- `notes.md` — interpretation, surprises, follow-ups

## Inventory

| ID | Title | Status | Key result |
|----|-------|--------|------------|
| B0 | Decisive experiment: locate and modify the redundant frame region | ✅ | Tail located at bytes 48–83 of transition frame |
| B1 | Multi-transition test: can we force multiple tails per stream? | ✅ | No — one-shot per stream |
| B2 | One-shot sweep: application × bitrate grid | ✅ | Channel exclusive to audio 20–40 kbps |
| B3 | Tail scaling: how does tail size depend on bitrate? | ✅ | Linear, ~43% of frame |
| B4 | Payload embedding: can we embed and extract a message? | ⏳ | Partial — 28 bits in one frame |
| B5 | Version comparison: is the channel stable across libopus? | ⏳ | Not started |

## How to re-run everything

```bash
bash scripts/experiments/run_all.sh
```

This regenerates every `results.csv` from scratch. It assumes:
- `opus/` is a patched libopus tree at commit 503d81b1
- `scripts/encode_raw` and `scripts/decode_raw` are built against it
- `data/pcm/spontaneous-speech-en-*.pcm` are the 20 converted inputs
