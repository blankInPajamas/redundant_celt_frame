# B6 — Steganalysis of the Opus Transition-Frame Tail Channel

## Overview

This directory characterizes the detectability of the covert channel
identified in experiments B0–B5. The channel consists of 46 inert bytes
in the transition frame of Opus hybrid-mode packets (audio mode, 20–40
kbps, CELT-only → hybrid transition). This experiment asks: **can a
defender detect that the transition frame has been modified?**

We implement four detectors, evaluate them against clean and stego
streams, and characterize the detection frontier.

## Contents

| File | Purpose |
|------|---------|
| `detectors.py` | Four detector implementations |
| `sanity_check.sh` | Quick end-to-end verification on one stream |
| `reproduce_s2.sh` | Generates clean + stego streams for accuracy study |
| `analyze_s2.py` | Computes TPR/FPR per detector per payload size |
| `reproduce_s3.sh` | Runs the blind detector across thresholds |
| `analyze_s3.py` | Computes ROC-like table for the blind detector |
| `analyze_s4.py` | Computes minimum detectable payload per detector |
| `detection_accuracy.csv` | S2 output: 609 rows |
| `blind_detection.csv` | S3 output: z-scores for clean and stego streams |

## Detectors

Four detectors model four defender capabilities. The first three assume
the defender knows the trigger condition (audio mode, 20–40 kbps,
CELT-only → hybrid transition) and can identify the transition frame as
the first frame with a large trailing-zero run. The fourth does not
assume trigger knowledge.

### 1. `trailing_zero_count`

Counts trailing zero bytes in the transition frame.

- **Clean stream**: exactly 36 trailing zeros at 32 kbps (deterministic).
- **Stego stream**: 36 − N trailing zeros for an N-byte payload.
- **Decision**: flag as stego if count < 35.
- **Threshold rationale**: any non-zero payload reduces the count.

### 2. `chi_squared`

Counts non-zero bytes in the last 40 bytes of the transition frame.

- **Clean stream**: 4 non-zero bytes (range-coder end-of-stream markers).
- **Stego stream**: 4 + N non-zero bytes for an N-byte payload.
- **Decision**: flag as stego if count > 5.

### 3. `entropy`

Shannon entropy over the same 40-byte window.

- **Clean stream**: H ≈ 0.67 (from the 4 non-zero bytes).
- **Stego stream**: H > 0.8 starting at 1-byte payloads.
- **Decision**: flag as stego if H > 0.8.

### 4. `blind_outlier`

Computes a z-score from the packet-size distribution of the stream.

- Does not use trigger knowledge.
- Flags streams whose largest packet exceeds the mean by more than σ
  standard deviations.
- **Decision**: flag as stego if z > σ.

## Experimental Design

### S2 — Detection Accuracy Study

- 19 clean streams (Mozilla Spontaneous Speech, audio 32 kbps).
- 7 payload sizes: 1, 2, 4, 8, 16, 24, 32 bytes.
- 19 stego streams per payload size (133 total).
- All four detectors run on every stream.
- Total: 19 + 133 = 152 streams × 4 detectors = 608 evaluations.

### S3 — Blind Detection

- Uses the same 19 clean + 133 stego streams.
- Sweeps the blind detector's σ threshold from 1.0 to 10.0.
- Computes TPR and FPR at each threshold.
- Identifies whether any threshold achieves separation (TPR − FPR > 0).

### S4 — Detection Thresholds

- Reuses S2 data.
- For each detector, computes the smallest payload size at which
  TPR ≥ 0.90.

## Results

### Detection Accuracy (S2)

TPR by payload size for each known-channel detector. FPR is 0.00 for
all three detectors at all payload sizes.

