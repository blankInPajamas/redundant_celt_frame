# Redundant CELT Frame Steganography in Opus — Research Log

**Author:** ishu  
**Date started:** 2026-09-29  
**Repository:** /home/ishu/research/redundant_celt_frame  
**Status:** Negative result — redundant CELT frame is not a viable covert channel under standard operating conditions

---

## 1. Research Question

Opus is the de facto standard codec for VoIP and WebRTC, yet steganographic research on Opus has focused almost exclusively on the SILK pulse domain. The CELT transform layer — and specifically the **redundant CELT frame** used for mode transitions — has never been empirically characterized as an embedding space.

This project asks:

> **Can the redundant CELT frame in Opus be used as a covert channel for steganographic communication, and does it survive packetization reliably enough to be viable?**

The redundant frame is a 5 ms CELT-only frame transmitted in-band during mode transitions (SILK↔CELT, SILK↔Hybrid). It operates with an isolated entropy coder state and always starts and ends on byte boundaries — structurally attractive for embedding.

---

## 2. Motivation

- All existing Opus steganography operates in the SILK pulse domain (Ren et al. 2020; Tian et al. 2025).
- The CELT transform domain — PVQ indices, energy envelope, raw bits — remains unexplored.
- The redundant CELT frame appeared to be the lowest-risk entry point because of its isolated entropy state and byte alignment.
- Opus 1.6.1 is the current reference implementation, used in production worldwide.

---

## 3. Project Structure

```text
redundant_celt_frame/
├── opus/                          # libopus 1.6.1-68 source (instrumented)
│   ├── src/opus_encoder.c         # Instrumented with REDUNDANCY and FINAL packet logging
│   ├── celt/celt_encoder.c
│   ├── silk/
│   └── .libs/libopus.so           # Built shared library
├── data/
│   ├── raw/                       # Mozilla Spontaneous Speech MP3 files
│   ├── pcm/                       # Converted raw PCM (48kHz mono s16le)
│   │   ├── spontaneous-speech-en-1.pcm ... en-19.pcm
│   │   ├── silence.pcm
│   │   ├── noise.pcm
│   │   ├── tone.pcm
│   │   ├── transition_test.pcm
│   │   ├── celt_to_silk.pcm
│   │   └── strong_transition.pcm
│   ├── bitstreams/
│   │   ├── encoded/               # Raw packets from encode_raw
│   │   └── modified/              # Modified packets for steg test
│   └── output/                    # Decoded PCM/WAV for comparison
├── scripts/
│   ├── encode_raw.c               # Opus API encoder
│   ├── decode_raw.c               # Opus API decoder
│   ├── encode_raw                 # Compiled binary
│   ├── decode_raw                 # Compiled binary
│   ├── parse_packets.py           # Bitstream packet parser
│   ├── modify_packet.py           # Byte-overwrite harness
│   └── automate.py                # Cross-check redundancy survival
├── logs/                          # Encoder logs
│   ├── encode_test01_audio32k.log
│   ├── encode_test01_audio64k.log
│   ├── encode_test01_voip24k.log
│   ├── encode_celt_to_silk.log
│   ├── encode_noise_speech.log
│   ├── encode_transition.log
│   ├── redundancy_12k.log
│   ├── redundancy_16k.log
│   ├── redundancy_celt_force.log
│   ├── redundancy_celt_to_silk.log
│   ├── redundancy_hybrid.log
│   └── redundancy_test01.log
└── README.md
```

---

## 4. Tools and Setup

### 4.1 libopus Build

```bash
git clone https://gitlab.xiph.org/xiph/opus.git
cd opus
./autogen.sh
./configure
make
```

Result: `libopus 1.6.1-68-g503d81b1` built with `opus_demo` and shared library at `opus/.libs/libopus.so`.

### 4.2 Dataset

Mozilla Spontaneous Speech 5.0 (English) from the Mozilla Data Collective, MP3 format. Converted to raw PCM:

```bash
for f in data/raw/*.mp3; do
    base=$(basename "$f" .mp3)
    ffmpeg -i "$f" -f s16le -acodec pcm_s16le -ar 48000 -ac 1 "data/pcm/${base}.pcm"
done
```

### 4.3 Synthetic Test Signals

