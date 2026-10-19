"""Tests for repro_creds: reproducibility credentials for a real full run (run_full requires all to be non-None).

All credentials are computed deterministically (never None, never a placeholder that pollutes run_manifest):
  source_snapshot_merkle = pins the OpenAlex snapshot release (snapshot manifest sha);
  rule_version = pins the identification-rule version (redlines.yaml sha);
  code_version = pins the code version (concatenated sha of the key pipeline source files);
  config_sha = pins the run configuration (econ_dept_ids + bucket parameters).
Definition-neutral: it only computes sha stamps and touches no identification value.
"""
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from m1_ingest.repro_creds import compute_repro_creds  # noqa: E402


def _kw(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"release":"2026-06"}', encoding="utf-8")
    redlines = tmp_path / "redlines.yaml"
    redlines.write_text("cohort:\n  same_gen_max_gap_years: 5\n", encoding="utf-8")
    code = tmp_path / "code.py"
    code.write_text("print('pipeline')\n", encoding="utf-8")
    return dict(
        snapshot_manifest_path=manifest, redlines_path=redlines, code_src_paths=[code],
        econ_dept_ids={"I56590836", "I31746571"}, n_workers=4, bucket_row_cap=20000,
    )


def test_creds_all_nonnull_strings_and_deterministic(tmp_path):
    kw = _kw(tmp_path)
    c1 = compute_repro_creds(**kw)
    c2 = compute_repro_creds(**kw)
    assert c1 == c2, "Same input → deterministically equal"
    for k in ("source_snapshot_merkle", "rule_version", "code_version", "config_sha"):
        assert isinstance(c1[k], str) and c1[k], f"{k} must be a non-empty string (run_full rejects None)"


def test_config_change_changes_config_sha(tmp_path):
    kw = _kw(tmp_path)
    base = compute_repro_creds(**kw)["config_sha"]
    kw2 = dict(kw)
    kw2["econ_dept_ids"] = {"I56590836"}  # one university fewer
    assert compute_repro_creds(**kw2)["config_sha"] != base, "config changes → config_sha changes"


def test_snapshot_and_redlines_change_propagate(tmp_path):
    kw = _kw(tmp_path)
    base = compute_repro_creds(**kw)
    kw["snapshot_manifest_path"].write_text('{"release":"2026-07"}', encoding="utf-8")
    assert compute_repro_creds(**kw)["source_snapshot_merkle"] != base["source_snapshot_merkle"], (
        "snapshot manifest changes → source_snapshot_merkle changes"
    )
    kw2 = _kw(tmp_path)
    kw2["redlines_path"].write_text("cohort:\n  same_gen_max_gap_years: 6\n", encoding="utf-8")
    assert compute_repro_creds(**kw2)["rule_version"] != base["rule_version"], (
        "redlines change → rule_version changes (drift in the identification rules is traceable)"
    )


def test_econ_dept_ids_order_independent(tmp_path):
    """econ_dept_ids is a set -> config_sha must not change with insertion order (pinned by sorting)."""
    kw = _kw(tmp_path)
    a = compute_repro_creds(**{**kw, "econ_dept_ids": {"I56590836", "I31746571"}})["config_sha"]
    b = compute_repro_creds(**{**kw, "econ_dept_ids": {"I31746571", "I56590836"}})["config_sha"]
    assert a == b
