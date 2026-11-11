# B.0 — Decisive Experiment

## Goal

Determine where the redundant CELT frame sits in the final packet, and
whether modifying that region breaks decoding.

## Method

1. Instrument `opus/src/opus_encoder.c` to log the redundant region.
2. Encode `spontaneous-speech-en-1.pcm` in audio mode at 32 kbps.
3. Parse the transition frame's hex.
4. Modify each byte of the transition frame, decode, compare to baseline.

## What we found

- Redundancy is proposed on `frame_id=7` (the 4th emitted frame, mode=1001).
- Proposed redundancy size: 38 bytes.
- Internal write offset: `nb_compr_bytes = 1237`.
- Final packet size: `ret = 84`.
- The redundant region `[1237, 1275)` is entirely outside the final packet.
- The tail of the 84-byte packet (bytes 48–83, 36 bytes) is zero-padded.
- Modifying any byte in [48, 83] produces identical decoded PCM.
- Modifying byte 0 truncates decode at frame 3 (structural TOC byte).
- Modifying bytes 1–47 changes decoded audio.

## Conclusion

The redundant frame does not survive packetization. Its reserved space
appears as a zero-padded tail that is modifiable without detection.

## Reproduction

```text
bash reproduce.sh
python3 analyze.py
```