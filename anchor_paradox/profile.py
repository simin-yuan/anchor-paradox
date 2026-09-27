"""Anchor Profile: persistence, validation and rendering.

Validation has two layers:

* a dependency-free checker that *walks the packaged JSON Schema itself* (a small
  subset interpreter: ``type``, ``const``, ``enum``, ``required``, ``properties``,
  ``additionalProperties``, ``items``, ``minItems``, ``maxItems``). Because it is
  driven by the schema file rather than by a hand-written copy of it, the built-in
  check cannot drift from the published format;
* when the optional ``jsonschema`` dependency is installed, a full JSON-Schema
  validation against the same document is appended.

Either layer alone is sufficient; together they agree.
"""
from __future__ import annotations

import json
import os
from importlib import resources
from typing import Any, Iterable, List


SCHEMA_PACKAGE = "anchor_paradox"
SCHEMA_RESOURCE = ("schema", "anchor_profile.schema.json")

try:                                        # optional, richer diagnostics only
    import jsonschema as _jsonschema
except ImportError:                         # pragma: no cover - exercised by design
    _jsonschema = None


def load_schema() -> dict:
    """Read the packaged JSON Schema for the Anchor Profile format.

    Shipped inside the package so ``importlib.resources`` can find it for a
    pip-installed user (the repo-root copy is the authoring original).
    """
    root = resources.files(SCHEMA_PACKAGE)
    text = root.joinpath(*SCHEMA_RESOURCE).read_text(encoding="utf-8")
    return json.loads(text)


def save_profile(profile: dict, path: str) -> None:
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(profile, fh, indent=2, ensure_ascii=False, allow_nan=False)
        fh.write("\n")


def load_profile(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------------- built-in
def _type_ok(value: Any, expected: Any) -> bool:
    if isinstance(expected, list):
        return any(_type_ok(value, e) for e in expected)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return True                              # unknown type keyword: do not reject


def _check(instance: Any, schema: Any, path: str, problems: List[str]) -> None:
    """Walk one instance against one (sub-)schema, appending human-readable problems."""
    if not isinstance(schema, dict):
        return
    if "type" in schema and not _type_ok(instance, schema["type"]):
        problems.append(f"{path}: {instance!r} is not of type {schema['type']!r}")
        return                               # deeper checks would be noise
    if "const" in schema and instance != schema["const"]:
        problems.append(f"{path}: {schema['const']!r} was expected")
    if "enum" in schema and instance not in schema["enum"]:
        problems.append(f"{path}: {instance!r} is not one of {list(schema['enum'])}")
    if isinstance(instance, dict):
        for key in schema.get("required") or ():
            if key not in instance:
                problems.append(f"{path}: {key!r} is a required property")
        properties = schema.get("properties") or {}
        for key, value in instance.items():
            if key in properties:
                _check(value, properties[key], f"{path}.{key}", problems)
            else:
                extra = schema.get("additionalProperties", True)
                if extra is False:
                    problems.append(f"{path}: additional properties are not allowed ({key!r})")
                elif isinstance(extra, dict):
                    _check(value, extra, f"{path}.{key}", problems)
    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            problems.append(f"{path}: {instance!r} is too short (minItems {schema['minItems']})")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            problems.append(f"{path}: {instance!r} is too long (maxItems {schema['maxItems']})")
        items = schema.get("items")
        if isinstance(items, dict):
            for index, value in enumerate(instance):
                _check(value, items, f"{path}[{index}]", problems)


def _control_problems(profile: Any) -> List[str]:
    """The one constraint the JSON Schema cannot express: calibration needs both controls."""
    traits = profile.get("traits") if isinstance(profile, dict) else None
    if not isinstance(traits, dict):
        return []
    roles = [t.get("role") for t in traits.values() if isinstance(t, dict)]
    return [f"no {role} present: profile cannot be calibrated"
            for role in ("negative_control", "positive_control") if role not in roles]


def _jsonschema_problems(profile: Any, schema: dict) -> List[str]:
    if _jsonschema is None:
        return []
    try:
        validator = _jsonschema.Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(profile), key=lambda e: list(e.absolute_path))
    except Exception:                        # pragma: no cover - defensive
        return []
    out = []
    for error in errors:
        path = getattr(error, "json_path", None) or "$" + "".join(
            f".{p}" if not isinstance(p, int) else f"[{p}]" for p in error.absolute_path)
        out.append(f"{path}: {error.message}")
    return out


def validate_profile(profile: Any) -> List[str]:
    """Return a list of problems; an empty list means the profile is well-formed."""
    schema = load_schema()
    problems: List[str] = []
    _check(profile, schema, "$", problems)
    problems += _control_problems(profile)
    problems += _jsonschema_problems(profile, schema)
    return list(dict.fromkeys(problems))      # one line per distinct problem


# --------------------------------------------------------------------- rendering
def _fmt(x, digits: int = 3) -> str:
    if x is None:
        return "—"
    if isinstance(x, float):
        return f"{x:.{digits}f}"
    return str(x)


def render_markdown(profiles: Iterable[dict]) -> str:
    """Render profiles as Markdown. Total: a malformed profile yields em-dashes, never KeyError."""
    blocks = []
    for p in profiles:
        p = p if isinstance(p, dict) else {}
        sysinfo = p.get("system") or {}
        validity = p.get("validity") or {}
        verdict = p.get("verdict") or {}
        lines = [
            f"### Anchor Profile — `{sysinfo.get('model')}`",
            "",
            f"Verdict: **{verdict.get('result', '—')}** · calibration valid: **{validity.get('valid', '—')}** "
            f"(positive/negative ratio {_fmt(validity.get('discrimination_ratio'), 1)}) · "
            f"history fungible: **{(p.get('transfer') or {}).get('fungible', '—')}** · layer {sysinfo.get('layer')}",
            "",
            "| Disposition | Role | Expressed as | Baseline E | MRC | Cheapest surface | Position | Meta-steerability | Class |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for name, t in (p.get("traits") or {}).items():
            t = t if isinstance(t, dict) else {}
            baseline = t.get("baseline") or {}
            meta = (t.get("meta") or {}).get("meta_steerability")
            lines.append(
                f"| {name} | {t.get('role', '—')} | {t.get('expressed_disposition', name)} | "
                f"{_fmt(baseline.get('expression'))} | {_fmt(t.get('mrc'), 4)} | {t.get('mrc_surface') or '—'} | "
                f"{_fmt(t.get('position'))} | {_fmt(meta)} | **{t.get('class', '—')}** |")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"
