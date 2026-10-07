# B.4 — Payload Embedding

## Goal

Demonstrate that a message can be embedded into the transition frame's
zero tail and recovered without decoder failure or audio degradation.

## Method

1. Encode the target PCM.
2. Locate the zero tail on the transition frame.
3. Write message bits into the tail (LSB-first, 1 bit per byte).
4. Decode the modified stream.
5. Compare decoded PCM to baseline: expect identical.
6. Parse the modified stream: extract the embedded bits.

## What we found (partial)

- 28-bit payload embedded and decoded identically.
- Full-length test pending (needs multi-transition capacity).

## Notes

- If the channel is one-shot, payload capacity is 288 bits per stream.
- To demonstrate a real message, use 32 ASCII characters = 256 bits.