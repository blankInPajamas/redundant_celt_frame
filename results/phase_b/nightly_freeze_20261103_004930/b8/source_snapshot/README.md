# B8 — LibriSpeech Content Test

## Goal

Test whether the transition-frame tail channel triggers on read speech
(LibriSpeech train-clean-100), which is a distinct content type from
spontaneous conversational speech (Mozilla).

## Method

1. Encode 20 LibriSpeech chapters (each ~30 s, concatenated from 5
   utterances) at audio 32 kbps.
2. Count frames with ≥ 4 trailing-zero bytes.
3. Compare to the speech (B2) and music (B7) results.

## Result

**0 of 20 files produced a tail.** Maximum trailing-zero count was 1
byte, indistinguishable from the range-coder's natural end-of-stream
bytes.

Combined with B7 (music: 0/100), this shows the channel is specific to
spontaneous conversational speech, not speech in general.

## Files

- `prepare.sh` — concatenates LibriSpeech chapters into 30 s PCM files.
- `reproduce.sh` — encodes each PCM and counts tails.
- `results.csv` — output table.

## Reproduction

```bash
bash experiments/B8_librispeech/prepare.sh
bash experiments/B8_librispeech/reproduce.sh
```