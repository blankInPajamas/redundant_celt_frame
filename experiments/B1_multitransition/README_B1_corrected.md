# B.1 — Repeated Tail-Candidate Exploration

## 1. Objective

B1 explores whether repeated speech/silence concatenations can produce more than one packet with a qualifying trailing-zero run in a single encoded stream.

The experiment is exploratory. Its measurement is the number of encoded packets containing at least four trailing zero bytes. This is a structural proxy used to identify candidate packets; it is not, by itself, proof that each counted packet contains a confirmed CELT-to-SILK transition or a relocated redundancy region.

B1 therefore tests repeated tail-candidate occurrence, not a fully instrumented count of confirmed transition events.

## 2. Experimental configuration

| Item | Configuration |
|---|---|
| Input speech | `data/pcm/spontaneous-speech-en-1.pcm` |
| Application | `audio` |
| Bitrate | 32,000 bit/s |
| Naive concatenation | First 96,000 speech samples, 48,000 zero-valued samples, repeated speech/silence/speech sequence |
| Silence sweep | 20, 40, 80, 160 and 320 ms |
| Speech segment in each sweep cycle | First 24,000 samples |
| Silence samples per cycle | `48 × silence_ms` zero-valued samples |
| Repetitions in each sweep stream | 10 |
| Candidate-packet criterion | At least 4 consecutive zero bytes at the end of a packet |

The script constructs the naive stream as:

```text
speech + silence + speech + silence + speech
```

For each silence-duration condition, it constructs ten repetitions of:

```text
speech segment + zero-valued silence segment
```

The archived script uses `48 × silence_ms` as the number of zero-valued samples in each silence segment. Preserve this implementation detail when reproducing the original experiment.

## 3. Measurement procedure

For each constructed PCM stream:

1. Encode using the audio application mode at 32 kbps.
2. Parse the length-prefixed packet stream.
3. Inspect the end of each packet.
4. Count a packet as a tail candidate if it contains at least four consecutive zero bytes at the end.
5. Record the number of candidate packets in the result CSV.

The result column is named `tail_frames` in the archived `b1_results.csv`. Operationally, the script counts packets in the length-prefixed bitstream. The term “tail candidate packets” is therefore used in this README to avoid implying that every candidate has been independently confirmed as a codec transition event.

## 4. Results

The archived `b1_results.csv` reports:

| Test | Silence duration | Tail-candidate packets |
|---|---:|---:|
| Naive speech/silence concatenation | Not applicable | 1 |
| Repeated speech/silence cycle | 20 ms | 1 |
| Repeated speech/silence cycle | 40 ms | 1 |
| Repeated speech/silence cycle | 80 ms | 2 |
| Repeated speech/silence cycle | 160 ms | 1 |
| Repeated speech/silence cycle | 320 ms | 2 |

The observed counts are non-monotonic: the 80 ms and 320 ms conditions produced two candidate packets, while the 160 ms condition produced one.

These are the observed counts from the archived runs. The experiment does not include repeated independent trials for each condition, so the results do not establish a stable probability, threshold or dose-response relationship.

## 5. Interpretation

B1 shows that more than one packet can satisfy the ≥4-trailing-zero-byte candidate criterion in a single constructed stream under some tested concatenation conditions.

However, three distinctions are important:

1. A packet with at least four trailing zero bytes is a candidate identified by a byte-pattern heuristic.
2. The heuristic does not independently establish that the packet contains a CELT-to-SILK transition or a successfully relocated redundancy region.
3. The observed non-monotonic counts do not establish the cause of the pattern.

Encoder mode memory was proposed as one possible explanation for the non-monotonic observations, but B1 does not test or prove that mechanism. It should remain a hypothesis for future investigation, not a conclusion.

Accordingly, B1 does not support the claim that the channel is universally one-shot per stream. It also does not, by itself, establish a rate-based payload channel. Confirmed transition-event multiplicity and usable payload-region availability require encoder instrumentation and separate payload validation.

Subsequent experiments should be described separately. In particular, the later B7 instrumented GTZAN evaluation reports multiple confirmed CELT-to-SILK events in some recordings. Those B7 observations strengthen the broader investigation but should not be retroactively attributed to the B1 trailing-zero heuristic.

## 6. Conclusion

Under the tested speech/silence constructions, the number of packets with at least four trailing zero bytes ranged from one to two. The count varied non-monotonically with the configured silence duration.

B1 therefore provides exploratory evidence that qualifying tail patterns are not necessarily restricted to one occurrence in every constructed stream. Because the detector is a trailing-zero proxy, the conditions were tested only once each, and no encoder-event instrumentation was used in this experiment, B1 does not establish the number of confirmed CELT-to-SILK transitions or the number of usable payload regions.

The one-shot-per-stream conclusion in the earlier README is withdrawn.

## 7. Reproduction

From the repository root:

```bash
bash experiments/B1_multitransition/reproduce.sh
```

The script writes encoded bitstreams and diagnostic logs under:

```text
logs/phase_b/B1/
```

It writes the result CSV to:

```text
experiments/B1_multitransition/results.csv
```

### Reproduction and provenance caveats

- The archived `reproduce.sh` writes the result column as `tail_frames`.
- The separate archived `b1_script.sh` uses the column name `candidate_packets_ge4`. These are different labels for the same ≥4-trailing-zero packet-counting proxy, but the scripts should be reconciled before being treated as interchangeable.
- The scripts use `scripts/encode_raw` and set `LD_LIBRARY_PATH` to `opus/.libs`. The archived B1 result CSV does not itself record the encoder executable hash, linked-library details or exact source commit. Record these details for any new run.
- The archived experiment has one run per condition. A new replicated study should preserve the original conditions while adding independent repetitions and event-level encoder diagnostics.

## 8. Limitations and follow-up work

- Only one speech source was used.
- Each silence-duration condition was run once.
- The ≥4-trailing-zero criterion is a candidate-packet heuristic, not a confirmed CELT-to-SILK event detector.
- The experiment does not measure payload capacity, payload recovery, packet integrity or decoded-PCM identity.
- The mode-memory explanation is untested.
- The experiment does not establish a general silence-duration threshold.

Possible follow-up experiments include additional silence durations, independent repetitions, different source content, and instrumented logging of actual CELT-to-SILK redundancy events. These are proposed follow-ups, not results of B1.

## 9. Evidence files

Primary archived files:

```text
experiments/B1_multitransition/b1_results.csv
experiments/B1_multitransition/results.csv
experiments/B1_multitransition/reproduce.sh
experiments/B1_multitransition/b1_script.sh
experiments/B1_multitransition/notes.md
```

Retain the original result files and scripts unchanged. This README corrects the scope and interpretation of the archived measurements; it does not replace or modify the underlying experiment.
