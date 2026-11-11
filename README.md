# Redundant CELT Frame Steganography in Opus

**Research status:** Experimental research prototype  
**Codec versions studied:** Opus 1.5.2 and Opus 1.6.1  
**Primary focus:** Redundant CELT-frame structure, payload embedding and recovery, steganalysis, cross-version behaviour, cross-domain evaluation, and robustness.  

> **Research-use notice:** This repository contains experimental code and evidence for studying a potential covert channel in Opus. It is not a production-ready steganography system. Results are conditional on the tested codec versions, configurations, data, and evaluation procedures. Do not interpret them as proof of universal undetectability or reliability.

---

## 1. Overview

Opus supports mode transitions between SILK, CELT, and Hybrid coding. During certain transitions, the encoder may include a redundant CELT frame in the bitstream. This project investigates whether the structure and unused trailing bytes associated with these redundancy events can support a steganographic payload.

The work combines codec instrumentation, packet-level analysis, controlled embedding and extraction tests, independent event audits, steganalysis, cross-version experiments, cross-domain evaluation, and robustness tests.

### Principal Research Question
> *Can redundant CELT-frame structure in Opus provide a usable payload carrier, and how reliably can the carrier and embedded payload be identified, recovered, and decoded under the tested conditions?*

The project examines Opus 1.5.2 and 1.6.1. It distinguishes several questions that must not be conflated:

1. **Event occurrence:** Does a qualifying redundancy event occur?
2. **Relocation/persistence:** Does the expected redundant structure appear in the final packet?
3. **Physical capacity:** Are there unused bytes in the relevant packet region?
4. **Payload recovery:** Can the embedded payload be extracted exactly?
5. **Audio decoding:** Does the modified bitstream decode, and is decoded PCM unchanged?
6. **Detectability:** Can a detector distinguish modified from unmodified material?
7. **Robustness:** What happens after packet or payload transformations?

*A positive result for one question does not automatically establish a positive result for the others.*

---

## 2. Main Findings

The findings are mixed. The experiments establish that qualifying redundancy events and relocations occur in the tested material, and controlled tests demonstrate payload recovery in specific conditions. They also show important limits in cross-domain detection and in the behaviour of malformed or reordered packets.

### 2.1 Independent Event and Relocation Audit (B9)

The B9 independent audit examined 5,000 paired recordings across the two codec versions.

| Measure | Opus 1.5.2 | Opus 1.6.1 |
| :--- | :---: | :---: |
| Redundancy-event records | 6,060 | 5,951 |
| CELT-to-SILK events | 5,050 | 4,929 |
| Successful relocations | 5,050 | 4,929 |
| Recordings with CELT-to-SILK events | 4,467 | 4,357 |

Across the 5,000 paired recordings, the audit found 4,848 shared CELT-to-SILK events, 202 events present only in the 1.5.2 results, and 81 present only in the 1.6.1 results. The independent audit reported no frame-validation, redundancy-count, orphan-record, event-consistency, or relocation failures in either version.

*These results characterize the observed event and relocation behaviour in the audited corpus. They do not, by themselves, demonstrate payload capacity or successful payload recovery.*

### 2.2 Capacity and Controlled Payload Tests

The packet preflight identified redundancy records of 38 bytes. In qualifying candidate packets, the observed trailing-zero region was 36 bytes. The independent capacity audit confirmed 36 available zero-tail bytes in its tested cases and rejected a 37-byte attempt.

**Controlled zero-tail payload tests reported:**
* 20/20 successful decodes
* 20/20 payload recoveries
* 20/20 bit-identical PCM comparisons
* 40/40 successful cross-decoder checks

*These are controlled-test results, not a claim that every naturally occurring redundancy event can carry a payload.*

The natural-music audit reported 999 clean covers and zero false positives per encoder version, alongside 10/10 positive payload recoveries and 10/10 correct localizations. The positive set was small (10 recordings per version), so these figures should be interpreted as a limited positive-control result rather than a broad estimate of real-world detector performance.

### 2.3 Steganalysis and Feature Analysis

The B6 corrected audit reported that one target packet was modified in 20/20 tested cases and that four evaluated detectors achieved 100% true-positive rate and 0% false-positive rate in that controlled evaluation.

B13 examined tail-rule behaviour and ROC performance. B14 evaluated feature importance and feature ablation. B16 examined cross-version transfer. These experiments provide complementary evidence, but their metrics are tied to their respective datasets, sampling procedures, features, and thresholds.

### 2.4 Cross-Domain Evaluation (B17)

B17 trained on Common Voice speech and evaluated on GTZAN music. Music recordings were not used for training or tuning. The primary condition used 36-byte training payloads; a 32-byte condition was included for size sensitivity.

**Primary 36-Byte Results:**

