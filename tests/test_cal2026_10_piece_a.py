"""Piece A of the October caliber (pipeline/frames/cal2026-10/): the in-post stage on a synthetic
frame, the config templates, and the frozen star-id supplement's internal consistency. The
data-disk controls (C1-C3) live in run_controls.py and are re-run there, not here."""
from __future__ import annotations

import csv
import hashlib
import json
import pathlib
import string
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
LAYER = REPO / "pipeline" / "frames" / "cal2026-10"
CAL = REPO / "data" / "cal2026-10"
sys.path.insert(0, str(LAYER))
import inpost_filter as ipf                                             # noqa: E402

COLS = ["incumbent_person_id", "year", "star_person_id", "event_id", "treated", "post",
        "dose_coupling_baseline", "dose_topic", "dose_low_confidence", "age_gap", "fwci_frac",
        "pub_count", "fwci_frac_ex_star", "pub_count_ex_star", "fwci_mean", "fwci_mean_ex_star"]


def _frame(tmp: pathlib.Path, rows: list[tuple[str, str, int]], post_word: str = "True") -> pathlib.Path:
    """rows = (pid, event, arrival) -> the 11-year prodlib window per pair, CRLF like prodlib."""
    p = tmp / "frame.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(COLS)
        for pid, ev, arr in rows:
            for y in range(arr - 5, arr + 6):
                w.writerow([pid, y, "S", ev, "True", post_word if y >= arr else post_word.replace("rue", "alse").replace("RUE", "ALSE"),
                            "", "0.5", "False", "3.0", "", "", "", "", "", ""])
    return p


def test_inpost_filter_classes_and_byte_preservation(tmp_path):
    frame = _frame(tmp_path, [("P_A1", "E:2010", 2010), ("P_A2", "E:2010", 2010),
                              ("P_A3", "E:2010", 2010), ("P_A1", "F:2020", 2020)])
    spells = {"P_A1": [(2008, 2012)], "P_A2": [(2011, 2015)]}         # A3 has no spell
    rep = ipf.run(frame, spells, {"synthetic": True}, tmp_path / "out.csv", tmp_path / "rep.json")
    assert rep["relations_by_class"] == {"kept": 1, "dropped_no_spell": 1, "dropped_not_in_post": 2}
    assert rep["rows_by_class"] == {"kept": 11, "dropped_no_spell": 11, "dropped_not_in_post": 22}
    assert rep["per_event"]["E:2010"]["arrival"] == 2010 and rep["per_event"]["F:2020"]["arrival"] == 2020
    assert rep["events_left_with_zero_rows"] == ["F:2020"]
    raw = frame.read_bytes().split(b"\n")
    kept = [ln for ln in raw[1:] if ln.startswith(b"P_A1,") and ln.split(b",")[3] == b"E:2010"]
    assert (tmp_path / "out.csv").read_bytes() == b"\n".join([raw[0]] + kept) + b"\n"
    assert b"\r\n" in (tmp_path / "out.csv").read_bytes()               # CRLF preserved


def test_inpost_filter_reads_lowercase_post(tmp_path):
    frame = _frame(tmp_path, [("A1", "E:2010", 2010)], post_word="true")
    rep = ipf.run(frame, {"A1": [(2010, 2010)]}, {}, tmp_path / "o.csv", tmp_path / "r.json")
    assert rep["relations_by_class"]["kept"] == 1 and rep["per_event"]["E:2010"]["arrival"] == 2010


def test_spells_take_every_id_form(tmp_path):
    import pyarrow as pa, pyarrow.parquet as pq                          # noqa: E401
    pq.write_table(pa.table({"author_id": ["A1"], "year_start": [2000], "year_end": [2005]}),
                   tmp_path / "roster.parquet")
    pq.write_table(pa.table({"author_id": ["A1"], "person_id": ["P_Z9"]}), tmp_path / "pm.parquet")
    spells, src = ipf.spells_from_roster(tmp_path / "roster.parquet", tmp_path / "pm.parquet", False)
    assert set(spells) == {"A1", "P_A1", "P_Z9"} and spells["P_Z9"] == [(2000, 2005)]
    spells_id, _ = ipf.spells_from_roster(tmp_path / "roster.parquet", None, True)
    assert set(spells_id) == {"A1"}
    with pytest.raises(AssertionError):
        pq.write_table(pa.table({"author_id": ["A1"], "year_start": [2000], "year_end": [None]}),
                       tmp_path / "open.parquet")
        ipf.spells_from_roster(tmp_path / "open.parquet", None, True)


