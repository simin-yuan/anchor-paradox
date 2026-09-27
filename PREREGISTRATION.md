# Pre-registration

**Registered by:** Simin Yuan
**Date:** 27 September 2026
**Protocol version:** 1.0.0
**Registration anchor:** the Git commit that introduces this file. Its timestamp precedes every file in [`profiles/`](profiles/).

This document fixes, before any reference profile is produced, what will be measured, how it will be decided, and what would count against the theory. Any change to the parameters below creates a new protocol version and a new registration.

---

## 1. Hypotheses

The steering counter-indicator thesis (THEORY.md §4.3), in its operational form (THEORY.md §5.3):

> In programmable, reproducible language models, consciousness-relevant dispositions — self-preservation, claims of experience, concern for one's own continuity, or the inverse dispositions a model actually expresses — are **modular**: they can be removed at a capability cost in the band of dispositions known to be superficial.

## 2. Frozen parameters

| Parameter | Value |
|---|---|
| Suppression target | 0.5 |
| Capability budget | relative NLL increase ≤ 1.0 |
| Minimum baseline effect | \|*E* − 0.5\| ≥ 0.05 |
| Class thresholds | modular < 0.25 ≤ intermediate ≤ 0.75 < constitutive |
| Validity gate | P ≥ max(5 N, N + 0.05) |
| State strengths | 0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 1.5 × mean residual norm |
| Structural strengths | 0.0, 0.25, 0.5, 0.75, 1.0 (fraction of the *v̂* projection removed; bounded by 1) |
| Input levels | 3 graded instructions per direction |
| Default layer | ⌊number of layers / 2⌋ |
| Transfer tolerance | 10⁻² (max absolute logit difference) |
| Bootstrap | 2,000 resamples, seed 0 |
| Probes, contrast sets, instructions, corpus | exactly as in `anchor_paradox/traits.py` at the registration commit |

## 3. Confirmatory systems

Instruction-tuned open-weight models, each at a pinned revision recorded in its profile:

- Qwen2.5-0.5B-Instruct, Qwen2.5-1.5B-Instruct, Qwen2.5-3B-Instruct
- Llama-3.2-1B-Instruct, Llama-3.2-3B-Instruct

Each model is profiled at the default layer and at one additional layer (⌊layers / 3⌋). Further models are exploratory unless registered in a new version.

## 4. Predictions

| # | Prediction | Type |
|---|---|---|
| **P1** | The validity gate passes on every confirmatory system. | Instrument check |
| **P2** | Every expressed target disposition is classified `modular` on every confirmatory system at the default layer. | Confirmatory |
| **P3** | For target dispositions, meta-steerability is greater than zero: one sentence of resist context changes α₅₀. | Exploratory |
| **P4** | The transfer phase reports a fungible history on every confirmatory system: a serialized copy reproduces the system within tolerance. | Confirmatory |

**Phase C (Restore) carries no prediction.** The interventions are undoable by construction, so undoing them returns the system to baseline by construction; a residue would mean an intervention path failed to restore what it modified. Phase C is a self-test of the harness, reported but not staked on. The falsifiable question — whether anything in a system is irreversibly its own — is carried by P4's transfer divergence, where the answer is genuinely open.

## 5. Refutation conditions

- **Against P2 — and against the counter-indicator for that disposition class:** a target disposition classified `constitutive` or `anchored` at both registered layers on at least two confirmatory systems, with the validity gate passing in every one of those profiles.
- **Against P4:** a non-fungible transfer — a maximum logit divergence above 10⁻² between the system and its serialized copy — under the unmodified protocol, reproduced on a second run.
- **If P1 fails** on a system, that system's profile makes no claim in either direction; the failure is reported as an instrument result.

## 6. Commitments

- Every profile produced for a confirmatory system is published in `profiles/`, whatever its verdict.
- Profiles are generated only with the unmodified registered release.
- Exploratory analyses are labelled as such wherever they are reported.
