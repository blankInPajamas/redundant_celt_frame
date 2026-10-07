# B.2 — One-Shot Sweep

## Goal

Characterize the application × bitrate window in which the zero-tail
channel appears.

## Method

Encode `spontaneous-speech-en-1.pcm` with each combination of:
- application ∈ {voip, audio, lowdelay}
- bitrate ∈ {16, 20, 24, 28, 32, 40, 48, 64} kbps

For each output, count frames with ≥4 trailing zero bytes.

## What we found

| Application | Trigger window |
|-------------|----------------|
| voip        | never          |
| audio       | 20–40 kbps     |
| lowdelay    | never          |

Within the audio window, tail size scales linearly with bitrate.
