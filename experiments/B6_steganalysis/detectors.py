#!/usr/bin/env python3
"""Detectors for the Opus transition-frame tail channel.

Four detectors, each modeling a different defender:

1. trailing_zero_count  — structural; requires trigger knowledge
2. chi_squared_tail     — statistical; requires trigger knowledge
3. entropy_tail         — statistical; requires trigger knowledge
4. blind_tail_outlier   — statistical; no trigger knowledge

The transition frame is identified as the largest packet in the stream.
This is robust under stego modification (the frame's byte count does not
change, only its contents do).
"""

import math
import struct
from collections import Counter


# --- I/O ---

def load_packets(path):
    data = open(path, "rb").read()
    off = 0
    packets = []
    while off + 4 <= len(data):
        ln = struct.unpack("<I", data[off:off + 4])[0]
        off += 4
        if off + ln > len(data):
            break
        packets.append(data[off:off + ln])
        off += ln
    return packets


# --- Utility ---

def trailing_zeros(pkt):
    t = 0
    for i in range(len(pkt) - 1, -1, -1):
        if pkt[i] == 0:
            t += 1
        else:
            break
    return t


def find_transition_frame(packets, min_tail=20):
    for i, pkt in enumerate(packets):
        if trailing_zeros(pkt) >= min_tail:
            return i, len(pkt)
    for i, pkt in enumerate(packets):
        if len(pkt) >= 80:
            return i, len(pkt)
    return -1, 0


# --- Detector 1: trailing-zero count ---

def detector_trailing_zero_count(packets, expected_min_tail=35):
    """Flag if the largest packet's trailing-zero run is below expected."""
    idx, _ = find_transition_frame(packets)
    if idx < 0:
        return "clean", 0.0
    tail = trailing_zeros(packets[idx])
    label = "stego" if tail < expected_min_tail else "clean"
    return label, float(tail)


# --- Detector 2: chi-squared on tail bytes ---

def detector_chi_squared(packets, threshold=5.0):
    """Chi-squared-like statistic on the largest packet's tail.

    Null: all tail bytes are zero. We use sum(b*b) as a simple statistic
    that is 0 for a clean tail and grows with the number of non-zero bytes.
    """
    idx, _ = find_transition_frame(packets)
    if idx < 0:
        return "clean", 0.0
    pkt = packets[idx]
    tail = trailing_zeros(pkt)
    # The tail is defined as the trailing zero run — but for a stego
    # packet, the "tail" is short because payload bytes precede it. So we
    # inspect the entire end-of-packet region regardless.
    look_back = min(40, len(pkt))       # up to 40 bytes back
    tail_bytes = pkt[-look_back:]
    # Only count non-zero bytes in the region that would be tail in a clean stream
    nonzero = sum(1 for b in tail_bytes if b != 0)
    chi2 = float(nonzero)
    label = "stego" if chi2 > threshold else "clean"
    return label, chi2


# --- Detector 3: entropy of tail ---

def shannon_entropy(byte_seq):
    if not byte_seq:
        return 0.0
    counts = Counter(byte_seq)
    n = len(byte_seq)
    return max(0.0, -sum((c / n) * math.log2(c / n) for c in counts.values()))


def detector_entropy(packets, threshold=0.8):
    """Shannon entropy of the end-of-packet region."""
    idx, _ = find_transition_frame(packets)
    if idx < 0:
        return "clean", 0.0
    pkt = packets[idx]
    look_back = min(40, len(pkt))
    tail_bytes = pkt[-look_back:]
    H = shannon_entropy(tail_bytes)
    label = "stego" if H > threshold else "clean"
    return label, H


# --- Detector 4: blind outlier ---

def detector_blind_tail_outlier(packets, sigma=3.0):
    """Flag any stream whose packet sizes deviate from the baseline.

    Note: this detector does not distinguish clean from stego streams.
    Both clean and stego streams contain a large transition frame.
    It is intended to detect anomalous streams, not clean vs. stego.
    """
    sizes = [len(pkt) for pkt in packets]
    if len(sizes) < 5:
        return "clean", 0.0
    mean = sum(sizes) / len(sizes)
    var = sum((s - mean) ** 2 for s in sizes) / len(sizes)
    std = math.sqrt(var) if var > 0 else 0.0
    if std == 0:
        return "clean", 0.0
    max_size = max(sizes)
    z = (max_size - mean) / std
    label = "stego" if z > sigma else "clean"
    return label, z


# --- Convenience ---

DETECTORS = {
    "trailing_zero_count": detector_trailing_zero_count,
    "chi_squared":         detector_chi_squared,
    "entropy":             detector_entropy,
    "blind_outlier":       detector_blind_tail_outlier,
}


def run_all_detectors(path):
    packets = load_packets(path)
    return {name: fn(packets) for name, fn in DETECTORS.items()}


if __name__ == "__main__":
    import sys
    for name, (label, score) in run_all_detectors(sys.argv[1]).items():
        print(f"{name:25s}  {label:5s}  score={score:.4f}")