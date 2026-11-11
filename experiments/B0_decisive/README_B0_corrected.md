# B.0 — Byte-Level Localization of the Candidate Transition-Frame Region

## 1. Objective

B0 investigates the byte-level structure of one candidate Opus transition packet and tests whether changing individual packet bytes alters the decoded PCM output.

The experiment addresses three separate questions:

1. Which byte positions can be perturbed individually while preserving decoded PCM identity?
2. Which positions affect decoded audio or packet interpretation?
3. Is there a contiguous region suitable for the subsequent payload experiments?

This is a single-recording, single-configuration characterization experiment. Its results should not be interpreted as proof that the same byte layout occurs in every Opus stream or encoder configuration.

## 2. Experimental configuration

| Item | Configuration |
|---|---|
| Input | `data/pcm/spontaneous-speech-en-1.pcm` |
| Application | `audio` |
| Bitrate | 32,000 bit/s |
| Target packet index | 3 (zero-based; fourth emitted packet) |
| Target packet length | 84 bytes |
| Instrumented transition frame | `frame_id=7`, mode `1001` |
| Proposed redundancy size | 38 bytes |
| Instrumented internal write offset | `nb_compr_bytes=1237` |
| Baseline decoded PCM size | 963,840 bytes |

The encoder instrumentation reported a proposed 38-byte redundancy write and an internal write offset of 1237. This is an encoder-internal buffer coordinate; it must not be interpreted as byte offset 1237 in the final 84-byte packet.

The final packet was inspected separately. Its byte positions 48–83 form a 36-byte zero-filled suffix in the tested bitstream.

## 3. Method

1. Encode the input PCM using the audio application mode at 32 kbps.
2. Decode the unmodified bitstream to create the baseline PCM.
3. Select packet index 3 (zero-based), whose observed length is 84 bytes.
4. Create one modified bitstream for each packet-byte offset from 0 through 83.
5. In each modified bitstream, perturb only the selected byte using the experiment's packet-modification utility.
6. Decode each modified bitstream.
7. Record the decoder return code, decoded PCM size and whether the decoded PCM is byte-identical to the baseline.
8. Classify the result using both PCM identity and output length. A successful decoder return code alone does not establish that the complete stream was decoded.

## 4. Results

The archived `b0_results.csv` contains 84 byte-offset observations.

| Classification | Byte positions | Count | Interpretation |
|---|---|---:|---|
| Structural/truncation effect | `0` | 1 | Decoder returned code 0, but output was only 5,760 bytes rather than the 963,840-byte baseline |
| Audio/content-changing | `1–29`, `32`, `34`, `37`, `40`, `44–47` | 37 | Decode returned code 0 and output length matched baseline, but PCM differed |
| Individually PCM-identical, isolated positions | `30`, `31`, `33`, `35`, `36`, `38`, `39`, `41`, `42`, `43` | 10 | A one-byte perturbation at each listed position preserved baseline PCM in this test |
| Individually PCM-identical, contiguous suffix | `48–83` | 36 | A one-byte perturbation at each position preserved baseline PCM in this test; these positions form the contiguous 36-byte zero-filled suffix |

Summary:

- 46 of 84 byte positions were individually classified as PCM-identical after perturbation.
- Of those 46 positions, 36 form one contiguous region: offsets 48–83.
- The other 10 PCM-identical positions are isolated and are not part of that contiguous suffix.
- Offset 0 produced a truncated output of 5,760 bytes, although the decoder process returned code 0.
- The remaining 37 positions produced a full-length output whose PCM differed from baseline.

The result supports the existence of a 36-byte contiguous region that was individually perturbable without changing the decoded PCM in this specific test.

### Important interpretation boundary

The 46 individually PCM-identical byte positions must not be reported as 46 bytes of contiguous payload capacity. The ten isolated positions were tested one at a time. These results do not establish that they can be modified simultaneously, that arbitrary payload values are safe at those positions, or that they form a usable contiguous channel.

For the subsequent payload experiments, the operational candidate region is therefore the 36-byte contiguous suffix at offsets 48–83. The later embedding experiments provide separate evidence about payload use and recovery; B0 alone establishes only the single-byte perturbation observations.

## 5. Conclusion

In the tested 84-byte transition packet, byte-level perturbation identified a 36-byte contiguous zero-filled suffix at offsets 48–83. Individual perturbations within this suffix preserved byte-identical decoded PCM. Ten additional isolated positions also preserved PCM when perturbed individually, but they do not form a contiguous payload region.

Changing the TOC byte at offset 0 resulted in a substantially truncated decoded output. Perturbations at 37 other positions changed the decoded PCM while preserving the baseline output length.

The proposed 38-byte redundancy size reported by encoder instrumentation should not be equated with the 36-byte contiguous PCM-invariant suffix. The experiment identifies the latter as the region used for subsequent payload investigations.

These findings are limited to the tested input, encoder build, application mode, bitrate and packet. Broader claims require validation across additional recordings and configurations.

## 6. Reproduction

From the repository root:

```bash
bash experiments/B0_decisive/reproduce.sh
```

The reproduction script writes the generated bitstream, baseline decode, modified bitstreams, modified PCM files and a result CSV under:

```text
logs/phase_b/B0/
```

### Reproduction-script caveat

The archived `reproduce.sh` currently writes a three-column CSV (`byte_offset`, `decode_rc`, `identical_to_baseline`) to `logs/phase_b/B0/results.csv`. The archived `analyze.py` reads `experiments/B0_decisive/results.csv` and uses a `pcm_size` column, when present, to identify truncated output. Therefore, the two scripts are not currently a fully connected one-command reproduction pipeline.

Before treating a fresh run as a complete reproduction, update the reproduction script to record the modified PCM file size in every row and update the analyzer to read the generated output path (or explicitly copy the generated CSV to the analyzer's expected location). This is necessary to distinguish offset 0's truncated output from a full-length, content-changing output.

The archived result file used for this README includes the `pcm_size` field and supports the classifications in Section 4.

## 7. Limitations and follow-up work

- B0 uses one input recording and one encoder configuration.
- Each byte position was perturbed individually; combinations of positions were not tested in B0.
- Individual PCM identity does not, by itself, demonstrate reliable payload capacity or robustness.
- The 36-byte suffix should be treated as a candidate region under the tested conditions, not a universal property of all Opus packets.
- Payload embedding, extraction, packet integrity and decoder compatibility are evaluated separately in later experiments.

## 8. Evidence files

Primary archived files:

```text
experiments/B0_decisive/b0_results.csv
experiments/B0_decisive/results.csv
experiments/B0_decisive/analyze.py
experiments/B0_decisive/reproduce.sh
experiments/B0_decisive/notes.md
```

Retain the original result files unchanged. This README corrects the interpretation; it does not replace or modify the underlying measurements.
