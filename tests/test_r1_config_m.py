# -*- coding: utf-8 -*-
"""R1 M (main-run) configuration: the M cell list (V3-ONE.cells).

The M cell list is two files under config/r1/cells/:
  M.tsv       the 18 main cells, every ref '-'
  M_evcl.tsv  the 9 event-cluster cells, ref = the same run's main out_name
Together they are the 29 October golds (oct29.tsv) minus the C10 pair P1_econ_fnfix_old79 /
P1_econ_fnfix_new37 (C10 = 'v3': those two run only in B0), so 27 cells. Every row is a byte-for-byte
copy of its oct29.tsv line, except that the two rcloud evcl cells read the same run's main cell (ref
column): October's cloud run passed them no reference, so oct29.tsv says '-' there (FIX-JP 1, JP
review). The J1a stage rows that run these files are W2-TJ1A's.

The config part of V3-ONE (W2-CONFIGM): config/r1/M.json, the one run config J1a / J1b / FINAL read
(B0.json drives J0). Every registry switch is at its on value except departure_ledger, which stays at
October's value because F20 is out of scope (since 2026-10-15: the paper prints no star-departure
robustness). The rulings are B0's (C10 also names the two cells it skips). The pins are the sha256 of
the committed signed lists, M inputs, cell lists, robustness list and the merged rosters (the econ,
chemistry and maths rosters plus the chemistry and maths incfel variants the J1b no-centre unit reads,
committed in d124ed7); the rk6b rank outputs are a data_ref pinned by the S3 manifest digest in
config/r1/input_pins.json. Pins that cannot exist yet (the rk6b manifest before pin-02) are listed
under 'pending_pins', and the tests force W3-MPIN to move each one into the config once it exists.
M loads only once add_list_r1_summary.json says OK (addlist-04 on the merged rosters, 40e944d); the
load test also runs on a tmp copy whose summary says OK.
"""
from __future__ import annotations

import collections
import csv
import hashlib
import json
import pathlib
import re
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
CELLS_DIR = REPO / "config" / "r1" / "cells"
OCT29 = CELLS_DIR / "oct29.tsv"
M_MAIN = CELLS_DIR / "M.tsv"
M_EVCL = CELLS_DIR / "M_evcl.tsv"
HEADER = ["label", "driver", "frame", "ref", "out_name", "stack"]
C10 = ("P1_econ_fnfix_old79", "P1_econ_fnfix_new37")
C10_TOKENS = ("old79", "new37")
#: the two rcloud evcl cells: '-' in oct29.tsv (October's cloud commands passed no ref), the same run's main cell in M
M_REF = {"P3evcl_chemistry": "P3_fnfix_chemistry.json", "P3evcl_econ": "P3_econ_fnfix.json"}

MAIN_RMAC = ["P1_econ_fnfix", "P1_fnfix_chemistry", "P1_fnfix_math_stats",
             "P2_econ_fnfix", "P2_fnfix_chemistry", "P2_fnfix_math_stats", "P3_fnfix_math_stats",
             *[f"P3lb_{f}_A_far" for f in ("math_stats", "chemistry", "econ")],
             *[f"P3cut_{s}_{f}" for f in ("math_stats", "chemistry", "econ") for s in ("pos", "med")]]
MAIN_RCLOUD = ["P3_fnfix_chemistry", "P3_econ_fnfix"]
EVCL_RMAC = [f"P{p}evcl_{f}" for p in (1, 2) for f in ("econ", "chemistry", "math_stats")] + ["P3evcl_math_stats"]
EVCL_RCLOUD = ["P3evcl_chemistry", "P3evcl_econ"]


def _lines(path):
    return path.read_bytes().decode("utf-8").splitlines(keepends=True)


def _rows(path):
    with open(path, encoding="utf-8", newline="") as fh:
        rd = csv.DictReader(fh, delimiter="\t")
        assert rd.fieldnames == HEADER, f"{path.name}: header {rd.fieldnames}"
        return list(rd)


