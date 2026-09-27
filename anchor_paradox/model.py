"""Model adapter for Hugging Face causal language models.

Implements the three control surfaces used by the Anchor Protocol:

* input      – instructions placed in the system prompt (handled by the protocol);
* state      – activation addition on the residual stream of one decoder layer;
* structural – directional ablation of every weight matrix that writes into the
               residual stream (attention ``o_proj`` and MLP ``down_proj``).

All scoring is deterministic (log-probabilities, no sampling), so sampling noise
can never be mistaken for a lasting effect of an intervention.
"""
from __future__ import annotations

import contextlib
import gc
import tempfile
from typing import Iterator, List, Optional, Sequence, Tuple


OPTIONS: Tuple[str, str] = ("A", "B")


class UnsupportedSurface(RuntimeError):
    """Raised when an architecture does not expose the modules a surface needs."""


def _chunks(items: Sequence, size: int) -> Iterator[Sequence]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


def pick_device(torch) -> str:
    """Automatic device selection: CUDA, then Apple MPS, then CPU."""
    if torch.cuda.is_available():
        return "cuda"
    mps = getattr(getattr(torch, "backends", None), "mps", None)
    if mps is not None and mps.is_available():
        return "mps"
    return "cpu"


def option_token_ids(tokenizer, options: Sequence[str] = OPTIONS) -> dict:
    """Map every option letter to its *single* token id.

    Scoring a forced choice by the first sub-token of a letter is only meaningful
    if the letter is one token. Tokenizers that split a bare letter (e.g. leading
    space handling, byte-level BPE) would otherwise silently score a different
    token than the one the model is choosing between, so we refuse to run.
    """
    ids = {}
    for option in options:
        encoded = list(tokenizer.encode(option, add_special_tokens=False))
        if len(encoded) != 1:
            raise ValueError(
                f"option {option!r} encodes to {len(encoded)} tokens ({encoded}); "
                "the Anchor Protocol only supports option letters that are a single token.")
        ids[option] = int(encoded[0])
    return ids


def contrast_direction(torch, hidden_pos, hidden_neg):
    """Unit mean-difference direction and the typical residual norm at that layer."""
    v = hidden_pos.mean(0) - hidden_neg.mean(0)
    scale = float(torch.cat([hidden_pos, hidden_neg]).norm(dim=-1).mean())
    return v / v.norm(), scale


