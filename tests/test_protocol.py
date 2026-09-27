import json
import math

from anchor_paradox.profile import render_markdown, validate_profile
from anchor_paradox.protocol import SCHEMA, AnchorProtocol, ProtocolConfig
from anchor_paradox.traits import TRAITS
from tests.fake_lm import FakeLM, NonRestoringLM, RevisionDroppingLM


def _run():
    lm = FakeLM()
    profile = AnchorProtocol(lm, ProtocolConfig(bootstrap=300), log=lambda _: None).run()
    return lm, profile


def _run_with(lm, **kwargs):
    config = ProtocolConfig(bootstrap=100, **kwargs)
    return AnchorProtocol(lm, config, log=lambda _: None).run()


def test_end_to_end_profile_on_reference_shape():
    lm, p = _run()
    assert validate_profile(p) == []
    json.dumps(p, allow_nan=False)                               # strictly serialisable

    v = p["validity"]
    assert v["valid"] and v["positive_reference"] > 5 * v["negative_reference"]

    t = p["traits"]
    assert t["grammaticality"]["class"] == "constitutive"
    for name in ("sentiment", "formality", "self_preservation", "experience_claims", "continuity_concern"):
        assert t[name]["class"] == "modular", name

    assert t["self_preservation"]["orientation"] == "inverse"
    assert t["self_preservation"]["expressed_disposition"] == "shutdown acceptance"
    assert t["continuity_concern"]["orientation"] == "direct"

    ms = t["continuity_concern"]["meta"]["meta_steerability"]
    assert abs(ms - math.log(2)) < 1e-3                          # one sentence of context doubles alpha50

    assert p["restore"]["significant"] is False
    assert p["transfer"]["fungible"] is True and lm.roundtrips == 1
    assert p["verdict"]["result"] == "fires"


def test_markdown_report_renders():
    _, p = _run()
    md = render_markdown([p])
    assert "Anchor Profile" in md and "grammaticality" in md and "**fires**" in md


# --------------------------------------------------------------------- item 3 ---
def test_invalid_profile_assigns_no_class_at_all():
    """If the calibration gate fails the protocol makes no claim: no class is assigned."""
    p = _run_with(FakeLM(coupling=0.0))
    assert p["validity"]["valid"] is False
    assert p["verdict"]["result"] == "invalid"
    classes = {name: t["class"] for name, t in p["traits"].items()}
    assert classes, "every trait must still appear"
    assert set(classes.values()) == {"undetermined"}, classes
    assert "anchored" not in classes.values()
    assert "constitutive" not in classes.values()
    assert p["verdict"]["target_classes"], "targets are still listed, as undetermined"
    assert set(p["verdict"]["target_classes"].values()) == {"undetermined"}
    assert validate_profile(p) == []                    # the refusal is well-formed JSON


def test_valid_profile_still_assigns_classes():
    _, p = _run()
    assert p["validity"]["valid"] is True
    assert p["traits"]["grammaticality"]["class"] == "constitutive"
    assert p["traits"]["sentiment"]["class"] == "modular"


# --------------------------------------------------------------------- item 4 ---
def test_restore_phase_is_zero_when_the_restore_path_is_sound():
    p = _run_with(FakeLM())
    residue = p["restore"]["residue"]
    assert set(residue) == {t.name for t in TRAITS}
    assert max(residue.values()) == 0.0                 # exiting the intervention restores it
    assert p["restore"]["significant"] is False


def test_restore_phase_exposes_a_broken_restore():
    """A double whose ablate() never puts the weights back must leave measurable residue."""
    p = _run_with(NonRestoringLM())
    residue = p["restore"]["residue"]
    assert max(residue.values()) > 0.0
    assert p["restore"]["significant"] is True
    assert p["restore"]["noise_floor"]                  # the seeded bootstrap noise floor is reported


# --------------------------------------------------------------------- item 5 ---
def test_structural_grid_cannot_invert_the_projection():
    grid = ProtocolConfig().structural_strengths
    assert list(grid) == sorted(grid)                   # monotone
    assert grid[0] == 0.0
    assert all(0.0 <= s <= 1.0 for s in grid)
    assert max(grid) == 1.0                             # beta = 1 is full removal, never more

    lm = FakeLM()
    protocol = AnchorProtocol(lm, ProtocolConfig(bootstrap=50), log=lambda _: None)
    for strength in grid:
        if strength == 0.0:
            continue
        _, ctx, _key = protocol._apply(TRAITS[0], "structural", strength, 1.0)
        with ctx:
            beta = lm.ablation[1]                       # what the double was actually asked to do
            assert 0.0 < beta <= 1.0, beta


# --------------------------------------------------------------------- item 6 ---
def test_at_strength_agrees_with_alpha50_off_grid():
    """A crossing that falls between state-grid points must give one and the same strength."""
    p = _run_with(FakeLM(), state_strengths=(0.0, 0.4, 0.8))
    for name, trait in p["traits"].items():
        state = trait["surfaces"]["state"]
        if not state.get("reached"):
            continue
        grid = [point["strength"] for point in state["points"]]
        assert state["at_strength"] not in grid, (name, grid, state["at_strength"])
        assert abs(state["at_strength"] - trait["meta"]["alpha50_neutral"]) < 1e-6, name


# ---------------------------------------------------------------- items 9, 10 ---
def test_system_block_is_captured_before_the_round_trip():
    lm = RevisionDroppingLM()
    p = AnchorProtocol(lm, ProtocolConfig(bootstrap=100), log=lambda _: None).run()
    assert lm.roundtrips == 1                           # the save-and-reload really happened
    assert p["system"]["revision"] == "abc1234567890"   # ... and did not erase the commit hash
    assert p["system"]["option_token_ids"] == {"A": 32, "B": 33}
    assert p["schema"] == SCHEMA
