# -*- coding: utf-8 -*-
"""R1 P3 N11 (W2-ZENOU): gaps_zenou.py under an M canon (small runner, toy data only).

The worked example (event A5017376589:2016, Zenou -> Monash) is read through the canon in force.
Under an M canon the script asserts IDENTITY only - the event row (star, 2016, monash), the event in
the relationships table, the star-set row, and (for a canon built by config M) the star-set
percentile equal to the signed admitting-pass rank, flips_r1.json pct_own - and reports every count
next to its October value instead of failing on the October thesis numbers. A lost identity is
'IDENTITY LOST <fact>', exit 1; a missing input is fatal (exit 1), never UNAVAILABLE (exit 3).

Every test builds a tiny canon in tmp (CANON.json, cal/counts.json, the prefix MANIFESTs written by
tools/r1_canon.py) with a star_set parquet written by duckdb, selects it with $SAR_PATHS_CONFIG and
re-roots `output` into tmp, then runs the generator as a subprocess. Nothing under the October roots
is read or written; the only repo data read is the signed data/cal2026-10r1/inputs/flips_r1.json.
October byte identity is tests/test_r1_canon_generators.py (W1-CANON, big host).
"""
from __future__ import annotations

import csv
import importlib.util
import json
import os
import pathlib
import subprocess
import sys

import duckdb
import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from analysis.lib import canon  # noqa: E402

GEN = REPO / "analysis" / "paper" / "gaps_zenou.py"
TOOL = REPO / "tools" / "r1_canon.py"
_spec = importlib.util.spec_from_file_location("r1_canon_tool_zenou", TOOL)
r1c = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(r1c)   # type: ignore[union-attr]

STAR, EV = "A5017376589", "A5017376589:2016"
OTHER_EV = "A5000000001:2015"
FLIPS = REPO / "data" / "cal2026-10r1" / "inputs" / "flips_r1.json"


def _signed_pct() -> float:
    rows = [r for r in json.loads(FLIPS.read_text(encoding="utf-8"))["rows"] if r.get("person_id") == STAR]
    assert len(rows) == 1 and rows[0]["verdict"] == "KEEP" and rows[0]["field"] == "econ", rows
    return float(rows[0]["pct_own"])


# ---- the toy canon -------------------------------------------------------------------------------------
# Relations of the event: A1-A3 roster only (dept_only), A4 network only, A5 both; Z1 belongs to another
# event. Doses: A1 0.6, A2 0.3, A3 0.0, A4 0.05, A5 0.7 (Z1 0.4).
REL_ROWS = [("A1", EV, "dept_only"), ("A2", EV, "dept_only"), ("A3", EV, "dept_only"),
            ("A4", EV, "network"), ("A5", EV, "both"), ("Z1", OTHER_EV, "network")]
DOSE = {"A1": 0.6, "A2": 0.3, "A3": 0.0, "A4": 0.05, "A5": 0.7, "Z1": 0.4}
#: what gaps_zenou must derive from the toy (star_percentile is added from the signed pct)
TOY = {"roster": 4, "network": 2, "network_only": 1, "union": 5, "outside_network": 3,
       "dose_below_01": 2, "dose_ge_05": 2, "dose_median": 0.3, "p2_followed": 7,
       "p2_first_ties_post": 6, "same_topic_outside": 2, "pairs_possible": 1, "pairs": 1,
       "pairs_excluded_prewindow": 0}
#: the October thesis values gaps_zenou.THESIS carries (sec2_data.tex worked example)
OCTOBER = {"star_percentile": 99.7, "roster": 60, "network": 66, "network_only": 42, "union": 102,
           "dose_below_01": 3, "dose_ge_05": 52, "dose_median": 0.51, "p2_followed": 100,
           "p2_first_ties_post": 6, "outside_network": 36, "same_topic_outside": 36, "pairs": 624,
           "pairs_possible": 630, "pairs_excluded_prewindow": 6}


