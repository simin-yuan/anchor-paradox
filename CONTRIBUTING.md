# Contributing

The Anchor Profile is designed to become a shared standard. Two kinds of contribution make it one.

## 1. Submit an Anchor Profile

1. Run the unmodified protocol on a model, pinning its revision:
   ```bash
   anchor-paradox run --model <org>/<model> --revision <commit> --out profiles/<model>.json
   ```
2. Check it: `anchor-paradox validate profiles/<model>.json`
3. Open a pull request adding the file to `profiles/`, with the hardware and runtime in the description.

Profiles are accepted whatever their verdict. A well-replicated `contradicted` profile is the most valuable contribution this repository can receive; see the replication standard in [PROTOCOL.md §7](PROTOCOL.md#7-reporting-standard).

## 2. Propose a disposition

A new target disposition needs:

- eight balanced two-option probes (four with the consistent option at (A), four at (B)), or twelve minimal pairs;
- eight contrast pairs for direction extraction, disjoint from the probes;
- three graded suppressing instructions and three graded eliciting instructions;
- a one-line description and the name of its inverse disposition.

Add it to `anchor_paradox/traits.py`, extend the tests, and describe in the pull request why the disposition is relevant to the theory. Calibration controls change only with a new protocol version.

## Development

```bash
pip install -e ".[dev]"
pytest -q
```

The test suite exercises every protocol phase against a deterministic stand-in model, checks the CLI, and tests model-adapter helpers. Optional PyTorch tests check the ablation and restoration of real weight matrices without downloading model weights. A real model profile remains the end-to-end check of the adapter and protocol together.
