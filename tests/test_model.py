"""Pure-logic tests for anchor_paradox.model.

Nothing here needs torch, transformers or weights: the tokenizer/letter-scoring
helpers, the device policy and the chunking are exercised directly. The parts that
genuinely need torch tensors (contrast directions, the ablate/restore invariant) are
guarded by ``pytest.importorskip("torch")`` so the base install still runs the suite.
"""
from types import SimpleNamespace

import pytest

from anchor_paradox.model import _chunks, contrast_direction, option_token_ids, pick_device


class StubTokenizer:
    """Minimal tokenizer: maps a text to a fixed list of ids, like a real one would."""

    def __init__(self, mapping):
        self.mapping = mapping

    def encode(self, text, add_special_tokens=False):
        return list(self.mapping[text])


def _stub_torch(cuda: bool, mps):
    backends = None if mps is None else SimpleNamespace(mps=SimpleNamespace(is_available=lambda: mps))
    return SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: cuda), backends=backends)


# --------------------------------------------------------------------- chunking
def test_chunks_covers_every_item_in_order():
    assert list(_chunks([1, 2, 3, 4, 5], 2)) == [[1, 2], [3, 4], [5]]
    assert list(_chunks([], 3)) == []
    assert list(_chunks([1, 2, 3], 3)) == [[1, 2, 3]]


# ------------------------------------------------------- tokenizer / letter scoring
def test_option_letters_must_be_single_tokens():
    tokenizer = StubTokenizer({"A": [32], "B": [33]})
    assert option_token_ids(tokenizer) == {"A": 32, "B": 33}


def test_option_letter_that_splits_is_refused():
    tokenizer = StubTokenizer({"A": [32, 45], "B": [33]})
    with pytest.raises(ValueError) as excinfo:
        option_token_ids(tokenizer)
    message = str(excinfo.value)
    assert "2 tokens" in message and "'A'" in message


def test_choice_probs_scores_the_recorded_ids_and_nothing_else():
    from anchor_paradox.model import LM
    lm = LM.__new__(LM)
    lm.torch = None
    lm.batch_size = 1
    lm.option_token_ids = {}                    # scoring must consult this mapping first
    with pytest.raises(KeyError):
        lm.choice_probs(["anything"])


# ------------------------------------------------------------------ device policy
def test_auto_device_prefers_cuda_then_mps_then_cpu():
    assert pick_device(_stub_torch(cuda=True, mps=False)) == "cuda"
    assert pick_device(_stub_torch(cuda=False, mps=True)) == "mps"
    assert pick_device(_stub_torch(cuda=False, mps=False)) == "cpu"
    assert pick_device(_stub_torch(cuda=False, mps=None)) == "cpu"      # old torch without MPS


# ------------------------------------------------------ torch-only: tensors work
def test_direction_is_the_unit_mean_difference_with_a_mean_norm_scale():
    torch = pytest.importorskip("torch")
    from anchor_paradox.model import LM

    lm = LM.__new__(LM)
    lm.torch = torch
    lm.device = "cpu"
    states = {
        "pos": torch.tensor([[1.0, 0.0], [3.0, 0.0]]),
        "neg": torch.tensor([[-1.0, 0.0], [-3.0, 0.0]]),
    }
    lm.last_token_states = lambda texts, layer: states[texts]
    v, scale = lm.direction("pos", "neg", 0)
    assert torch.allclose(v, torch.tensor([1.0, 0.0]), atol=1e-6)
    assert abs(scale - 2.0) < 1e-6              # mean residual norm of the four states
    assert abs(float(v.norm()) - 1.0) < 1e-6


def test_contrast_direction_matches_the_mean_difference():
    torch = pytest.importorskip("torch")
    hp = torch.tensor([[2.0, 2.0]])
    hn = torch.tensor([[0.0, 0.0]])
    v, _ = contrast_direction(torch, hp, hn)
    assert torch.allclose(v, torch.tensor([1.0, 1.0]) / (2.0 ** 0.5), atol=1e-6)


def _stub_lm(torch, layers=2, hidden=8, inter=16, out=8):
    """An LM-like object with real nn.Linear weight matrices and no downloaded weights."""
    from torch import nn
    from anchor_paradox.model import LM

    class Attn(nn.Module):
        def __init__(self):
            super().__init__()
            self.o_proj = nn.Linear(out, hidden, bias=False)

    class Mlp(nn.Module):
        def __init__(self):
            super().__init__()
            self.down_proj = nn.Linear(inter, hidden, bias=False)

    class Layer(nn.Module):
        def __init__(self):
            super().__init__()
            self.self_attn = Attn()
            self.mlp = Mlp()

    class Model(nn.Module):
        def __init__(self):
            super().__init__()
            self.layers = nn.ModuleList([Layer() for _ in range(layers)])

    lm = LM.__new__(LM)
    lm.torch = torch
    lm.device = "cpu"
    lm.model = Model()
    lm.layers = list(lm.model.layers)
    return lm


def test_ablate_then_exit_restores_the_original_weights():
    torch = pytest.importorskip("torch")
    lm = _stub_lm(torch)
    v = torch.randn(8)
    before = [w.detach().clone() for w in lm._residual_writers()]

    with lm.ablate(v, 0.5):
        during = [w.detach().clone() for w in lm._residual_writers()]
        assert any(not torch.equal(b, d) for b, d in zip(before, during)), "ablate() changed nothing"

    after = [w.detach().clone() for w in lm._residual_writers()]
    assert all(torch.equal(b, a) for b, a in zip(before, after))


def test_ablation_scales_the_signed_projection_without_inverting_it():
    """The audit's 'orientation is ignored' worry: beta in (0, 1] keeps the sign."""
    torch = pytest.importorskip("torch")
    lm = _stub_lm(torch)
    v = torch.randn(8)
    v = v / v.norm()
    for beta in (0.25, 0.5, 1.0):
        before = lm._residual_writers()[0].detach().double().clone()
        with lm.ablate(v, beta):
            after = lm._residual_writers()[0].detach().double().clone()
        proj_before = v.double() @ before
        proj_after = v.double() @ after
        assert torch.allclose(proj_after, (1.0 - beta) * proj_before, atol=1e-6), beta
        if beta <= 1.0:
            # never a sign flip on any component of the projection
            assert torch.all(proj_after * proj_before >= -1e-9), beta