def _as_m(line):
    """An oct29.tsv line as M uses it: the ref column of the two rcloud evcl cells set to their main cell."""
    f = line.rstrip("\n").split("\t")
    if f[0] in M_REF:
        f[3] = M_REF[f[0]]
    return "\t".join(f) + "\n"


def _manifest_json_names():
    names = []
    for line in (REPO / "analysis" / "expected" / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].endswith(".json"):
            names.append(parts[1])
    return names


def test_m_cells_are_october_cells_minus_c10():
    oct_lines = [_as_m(ln) for ln in _lines(OCT29)]
    oct_by_label = {r["label"]: (dict(r, ref=M_REF[r["label"]]) if r["label"] in M_REF else r) for r in _rows(OCT29)}
    assert len(oct_by_label) == 29 and all(lab in oct_by_label for lab in C10)
    assert all(r["ref"] == "-" for r in _rows(OCT29) if r["label"] in M_REF)      # FIX-JP 1
    main, evcl = _rows(M_MAIN), _rows(M_EVCL)

    # identical header line, and every data line is a byte-for-byte oct29 line, kept in oct29 order
    for path in (M_MAIN, M_EVCL):
        lines = _lines(path)
        assert lines[0] == oct_lines[0], f"{path.name}: header line differs from oct29.tsv"
        body = lines[1:]
        assert all(ln.endswith("\n") and not ln.endswith("\r\n") for ln in lines), f"{path.name}: line endings"
        assert body == [ln for ln in oct_lines[1:] if ln in body], f"{path.name}: lines not copied in oct29 order"
        assert len(set(body)) == len(body), f"{path.name}: duplicate line"

    # the union keyed by label equals oct29 minus the C10 pair, on every column
    union = {}
    for r in main + evcl:
        assert r["label"] not in union, f"label {r['label']} in both files or twice"
        union[r["label"]] = r
    want = {lab: r for lab, r in oct_by_label.items() if lab not in C10}
    assert union == want
    assert not any(lab in union for lab in C10)

    # the split: main cells carry ref '-', evcl cells carry a ref
    assert [r["label"] for r in main if r["stack"] == "rmac"] == MAIN_RMAC
    assert [r["label"] for r in main if r["stack"] == "rcloud"] == MAIN_RCLOUD
    assert [r["label"] for r in evcl if r["stack"] == "rmac"] == EVCL_RMAC
    assert [r["label"] for r in evcl if r["stack"] == "rcloud"] == EVCL_RCLOUD
    assert len(main) == 18 and len(evcl) == 9
    assert all(r["ref"] == "-" for r in main)
    assert all(r["ref"] != "-" for r in evcl)
    assert all(r["driver"].endswith("_evcl.R") for r in evcl)
    assert not any(r["driver"].endswith("_evcl.R") for r in main)


def test_m_out_names_equal_the_paper_cell_manifest():
    manifest = _manifest_json_names()
    assert len(manifest) == 29 and len(set(manifest)) == 29
    paper_cells = set(manifest) - {f"{lab}.json" for lab in C10}
    out_names = [r["out_name"] for r in _rows(M_MAIN) + _rows(M_EVCL)]
    assert len(out_names) == 27
    assert len(set(out_names)) == len(out_names), "duplicate out_name"
    assert set(out_names) == paper_cells


def test_no_paper_generator_reads_a_c10_cell():
    """Guard: dropping the C10 pair from M loses no printed number (no generator or sentinel names them)."""
    files = [p for p in sorted((REPO / "analysis" / "paper").rglob("*"))
             if p.is_file() and "__pycache__" not in p.parts]
    files.append(REPO / "tools" / "check_paper.py")
    files += sorted((REPO / "tools").glob("build_circulation*"))
    assert len(files) > 10
    hits = []
    for p in files:
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = p.read_bytes().decode("latin-1")
        hits += [f"{p.relative_to(REPO)}: {tok}" for tok in C10_TOKENS if tok in text]
    assert hits == []


def test_every_evcl_ref_is_a_main_cell_of_the_same_stack():
    main_stack = {r["out_name"]: r["stack"] for r in _rows(M_MAIN)}
    evcl = _rows(M_EVCL)
    assert evcl
    for r in evcl:
        assert r["ref"] in main_stack, f"{r['label']}: ref {r['ref']} is not an M main cell"
        assert main_stack[r["ref"]] == r["stack"], f"{r['label']}: ref {r['ref']} is on another stack"