```bash
# 2 seconds of silence
ffmpeg -f lavfi -i anullsrc=r=48000:cl=mono -t 2 -f s16le -acodec pcm_s16le data/pcm/silence.pcm

# 3 seconds of white noise
ffmpeg -f lavfi -i anoisesrc=r=48000:amplitude=0.5 -t 3 -f s16le -acodec pcm_s16le data/pcm/noise.pcm

# 2 seconds of 1 kHz tone
ffmpeg -f lavfi -i "sine=frequency=1000:duration=2" -f s16le -acodec pcm_s16le -ar 48000 -ac 1 data/pcm/tone.pcm

# Concatenations for transition testing
cat data/pcm/noise.pcm data/pcm/spontaneous-speech-en-1.pcm > data/pcm/celt_to_silk.pcm
cat data/pcm/tone.pcm data/pcm/spontaneous-speech-en-1.pcm > data/pcm/strong_transition.pcm
cat data/pcm/spontaneous-speech-en-1.pcm data/pcm/silence.pcm data/pcm/spontaneous-speech-en-5.pcm > data/pcm/transition_test.pcm
```

---

## 5. Instrumentation of libopus

### 5.1 Redundancy Logging

Added `fprintf` statements in `opus/src/opus_encoder.c` at the redundancy decision points (around lines 2353–2376 and 2434/2538):

```c
static int dbg_frame_counter = 0;
dbg_frame_counter++;
fprintf(stderr, "REDUNDANCY: frame=%d mode=%d celt_to_silk=%d bytes=%d\n",
        dbg_frame_counter, st->mode, celt_to_silk, redundancy_bytes);
```

And when the redundant frame is written:

```c
fprintf(stderr, "  -> redundant frame written at offset %d, size %d\n",
        nb_compr_bytes, redundancy_bytes);
```

### 5.2 Final Packet Logging

Added at the end of `opus_encode_frame_native` (around line 2663):

```c
fprintf(stderr, "  -> FINAL packet: ret=%d, mode=%d\n", ret, st->mode);
return ret;
```

### 5.3 Rebuild

```bash
cd opus && make && cd ..
```

### 5.4 Note on `stderr`

Added `#include <stdio.h>` to `opus_encoder.c` to declare `stderr`.

---

## 6. Custom Encoder/Decoder Pipeline

### 6.1 `scripts/encode_raw.c`

A minimal C program using the public Opus API directly. Writes output in a simple format:

```text
[4-byte little-endian packet length][packet payload]  (repeated)
```

This format is trivial to parse in Python, unlike `opus_demo`'s internal framing.

Usage:

```bash
./scripts/encode_raw <input.pcm> <output.bin> <mode> <bitrate>
# mode: voip | audio | lowdelay
```

### 6.2 `scripts/decode_raw.c`

Matching decoder that reads the `[len][packet]` format and writes raw PCM.

### 6.3 Compilation

```bash
export LD_LIBRARY_PATH=$PWD/opus/.libs:$LD_LIBRARY_PATH

gcc -O2 -o scripts/encode_raw scripts/encode_raw.c \
    -I opus/include -L opus/.libs -lopus -lm

gcc -O2 -o scripts/decode_raw scripts/decode_raw.c \
    -I opus/include -L opus/.libs -lopus -lm
```

### 6.4 Why Not `opus_demo`

`opus_demo` uses an internal framing format that interleaves length, range coder state, and payload in an undocumented way. Empirical attempts to parse it produced contradictory packet sizes (e.g., `pkt_len=3` vs. log offset `1237`). Switching to the Opus API gave exact, reproducible packet bytes.

---

## 7. Experiments and Results

### 7.1 Initial Encode — VoIP Mode, 24 kbps

```bash
./opus/opus_demo -e voip 48000 1 24000 \
    data/pcm/spontaneous-speech-en-1.pcm \
    data/bitstreams/test01_voip.bit \
    2> logs/redundancy_test01.log
```

Result: **0 redundancy decisions**. Encoder stayed in SILK mode throughout.

### 7.2 Bitrate Sweep — VoIP Mode

| Bitrate | Redundancy decisions |
|:---|:---|
| 24 kbps | 0 |
| 16 kbps | 0 |
| 12 kbps | 0 |

### 7.3 Transition Test — Speech + Silence + Speech

