# B0b — Silent-buffer measurement and trigger controls

## Purpose

Verify that the PCM buffer fed to the redundant CELT encoder is digitally
silent, and confirm the trigger requires silence rather than the
redundancy path in isolation.

## Experiments

1. **Baseline sweep (20 files):** every spontaneous-speech file produces
   `RED_PCM: samples=240 rms=0.000000 peak=0.000000`. All readings
   effectively zero.

2. **Noise-replacement control:** replacing the first 100 ms of a speech
   file with low-amplitude Gaussian noise (RMS ≈ 200) prevents the
   trigger. No REDUNDANCY event, no RED_PCM reading, no zero-fill tail.

3. **Silence-prepend control:** prepending 200 ms of silence to the
   same file shifts the transition from frame 3 to frame 13 (exactly
   +10 frames of 20 ms) and preserves the identical 84-byte packet
   structure with 36-byte zero-fill tail.

## Conclusion

The channel requires a silence-induced mode transition. The redundant
frame's content is exactly zero, not merely low-energy. The zero-fill is
a direct consequence of CBR-encoding an all-zero buffer, and is not a
property of the redundancy encoding path in isolation.