def test_config_templates_are_prodlib_schema_with_only_known_placeholders():
    keys = ("discipline", "snapshot", "person_map", "events", "roster", "indept",
            "star_first_pub", "ego_first_pub", "run_dir")                 # prodlib.load_config
    allowed = {"DERIVED", "LEGACY_V2", "SHADOW", "RUN_DIR"}
    for field in ("chemistry", "math_stats", "econ"):
        txt = (LAYER / "configs" / f"{field}.json").read_text("utf-8")
        cfg = json.loads(txt)
        assert all(k in cfg for k in keys), field
        used = {m[1] or m[2] for m in string.Template.pattern.findall(txt) if m[1] or m[2]}
        assert used <= allowed, (field, used - allowed)
        assert "/Volumes/" not in txt and "/Users/" not in txt, f"{field}: literal machine path"
    chem, math = (json.loads((LAYER / "configs" / f"{f}.json").read_text("utf-8"))
                  for f in ("chemistry", "math_stats"))
    assert chem["roster"]["mode"] == math["roster"]["mode"] == "silver_parquet"
    econ = json.loads((LAYER / "configs" / "econ.json").read_text("utf-8"))
    assert econ["roster"]["mode"] == "u4_roster_pool" and econ["person_map"]["mode"] == "parquet"
    assert econ["events"]["mode"] == "u4_frozen" and econ["outcome_exclusion_stars"]["mode"] == "exclude_list"


def test_star_id_supplement_is_internally_consistent():
    rep = json.loads((CAL / "supplement_report_star_id_corrections_2026-10.json").read_text("utf-8"))
    sup = CAL / "edges_supplement_star_id_corrections_2026-10.jsonl"
    log = CAL / "api_request_log_star_id_corrections_2026-10.jsonl"
    lines = [json.loads(ln) for ln in sup.read_text("utf-8").splitlines()]
    corrections = list(csv.DictReader(open(CAL / "star_id_corrections_2026-10.csv", encoding="utf-8")))
    assert {c["new_id"] for c in corrections} == set(rep["stars"])
    for new, s in rep["stars"].items():
        mine = [ln for ln in lines if ln["seed_author"] == new]
        assert len(mine) == s["supplement_rows"]
        assert all(new in ln["authors"] for ln in mine)
        assert all(list(ln.keys()) == ["work_id", "publication_year", "type", "seed_author",
                                       "authors"] for ln in mine)
        dropped = {e["work_id"] for e in s["exclusions_applied"] if e["dropped"]}
        assert dropped.isdisjoint({ln["work_id"] for ln in mine})
        works = json.loads((CAL / s["_works_json"]).read_text("utf-8"))
        assert len(works) == s["works_fetched"] and s["tripwire"]["missing_from_live"] == []
        calls = {r["work_id"] for r in csv.DictReader(open(CAL / "calls_2026-10.csv", encoding="utf-8"))
                 if r["author_id"] == new and r["action"] == "exclude"}
        assert calls == {e["work_id"] for e in s["exclusions_applied"]}
    for name, want in rep["outputs_sha256"].items():
        assert hashlib.sha256((CAL / name).read_bytes()).hexdigest() == want, name
    assert "api_key" not in log.read_text("utf-8")
    assert rep["request_total"] == len(log.read_text("utf-8").splitlines())


# ---------------------------------------------------------------------------------------------
# review additions (2026-09-22): the stage derivations on synthetic inputs — no data disk needed
# ---------------------------------------------------------------------------------------------
import stage                                                            # noqa: E402


