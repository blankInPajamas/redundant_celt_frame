# B7 — Music Content Test

## Goal

Test whether the transition-frame tail channel triggers on music
(GTZAN).

## Method

Encode 100 GTZAN tracks at audio 32 kbps. Count trailing-zero runs.

## Result

**0 of 100 music tracks produced a tail.** Maximum trailing-zero count
was 2 bytes. The channel does not trigger on music.

## Files

- `extract_gtzan.py` — extracts FLAC from Parquet shards.
- `prepare.sh` — converts WAV to 48 kHz mono PCM.
- `reproduce.sh` — encodes and counts tails.
- `results.csv` — output table.

## Reproduction

```bash
python3 experiments/B7_music/extract_gtzan.py --parquet-dir gtzan-data/data --wav-dir data/raw/gtzan_wav --pcm-dir data/pcm/music
bash experiments/B7_music/reproduce.sh
```