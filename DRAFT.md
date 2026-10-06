# An Empirical Characterization of Redundant Frame Persistence in Opus CELT Mode: Implications for Steganographic Embedding

## Abstract

Opus is widely deployed in interactive speech and audio applications, yet prior steganographic research has focused primarily on the SILK pulse domain. This paper empirically investigates whether the redundant CELT frame used during Opus mode transitions can serve as a practical covert channel. The redundant frame appears structurally attractive because it uses an isolated entropy-coder state and is aligned to byte boundaries. We instrumented libopus 1.6.1, built an API-level encoding and decoding pipeline, parsed the resulting packet streams, and tested multiple encoder modes, bitrates, signal types, and transition scenarios. The experiments show that redundancy decisions are opportunistic and highly dependent on encoder state and available packet budget. In the most favorable observed case—audio mode at 32 kbps on spontaneous speech—the encoder logged one 38-byte redundancy decision, but the corresponding final packet was only 3 bytes and the redundant frame did not survive packetization. Other tested configurations produced no redundancy decisions. A byte-overwrite experiment further showed that modifying the Table of Contents region caused immediate decoder failure. These results indicate that the redundant CELT frame is not a reliable covert channel under standard operating conditions. The study contributes an instrumented characterization of redundancy persistence in Opus 1.6.1 and motivates future work on the CELT transform domain, including PVQ indices, energy envelopes, and raw packet bits.

## Problem Statement and Methodology

### Problem statement

Opus supports both SILK and CELT coding layers, as well as hybrid operation. Existing Opus steganography studies have concentrated largely on the SILK pulse domain, leaving the CELT transform domain comparatively unexplored. The redundant CELT frame, transmitted in-band during certain mode transitions, presents a potentially useful embedding location: it is short, isolated from the primary entropy-coder state, and written on byte boundaries.

The central research question is:

> Can the redundant CELT frame in Opus be used as a covert channel for steganographic communication, and does it survive packetization reliably enough to be viable?

A practical channel must satisfy more than a theoretical capacity requirement. It must be generated with reasonable frequency, persist in the final encoded packet, survive decoding and transport, and permit controlled modification without corrupting the stream. The study therefore treats redundancy generation, packet persistence, and decoder behavior as separate empirical questions.

### Methodology

The experiments used an instrumented build of libopus 1.6.1. Instrumentation was added to `opus_encoder.c` at the redundancy decision points and at the end of native frame encoding. The instrumentation recorded the frame number, coding mode, transition direction, proposed redundancy size, final return value, and final packet size. A minimal C encoder and decoder using the public Opus API were also implemented. Encoded output used a simple framing format consisting of a four-byte little-endian packet length followed by the packet payload.

The primary dataset was Mozilla Spontaneous Speech 5.0 in English. Source audio was converted to 48 kHz, mono, signed 16-bit PCM. Synthetic signals were additionally generated for silence, white noise, a 1 kHz tone, and concatenated transition cases. The tested scenarios included:

- VoIP mode at 12, 16, and 24 kbps.
- Audio mode at 32 and 64 kbps.
- Restricted-lowdelay CELT operation at 96 kbps.
- Speech, silence, noise, tone, and concatenated transition signals.
- A byte-overwrite test targeting the first byte of a packet associated with a redundancy decision.

The resulting logs were cross-checked against a Python packet parser. A redundancy event was considered to have survived only when the corresponding final packet contained the proposed redundant payload. This distinction is important because an encoder-side decision does not necessarily imply that the data appears in the transmitted packet.

## Implementation

### Instrumented encoder

The encoder was built from the libopus source tree using the standard Autotools workflow. The resulting build identified itself as `libopus 1.6.1-68-g503d81b1`. Logging was added around the redundancy decision and frame-writing paths. Conceptually, the instrumentation recorded events of the following form:

```text
REDUNDANCY: frame=<n> mode=<mode> celt_to_silk=<direction> bytes=<size>
  -> redundant frame written at offset <offset>, size <size>
```

A final-packet log was emitted after native frame encoding:

```text
-> FINAL packet: ret=<packet_size>, mode=<mode>
```

The final return value was compared with the packet length emitted by the API-level encoder. This provided an independent check that the instrumentation corresponded to actual output packets rather than to an intermediate encoder state.

### Encoding and decoding pipeline

The custom encoder accepted an input PCM file, an output bitstream path, an Opus application mode, and a bitrate. It encoded each frame through the public Opus API and wrote packets in the following format:

```text
[4-byte little-endian packet length][packet payload]
```