```bash
cat data/pcm/spontaneous-speech-en-1.pcm data/pcm/silence.pcm \
    data/pcm/spontaneous-speech-en-5.pcm > data/pcm/transition_test.pcm

./opus/opus_demo -e voip 48000 1 16000 \
    data/pcm/transition_test.pcm \
    data/bitstreams/transition_test.bit \
    2> logs/redundancy_transition.log
```

Result: **0 redundancy decisions**. Silence gap too short to force a mode switch.

### 7.4 Forced CELT Mode

```bash
./opus/opus_demo -e restricted-lowdelay 48000 1 96000 \
    data/pcm/spontaneous-speech-en-1.pcm \
    data/bitstreams/celt_force.bit \
    2> logs/redundancy_celt_force.log
```

Result: **0 redundancy decisions**.

### 7.5 Audio Mode, 32 kbps — First Redundancy Decision

```bash
./scripts/encode_raw data/pcm/spontaneous-speech-en-1.pcm \
    data/bitstreams/encoded/test01_audio32k.bin audio 32000 \
    2> logs/encode_test01_audio32k.log
```

Log output:

```text
FRAME 0: len=3
FRAME 1: len=3
FRAME 2: len=3
REDUNDANCY: frame=1 mode=1001 celt_to_silk=1 bytes=38
  -> redundant frame written at offset 1237, size 38
FRAME 3: len=84
...
```

**Key observation:** `REDUNDANCY` logged at frame 1 (mode 1001 = MODE_CELT_ONLY), but the final packet for frame 1 was only **3 bytes**. A 3-byte packet cannot contain 38 bytes of redundant data.

### 7.6 Parser Validation

`scripts/parse_packets.py` output for the same file:

```text
Frame 0: pkt_len=3, pkt_offset=4, first_bytes=f8fffe
Frame 1: pkt_len=3, pkt_offset=11, first_bytes=f8fffe
Frame 2: pkt_len=3, pkt_offset=18, first_bytes=f8fffe
Frame 3: pkt_len=84, pkt_offset=25, first_bytes=780be4c136ecc74f
...
Total packets: 502
```

The `FINAL packet: ret=N` log entries matched the parser's `pkt_len=N` exactly. This validated the instrumentation.

### 7.7 Redundancy Survival Cross-Check

`scripts/automate.py` correlates `REDUNDANCY` decisions with `FINAL packet` sizes:

```text
Frame 1: redundancy_bytes=38, final_packet=3, survived=False, mode=1002
```

**Result: the redundant frame did NOT survive packetization.**

### 7.8 Additional Encoder Configurations

| Configuration | Redundancy decisions | Survived |
|:---|:---|:---|
| audio 32 kbps | 1 | No |
| audio 64 kbps | 0 | — |
| voip 24 kbps | 0 | — |
| voip 16 kbps (FEC enabled) | 0 | — |
| noise → speech 32 kbps | 0 | — |
| transition test 16 kbps | 0 | — |

### 7.9 Byte-Overwrite Test

Flipped byte 0 of frame 1 (`0xf8` → `0x07`) in `test01_audio32k.bin`:

```bash
python3 scripts/modify_packet.py \
    data/bitstreams/encoded/test01_audio32k.bin \
    data/bitstreams/modified/test01_modified.bin \
    1 0
```

Decode result:

```text
Decoded 1 frames
opus_decode failed at frame 1: corrupted stream
```

**Result: modifying the ToC byte of a 3-byte packet causes immediate decoder desynchronization.** The packet structure is not freely modifiable.

---

## 8. Key Findings

1. **Redundancy decisions in Opus 1.6.1 are opportunistic, not guaranteed.** The encoder logs the intent to include a redundant frame before checking whether the packet has sufficient bit budget.

2. **At 32 kbps `audio` mode on spontaneous speech, exactly one redundancy decision occurred (38 bytes, frame 1, mode 1002) and it did not survive into the final 3-byte packet.**

3. **At 64 kbps, 24 kbps VoIP, 16 kbps VoIP with FEC, and on transition-heavy content, no redundancy decision was logged at all.**

4. **`FINAL packet: ret=N` logging reliably matches `pkt_len=N` in the parsed bitstream**, validating the API-level instrumentation approach.