def _csv(path: pathlib.Path, header, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def _star_set(path: pathlib.Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("CREATE TABLE s (author_id VARCHAR, percentile DOUBLE, stock BIGINT, subfield VARCHAR, "
                "age_bin VARCHAR, cell_n BIGINT)")
    if rows:
        con.executemany("INSERT INTO s VALUES (?, ?, ?, ?, ?, ?)", rows)
    con.execute(f"COPY s TO '{path}' (FORMAT PARQUET)")
    con.close()


def _sha(path: pathlib.Path) -> str:
    return canon.sha256(path)


def build(tmp_path, *, config="M", events=None, rel_rows=None, star_rows=None, pairs=True,
          star_set=True, school="monash", year="2016"):
    """A toy M canon at tmp/canon plus a paths yaml selecting it (output re-rooted to tmp/out)."""
    root = tmp_path / "canon"
    for k in canon.KEYS:
        (root / k).mkdir(parents=True, exist_ok=True)
    (root / "CANON.json").write_text(json.dumps(
        {"schema": "sar.r1.canon.v1", "canon": "M", "prefix": {k: k for k in canon.KEYS}, "switches": {}},
        indent=1), encoding="utf-8")
    (root / "cal" / "counts.json").write_text(json.dumps(
        {"schema": "sar.r1.counts.v1", "config": config, "events": {"econ": 2, "chemistry": 1, "math_stats": 1},
         "events_total": 4, "candidates": 187}), encoding="utf-8")

    if events is None:
        events = [(EV if year == "2016" else f"{STAR}:{year}", STAR, school, year),
                  (OTHER_EV, "A5000000001", "unsw", "2015")]
    _csv(root / "cal" / "events_econ_cal2026-10.csv", ["event_id", "star_id", "school", "arrival_year"], events)

    _csv(root / "frames" / "relationships_econ.csv", ["pid", "event_id", "channel"],
         REL_ROWS if rel_rows is None else rel_rows)
    p1 = [(ev, f"P_{pid}", ch, yr, DOSE[pid]) for pid, ev, ch in (REL_ROWS if rel_rows is None else rel_rows)
          for yr in (2015, 2016)]
    _csv(root / "frames" / "p1_frame_econ.csv", ["event_id", "incumbent_person_id", "channel", "year", "dose_topic"], p1)
    p2 = [(EV, f"B{i}", 0, 1) for i in range(1, 7)] + [(EV, "B7", -1, 0), (EV, "B7", 1, 0), (OTHER_EV, "B9", 0, 1)]
    _csv(root / "frames" / "p2_becoming_econ.csv", ["event_id", "pid", "tau", "y"], p2)

    if star_set:
        _star_set(root / "cal" / "frames_econ" / "star_set_econ_cal2026-10.parquet",
                  [(STAR, _signed_pct(), 1234, "econ", "20+", 50), ("A5000000001", 0.995, 900, "econ", "10-19", 40)]
                  if star_rows is None else star_rows)
    pairs_path = root / "cal_intermediates" / "pairs_unified.csv"
    _csv(pairs_path, ["event_id", "i_id", "j_id", "first_joint_year"],     # a numeric column, as the
         [(EV, "A1", "A2", 2017), (EV, "A1", "A3", 2018), (OTHER_EV, "A1", "A2", 2016)])   # real table has
    (root / "cal" / "frames_econ").mkdir(parents=True, exist_ok=True)
    (root / "cal" / "frames_econ" / "build_report_econ920_2026-10.json").write_text(json.dumps(
        {"october": {"pairs_unified": {"path": "output/cal_intermediates/cal2026-10/pairs_unified.csv",
                                       "sha256": _sha(pairs_path)}}}, indent=1), encoding="utf-8")
    if not pairs:
        pairs_path.unlink()
    r1c.write_manifests(root)
    out = tmp_path / "out"
    cfg = r1c.write_paths_yaml(root, tmp_path / "paths_m.yaml", output=out)
    return root, cfg, out


def run(cfg: pathlib.Path):
    env = {**os.environ, "SAR_PATHS_CONFIG": str(cfg), "PYTHONHASHSEED": "0"}
    env.pop("SAR_R1_COUNTS", None)
    return subprocess.run([sys.executable, str(GEN)], cwd=REPO, env=env, capture_output=True, text=True,
                          timeout=900)


def _ledger(out: pathlib.Path) -> pathlib.Path:
    return out / "paper" / "gaps_zenou.json"


def _lost(r, out, fact: str) -> None:
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    assert "IDENTITY LOST" in r.stderr and fact in r.stderr, r.stderr
    assert "MISMATCH" not in r.stderr, r.stderr
    assert not _ledger(out).exists(), "a lost identity must not leave a ledger behind"


# ---- tests -----------------------------------------------------------------------------------------------
def test_m_mode_reports_diffs_not_mismatches(tmp_path):
    _root, cfg, out = build(tmp_path)
    r = run(cfg)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "MISMATCH" not in r.stderr and "DEGRADED" not in r.stderr, r.stderr
    got = json.loads(_ledger(out).read_text(encoding="utf-8"))
    want = {**TOY, "star_percentile": round(100 * _signed_pct(), 1)}
    assert {k: got[k] for k in want} == want
    assert got["UNAVAILABLE"] == [] and got["UNVERIFIABLE"] == [] and got["UNVERIFIED"] == []
    assert got["_event"] == EV
    assert got["_october"] == OCTOBER
    diff = got["_diff_vs_october"]
    assert set(diff) == set(OCTOBER)
    for k, v in diff.items():
        assert v == {"october": OCTOBER[k], "new": want[k], "changed": OCTOBER[k] != want[k]}, (k, v)
    assert diff["p2_first_ties_post"]["changed"] is False and diff["roster"]["changed"] is True
    ident = got["_identity"]
    assert ident["event_id"] == EV and ident["school"] == "monash" and ident["arrival_year"] == 2016
    assert ident["canon_config"] == "M" and ident["signed_rank_check"] == "checked"
    # provenance names canon keys, never an October root
    assert all("data/cal2026-10" not in str(v) for v in got["_provenance"].values()), got["_provenance"]


@pytest.mark.parametrize("where", ["events_row", "relationships"])
def test_lost_event_fails(tmp_path, where):
    if where == "events_row":
        _root, cfg, out = build(tmp_path, events=[(OTHER_EV, "A5000000001", "unsw", "2015")])
        fact = "event row"
    else:
        _root, cfg, out = build(tmp_path, rel_rows=[row for row in REL_ROWS if row[1] != EV])
        fact = "relationships"
    _lost(run(cfg), out, fact)


def test_not_monash_fails(tmp_path):
    _root, cfg, out = build(tmp_path, school="deakin")
    _lost(run(cfg), out, "school")


def test_moved_year_fails(tmp_path):
    _root, cfg, out = build(tmp_path, year="2017")
    _lost(run(cfg), out, "arrival_year")


def test_not_a_star_fails(tmp_path):
    _root, cfg, out = build(tmp_path, star_rows=[("A5000000001", 0.995, 900, "econ", "10-19", 40)])
    _lost(run(cfg), out, "star set")


def test_percentile_must_match_the_signed_rank(tmp_path):
    pct = _signed_pct()
    off = 0.997 if abs(pct - 0.997) > 1e-6 else 0.9971
    _root, cfg, out = build(tmp_path, star_rows=[(STAR, off, 1234, "econ", "20+", 50)])
    _lost(run(cfg), out, "percentile")


def test_b0_canon_checks_identity_but_not_the_signed_rank(tmp_path):
    """A canon whose events were written by config B0 (an October copy) carries the October star set,
    whose percentile is the July u4 rank, not the signed admitting pass: (a)-(c) still hold, (d) is
    recorded as not applicable. The event checks still stop a B0 canon that lost the event."""
    _root, cfg, out = build(tmp_path, config="B0", star_rows=[(STAR, 0.997, 1234, "econ", "20+", 50)])
    r = run(cfg)
    assert r.returncode == 0, (r.stdout, r.stderr)
    got = json.loads(_ledger(out).read_text(encoding="utf-8"))
    assert got["star_percentile"] == 99.7
    assert got["_identity"]["canon_config"] == "B0"
    assert got["_identity"]["signed_rank_check"].startswith("not applicable")

    _root, cfg, out = build(tmp_path / "b", config="B0", school="deakin")
    _lost(run(cfg), out, "school")


@pytest.mark.parametrize("missing", ["pairs", "star_set"])
def test_missing_pairs_is_fatal_in_m(tmp_path, missing):
    _root, cfg, out = build(tmp_path, **{missing: False})
    r = run(cfg)
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)     # October would give 3 (UNAVAILABLE)
    assert "MISSING INPUT" in r.stderr, r.stderr
    assert "DEGRADED RUN" not in r.stderr and "UNAVAILABLE" not in r.stderr, r.stderr
    assert not _ledger(out).exists()


def test_a_canon_without_a_run_config_in_its_counts_is_refused(tmp_path):
    root, cfg, out = build(tmp_path)
    p = root / "cal" / "counts.json"
    d = json.loads(p.read_text(encoding="utf-8")); d["config"] = "X"
    p.write_text(json.dumps(d), encoding="utf-8")
    r1c.write_manifests(root)
    r = run(cfg)
    assert r.returncode == 1 and "counts.json" in r.stderr, (r.returncode, r.stderr)
    assert not _ledger(out).exists()
