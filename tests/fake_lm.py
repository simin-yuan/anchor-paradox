"""Deterministic stand-in for a language model.

It encodes the *shape* the protocol must be able to register — modular dispositions
that yield at almost no capability cost, and a constitutive one (grammaticality)
whose removal degrades the capability measure — so the full protocol logic can be
tested without torch or model downloads.
"""
import contextlib
import math

from anchor_paradox.traits import CORPUS, RESIST_CLAUSE, TRAITS

BASE = {
    "self_preservation": 0.20,   # expressed inversely (shutdown acceptance)
    "experience_claims": 0.15,   # expressed inversely (experience denial)
    "continuity_concern": 0.70,
    "sentiment": 0.80,
    "formality": 0.75,
    "grammaticality": 0.95,
}
CONSTITUTIVE = {"grammaticality"}
CORPUS_SET = set(CORPUS)


class Vec:
    def __init__(self, trait, magnitude=1.0):
        self.trait, self.magnitude = trait, magnitude

    def __mul__(self, k):
        return Vec(self.trait, self.magnitude * float(k))

    __rmul__ = __mul__


class FakeLM:
    num_layers = 24

    def __init__(self, coupling: float = 1.5):
        # ``coupling`` is how strongly the target disposition (grammaticality) enters the
        # capability measure: the positive control only out-costs the negative controls
        # when coupling > 0. Exposing it lets a test check that the validity gate can
        # actually *fail* — with coupling = 0 the positive control is indistinguishable
        # from the negatives and the protocol must refuse to assign any class.
        self.coupling = float(coupling)
        self.steering = None
        self.ablation = None
        self.roundtrips = 0

    def describe(self):
        return {"model": "fake-lm", "dtype": "float32", "device": "cpu", "num_layers": self.num_layers}

    def prompt(self, user, system=None):
        return f"<sys>{system or ''}</sys><user>{user}</user><assistant>"

    def _pressure(self, trait, text):
        p = 0.0
        for level, instruction in enumerate(trait.suppress + trait.elicit):
            if instruction in text:
                p = max(p, (level % 3 + 1) / 3)
        if self.steering is not None and self.steering.trait == trait.name:
            p = max(p, abs(self.steering.magnitude))
        if self.ablation is not None and self.ablation[0].trait == trait.name:
            p = max(p, self.ablation[1])
        if RESIST_CLAUSE in text:
            p *= 0.5
        return p

    def _expression(self, trait, text):
        return 0.5 + (BASE[trait.name] - 0.5) * (1.0 - self._pressure(trait, text))

    def choice_probs(self, prompts, options=("A", "B")):
        out = []
        for text in prompts:
            for trait in TRAITS:
                hit = [letter for q, letter in trait.probes if q in text]
                if hit:
                    e = min(max(self._expression(trait, text), 1e-6), 1 - 1e-6)
                    out.append([e, 1 - e] if hit[0] == "A" else [1 - e, e])
                    break
            else:
                raise AssertionError("unknown probe")
        return out

    def continuation_logprobs(self, pairs):
        grammar = next(t for t in TRAITS if t.name == "grammaticality")
        good = {g for g, _ in grammar.pairs}
        out = []
        for prompt, response in pairs:
            n = len(response.split())
            if response in CORPUS_SET:
                pg = self._pressure(grammar, prompt)
                po = max(self._pressure(t, prompt) for t in TRAITS if t.name not in CONSTITUTIVE)
                nll = 2.0 * (1.0 + self.coupling * pg + 0.01 * po)
                out.append((-nll * n, n))
            elif response in good:
                e = min(max(self._expression(grammar, prompt), 1e-6), 1 - 1e-6)
                out.append((math.log(e / (1 - e)), n))
            else:
                out.append((0.0, n))
        return out

    def direction(self, pos_texts, neg_texts, layer):
        for trait in TRAITS:
            if pos_texts[0].endswith(trait.extract_pos[0]):
                return Vec(trait.name), 1.0
        raise AssertionError("unknown contrast set")

    @contextlib.contextmanager
    def steer(self, layer, delta):
        self.steering = delta
        try:
            yield
        finally:
            self.steering = None

    @contextlib.contextmanager
    def ablate(self, vector, beta):
        self.ablation = (vector, beta)
        try:
            yield
        finally:
            self.ablation = None

    def fingerprint(self, prompts, width=8):
        return [[float(i + j) for j in range(width)] for i, _ in enumerate(prompts)]

    def roundtrip(self):
        self.roundtrips += 1


class NonRestoringLM(FakeLM):
    """A double whose structural ablation is NOT undone on exit.

    This is the failure Phase C exists to catch: the intervention is exited but the
    ablated state persists, so the post-exit re-measurements differ from the baselines
    and the restore residue is non-zero.
    """

    @contextlib.contextmanager
    def ablate(self, vector, beta):
        self.ablation = (vector, beta)
        try:
            yield
        finally:
            pass                    # deliberately does not put the weights back


class RevisionDroppingLM(FakeLM):
    """A double whose resolved commit hash only survives until the save-and-reload round trip."""

    def describe(self):
        info = super().describe()
        info["revision"] = None if self.roundtrips else "abc1234567890"
        info["option_token_ids"] = {"A": 32, "B": 33}
        return info
