# B.2 Results

Application × bitrate matrix (max_tail in bytes; 0 or 1 = no channel).

| Application | 16k | 20k | 24k | 28k | 32k | 40k | 48k | 64k |
|-------------|-----|-----|-----|-----|-----|-----|-----|-----|
| voip        |  1  |  0  |  1  |  1  |  1  |  1  |  1  |  1  |
| audio       |  1  | 25  | 28  | 32  | 36  | 43  |  1  |  1  |
| lowdelay    |  1  |  1  |  1  |  1  |  1  |  1  |  1  |  1  |

**Observation:** the channel is exclusive to `audio` in the 20–40 kbps
window. VoIP and lowdelay never produce tails ≥4 bytes. Audio at ≤16 kbps
or ≥48 kbps produces no tails either.