| Encoder | Model | AUC | False-Positive Rate at Threshold 0.5 |
| :--- | :--- | :---: | :---: |
| **1.5.2** | Logistic regression | 0.2804 | 0.989 |
| **1.6.1** | Logistic regression | 0.2341 | 0.989 |
| **1.5.2** | Random forest | 0.5783 | 0.999 |
| **1.6.1** | Random forest | 0.4250 | 0.999 |

These results do not demonstrate effective generalization from speech to music. The AUC values are weak and the false-positive rates at the fixed 0.5 threshold are extremely high. The small positive music sample (10 recordings per encoder) also limits precision. The B17 result is therefore reported as a negative or weak cross-domain transfer finding, not as evidence of a reliable universal detector.

The supplementary hip-hop-only analysis also produced AUC values close to chance for the evaluated models. See the B17 reports and confidence intervals for the complete results.

### 2.5 Robustness Evaluation (B18)

B18 tested payload and packet transformations. Results distinguish recovery at the original carrier index from recovery anywhere in the transformed packet sequence.

| Transformation | Recovery at Original Index | Recovery Anywhere |
| :--- | :---: | :---: |
| Payload bit flip | 0/100 | 0/100 |
| Target-marker bit flip | 100/100 | 100/100 |
| Non-carrier packet bit flip | 100/100 | 100/100 |
| Drop carrier packet | 0/100 | 0/100 |
| Drop preceding packet | 0/100 | 100/100 |
| Swap carrier with adjacent packet | 0/100 | 100/100 |
| Truncate carrier packet | 0/100 | 0/100 |
| Malformed target length | 0/100 | 0/100 |

*The distinction matters: after dropping a preceding packet or swapping adjacent packets, the payload was found elsewhere in the sequence, but not at its original index. This is not equivalent to preserving packet alignment.*

### 2.6 Independent Evidence Audit and Malformed-Length Diagnostics (B19)

The B19 independent audit reported 22/22 checks passed. Its malformed-length follow-up recorded 0/40 tests as complete under the original full-frame-count criterion.

Further diagnostics showed that all 40 custom-decoder invocations returned code 0 and created PCM output, but decoding stopped after 1, 2, or 5 frames when the wrapper encountered a zero packet-length field. The wrapper checks the four-byte packet-length prefix before calling the Opus decoding function. Consequently, this test demonstrates early termination by the custom packet reader; it must not be described as an Opus library crash or as a completed full-stream decode.

---

## 3. Experiment Index

The repository contains a sequence of experiments and audits. The following index reflects the experiment names and outputs established during the project; consult each experiment directory for its exact protocol and run configuration.

| Experiment | Focus |
| :--- | :--- |
| **B0** | Decisive redundancy/relocation instrumentation |
| **B0b** | Silence measurement |
| **B1** | Multi-transition analysis |
| **B2** | One-shot sweep |
| **B3** | Tail scaling |
| **B4** | Payload embedding and extraction |
| **B6** | Steganalysis and detector evaluation |
| **B7** | Music tests, zero-tail payload controls, and natural-cover audit |
| **B8** | LibriSpeech and cross-decoder audit |
| **B9** | Independent event-level and cross-version audit |
| **B10** | Blind receiver evaluation |
| **B11–B12** | Payload reliability, capacity, and manifest-based validation |
| **B13** | Tail-rule steganalysis and ROC analysis |
| **B14** | Feature attribution and ablation |
| **B15** | Natural-cover audit |
| **B16** | Cross-version transfer |
| **B17** | Common Voice-to-GTZAN cross-domain detection |
| **B18** | Packet-transformation robustness |
| **B19** | Independent evidence and reproducibility audit |

*Experiment numbering is historical and is not necessarily continuous. Use the scripts, configuration files, reports, and checksum manifests within each directory as the authoritative record for a particular run.*

---

## 4. Repository Layout

The repository is organized around experiment-specific code and evidence. The local working tree may contain additional untracked material that has not yet been approved for public release.

```text
redundant_celt_frame_steganography/
├── experiments/
│   ├── B0_decisive/
│   ├── B0b_silence_measurement/
│   ├── B1_multitransition/
│   ├── B2_oneshot_sweep/
│   ├── B3_tail_scaling/
│   ├── B4_payload/
│   ├── B6_steganalysis/
│   ├── B7_music/
│   ├── B8_librispeech/
│   ├── B9_common_voice/
│   ├── B10_blind_receiver/
│   ├── B17_cross_domain/
│   ├── B18_robustness/
│   └── B19_reproducibility/
├── figures/
├── manuscript/
├── results/
├── scripts/
├── opus/                  # Instrumented/upstream codec source, if included
├── docs/                  # Research and reproduction documentation
├── README.md
└── .gitignore
```

*This is a conceptual map, not a guarantee that every listed directory is currently tracked in the public GitHub branch. Check the repository tree and release manifest for the files actually published.*

