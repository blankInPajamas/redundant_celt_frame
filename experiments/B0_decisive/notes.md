# B.0 Notes

## Surprises

1. The internal write offset `nb_compr_bytes=1237` is not a byte offset
   in the 84-byte packet — it's an offset in the encoder's internal
   buffer. This is the mechanism of failure.

2. The inert region is 36 bytes, not 38. The proposed redundancy was
   38 bytes; the last 2 bytes are consumed by range coder termination
   (`74 84 fa b6 37 22 ff fe` at offsets 40–47).

3. Byte 0 (TOC) modification truncates the decode at frame 3 — the
   decoder sees a corrupted TOC and stops. All other bytes (1–47) cause
   PCM differences without decoding failure.

## Implications for the paper

- The channel capacity is 288 bits per transition.
- The channel is bounded by the transition rate (one per stream).
- The mechanism is a buffer-offset truncation, not a budget check.

## Follow-ups

- Test B.0 on other speech files to confirm universality. (Done in B.2.)
- Test the mechanism on libopus 1.5 and 1.4. (Planned B.5.)
- Test whether the modified stream survives a re-encode (out of scope).