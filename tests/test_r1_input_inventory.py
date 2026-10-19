# -*- coding: utf-8 -*-
"""tools/r1_input_inventory.py - F27: every input the P4 jobs read, and where it is (toy tree, no disk)."""
from __future__ import annotations

import pathlib
import sys

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import r1_input_inventory as inv   # noqa: E402

TOY = {
    "pipeline/frames/cal2026-10/x.py":
        'A = legacy_thesis() / "v2_output" / "econ_fnfix_2026-08-15"\n'
        'B = "${DERIVED}/u1_edges_full_2026-07-05/works/*.parquet"\n'
        'C = derived_root() / "u0p5_roster"\n'
        'D = "derived/u9_gone_2026-01-01/x.parquet"\n',
    "analysis/robustness/z.R": 'f <- "v2_output/cluster_event_2026-08-16/out.csv"\n',
    "pipeline/lib/y.py": 'U3P = f"{SSD}/u3_panel_11school_2026-07-16/panel/data.parquet"\n'
                         'E = f"{SSD}/authorship_edges/**/*.parquet"\n',
    "analysis/paper/p.py": 'PAIRS = "output/cal_intermediates/cal2026-10/pairs_unified.csv"\n'
                           'S = "snapshot/authors/part.gz"\n'
                           'H = "multiplex_pipeline/_handoff_2026-07-23/funnel.json"\n',
}


def _toy(tmp_path):
    repo = tmp_path / "repo"
    for rel, text in TOY.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
    mac = tmp_path / "mac" / "v2_output"
    (mac / "cluster_event_2026-08-16").mkdir(parents=True)
    s3 = {"u1_edges_full_2026-07-05/", "r1/derived/u0p5_roster/", "r1/snapshot/authors/",
          "r1/legacy/legacy_v2_output/econ_fnfix_2026-08-15/", "r1/legacy/legacy_multiplex/_handoff_2026-07-23/"}
    return repo, {"legacy_v2_output": mac}, s3


def _rows(tmp_path):
    repo, mac, s3 = _toy(tmp_path)
    return inv.classify(inv.scan(repo), mac_roots=mac, s3_prefixes=s3, tracked=set())


def test_every_reference_is_found_with_its_root(tmp_path):
    repo, _, _ = _toy(tmp_path)
    assert {(r.root, r.name) for r in inv.scan(repo)} == {
        ("legacy_v2_output", "econ_fnfix_2026-08-15"), ("legacy_v2_output", "cluster_event_2026-08-16"),
        ("derived", "u1_edges_full_2026-07-05"), ("derived", "u0p5_roster"), ("derived", "u9_gone_2026-01-01"),
        ("output", "cal_intermediates"), ("snapshot", "authors"),
        ("derived", "u3_panel_11school_2026-07-16"),          # f"{SSD}/..." (SSD = the derived root in econ920)
        ("legacy_multiplex", "_handoff_2026-07-23")}          # a leading '_' (review P3b: ledger_funnel.py)


def test_ssd_subtable_hits_are_ignored_with_a_reason():
    assert ("derived", "authorship_edges") in inv.IGNORE and len(inv.IGNORE[("derived", "authorship_edges")]) > 30


def test_availability_needed_by_and_a_missing_input(tmp_path):
    rows = {(r.root, r.name): r for r in _rows(tmp_path)}
    assert rows[("legacy_v2_output", "econ_fnfix_2026-08-15")].availability == "s3"
    assert rows[("legacy_v2_output", "cluster_event_2026-08-16")].availability == "mac"
    u1 = rows[("derived", "u1_edges_full_2026-07-05")]
    assert (u1.availability, u1.s3_prefix, u1.instance_path) == (
        "s3", "u1_edges_full_2026-07-05/", "/data/openalex_pipeline/derived/u1_edges_full_2026-07-05/")
    assert rows[("derived", "u0p5_roster")].s3_prefix == "r1/derived/u0p5_roster/"
    assert rows[("derived", "u9_gone_2026-01-01")].availability == "missing"
    assert rows[("output", "cal_intermediates")].availability == "generated"
    assert rows[("derived", "u0p5_roster")].needed_by == "j0,j1a,j1b"     # j1b's drivers rebuild frames (review P3b)
    assert rows[("legacy_v2_output", "cluster_event_2026-08-16")].needed_by == "j1b"


def test_signed_inputs_are_repo_rows(tmp_path):
    repo, mac, s3 = _toy(tmp_path)
    rows = {(r.root, r.name): r for r in inv.classify(
        [], mac_roots=mac, s3_prefixes=s3, tracked={"data/cal2026-10r1/inputs/add_list_r1.json"})}
    assert rows[("repo", "data/cal2026-10r1/inputs/add_list_r1.json")].availability == "repo"
    assert rows[("repo", "data/cal2026-10r1/inputs/flips_r1.json")].availability == "missing"


def test_sync_pairs_collapse_to_roots_and_refuse_what_is_not_on_s3(tmp_path):
    rows = [r for r in _rows(tmp_path) if r.name != "u9_gone_2026-01-01"]
    assert inv.sync_pairs(rows, "j0") == [
        ["r1/derived/", "/data/openalex_pipeline/derived/"],
        ["r1/legacy/legacy_v2_output/", "/data/legacy/thesis/v2_output/"],
        ["u1_edges_full_2026-07-05/", "/data/openalex_pipeline/derived/u1_edges_full_2026-07-05/"]]
    with pytest.raises(ValueError, match="cluster_event_2026-08-16 is mac"):
        inv.sync_pairs(rows, "j1b")
    assert ["r1/ref/october/", "/data/ref/october/"] in inv.sync_pairs(
        [r for r in rows if r.root != "legacy_v2_output"], "final")


def test_tsv_round_trip(tmp_path):
    rows = _rows(tmp_path)
    p = tmp_path / "inv.tsv"
    inv.write_tsv(rows, p)
    assert inv.read_tsv(p) == rows


def test_paths_aws_matches_paths_october_and_the_instance_roots():
    mac = yaml.safe_load((REPO / "config" / "paths_october.yaml").read_text(encoding="utf-8"))
    aws = yaml.safe_load((REPO / "config" / "r1" / "paths_aws.yaml").read_text(encoding="utf-8"))
    assert set(aws) == set(mac)
    for k, v in mac.items():
        if not str(v).startswith(("/", "${")):
            assert aws[k] == v, k
    assert aws["ssd_root"] == "/data/openalex_pipeline"
    for key in ("legacy_v2_output", "legacy_thesis", "legacy_multiplex"):
        assert aws[key].rstrip("/") + "/" == inv.ROOTS[key].local, key
