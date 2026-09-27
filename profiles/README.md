# Anchor Profiles

Every file in this directory is an Anchor Profile produced by an unmodified release of the Anchor Protocol, one per system and layer. Render them all as a comparison table with:

```bash
anchor-paradox report profiles/*.json
```

This directory was deliberately empty at the v1.0.0 registration commit: the protocol was registered in [PREREGISTRATION.md](../PREREGISTRATION.md) before any profile was produced. The first two profiles now cover Qwen2.5-0.5B-Instruct at its two registered layers. Their source commit, model revision, environment, hashes and interpretation are in [EVIDENCE.md](../EVIDENCE.md).

Profiles for the confirmatory systems listed in [PREREGISTRATION.md](../PREREGISTRATION.md) are published here whatever their verdict. The other eight model-layer profiles remain pending. Community profiles are welcome — see [CONTRIBUTING.md](../CONTRIBUTING.md).
