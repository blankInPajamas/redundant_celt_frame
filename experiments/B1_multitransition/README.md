# B.1 — Multi-Transition Test

## Goal

Determine whether multiple CELT-only → hybrid transitions can be forced
in a single stream, giving a rate-based rather than one-shot channel.

## Method

1. Concatenate speech/silence segments with varying silence durations.
2. Encode with `audio` at 32 kbps.
3. Count frames with ≥4 trailing zero bytes.

## What we found

- Naive concatenation (speech-silence-speech-silence-speech) yields **1** tail.
- Silence durations 20, 40, 80, 160, 320 ms produce 1, 1, 2, 1, 2 tails.
- Non-monotonic: encoder mode memory suppresses repeated transitions.

## Conclusion

The channel is one-shot per stream under normal content.