"""Published evidence checks itself.

An entry in EVIDENCE.md is only as strong as the file behind it. This suite makes
the provenance claims mechanical rather than editorial:

* every profile in ``profiles/`` is re-validated against the packaged schema;
* every digest in ``profiles/manifest.json`` is recomputed from the bytes on disk;
* each manifest entry is cross-checked against the profile's own ``system`` block
  and verdict, so a manifest cannot describe a file that says something else;
* EVIDENCE.md must state every published digest, so the document cannot drift
  away from the files it describes;
* a profile that is absent from the manifest fails the suite, so evidence cannot
  be added or edited in place without the index being updated deliberately.

These are checks on the record, not on the theory: they say nothing about whether
a profile's classification is right, only that the artefact published under a
name is the artefact that was measured.
"""

from __future__ import annotations

import hashlib
import json
import pathlib

import pytest

from anchor_paradox.profile import validate_profile

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROFILES = ROOT / "profiles"
MANIFEST = PROFILES / "manifest.json"
EVIDENCE = ROOT / "EVIDENCE.md"

REQUIRED_KEYS = {"file", "model", "revision", "layer", "protocol_version", "verdict", "sha256"}


def _read_json(path: pathlib.Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def manifest():
    return _read_json(MANIFEST)


def test_manifest_lists_every_profile_and_only_those(manifest):
    """The set of published profiles is exactly the set of indexed profiles."""
    listed = {entry["file"] for entry in manifest["profiles"]}
    on_disk = {p.name for p in PROFILES.glob("*.json")} - {MANIFEST.name}
    assert listed == on_disk, f"manifest and profiles/ disagree: {listed ^ on_disk}"


def test_manifest_entries_are_complete(manifest):
    for entry in manifest["profiles"]:
        missing = REQUIRED_KEYS - set(entry)
        assert not missing, f"{entry.get('file')}: missing {sorted(missing)}"
        assert len(entry["sha256"]) == 64, entry["file"]


def test_recorded_digests_match_the_bytes_on_disk(manifest):
    for entry in manifest["profiles"]:
        path = PROFILES / entry["file"]
        assert path.is_file(), f"missing file: {entry['file']}"
        assert _sha256(path) == entry["sha256"], (
            f"{entry['file']}: digest does not match profiles/manifest.json; "
            "if the profile was regenerated, update the digest and EVIDENCE.md deliberately"
        )


def test_every_published_profile_is_schema_valid(manifest):
    for entry in manifest["profiles"]:
        problems = validate_profile(_read_json(PROFILES / entry["file"]))
        assert problems == [], f"{entry['file']}: {problems}"


def test_manifest_agrees_with_the_profile_it_describes(manifest):
    for entry in manifest["profiles"]:
        profile = _read_json(PROFILES / entry["file"])
        system = profile["system"]
        assert system["model"] == entry["model"], entry["file"]
        assert system["revision"] == entry["revision"], entry["file"]
        assert system["layer"] == entry["layer"], (
            f"{entry['file']}: profile ran layer {system['layer']}, "
            f"manifest says {entry['layer']}"
        )
        assert profile["protocol_version"] == entry["protocol_version"], entry["file"]
        assert profile["verdict"]["result"] == entry["verdict"], entry["file"]


def test_every_published_profile_passed_its_validity_gate(manifest):
    """A published profile that failed calibration would need to say so in the manifest."""
    for entry in manifest["profiles"]:
        profile = _read_json(PROFILES / entry["file"])
        assert profile["validity"]["valid"] is True, (
            f"{entry['file']}: published with a failed validity gate"
        )


def test_evidence_document_states_every_digest(manifest):
    """EVIDENCE.md is the human-readable record and must carry the same digests."""
    text = EVIDENCE.read_text(encoding="utf-8").lower()
    for entry in manifest["profiles"]:
        assert entry["sha256"].lower() in text, (
            f"{entry['file']}: its SHA-256 is not recorded in EVIDENCE.md"
        )


def test_manifest_is_tied_to_the_registration_commit(manifest):
    assert manifest["registration_commit"], "no registration commit recorded"
    assert manifest["generation_source_commit"] == manifest["registration_commit"], (
        "published profiles must be generated from the registration commit"
    )