5. **Blind byte-overwrite in the ToC region causes `corrupted stream`**, confirming that the packet structure is not freely modifiable and that any embedding scheme must respect the range coder state and ToC layout.

6. **FEC/LBRR does not help in CELT mode.** The Opus specification disables FEC in CELT-only mode, and the redundant frame mechanism is separate from LBRR.

7. **The redundant CELT frame is not a reliable covert channel under standard operating conditions.** It is budget-dependent, content-dependent, and rarely survives packetization.

---

## 9. Interpretation

The redundant CELT frame was hypothesized to be an attractive embedding target because of its isolated entropy coder state and byte alignment. Empirically, however:

- The encoder decides to include redundancy only during **specific mode transitions**.
- Even when the decision is made, the final packet may be too small to hold the redundant frame.
- The packetization stage silently discards the redundant frame rather than expanding the packet.
- There is no configuration tested that reliably produces a surviving redundant frame on real speech content.

This closes off the redundant CELT frame as a practical steganographic channel and motivates investigation of the **CELT transform domain** (PVQ indices, energy envelope, raw bits), which is not subject to the same budget-dependent drop.

---

## 10. Commands Reference

### Encode

```bash
export LD_LIBRARY_PATH=$PWD/opus/.libs:$LD_LIBRARY_PATH

./scripts/encode_raw \
    data/pcm/spontaneous-speech-en-1.pcm \
    data/bitstreams/encoded/test01_audio32k.bin \
    audio 32000 \
    2> logs/encode_test01_audio32k.log
```

### Parse

```bash
python3 scripts/parse_packets.py data/bitstreams/encoded/test01_audio32k.bin
```

### Cross-Check

```bash
python3 automate.py logs/encode_test01_audio32k.log
```

### Modify

```bash
python3 scripts/modify_packet.py \
    data/bitstreams/encoded/test01_audio32k.bin \
    data/bitstreams/modified/test01_modified.bin \
    <frame_idx> <byte_offset>
```

### Decode

```bash
./scripts/decode_raw data/bitstreams/encoded/test01_audio32k.bin \
    data/output/test01_orig.pcm

./scripts/decode_raw data/bitstreams/modified/test01_modified.bin \
    data/output/test01_mod.pcm
```

### Compare

```bash
ffmpeg -f s16le -ar 48000 -ac 1 -i data/output/test01_orig.pcm \
    data/output/test01_orig.wav -y

ffmpeg -f s16le -ar 48000 -ac 1 -i data/output/test01_mod.pcm \
    data/output/test01_mod.wav -y
```

---

## 11. Negative Result — Paper Framing

**Proposed title:**  
*An Empirical Characterization of Redundant Frame Persistence in Opus CELT Mode: Implications for Steganographic Embedding*

**Contribution:**
- First instrumentation of Opus 1.6.1 redundancy decisions at the API level.
- Empirical finding that redundancy decisions are discarded before packetization under standard operating conditions.
- Demonstration that ToC byte modification causes decoder desynchronization.
- Recommendation that Opus steganography research target the CELT transform domain instead.

**Target venue:**  
IH&MMSec (ACM Workshop on Information Hiding and Multimedia Security) — short paper (4–6 pages). Best scope match. Next deadline likely February 2027.

**Backup venue:**  
IEEE Signal Processing Letters (stretch — requires stronger contribution).

---

## 12. Next Steps

1. Document this negative result for the paper.
2. Pivot to CELT transform-domain steganography:
   - Characterize embedding capacity of PVQ indices.
   - Characterize energy envelope modification tolerance.
   - Investigate raw bits at the end of the packet (isolated from range coder).
3. Use the negative result as motivation in the CELT paper's introduction.
4. Retain the instrumentation and API pipeline as reusable infrastructure.

---

## 13. References

- RFC 6716: Definition of the Opus Audio Codec
- RFC 8251: Updates to the Opus Audio Codec
- Tian et al. (2025): Deep reinforcement learning for Opus steganography
- Ren et al. (2020): Pulse-domain steganography in Opus
- Xiph Opus documentation: https://opus-codec.org/
- Mozilla Data Collective: Spontaneous Speech 5.0 — English

---

## 14. Acknowledgments

This work was conducted as an independent research project. The instrumentation, pipeline, and negative result form the empirical foundation for subsequent CELT transform-domain steganography research.

---