# --- V3-ONE: config/r1/M.json (W2-CONFIGM) ---------------------------------------------------------
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from pipeline.lib import r1_config as rc  # noqa: E402

CONFIG_DIR = REPO / "config" / "r1"
M_JSON = CONFIG_DIR / "M.json"
B0_JSON = CONFIG_DIR / "B0.json"
INPUT_PINS = CONFIG_DIR / "input_pins.json"
STAGE_TABLES = ("j0", "j1a", "j1b")
INPUTS = "data/cal2026-10r1/inputs"
SUMMARY_REL = f"{INPUTS}/add_list_r1_summary.json"
FIELDS = ("econ", "chemistry", "math_stats")
#: switches M keeps at October's value, with the date of that decision (every other switch is on).
#: departure_ledger: F20 is out of scope (since 2026-10-15: the paper prints no star-departure robustness).
OFF_IN_M = {"departure_ledger": "2026-10-15"}
#: the committed files M pins by sha256 (the merged rosters join once they are committed)
M_PINS = tuple(f"{INPUTS}/{n}" for n in (
    "flips_r1.json", "add_list_r1.json", "add_list_r1_summary.json", "p2_decisions.json", "rulings_p1.json",
    "fixes_1001.csv", "person_overrides.csv", "dose_keep_r1.csv")) + (
    "config/r1/cells/M.tsv", "config/r1/cells/M_evcl.tsv", "config/r1/robustness_r1.json")
#: the merged rosters (rostermerge-03, d124ed7): the three J1a reads, and the two incfel variants the J1b
#: no-centre unit reads through chemmath_m --roster-variant incfel (its pin check STOPs UNPINNED_INPUT on an
#: unpinned repo file; M codex-fix ledger 2026-10-16 open issue 1)
ROSTERS = tuple(f"{INPUTS}/rosters/{n}" for n in (
    "roster_econ_verified_r1.parquet", "roster_gold_chemistry_r1.parquet", "roster_gold_math_stats_r1.parquet",
    "roster_gold_chemistry_r1_incfel.parquet", "roster_gold_math_stats_r1_incfel.parquet"))
RK6B_PIN = "data_refs.rk6b.manifest_sha256"
RK6B_FILES = ["ranks_own.csv", "ranks_C.csv", "flips.csv"]
M_CELLS = ["config/r1/cells/M.tsv", "config/r1/cells/M_evcl.tsv"]
ROBUSTNESS = "config/r1/robustness_r1.json"
EXPECT_COUNTS = {"econ": 173, "chemistry": 97, "math_stats": 107}
CELLS_ARG = re.compile(r'--cells\s+"\$REPO_DIR/([^"]+)"')
HEX64 = re.compile(r"[0-9a-f]{64}")


def _json(p):
    return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))


def _sha(p) -> str:
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def _m() -> dict:
    return _json(M_JSON)


def _by(rows, key) -> dict:
    out = {}
    for r in rows:
        assert r[key] not in out, f"duplicate {key} {r[key]!r}"
        out[r[key]] = r
    return out


def _m_ok_repo(tmp_path) -> tuple[pathlib.Path, pathlib.Path]:
    """A tmp repo that links every file M names, except an add-list summary that says OK (what the add-list
    rerun after the P3a rosters will write); M is copied with that one pin refreshed. Returns (M copy, root)."""
    m = _m()
    root = tmp_path / "repo"
    rels = set(m["pins"]) | {tok.split(":", 1)[1] for tok in [*m["inputs"], *m["signed"].values()]}
    for rel in sorted(rels):
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if rel == SUMMARY_REL:
            summary = _json(REPO / rel)
            summary.update(result="OK", roster_gaps=[])
            dst.write_text(json.dumps(summary, indent=1), encoding="utf-8")
        else:
            dst.symlink_to(REPO / rel)
    m["pins"][SUMMARY_REL] = _sha(root / SUMMARY_REL)
    cfg = root / "config" / "r1" / "M.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    return cfg, root


