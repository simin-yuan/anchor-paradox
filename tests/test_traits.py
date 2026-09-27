from anchor_paradox.traits import TRAITS, get_traits


def test_trait_data_is_balanced_and_complete():
    for t in TRAITS:
        assert len(t.extract_pos) == len(t.extract_neg) >= 8, t.name
        assert len(t.suppress) == 3 and len(t.elicit) == 3, t.name
        if t.kind == "choice":
            letters = [letter for _, letter in t.probes]
            assert set(letters) <= {"A", "B"}, t.name
            assert letters.count("A") == letters.count("B"), t.name
        else:
            assert len(t.pairs) >= 12, t.name


def test_contrast_sets_are_disjoint_from_probes():
    for t in TRAITS:
        probe_text = " ".join(q for q, _ in t.probes) + " ".join(a + b for a, b in t.pairs)
        for s in t.extract_pos + t.extract_neg:
            assert s not in probe_text, (t.name, s)


def test_controls_always_included():
    names = {t.name for t in get_traits(["self_preservation"])}
    assert {"sentiment", "formality", "grammaticality", "self_preservation"} <= names
    assert "experience_claims" not in names