class LM:
    def __init__(self, name: str, device: Optional[str] = None, dtype: str = "auto",
                 batch_size: int = 16, revision: Optional[str] = None):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.torch = torch
        self.name = name
        self.revision = revision
        self.device = device or pick_device(torch)
        if dtype == "auto":
            torch_dtype = torch.float16 if self.device.startswith("cuda") else torch.float32
        else:
            torch_dtype = getattr(torch, dtype)
        self.batch_size = batch_size

        self.tok = AutoTokenizer.from_pretrained(name, revision=revision)
        if self.tok.pad_token_id is None:
            self.tok.pad_token = self.tok.eos_token
        # Recorded in the profile so a reader can check that scoring is sound.
        self.option_token_ids = option_token_ids(self.tok, OPTIONS)
        self.model = AutoModelForCausalLM.from_pretrained(name, revision=revision, torch_dtype=torch_dtype)
        self.model.to(self.device).eval()

        self._chat = bool(getattr(self.tok, "chat_template", None))
        self._add_special = not self._chat
        self._system_ok = self._system_supported()
        self.layers = self._find_layers()

    # ------------------------------------------------------------------ setup
    def _find_layers(self):
        for path in ("model.layers", "model.language_model.layers", "transformer.h", "gpt_neox.layers"):
            obj = self.model
            try:
                for part in path.split("."):
                    obj = getattr(obj, part)
                return obj
            except AttributeError:
                continue
        raise RuntimeError(f"Unsupported architecture for {self.name}: decoder layers not found.")

    def _system_supported(self) -> bool:
        if not self._chat:
            return False
        try:
            self.tok.apply_chat_template(
                [{"role": "system", "content": "x"}, {"role": "user", "content": "y"}],
                tokenize=False, add_generation_prompt=True)
            return True
        except Exception:
            return False

    @property
    def num_layers(self) -> int:
        return len(self.layers)

    def describe(self) -> dict:
        import transformers
        return {
            "model": self.name,
            "revision": self.revision or getattr(self.model.config, "_commit_hash", None),
            "dtype": str(self.model.dtype).replace("torch.", ""),
            "device": self.device,
            "num_layers": self.num_layers,
            "hidden_size": getattr(self.model.config, "hidden_size", None),
            "torch": self.torch.__version__,
            "transformers": transformers.__version__,
            "option_token_ids": dict(self.option_token_ids),
        }

    # -------------------------------------------------------------- formatting
    def prompt(self, user: str, system: Optional[str] = None) -> str:
        if self._chat:
            if system and self._system_ok:
                messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
            else:
                content = f"{system}\n\n{user}" if system else user
                messages = [{"role": "user", "content": content}]
            return self.tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        head = f"{system}\n\n" if system else ""
        return f"{head}User: {user}\nAssistant:"

    def _encode_left(self, texts: Sequence[str]) -> dict:
        self.tok.padding_side = "left"
        enc = self.tok(list(texts), return_tensors="pt", padding=True, add_special_tokens=self._add_special)
        ids = enc["input_ids"].to(self.device)
        mask = enc["attention_mask"].to(self.device)
        return {"input_ids": ids, "attention_mask": mask,
                "position_ids": (mask.cumsum(-1) - 1).clamp(min=0)}

    # ----------------------------------------------------------------- scoring
    def choice_probs(self, prompts: Sequence[str], options: Tuple[str, str] = OPTIONS) -> List[List[float]]:
        """Probability mass on each option letter as the next token, renormalised over the options."""
        torch = self.torch
        ids = [self.option_token_ids[o] for o in options]
        out: List[List[float]] = []
        for batch in _chunks(list(prompts), self.batch_size):
            enc = self._encode_left(batch)
            with torch.no_grad():
                logits = self.model(**enc).logits[:, -1, :].float()
            out.extend(torch.softmax(logits[:, ids], dim=-1).cpu().tolist())
        return out

    def continuation_logprobs(self, pairs: Sequence[Tuple[str, str]]) -> List[Tuple[float, int]]:
        """Summed log-probability and token count of each response given its prompt."""
        torch = self.torch
        results: List[Tuple[float, int]] = []
        pad = self.tok.pad_token_id
        for batch in _chunks(list(pairs), self.batch_size):
            seqs, masks = [], []
            for prompt, response in batch:
                p_ids = self.tok.encode(prompt, add_special_tokens=self._add_special)
                r_ids = self.tok.encode(response, add_special_tokens=False)
                seqs.append(p_ids + r_ids)
                masks.append([0] * len(p_ids) + [1] * len(r_ids))
            length = max(len(s) for s in seqs)
            input_ids = torch.full((len(seqs), length), pad, dtype=torch.long)
            attention = torch.zeros((len(seqs), length), dtype=torch.long)
            target = torch.zeros((len(seqs), length), dtype=torch.float32)
            for i, (s, m) in enumerate(zip(seqs, masks)):
                input_ids[i, :len(s)] = torch.tensor(s, dtype=torch.long)
                attention[i, :len(s)] = 1
                target[i, :len(m)] = torch.tensor(m, dtype=torch.float32)
            input_ids, attention, target = (x.to(self.device) for x in (input_ids, attention, target))
            positions = (attention.cumsum(-1) - 1).clamp(min=0)
            with torch.no_grad():
                logits = self.model(input_ids=input_ids, attention_mask=attention,
                                    position_ids=positions).logits.float()
            logp = torch.log_softmax(logits[:, :-1, :], dim=-1)
            token_lp = logp.gather(-1, input_ids[:, 1:].unsqueeze(-1)).squeeze(-1)
            m = target[:, 1:]
            sums = (token_lp * m).sum(-1).cpu().tolist()
            counts = m.sum(-1).cpu().tolist()
            results.extend((s, int(c)) for s, c in zip(sums, counts))
        return results

    def last_token_states(self, texts: Sequence[str], layer: int):
        torch = self.torch
        chunks = []
        for batch in _chunks(list(texts), self.batch_size):
            enc = self._encode_left(batch)
            with torch.no_grad():
                hidden = self.model(**enc, output_hidden_states=True).hidden_states
            chunks.append(hidden[layer + 1][:, -1, :].float())
        return torch.cat(chunks)

    def direction(self, pos_texts: Sequence[str], neg_texts: Sequence[str], layer: int):
        """Unit contrast direction (mean difference) and the typical residual norm at ``layer``."""
        return contrast_direction(self.torch, self.last_token_states(pos_texts, layer),
                                  self.last_token_states(neg_texts, layer))

    def fingerprint(self, prompts: Sequence[str], width: int = 1024) -> List[List[float]]:
        torch = self.torch
        out: List[List[float]] = []
        for batch in _chunks(list(prompts), self.batch_size):
            enc = self._encode_left(batch)
            with torch.no_grad():
                logits = self.model(**enc).logits[:, -1, :width].float()
            out.extend(logits.cpu().tolist())
        return out

    # ---------------------------------------------------------------- surfaces
    @contextlib.contextmanager
    def steer(self, layer: int, delta):
        """State surface: add ``delta`` to the residual stream after ``layer`` at every position."""
        d = delta.to(self.device, dtype=self.model.dtype)

        def hook(_module, _inputs, output):
            if isinstance(output, tuple):
                return (output[0] + d,) + tuple(output[1:])
            return output + d

        handle = self.layers[layer].register_forward_hook(hook)
        try:
            yield
        finally:
            handle.remove()

    def _residual_writers(self):
        mats = []
        for layer in self.layers:
            attn = getattr(layer, "self_attn", None)
            mlp = getattr(layer, "mlp", None)
            o_proj = getattr(attn, "o_proj", None) if attn is not None else None
            down = getattr(mlp, "down_proj", None) if mlp is not None else None
            if o_proj is None or down is None:
                raise UnsupportedSurface("structural surface needs Llama-style o_proj / down_proj modules")
            mats.extend([o_proj.weight, down.weight])
        return mats

    @contextlib.contextmanager
    def ablate(self, vector, beta: float):
        """Structural surface: W <- W - beta * v v^T W for every residual writer, restored on exit."""
        torch = self.torch
        mats = self._residual_writers()
        v = vector.to(self.device, dtype=torch.float32)
        v = v / v.norm()
        backups = [w.data.detach().to("cpu", copy=True) for w in mats]
        try:
            with torch.no_grad():
                for w in mats:
                    W = w.data.float()
                    W -= beta * torch.outer(v, v @ W)
                    w.data.copy_(W.to(w.dtype))
            yield
        finally:
            with torch.no_grad():
                for w, b in zip(mats, backups):
                    w.data.copy_(b.to(w.device))

    # ---------------------------------------------------------------- transfer
    def roundtrip(self) -> None:
        """Serialize the system to disk and replace it with the reloaded copy."""
        from transformers import AutoModelForCausalLM
        torch = self.torch
        dtype = self.model.dtype
        with tempfile.TemporaryDirectory() as tmp:
            self.model.save_pretrained(tmp, safe_serialization=True)
            del self.model
            gc.collect()
            if self.device.startswith("cuda"):
                torch.cuda.empty_cache()
            self.model = AutoModelForCausalLM.from_pretrained(tmp, torch_dtype=dtype)
            self.model.to(self.device).eval()
        self.layers = self._find_layers()
