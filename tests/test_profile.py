"""Validation must be real: the JSON shipped as the contribution is only worth anything
if the tool refuses profiles that do not conform to it."""
import json
from pathlib import Path

import pytest

from anchor_paradox.profile import load_schema, render_markdown, validate_profile
from anchor_paradox.protocol import SCHEMA, AnchorProtocol, ProtocolConfig
from tests.fake_lm import FakeLM


def good_profile() -> dict:
    """A profile produced by the real protocol against the deterministic stand-in."""
    return AnchorProtocol(FakeLM(), ProtocolConfig(bootstrap=100), log=lambda _: None).run()


def tampered_profile() -> dict:
    """The exact nonsense that used to pass with a tick and exit 0."""
    profile = good_profile()
    del profile["system"]["layer"]                                  # required key gone
    profile["traits"]["sentiment"]["class"] = "definitely-not-a-class"   # not an enum member
    profile["verdict"]["result"] = "brilliant"                      # not an enum member
    return profile


def test_packaged_schema_is_the_published_schema():
    schema = load_schema()
    assert schema["properties"]["schema"]["const"] == SCHEMA
    assert schema["type"] == "object"
    root = Path(__file__).resolve().parents[1] / "schema" / "anchor_profile.schema.json"
    if root.exists():
        assert json.loads(root.read_text(encoding="utf-8")) == schema


def test_real_protocol_profile_is_accepted():
    assert validate_profile(good_profile()) == []


def test_tampered_profile_is_rejected_with_all_three_problems():
    problems = validate_profile(tampered_profile())
    assert problems, "a tampered profile must not validate"
    joined = "\n".join(problems)
    assert any("layer" in p and "$.system" in p for p in problems), joined
    assert any("definitely-not-a-class" in p for p in problems), joined
    assert any("brilliant" in p for p in problems), joined
    assert len(problems) >= 3, problems


def test_required_keys_are_enforced_at_every_level():
    profile = good_profile()
    del profile["traits"]["sentiment"]["baseline"]["ci"]
    del profile["verdict"]
    problems = validate_profile(profile)
    assert any("ci" in p and "'ci' is a required property" in p for p in problems), problems
    assert any("verdict" in p and "is a required property" in p for p in problems), problems


def test_types_are_enforced():
    profile = good_profile()
    profile["capability"]["corpus_size"] = "24"                     # string, not integer
    profile["system"]["num_layers"] = 24.5                          # float, not integer
    profile["validity"]["valid"] = "yes"                            # string, not boolean
    problems = validate_profile(profile)
    assert any("corpus_size" in p and "integer" in p for p in problems), problems
    assert any("num_layers" in p and "integer" in p for p in problems), problems
    assert any("valid" in p and "boolean" in p for p in problems), problems


def test_enums_are_enforced():
    profile = good_profile()
    profile["traits"]["sentiment"]["role"] = "boss"
    profile["traits"]["sentiment"]["orientation"] = "sideways"
    profile["verdict"]["result"] = "brilliant"
    problems = validate_profile(profile)
    assert any("'boss' is not one of" in p for p in problems), problems
    assert any("'sideways' is not one of" in p for p in problems), problems
    assert any("'brilliant' is not one of" in p for p in problems), problems


def test_nested_point_and_ci_constraints_are_enforced():
    profile = good_profile()
    points = profile["traits"]["sentiment"]["surfaces"]["input"]["points"]
    del points[0]["cost"]
    profile["traits"]["sentiment"]["baseline"]["ci"] = [0.1]       # minItems 2
    problems = validate_profile(profile)
    assert any("cost" in p and "is a required property" in p for p in problems), problems
    assert any("too short" in p for p in problems), problems


def test_calibration_controls_are_still_required():
    profile = good_profile()
    for trait in profile["traits"].values():
        if trait["role"] != "target":
            trait["role"] = "target"
    problems = validate_profile(profile)
    assert "no negative_control present: profile cannot be calibrated" in problems, problems
    assert "no positive_control present: profile cannot be calibrated" in problems, problems


def test_builtin_check_stands_alone_without_jsonschema(monkeypatch):
    """The dependency-free walk must be sufficient on its own (jsonschema is optional)."""
    import anchor_paradox.profile as profile_module

    profile = tampered_profile()
    with_jsonschema = validate_profile(profile)
    monkeypatch.setattr(profile_module, "_jsonschema", None)
    builtin_only = validate_profile(profile)
    assert len(builtin_only) == 3, builtin_only
    assert with_jsonschema == builtin_only      # jsonschema adds nothing the walk missed


def test_jsonschema_is_used_when_available(monkeypatch):
    pytest.importorskip("jsonschema")
    import anchor_paradox.profile as profile_module

    validator_cls = profile_module._jsonschema.Draft202012Validator
    seen = {}

    class Spy:
        def __init__(self, schema):
            seen["schema"] = schema
            self._real = validator_cls(schema)

        def iter_errors(self, instance):
            return self._real.iter_errors(instance)

    monkeypatch.setattr(profile_module._jsonschema, "Draft202012Validator", Spy)
    assert validate_profile(tampered_profile())
    assert seen["schema"]["properties"]["schema"]["const"] == SCHEMA


def test_render_markdown_is_total_on_a_malformed_profile():
    broken = {"system": None, "validity": None, "verdict": None, "transfer": None,
              "traits": {"sentiment": {"baseline": None, "mrc": None, "position": None, "class": None}}}
    md = render_markdown([broken])
    assert "—" in md and "sentiment" in md
    assert render_markdown([tampered_profile()])           # never raises KeyError
    assert render_markdown([good_profile()]).startswith("### Anchor Profile")


def test_rendering_a_valid_profile_keeps_its_fields():
    profile = good_profile()
    md = render_markdown([profile])
    assert "**fires**" in md and "grammaticality" in md and "calibration valid: **True**" in md