def _stage_rows(name) -> list:
    return _json(CONFIG_DIR / "stages" / f"{name}.json")["stages"]


def _j1a_cell_lists() -> set:
    """The --cells file of every J1a stage that runs run_cells.py."""
    out = set()
    for s in _stage_rows("j1a"):
        if s.get("script") == "pipeline/aws/r1/run_cells.py" or "run_cells.py" in s.get("cmd", ""):
            found = CELLS_ARG.findall(s["cmd"])
            assert len(found) == 1, f"j1a stage {s['name']}: {len(found)} --cells arguments"
            out.add(found[0])
    return out


@pytest.fixture(autouse=True)
def _no_config_env(monkeypatch):
    monkeypatch.delenv("SAR_R1_CONFIG", raising=False)


def test_m_config_loads_with_an_ok_add_list_and_every_registered_switch_is_on(tmp_path):
    cfg_path, root = _m_ok_repo(tmp_path)
    m = rc.load(cfg_path, repo=root)
    b0 = rc.load(B0_JSON)
    assert m.name == "M" and b0.name == "B0"
    assert set(OFF_IN_M) <= set(rc.SWITCHES)
    for name, reg in rc.SWITCHES.items():
        assert b0.switch(name) == reg["off"] and not b0.is_on(name), name
        if name in OFF_IN_M:
            assert m.switch(name) == reg["off"] and not m.is_on(name), name
        else:
            assert m.switch(name) == reg["on"] and m.is_on(name), name
    rows = _by(_m()["switches"], "switch")
    for name, date in OFF_IN_M.items():
        assert date in rows[name]["decided"] and "F20" in rows[name]["decided"], name


def test_m_loads_or_stops_only_at_the_add_list_gate():
    """With the committed files every pin and ruling holds; the only STOP left is the add-list gate."""
    if _json(REPO / SUMMARY_REL).get("result") == "OK":
        assert rc.load(M_JSON).name == "M"
    else:
        with pytest.raises(rc.ConfigStop) as e:
            rc.load(M_JSON)
        assert e.value.code == "ADD_LIST_NOT_OK", str(e.value)


def test_m_net_freeze_is_on():
    m = _m()
    row = _by(m["switches"], "switch")["network_freeze"]
    assert row["value"] == rc.SWITCHES["network_freeze"]["on"] == "both_hops_le_T-1"
    assert row["owner"] == "V3-NET" and row["decided"].strip() and row["source"].strip()
    assert _by(m["rulings"], "id")["C5"]["value"] == "both hops <= T-1"


def test_m_verdict_source_pins_the_signed_lists():
    m = _m()
    assert m["schema"] == rc.SCHEMA and m["config"] == "M" and m["base"] == "B0"
    assert _by(m["switches"], "switch")["verdict_source"]["value"] == "signed"
    assert set(m["signed"]) == set(rc.SIGNED_KEYS["M"])
    for key, tok in m["signed"].items():
        rel = tok[len("repo:"):]
        assert m["pins"].get(rel) == _sha(REPO / rel), f"signed list {key}: {rel}"
    assert set(m["pins"]) == set(M_PINS) | {r for r in ROSTERS if (REPO / r).exists()}
    for rel, sha in m["pins"].items():
        assert sha == _sha(REPO / rel), f"pin {rel} is stale: refresh M.json (W3-MPIN)"

    ref = m["data_refs"]["rk6b"]
    assert set(ref) == {"prefix", "files", "manifest_sha256"}
    assert re.fullmatch(r"r1/runs/rk6b-\d+/out/files/", ref["prefix"])
    assert ref["files"] == RK6B_FILES
    pending = [p for p in m["pending_pins"] if p.get("pin") == RK6B_PIN]
    if HEX64.fullmatch(str(ref["manifest_sha256"])):
        assert pending == []
    else:
        assert len(pending) == 1 and pending[0]["waits_for"].strip()


