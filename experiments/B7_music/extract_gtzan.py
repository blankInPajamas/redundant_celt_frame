#!/usr/bin/env python3
"""Extract audio from GTZAN parquet files to 48 kHz mono PCM.

GTZAN from Hugging Face stores audio as encoded WAV bytes inside Parquet.
This script decodes each row's audio, writes a WAV, then converts to
48 kHz mono PCM via ffmpeg.
"""
import argparse
import io
import subprocess
from pathlib import Path

import pyarrow.parquet as pq
import soundfile as sf


def decode_audio(entry):
    """Decode an HF Audio entry to (numpy_array, sample_rate)."""
    # Case 1: dict with 'bytes' and 'path'
    if isinstance(entry, dict) and "bytes" in entry and entry["bytes"] is not None:
        data, sr = sf.read(io.BytesIO(entry["bytes"]))
        return data, sr
    # Case 2: dict with 'array' and 'sampling_rate' (already decoded)
    if isinstance(entry, dict) and "array" in entry:
        import numpy as np
        return np.asarray(entry["array"], dtype="float32"), int(entry.get("sampling_rate", 22050))
    # Case 3: raw bytes
    if isinstance(entry, (bytes, bytearray)):
        data, sr = sf.read(io.BytesIO(entry))
        return data, sr
    raise ValueError(f"unknown audio entry structure: {type(entry)} {list(entry.keys()) if isinstance(entry, dict) else ''}")


def extract_parquet(parquet_path: Path, wav_dir: Path, limit: int = 0):
    table = pq.read_table(str(parquet_path))
    print(f"  rows: {table.num_rows}")
    print(f"  columns: {table.column_names}")

    if "audio" not in table.column_names:
        raise RuntimeError(f"no 'audio' column in {table.column_names}")

    audio_col = table["audio"].to_pylist()
    if "file" in table.column_names:
        names = table["file"].to_pylist()
    else:
        names = [f"track_{i:05d}" for i in range(len(audio_col))]

    written = 0
    for i, (name, entry) in enumerate(zip(names, audio_col)):
        if limit and written >= limit:
            break
        try:
            array, sr = decode_audio(entry)
        except Exception as e:
            print(f"  skip {name}: {e}")
            continue

        safe = str(name).replace("/", "_").replace("\\", "_")
        if not safe.endswith(".wav"):
            safe += ".wav"

        sf.write(str(wav_dir / safe), array, sr)
        written += 1
    return written


def convert_to_pcm(wav_dir: Path, pcm_dir: Path, limit: int = 0):
    converted = 0
    for wav in sorted(wav_dir.glob("*.wav")):
        if limit and converted >= limit:
            break
        pcm = pcm_dir / (wav.stem + ".pcm")
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav),
             "-ac", "1", "-ar", "48000", "-f", "s16le", str(pcm)],
            check=True,
        )
        converted += 1
    return converted


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet-dir", required=True)
    parser.add_argument("--wav-dir", required=True)
    parser.add_argument("--pcm-dir", required=True)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    parquet_dir = Path(args.parquet_dir)
    wav_dir = Path(args.wav_dir)
    pcm_dir = Path(args.pcm_dir)
    wav_dir.mkdir(parents=True, exist_ok=True)
    pcm_dir.mkdir(parents=True, exist_ok=True)

    shards = sorted(parquet_dir.glob("*.parquet"))
    print(f"Found {len(shards)} parquet shards")

    total = 0
    for shard in shards:
        print(f"\nProcessing {shard.name}")
        remaining = (args.limit - total) if args.limit else 0
        n = extract_parquet(shard, wav_dir, limit=remaining)
        total += n
        print(f"  wrote {n} WAVs (running total: {total})")
        if args.limit and total >= args.limit:
            break

    print(f"\nTotal WAVs: {total}")
    print("Converting to 48 kHz mono PCM...")
    converted = convert_to_pcm(wav_dir, pcm_dir)
    print(f"Converted: {converted}")
    print(f"PCM files: {pcm_dir}")


if __name__ == "__main__":
    main()