def _write_csv(p: pathlib.Path, header: list[str], rows: list[list]) -> None:
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def test_derived_fnfixbase_drops_removed_events_and_appends_admissions(tmp_path):
    v2 = tmp_path / "v2"
    gold = v2 / stage.GOLD / "data"
    gold.mkdir(parents=True)
    src = gold / "events_chemistry_fnfixbase_2026-08-10.csv"
    _write_csv(src, ["event_id", "arrival_year"], [["A1:anu", 2005], ["A2:uq", 2010], ["A3:unsw", 2012]])
    table = tmp_path / "events_chemistry_cal2026-10.csv"
    _write_csv(table, ["author_id", "field", "school", "arrival_corrected"],
               [["A1", "chemistry", "anu", 2005], ["A3", "chemistry", "unsw", 2012],
                ["A9", "chemistry", "monash", 2020]])                    # A2 dropped, A9 admitted
    blob, d = stage.derived_fnfixbase(v2, "chemistry", table)
    rows = list(csv.DictReader(blob.decode("utf-8").splitlines()))
    assert [r["event_id"] for r in rows] == ["A1:anu", "A3:unsw", "A9:monash"]
    assert rows[-1]["arrival_year"] == "2020"
    assert d == {"frozen_rows": 3, "kept": 2, "dropped": ["A2:uq"], "added": ["A9:monash"]}
    # frozen prefix bytes are preserved when nothing is dropped (the 08-28 case, C2's byte control)
    _write_csv(table, ["author_id", "field", "school", "arrival_corrected"],
               [["A1", "chemistry", "anu", 2005], ["A2", "chemistry", "uq", 2010],
                ["A3", "chemistry", "unsw", 2012], ["A9", "chemistry", "monash", 2020]])
    blob2, _ = stage.derived_fnfixbase(v2, "chemistry", table)
    assert blob2.startswith(src.read_bytes())


def test_derived_shortlist_is_a_byte_preserving_superset(tmp_path):
    v2 = tmp_path / "v2"
    gold = v2 / stage.GOLD / "data"
    gold.mkdir(parents=True)
    src = gold / "shortlist_fnfix.csv"
    _write_csv(src, ["author_id", "field", "school", "arrival_year"],
               [["A1", "chemistry", "anu", 2005], ["M1", "math_stats", "uq", 2001]])
    tables = {}
    for field, rows in (("chemistry", [["A1", "chemistry", "anu", 2005], ["A7", "chemistry", "uwa", 2015]]),
                        ("math_stats", [["M1", "math_stats", "uq", 2001]])):
        tables[field] = tmp_path / f"events_{field}.csv"
        _write_csv(tables[field], ["author_id", "field", "school", "arrival_corrected"], rows)
    blob, d = stage.derived_shortlist(v2, tables)
    assert blob.startswith(src.read_bytes())
    assert d == {"frozen_rows": 2, "added": ["A7:chemistry:uwa"]}
    rows = list(csv.DictReader(blob.decode("utf-8").splitlines()))
    assert rows[-1] == {"author_id": "A7", "field": "chemistry", "school": "uwa", "arrival_year": "2015"}


def test_build_exclusion_adds_every_fragment_of_an_econ_star_person(tmp_path):
    import pyarrow as pa, pyarrow.parquet as pq                          # noqa: E401
    base = tmp_path / "base.parquet"
    pq.write_table(pa.table({"author_id": ["Z1", "C1"]}), base)
    pm = tmp_path / "pm.parquet"
    pq.write_table(pa.table({"author_id": ["E1", "E1b", "E1c", "X1", "C1"],
                             "person_id": ["P_E1", "P_E1", "P_E1", "P_X1", "P_C1"]}), pm)
    out = tmp_path / "excl.parquet"
    d = stage.build_exclusion({"econ": ["E1"], "chemistry": ["C1", "C2"]}, out, person_map=pm, base=base)
    got = pq.read_table(out).column("author_id").to_pylist()
    assert got == ["C1", "C2", "E1", "E1b", "E1c", "Z1"]                 # ORDER BY author_id, deduped
    assert d["fragments_added"] == ["E1b", "E1c"] and d["fragments_by_star"] == {"E1": ["E1b", "E1c"]}
    assert d["added"] == ["C2", "E1"] and d["total"] == 6 and d["stars_with_fragments"] == 1
    # without a person map: bare ids only (the identity-mapped fields' rule)
    d2 = stage.build_exclusion({"econ": ["E1"], "chemistry": ["C1"]}, tmp_path / "e2.parquet", base=base)
    assert pq.read_table(tmp_path / "e2.parquet").column("author_id").to_pylist() == ["C1", "E1", "Z1"]
    assert d2["fragments_added"] == []


