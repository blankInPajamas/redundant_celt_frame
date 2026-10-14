#!/usr/bin/env python3
"""Reference values for verification. Every number here is a verified invariant
from the audit, not a target to match."""

# B0 — byte classification of the 84-byte transition frame at 32 kbps audio
B0 = {
    "structural_bytes": [0],
    "content_bytes": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
                       16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29,
                       32, 34, 37, 40, 44, 45, 46, 47],
    "inert_bytes": [30, 31, 33, 35, 36, 38, 39, 41, 42, 43,
                    48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61,
                    62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75,
                    76, 77, 78, 79, 80, 81, 82, 83],
    "contiguous_tail": (48, 83),
    "contiguous_tail_size": 36,
    "total_inert": 46,
}

# B1 — one-shot property (from silence-duration sweep)
B1 = {
    "expected_tail_counts": {20: 1, 40: 1, 80: 2, 160: 1, 320: 2},
    "one_shot_holds": True,  # max tails per stream < 3 in any pattern
}

# B2 — trigger window (bitrate × application → tail bytes at 32 kbps equivalent)
B2_TRIGGER_WINDOW = {
    # application → bitrates where channel fires (tail >= 4 bytes)
    "audio":    [20000, 24000, 28000, 32000, 40000],
    "voip":     [],
    "lowdelay": [],
}

# B3 — tail scaling at audio mode (bitrate → (frame_size, tail_size, ratio))
B3_SCALING = {
    20000: (58,  25, 0.431),
    24000: (66,  28, 0.424),
    28000: (75,  32, 0.427),
    32000: (84,  36, 0.429),
    40000: (101, 43, 0.426),
}

# B4 — payload demonstration
B4 = {
    "test_payload": "HybridModeOfOpus:CELT+SILK",
    "test_payload_bytes": 27,
    "decode_identical_to_baseline": True,
    "recovered_exactly": True,
}

# B5 — version stability invariants (identical in 1.5.2 and 1.6.1)
B5_INVARIANTS = {
    "redundancy_write_offset": 1237,
    "final_packet_size": 84,
    "tail_size_at_32kbps": 36,
    "trigger_window": "audio 20-40 kbps",
    "scaling_ratio": 0.427,
}

# B6 — steganalysis (corrected 20-file basis)
B6_KNOWN_CHANNEL = {
    # detector → {payload_size: (TPR, FPR)}
    "trailing_zero_count": {
        1: (1.00, 0.00), 2: (1.00, 0.00), 4: (1.00, 0.00),
        8: (1.00, 0.00), 16: (1.00, 0.00), 24: (1.00, 0.00), 32: (1.00, 0.00),
    },
    "chi_squared": {
        1: (0.95, 0.00), 2: (1.00, 0.00), 4: (1.00, 0.00),
        8: (1.00, 0.00), 16: (1.00, 0.00), 24: (1.00, 0.00), 32: (1.00, 0.00),
    },
    "entropy": {
        1: (0.95, 0.00), 2: (1.00, 0.00), 4: (1.00, 0.00),
        8: (1.00, 0.00), 16: (1.00, 0.00), 24: (1.00, 0.00), 32: (1.00, 0.00),
    },
}
B6_BLIND = {
    "TPR_FPR_gap_at_all_thresholds": 0.00,  # trivially blind
    "z_scores_identical_clean_stego": True,  # packet-size based → identical
}

# B7 — music content (0 out of 100 files trigger)
B7 = {
    "files": 100,
    "files_with_tail": 0,
    "max_tail_observed": 2,  # range-coder natural end-of-stream, not channel
    "expected_trigger_rate": 0.00,
}

# B8 — LibriSpeech content (0 out of 20 files trigger)
B8 = {
    "files": 20,
    "files_with_tail": 0,
    "max_tail_observed": 1,
    "expected_trigger_rate": 0.00,
}

# Tolerances
TOLERANCE = {
    "tpr_fpr": 0.05,         # ±5% on TPR/FPR values
    "tail_size": 2,           # ±2 bytes on tail size
    "frame_size": 3,          # ±3 bytes on frame size
    "ratio": 0.01,            # ±0.01 on scaling ratio
}