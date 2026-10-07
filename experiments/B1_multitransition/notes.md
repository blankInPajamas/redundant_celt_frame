# B.1 Notes

## Surprises

The non-monotonic pattern (80 ms → 2 tails, 160 ms → 1 tail, 320 ms → 2 tails)
is puzzling. Hypothesis: the encoder's mode memory spans ~100–200 ms, so
80 ms and 320 ms happen to reset it, but 160 ms does not. Needs further
probing at 60, 100, 120, 200, 240 ms.

## Follow-ups

- Why does 160 ms fail to trigger? Test 140, 180, 220, 260 ms.
- Does changing content (speech vs noise vs tone) affect this?