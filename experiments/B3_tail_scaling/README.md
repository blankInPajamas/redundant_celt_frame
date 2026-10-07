# B.3 — Tail Scaling

## Goal

Determine the functional form of tail_size(bitrate) within the audio window.

## Method

Encode at 20, 24, 28, 32, 40 kbps in audio mode. Extract max_tail.

## What we found

| Bitrate | Frame size | Tail | Ratio |
|---------|-----------|------|-------|
| 20000   | 58        | 25   | 43.1% |
| 24000   | 66        | 28   | 42.4% |
| 28000   | 75        | 32   | 42.7% |
| 32000   | 84        | 36   | 42.9% |
| 40000   | 101       | 43   | 42.6% |

Linear fit: tail = 0.43 × frame_size + small_offset.

## Conclusion

The reservation is a fixed fraction of the transition frame.