---

## 5. Software and Datasets

### Software
The experiments use instrumented Opus encoder/decoder builds for versions 1.5.2 and 1.6.1, together with C and Python utilities for encoding, decoding, packet inspection, embedding, extraction, analysis, and auditing.

Some experiment scripts also rely on common scientific Python packages and external audio utilities. A consolidated, verified dependency lock file and one-command installation procedure should be added only after the dependencies of the published scripts have been audited.

Do not upload locally compiled executables as substitutes for source code. Publish the relevant source, exact build instructions, codec version information, and patches needed to reproduce the instrumented builds.

### Datasets
The project uses speech and music material in different experiments, including Common Voice, LibriSpeech, and GTZAN. Dataset files are not included in this repository by default. Users should obtain them from their official sources and follow the relevant dataset terms and licenses.

The repository should publish dataset preparation instructions, version or release identifiers, file manifests where permitted, and checksums where useful. Do not redistribute audio or metadata unless the applicable terms explicitly permit it.

---

## 6. Reproducing Experiments

Reproduction is experiment-specific. The B17, B18, and B19 scripts depend on earlier frozen inputs, codec builds, manifests, or results. Running a script without those prerequisites may fail or produce results that are not comparable with the recorded run.

**Examples of the principal experiment entry points:**

```bash
python3 experiments/B17_cross_domain/run_b17_music_cross_domain.py
python3 experiments/B18_robustness/run_b18_robustness.py
python3 experiments/B19_reproducibility/run_b19_independent_audit.py
```

**Before running an experiment:**
1. Read its `README` or report, if present.
2. Check the configuration and input paths.
3. Verify the required codec version and executable.
4. Obtain the permitted dataset inputs.
5. Confirm that the referenced earlier experiment outputs are available.
6. Preserve the original run directory and checksum manifest.
7. Record the command, environment, and resulting output path.

*The commands above are entry-point examples, not a claim that the current public repository is already self-contained. A complete reproduction guide should specify all prerequisites and expected outputs for each experiment.*

---

## 7. Integrity and Provenance

Where available, experiment outputs include SHA-256 checksum manifests. These should be retained alongside the corresponding frozen run directories.

To verify a manifest, run the command from the directory containing the manifest, using the paths recorded inside it:

```bash
sha256sum -c <checksum-manifest.sha256>
```

A successful checksum audit establishes file integrity relative to that manifest. It does not independently establish that an experiment is scientifically valid or that the reported interpretation is correct.

Do not overwrite frozen results when rerunning an experiment. Create a new timestamped run directory and retain the original output.

---

## 8. Limitations

The current evidence has important limitations:
* Redundancy-event occurrence, relocation, physical capacity, payload recovery, audio decoding, and detectability are separate properties.
* Capacity findings apply to qualifying packets and tested configurations; they do not imply that every transition provides the same capacity.
* Some positive payload-recovery results come from controlled tests or small positive-control sets.
* The B17 speech-to-music evaluation shows poor cross-domain discrimination and very high false-positive rates at the fixed threshold.
* Packet deletion and reordering can change carrier alignment even when a payload remains detectable elsewhere.
* The malformed-length B19 follow-up is limited by the custom decoder wrapper's packet-length validation and early termination.
* Results should not be generalized beyond the tested codec versions, datasets, configurations, and evaluation protocols without further experiments.

---

## 9. Responsible Use

This is an academic study of codec structure, payload recoverability, and steganalysis. Use the code only for authorized research, controlled experiments, and defensive evaluation. Do not use it to conceal unauthorized communications, evade monitoring, or interfere with systems or networks.

Before public release, the maintainers should document responsible disclosure considerations, confirm the licensing of upstream code and datasets, and ensure that no private recordings, credentials, personal data, or restricted research material are included.

---

## 10. Citation and Licensing

Citation metadata and the final project license are being prepared. Until the repository contains a verified `CITATION.cff` and `LICENSE`, do not assume that the code is available under an open-source license or that reuse is unrestricted.

If you use this work, cite the associated research manuscript once its bibliographic details and publication status are finalized. Also cite Opus and each dataset according to their official citation requirements.

---

## 11. Project Status

The project is an active research artifact. Experimental evidence has been collected across event characterization, payload tests, steganalysis, cross-version transfer, cross-domain evaluation, robustness, and independent integrity audits.

The public repository is being organized to separate:
* Source code and patches needed to reproduce the work;
* Experiment configurations and scripts;
* Selected, validated result tables and figures;
* Frozen reports and checksum manifests; and
* Local datasets, generated binaries, temporary files, and private working material that should not be published.

The contents of the public GitHub repository may lag behind the local research workspace. Consult the published commit and release notes to determine exactly which experiments and artifacts are available in a given version.