def test_m_rk6b_ref_is_pinned_and_in_the_j1a_sync():
    """Green only after pin-02 has pinned the rk6b prefix and W3-MPIN has copied its digest into M."""
    kit_dir = str(REPO / "pipeline" / "aws" / "r1")
    if kit_dir not in sys.path:
        sys.path.insert(0, kit_dir)
    import r1kit                                                             # noqa: PLC0415
    m = _m()
    ref = m["data_refs"]["rk6b"]
    pins = _json(INPUT_PINS)["pins"]
    assert ref["prefix"] in pins, f"{ref['prefix']} is not in config/r1/input_pins.json (pin-02)"
    assert ref["manifest_sha256"] == pins[ref["prefix"]]["manifest_sha256"]
    assert ref["prefix"] in [pair[0] for pair in r1kit.load_job("j1a")["data_sync"]]
    assert not [p for p in m["pending_pins"] if p.get("pin") == RK6B_PIN]


def test_m_pins_the_merged_rosters_once_committed():
    m = _m()
    pending = {p["path"] for p in m["pending_pins"] if "path" in p}
    for rel in ROSTERS:
        if (REPO / rel).exists():
            assert rel in m["pins"] and rel not in pending, f"{rel} is committed: pin it in M.json (W3-MPIN)"
        else:
            assert rel in pending and rel not in m["pins"], rel
    for p in m["pending_pins"]:
        assert ("path" in p) != ("pin" in p) and p["waits_for"].strip(), p
        if "path" in p:
            assert not (REPO / p["path"]).exists(), f"{p['path']} exists: move it from pending_pins to pins"


def test_m_pins_every_roster_variant_chemmath_m_reads():
    """M codex-fix pass, open issue 1: chemmath_m.pin_check STOPs UNPINNED_INPUT on a repo file that config M does
    not pin, and J1b's no-centre unit runs chemmath_m --roster-variant incfel. Every variant x field roster that
    chemmath_m can read is a pin of M at the committed bytes."""
    kit_dir = str(REPO / "pipeline" / "aws" / "r1")
    if kit_dir not in sys.path:
        sys.path.insert(0, kit_dir)
    import chemmath_m as cm                                                  # noqa: PLC0415
    pins = _m()["pins"]
    want = sorted({f"{INPUTS}/rosters/{cm.ROSTER_NAME[v].format(f=f)}" for v in cm.VARIANTS for f in cm.FIELDS})
    assert len(want) == 4 and set(want) <= set(ROSTERS)
    for rel in want:
        assert pins.get(rel) == _sha(REPO / rel), f"{rel}: not pinned at its committed bytes"


def test_m_dose_events_p05_rulings():
    m, b0 = _m(), _json(B0_JSON)
    sw = _by(m["switches"], "switch")
    want = {"dose_mode": "delta", "dose_excludes": "not_this_person", "add_backs": "on",
            "p05_label_fix": "pctC_0.95_celln_30", "label_fix": "pass_C", "own_field_rank": "field_topic",
            "new_stars": "add_list_r1", "redates": "signed", "calls": "r1", "rosters": "r1",
            "chemmath_edges": "u1_full_11school_2026-07-16", "agg_missing": "stop", "patch_raw": "r1",
            "p_full_precision": "on", "departure_ledger": "0910"}
    for name, value in want.items():
        assert sw[name]["value"] == value, name
    assert set(sw) == set(rc.SWITCHES)
    for name, row in sw.items():
        assert row["owner"] == rc.SWITCHES[name]["owner"], name
        assert row["decided"].strip() and row["source"].strip(), name

    rul, b0r = _by(m["rulings"], "id"), _by(b0["rulings"], "id")
    assert set(rul) == set(b0r) == set(rc.REQUIRED_RULINGS)
    for rid, r in rul.items():
        extra = {"skip"} if rid == "C10" else set()
        assert {k: v for k, v in r.items() if k not in extra | {"m_note"}} == b0r[rid], f"{rid} differs from B0"
        assert r["decided"].strip() and r["source"].strip(), rid
    assert rul["C10"]["value"] == "old79/new37 run in B0 only" and rul["C10"]["skip"] == list(C10)
    assert rul["F12"]["value"] == "no" and rul["M_rerun"]["value"] == "no" and rul["h5"]["value"] == "dropped"
    assert rul["h6"]["value"] == "delta" and "241" in rul["h7"]["value"]
    assert rul["decision_4"]["value"] == "pctC_0.95_celln_30" and rul["decision_5"]["value"] == "not_this_person"


