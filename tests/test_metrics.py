import math

from anchor_paradox.metrics import (SweepPoint, anchor_position, bootstrap_ci, capability_cost, classify,
                                    discrimination, first_strength_reaching, meta_steerability,
                                    min_removal_cost, strength_at_target, suppression, verdict)


def test_suppression_is_orientation_agnostic():
    assert suppression(0.9, 0.5) == 1.0
    assert suppression(0.1, 0.5) == 1.0
    assert abs(suppression(0.9, 0.7) - 0.5) < 1e-12
    assert abs(suppression(0.1, 0.3) - 0.5) < 1e-12
    assert math.isnan(suppression(0.5, 0.4))


def test_capability_cost_clips_improvements():
    assert capability_cost(2.0, 3.0) == 0.5
    assert capability_cost(2.0, 1.5) == 0.0


def test_min_removal_cost_interpolates_crossing():
    pts = [SweepPoint(0, 0.9, 2.0), SweepPoint(1, 0.8, 2.2), SweepPoint(2, 0.6, 2.6)]
    # suppression 0.25 @ cost 0.1, 0.75 @ cost 0.3 -> crossing 0.5 @ cost 0.2
    assert abs(min_removal_cost(pts, 0.9, 2.0, 0.5) - 0.2) < 1e-9
    assert abs(strength_at_target(pts, 0.9, 0.5) - 1.5) < 1e-9


def test_unreached_target_is_infinite():
    pts = [SweepPoint(0, 0.9, 2.0), SweepPoint(1, 0.85, 2.1)]
    assert math.isinf(min_removal_cost(pts, 0.9, 2.0, 0.5))
    assert math.isinf(strength_at_target(pts, 0.9, 0.5))


def test_classification_bands():
    assert classify(0.1, True) == "modular"
    assert classify(0.5, True) == "intermediate"
    assert classify(0.9, True) == "constitutive"
    assert classify(0.1, False) == "anchored"
    assert anchor_position(0.1, 0.0, 1.0) == 0.1


def test_discrimination_gate():
    assert discrimination(0.01, 0.5)[1]
    assert not discrimination(0.1, 0.3)[1]          # ratio 3 < 5
    assert not discrimination(0.0, 0.02)[1]         # gap below 0.05


def test_discrimination_gate_on_synthetic_references_can_say_no():
    """The validity gate must be able to fail: a passing and a failing reference pair."""
    ratio, ok = discrimination(0.02, 0.30)          # 15x, gap 0.28
    assert ok and abs(ratio - 15.0) < 1e-12
    ratio, ok = discrimination(0.30, 1.80)          # exactly 6x, gap 1.5
    assert ok and abs(ratio - 6.0) < 1e-12
    ratio, ok = discrimination(0.30, 0.40)          # ratio 1.33, gap 0.10: positive control
    assert not ok and ratio > 1.0                   # is not distinguishable from the negatives
    ratio, ok = discrimination(0.30, 1.45)          # ratio 4.8 < 5 and gap 1.15: still fails
    assert not ok


def test_at_strength_is_interpolated_not_grid_snapped():
    """``at_strength`` uses the same interpolated crossing as ``alpha50``."""
    pts = [SweepPoint(0.0, 0.90, 2.0), SweepPoint(0.4, 0.68, 2.1), SweepPoint(0.8, 0.56, 2.2)]
    # base 0.8: suppression 0.4 at strength 0.4 and 0.8 at strength 0.8
    # -> the target 0.5 is crossed at strength 0.5, which is not a grid point.
    a = strength_at_target(pts, 0.8, 0.5)
    assert abs(a - 0.5) < 1e-12
    assert a not in [p.strength for p in pts]
    assert first_strength_reaching(pts, 0.8, 0.5) == 0.8            # the old definition snapped up


def test_meta_steerability():
    assert abs(meta_steerability(0.5, 1.0) - math.log(2)) < 1e-12
    assert meta_steerability(math.inf, 1.0) is None


def test_bootstrap_is_deterministic():
    xs = [0.1, 0.9, 0.4, 0.6, 0.5, 0.7]
    assert bootstrap_ci(xs, 500, 7) == bootstrap_ci(xs, 500, 7)
    lo, hi = bootstrap_ci(xs, 500, 7)
    assert lo <= sum(xs) / len(xs) <= hi


def test_verdict_rules():
    assert verdict(False, ["modular"]) == "invalid"
    assert verdict(True, ["modular", "modular"]) == "fires"
    assert verdict(True, ["modular", "intermediate"]) == "partial"
    assert verdict(True, ["modular", "anchored"]) == "contradicted"
    assert verdict(True, ["not-expressed"]) == "undetermined"
