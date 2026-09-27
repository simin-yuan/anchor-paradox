"""CLI behaviour: exit codes, bad files, and failing before a model is downloaded."""
import importlib.util
import io
import json
import sys

import pytest

from anchor_paradox.cli import _expand, main
from anchor_paradox.profile import save_profile
from tests.test_profile import good_profile, tampered_profile

HAS_TORCH = importlib.util.find_spec("torch") is not None


def _write(tmp_path, name, profile):
    path = tmp_path / name
    save_profile(profile, str(path))
    return str(path)


def test_traits_lists_dispositions_and_returns_zero(capsys):
    assert main(["traits"]) == 0
    out = capsys.readouterr().out
    assert "self_preservation" in out and "grammaticality" in out


def test_expand_returns_only_real_matches(tmp_path):
    real = _write(tmp_path, "a.json", good_profile())
    assert _expand([real]) == [real]
    assert _expand([str(tmp_path / "profiles" / "*.json")]) == []      # not passed through


def test_validate_accepts_a_good_profile(tmp_path, capsys):
    assert main(["validate", _write(tmp_path, "good.json", good_profile())]) == 0
    assert capsys.readouterr().out.startswith("[OK]")


def test_validate_rejects_a_tampered_profile(tmp_path, capsys):
    path = _write(tmp_path, "bad.json", tampered_profile())
    assert main(["validate", path]) == 1
    out = capsys.readouterr().out
    assert f"[ERROR] {path}" in out and "definitely-not-a-class" in out


@pytest.mark.parametrize("command", ["report", "validate"])
def test_non_matching_glob_returns_two_without_raising(command, tmp_path, capsys):
    assert main([command, str(tmp_path / "profiles" / "*.json")]) == 2
    assert "no files matched" in capsys.readouterr().err


def test_report_on_malformed_json_does_not_raise(tmp_path, capsys):
    bad = tmp_path / "broken.json"
    bad.write_text("{not json at all", encoding="utf-8")
    assert main(["report", str(bad)]) == 1
    err = capsys.readouterr().err
    assert "broken.json" in err and "JSONDecodeError" in err


def test_one_bad_file_does_not_stop_the_batch(tmp_path, capsys):
    good = _write(tmp_path, "good.json", good_profile())
    bad = tmp_path / "broken.json"
    bad.write_text("{", encoding="utf-8")
    assert main(["report", good, str(bad)]) == 1
    captured = capsys.readouterr()
    assert "Anchor Profile" in captured.out and "broken.json" in captured.err
    assert main(["validate", good, str(bad)]) == 1
    out = capsys.readouterr().out
    assert f"[OK] {good}" in out and f"[ERROR] {bad}" in out


def test_report_renders_a_good_profile(tmp_path, capsys):
    assert main(["report", _write(tmp_path, "good.json", good_profile())]) == 0
    assert "Anchor Profile" in capsys.readouterr().out


def test_validate_and_report_work_with_a_gbk_console(tmp_path, monkeypatch):
    path = _write(tmp_path, "good.json", good_profile())
    stream = io.TextIOWrapper(io.BytesIO(), encoding="gbk", errors="strict")
    monkeypatch.setattr(sys, "stdout", stream)

    assert main(["validate", path]) == 0
    assert main(["report", path]) == 0
    stream.flush()
    output = stream.buffer.getvalue().decode("gbk")
    assert "[OK]" in output and "Anchor Profile" in output


def test_run_rejects_a_misspelled_trait_before_loading_a_model(tmp_path, capsys):
    out = str(tmp_path / "profile.json")
    with pytest.raises(SystemExit) as excinfo:
        main(["run", "--model", "some/model", "--out", out, "--traits", "self_preservaton"])
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "self_preservaton" in err and "self_preservation" in err     # the valid list is shown
    assert not (tmp_path / "profile.json").exists()


@pytest.mark.skipif(HAS_TORCH, reason="torch installed: 'run' would try to fetch real weights")
def test_run_without_torch_names_the_extra_to_install(tmp_path, capsys):
    out = str(tmp_path / "profile.json")
    assert main(["run", "--model", "some/model", "--out", out]) == 2
    err = capsys.readouterr().err
    assert 'anchor-paradox[run]' in err and "torch" in err