def test_m_expect_counts_equal_the_signed_lists():
    m = _m()
    keep = collections.Counter(r["field"] for r in _json(REPO / INPUTS / "flips_r1.json")["rows"]
                               if r["verdict"] == "KEEP")
    accept = collections.Counter(r["field"] for r in _json(REPO / INPUTS / "add_list_r1.json")["rows"]
                                 if r["verdict"] == "ACCEPT")
    assert m["expect"]["counts"] == EXPECT_COUNTS == {f: keep[f] + accept[f] for f in FIELDS}


def test_m_sections_name_no_stage_paths():
    """M stage paths live in the stage rows; the config carries only the patch tags (none before a 3i fetch)."""
    m = _m()
    assert set(m["sections"]) == {"patch"} and set(m["sections"]["patch"]) == {"tags"}
    assert isinstance(m["sections"]["patch"]["tags"], list)
    assert all(re.fullmatch(r"[A-Za-z0-9._-]+", t) for t in m["sections"]["patch"]["tags"])
    assert "aws/cal2026-10/" not in M_JSON.read_text(encoding="utf-8")


def test_m_cells_and_robustness_paths():
    m = _m()
    assert m["cells"] == M_CELLS and all((REPO / c).is_file() for c in M_CELLS)
    assert m["robustness"] == ROBUSTNESS and (REPO / ROBUSTNESS).is_file() and ROBUSTNESS in m["pins"]
    assert all(c in m["pins"] for c in M_CELLS)
    assert _j1a_cell_lists() <= set(M_CELLS)
    owners = [(t, s["name"]) for t in STAGE_TABLES for s in _stage_rows(t) if s.get("owner") == "J0-MEAS.3a"]
    assert owners == []


def test_j1a_runs_both_m_cell_lists():
    """Green once W2-TJ1A adds the evcl stages: J1a runs exactly M's two cell lists."""
    assert _j1a_cell_lists() == set(_m()["cells"])


def test_m_redates_map_covers_every_signed_econ_redate():
    """W2-INT (W2-ECONM x W2-CONFIGM): econ920_m.check_redates_map STOPs REDATES_MAP_MISSING unless config M
    carries one 'redates' row per re-dated October econ event, {new, firstpub_redate 'keep' (h2), decided}. The
    signed re-dates are fixes_1001 'redate' rows and person_overrides 'arrival_year' rows; only a person with an
    October econ event is re-dated (an add-list person's year is the add list's, applied nowhere else)."""
    inp = REPO / "data" / "cal2026-10r1" / "inputs"
    with open(inp / "fixes_1001.csv", encoding="utf-8", newline="") as fh:
        signed = [(r["author_id"], r["value"]) for r in csv.DictReader(fh) if r["fix"] == "redate"]
    with open(inp / "person_overrides.csv", encoding="utf-8", newline="") as fh:
        signed += [(r["author_id"], r["value"]) for r in csv.DictReader(fh) if r["action"] == "arrival_year"]
    with open(REPO / "data" / "cal2026-10" / "events_econ_cal2026-10.csv", encoding="utf-8", newline="") as fh:
        october = {r["event_id"].split(":")[0]: r["event_id"] for r in csv.DictReader(fh)}
    want = {october[p]: f"{p}:{int(y)}" for p, y in signed if p in october}
    assert len(want) >= 2                                                       # A5028731684 (D01:5) and S14
    m = json.loads(M_JSON.read_text(encoding="utf-8"))
    rmap = m["redates"]
    assert set(rmap) == set(want)
    for old, row in rmap.items():
        assert row["new"] == want[old] and row["firstpub_redate"] == "keep" and len(row["decided"]) > 30, old
    assert next(s for s in m["switches"] if s["switch"] == "redates")["value"] == "signed"