The matching decoder read this framing, passed each payload to the Opus decoder, and wrote raw PCM output. This pipeline was selected instead of relying on `opus_demo`, whose internal framing made packet-size interpretation ambiguous during early parsing attempts.

### Packet parsing and modification

The packet parser walked the length-prefixed stream and reported packet lengths, offsets, and initial bytes. The cross-check script correlated encoder-side redundancy events with final packet sizes and marked whether each event survived. A separate modification harness overwrote a selected byte at a selected frame and byte offset, allowing decoder robustness to be tested directly.

The implementation and experiment artifacts were organized into source, dataset, bitstream, logging, and output directories. This separation supported repeatable encoding, parsing, modification, decoding, and comparison steps.

## Results and Evaluation

### Redundancy occurrence

The experiments found that redundancy decisions were uncommon and configuration-dependent. The bitrate sweep in VoIP mode produced no redundancy decisions at 24, 16, or 12 kbps. A speech–silence–speech transition test also produced no decisions, indicating that the tested silence interval did not force a relevant mode switch. Forced CELT operation likewise produced no redundancy decisions.

The first observed event occurred in audio mode at 32 kbps on spontaneous speech:

```text
REDUNDANCY: frame=1 mode=1001 celt_to_silk=1 bytes=38
  -> redundant frame written at offset 1237, size 38
```

However, the same run reported a final packet of only 3 bytes for frame 1. The parsed stream confirmed the discrepancy:

```text
Frame 0: pkt_len=3
Frame 1: pkt_len=3
Frame 2: pkt_len=3
Frame 3: pkt_len=84
```

The cross-check therefore classified the event as not surviving packetization.

### Configuration-level results

| Configuration | Redundancy decisions | Survived packetization |
|:---|---:|---:|
| Audio, 32 kbps | 1 | No |
| Audio, 64 kbps | 0 | Not applicable |
| VoIP, 24 kbps | 0 | Not applicable |
| VoIP, 16 kbps with FEC | 0 | Not applicable |
| Noise to speech, 32 kbps | 0 | Not applicable |
| Transition test, 16 kbps | 0 | Not applicable |

These results do not establish that redundant frames can never be emitted. They do show that, across the tested standard configurations and signals, no reliable production condition was identified. Even the sole observed decision was discarded before the final packet was produced.

### Packet integrity test

The byte-overwrite experiment changed the first byte of frame 1 from `0xf8` to `0x07`. Decoding then failed at the modified frame:

```text
Decoded 1 frames
opus_decode failed at frame 1: corrupted stream
```

This result indicates that the packet's Table of Contents and associated coding structure cannot be treated as freely modifiable byte storage. Any future embedding method must preserve the constraints imposed by the ToC layout, range-coder state, and packet bit budget.

### Evaluation and interpretation

The original hypothesis was that the redundant CELT frame would be an attractive low-risk embedding target because it has an isolated entropy state and byte alignment. The observations instead identify three practical limitations:

1. Redundancy is triggered only under specific mode-transition conditions.
2. A redundancy decision may be made before the encoder determines that the final packet has enough budget to carry it.
3. The packetization stage can silently discard the proposed redundant frame rather than expanding the packet.

The agreement between `FINAL packet: ret=N` log entries and parsed `pkt_len=N` values validates the API-level instrumentation and packet-processing pipeline. The negative result is therefore not explained by a parser mismatch in the final experiment. Rather, it reflects the distinction between an internal encoder decision and transmitted packet content.

The findings also show that FEC/LBRR does not provide a fallback mechanism for CELT-only redundancy: FEC behavior is separate from the redundant-frame mechanism and does not make the observed channel reliable. Under the tested conditions, the redundant CELT frame is budget-dependent, content-dependent, and too infrequent to support a practical covert channel.

### Limitations and future work

The study evaluates libopus 1.6.1 and a finite set of bitrates, modes, signals, and transition constructions. It does not claim to exhaustively characterize every encoder state or application configuration. In particular, additional work could investigate longer and more abrupt mode transitions, packet-duration variations, broader bitrate ranges, and controlled encoder-state manipulation.

Nevertheless, the current evidence is sufficient to reject the redundant CELT frame as a dependable embedding location under standard operating conditions. Future research should instead examine the CELT transform domain directly, including PVQ indices, energy-envelope modifications, and raw bits at the end of the packet. The instrumentation and API pipeline developed here can be retained as reusable infrastructure for those experiments.

## References

1. RFC 6716. *Definition of the Opus Audio Codec*.
2. RFC 8251. *Updates to the Opus Audio Codec*.
3. Xiph.Org Foundation. *Opus Documentation*.
4. Mozilla Data Collective. *Spontaneous Speech 5.0 — English*.
