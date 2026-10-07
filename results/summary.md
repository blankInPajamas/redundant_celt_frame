# Experimental Summary

## Key result

The Opus redundant CELT frame does **not** survive packetization.
However, the encoder reserves space for it and does not reclaim that
space when the write fails, leaving a zero-padded tail equal to ~43%
of the transition frame size.

## Trigger condition

- Application: **audio** only
- Bitrate: **20–40 kbps**
- Content: any speech with a CELT-only → hybrid transition

## Channel capacity

| Bitrate | Tail bytes | Tail bits |
|---------|-----------|-----------|
| 20000   | 25        | 200       |
| 24000   | 28        | 224       |
| 28000   | 32        | 256       |
| 32000   | 36        | 288       |
| 40000   | 43        | 344       |

One-shot per stream. Not rate-based.

## Modifiability

Bit-level modification is undetectable by the decoder.
Byte 0 (TOC) is structural; bytes 1–47 are content; bytes 48–83 are inert.

## Open questions

- Why does 160 ms silence fail to retrigger the transition?
- Is the effect present in libopus 1.4 and 1.5?
- Does the effect survive re-encoding?