| Detector | 0 B | 1 B | 2 B | 4 B | 8 B | 16 B | 24 B | 32 B |
|----------|-----|-----|-----|-----|-----|------|------|------|
| `trailing_zero_count` | 0.00 | **1.00** | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| `chi_squared`         | 0.00 | **0.95** | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| `entropy`             | 0.00 | **0.95** | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| `blind_outlier`       | 0.00 | 0.26 | 0.26 | 0.26 | 0.26 | 0.26 | 0.26 | 0.26 |

**Headline:** A 1-byte payload is detected with ≥95% TPR by all
known-channel detectors. At 2 bytes and above, detection is perfect
(100% TPR, 0% FPR).

### Blind Detection (S3)

TPR and FPR at varying σ. The gap column shows that the blind detector
provides zero separation at every threshold.

| σ | TPR | FPR | TPR − FPR |
|---|-----|-----|-----------|
| 1.0 | 1.00 | 1.00 | 0.00 |
| 2.0 | 1.00 | 1.00 | 0.00 |
| 3.0 | 1.00 | 1.00 | 0.00 |
| 5.0 | 1.00 | 1.00 | 0.00 |
| 8.0 | 1.00 | 1.00 | 0.00 |
| 10.0 | 0.95 | 0.95 | 0.00 |

**Headline:** Blind detection is chance-level. Without trigger
knowledge, the defender cannot distinguish clean from stego streams
using packet-size statistics alone.

### Detection Thresholds (S4)

The smallest payload size at which each detector achieves TPR ≥ 0.90.

| Detector | Threshold (bytes) | TPR at threshold |
|----------|-------------------|------------------|
| `trailing_zero_count` | 1 | 1.00 |
| `chi_squared`         | 1 | 0.95 |
| `entropy`             | 1 | 0.95 |
| `blind_outlier`       | >32 | — |

**Headline:** All three known-channel detectors require only a
single-byte payload to exceed 90% TPR. The blind detector never reaches
this threshold at any tested payload size.

## Interpretation

The steganalysis results characterize a sharp asymmetry in the
channel's detectability profile.

**With trigger knowledge**: the channel is trivially detectable.
`trailing_zero_count` achieves 100% TPR at 1 byte with 0% FPR. The
channel is defeated by a one-line check on the transition frame's tail
length.

**Without trigger knowledge**: the channel is effectively undetectable.
The blind detector's TPR and FPR are identical across the entire σ
range, meaning no threshold separates clean from stego. The packet-size
distribution is identical in both cases because steganographic
modification changes packet contents, not packet sizes.

**Practical security implication**: The channel occupies a defensive
blind spot. A defender unaware of the trigger condition will not detect
the channel. A defender aware of the mechanism can eliminate it
entirely by validating the transition frame's trailing-zero count. This
is a common pattern in covert channels: invisible to generic
steganalysis, trivially defeated by specialized countermeasures.

## Secondary Observation

While the blind detector cannot separate clean from stego streams at the
population level, we observe a small but consistent shift in the
z-score distribution:

- **Clean streams**: mean z = 23.70, median z = 22.95
- **Stego streams**: mean z = 19.71, median z = 19.90

Both distributions overlap heavily, and both contain values well above
any reasonable detection threshold (σ ∈ {1, 2, 3, 5}). The shift is
not usable as a standalone detector. However, it suggests that a
defender with a prior distribution over packet-size statistics could
build a Bayesian detector with slightly better than chance accuracy.
We leave such refinements to future work.

## Reproducing

From the project root:

```bash
# Sanity check on one stream
bash experiments/B6_steganalysis/sanity_check.sh

# Run S2 (detection accuracy) — takes ~15 minutes
bash experiments/B6_steganalysis/reproduce_s2.sh
python3 experiments/B6_steganalysis/analyze_s2.py

# Run S3 (blind detection ROC)
bash experiments/B6_steganalysis/reproduce_s3.sh
python3 experiments/B6_steganalysis/analyze_s3.py

# Run S4 (detection thresholds) — reuses S2 data
python3 experiments/B6_steganalysis/analyze_s4.py