def test_build_roster_pool_keeps_the_dept_roster_panel_shape_and_drops_excluded(tmp_path):
    import pyarrow as pa, pyarrow.parquet as pq                          # noqa: E401
    src = tmp_path / "roster.parquet"
    pq.write_table(pa.table({"dept_key": ["uq_econ", "anu_econ", "anu_econ"],
                             "author_id": ["B1", "A1", "S1"], "year_start": [2001, 2010, 2005],
                             "year_end": [2004, 2020, 2009], "evidence": ["e", "e", "e"],
                             "confidence": ["high", "high", "high"],
                             "human_verified": [True, True, False]}), src)
    out = tmp_path / "pool.parquet"
    d = stage.build_roster_pool({"S1", "S9"}, out, src=src)
    t = pq.read_table(out)
    assert t.column_names == ["dept_key", "author_id", "display_name", "year_start", "year_end",
                              "evidence", "confidence", "human_verified"]
    assert t.column("author_id").to_pylist() == ["A1", "B1"]             # ORDER BY dept_key, author_id
    assert t.column("display_name").to_pylist() == [None, None]
    assert str(t.schema.field("year_start").type) == "int16"
    assert d["rows_in"] == 3 and d["rows_out"] == 2 and d["dropped_star_rows"] == ["S1"]
    pq.write_table(pa.table({"dept_key": ["uq_econ"], "author_id": ["B1"], "year_start": [2001],
                             "year_end": pa.array([None], pa.int64()), "evidence": ["e"],
                             "confidence": ["high"], "human_verified": [True]}), src)
    with pytest.raises(AssertionError):
        stage.build_roster_pool(set(), tmp_path / "pool2.parquet", src=src)


def test_render_config_substitutes_every_placeholder(monkeypatch, tmp_path):
    monkeypatch.setattr(stage, "derived_root", lambda: tmp_path / "derived")
    monkeypatch.setattr(stage, "legacy_v2", lambda: tmp_path / "v2")
    for field in stage.FIELDS:
        cfg = stage.render_config(field, tmp_path / "shadow", tmp_path / "run")
        assert cfg["run_dir"] == str(tmp_path / "run")
        assert cfg["snapshot"]["edges_glob"].startswith(str(tmp_path / "derived"))
        assert "${" not in json.dumps(cfg)


def test_event_tables_modes(tmp_path):
    # R1 F3 (2026-10-15): the tables are named — 'auto' (choose by which files exist) is gone, and the
    # October tables are read from the root the run config's stage.events_root names
    for bad in ("bogus", "auto"):
        with pytest.raises(ValueError):
            stage.event_tables(bad, root=CAL)
    tables, tag = stage.event_tables("cal2026-08-28", root=CAL)
    assert tag == "cal2026-08-28" and set(tables) == set(stage.FIELDS)
    for f, p in tables.items():
        assert p.read_bytes() == (REPO / "data" / "raw_verified" / f"events_{f}_cal2026-08-28.csv").read_bytes()
    tables, tag = stage.event_tables("cal2026-10", root=CAL)
    assert tag == "cal2026-10" and tables == {f: CAL / f"events_{f}_cal2026-10.csv" for f in stage.FIELDS}
    with pytest.raises(FileNotFoundError):                       # an empty root is a STOP, not 08-28
        stage.event_tables("cal2026-10", root=tmp_path)
