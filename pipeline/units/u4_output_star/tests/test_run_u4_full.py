"""U4 shipping - run_u4_full master orchestration.

In plain words: one entry point runs the three tables U4 owes downstream + the star_set rebuild, in dependency order:
  preflight (inputs complete + provenance resolvable + frozen-file fingerprint binding check)
  -> ship_fwci_baseline -> ship_paper_contrib (isc consumes the frozen rows)
  -> build_star_set rebuild + star-flag consistency gate (both flags + age_eligible + arrival + poach, person by
    person == the frozen files; percentile may differ, the difference distribution goes into a report) + freeze
    (includes the Zenou golden gate; the idempotency key stars_set_hash must == the frozen file)
  -> three real-data assembly pieces -> ship_events (includes the arrival-year consistency hard gate).
Each stage writes a tally (reconcile_fetch six keys, in-memory counts vs read-back from disk) + a ledger event +
a resume anchor (upstream content hash + rule_version/config_sha; a stage is skipped only if these are unchanged
and the real artifact is present with a matching sha).
M6 generations are not covered here. Fully synthetic data, zero SSD writes.
"""
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from identity.cohort import cohort_bin
from m7a_star.adjudications import ADJUDICATIONS_SUB
from run_u4 import ROSTER_FILES

ZID = "A5017376589"          # Zenou (the golden gate requires this person to be present)
BID = "A_B_MON"              # benchmark candidate in the same cell (not a star)
NOARR = "A_U_NOARR"          # UNSW candidate without an arrival year (no_arrival path)
MON = "I56590836"
UNSW = "I31746571"
SE = "I_SE_STOCKHOLM"
ECON = "2002"
EDGES = "u1_edges_full_2026-07-05"


def _w(root, subpath, rows, schema=None):
    p = root / subpath
    p.parent.mkdir(parents=True, exist_ok=True)
    tbl = pa.Table.from_pylist(rows, schema=schema) if schema else pa.Table.from_pylist(rows)
    pq.write_table(tbl, str(p))


_ROSTER_SCHEMA = pa.schema([
    ("dept_key", pa.string()), ("author_id", pa.string()), ("display_name", pa.string()),
    ("year_start", pa.int64()), ("year_end", pa.int64()), ("evidence", pa.string()),
    ("confidence", pa.string()), ("human_verified", pa.bool_()),
])


def _roster_row(dept, aid, name, year, *, hv=True, conf="high"):
    return {"dept_key": dept, "author_id": aid, "display_name": name,
            "year_start": year, "year_end": None, "evidence": "seek",
            "confidence": conf, "human_verified": hv}


def _write_adjudications(r, *, exclude=None, poach=None, year_fixes=None,
                         signal_discards=None, arrival_verifications=None):
    """Hand-review adjudication file (a required input of run_u4_full, fail-loud; the default is an empty adjudication)."""
    ann = {"date": "2026-07-10", "authorized_by": "2026-07-10 (test fixture)",
           "year_start_fixes": year_fixes or {},
           "identity_dispositions": {
               aid: {"dept_key": "monash_econ", "disposition": "adjunct_q3_not_incumbent",
                     "exclude_from_candidates": True, "note": f"adjunct_q3: {note}"}
               for aid, note in (exclude or {}).items()},
           "poach_dispositions": {
               aid: {"dept_key": "monash_econ", "prior_au_employment": True,
                     "is_foreign_poach": False, "note": note}
               for aid, note in (poach or {}).items()},
           "signal_discards": signal_discards or {},
           "arrival_verifications": arrival_verifications or {}}
    p = r / ADJUDICATIONS_SUB                # single source of truth: production and tests use the same path constant
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(ann, ensure_ascii=False), encoding="utf-8")
    return p


def _universe(tmp_path, *, monash_years=(2016, 2017), exclude=None, poach=None,
              year_fixes=None, zenou_hv=True, fake_au_year=None, signal_discards=None,
              arrival_verifications=None):
    """Minimal real-shaped universe: Zenou (roster 2016 hand-verified, stock rank 1 in the cell, cell_n=102>=100 -> 1% star,
    at Stockholm (SE) before arrival -> pure foreign poach) + B (stock rank 51 in the cell -> not a star) + NOARR
    (no arrival year).
    monash_years: Monash years of Zenou's timeline (default 2016/2017 -> detect == star set 2016).
    zenou_hv: human_verified of Zenou's roster row - False = a universe without hand-verification evidence (the
    HALT side of the events gate).
    fake_au_year: add a fake clean Monash row before arrival to Zenou's timeline (signal-discard fixture).
    exclude/poach/year_fixes/signal_discards/arrival_verifications -> the hand-review adjudication file.
    """
    r = tmp_path / "derived"
    # roster (table B; corrected-version path = the single source of truth run_u4.ROSTER_FILES)
    _w(r, ROSTER_FILES[0], [
        _roster_row("monash_econ", ZID, "Yves Zenou", 2016, hv=zenou_hv),
        _roster_row("monash_econ", BID, "Bob Benchmark", 2016),
    ], schema=_ROSTER_SCHEMA)
    _w(r, ROSTER_FILES[1], [
        _roster_row("unsw_econ", NOARR, "No Arrival", None, hv=False, conf="low"),
    ], schema=_ROSTER_SCHEMA)
    _write_adjudications(r, exclude=exclude, poach=poach, year_fixes=year_fixes,
                         signal_discards=signal_discards,
                         arrival_verifications=arrival_verifications)
    # U1 works / edges: Zenou 99999 citations + B 50 citations + 100 pool people with 0..99 citations, all 1990/econ/article
    works = [{"work_id": "WZ", "publication_year": 1990, "subfield_id": ECON,
              "work_type": "article", "cited_by_count": 99999, "is_paratext": False,
              "fwci": 50.0},
             {"work_id": "WB", "publication_year": 1990, "subfield_id": ECON,
              "work_type": "article", "cited_by_count": 50, "is_paratext": False,
              "fwci": 0.5}]
    edges = [{"author_id": ZID, "work_id": "WZ"}, {"author_id": BID, "work_id": "WB"}]
    for i in range(100):
        works.append({"work_id": f"WP{i:03d}", "publication_year": 1990,
                      "subfield_id": ECON, "work_type": "article",
                      "cited_by_count": i, "is_paratext": False, "fwci": None})
        edges.append({"author_id": f"PL{i:03d}", "work_id": f"WP{i:03d}"})
    _w(r, f"{EDGES}/works/part.parquet", works)
    _w(r, f"{EDGES}/authorship_edges/part.parquet", edges)
    _w(r, f"{EDGES}/institutions/part.parquet", [
        {"institution_id": SE, "country_code": "SE", "lineage": [SE]},
        {"institution_id": MON, "country_code": "AU", "lineage": [MON]},
        {"institution_id": UNSW, "country_code": "AU", "lineage": [UNSW]}])
    # works_affil (source of the affiliation-gate counts) - Zenou/B each have 1 paper at Monash (share 1.0, not flagged).
    _w(r, f"{EDGES}/works_affil/part.parquet", [
        {"work_id": "WZ", "author_id": ZID, "institution_id": MON,
         "raw_affiliation_strings": ["Monash University"]},
        {"work_id": "WB", "author_id": BID, "institution_id": MON,
         "raw_affiliation_strings": ["Monash University"]}])
    # registry table A (the real consumer of the discipline gate; a required input of run_u4_full, fail-loud).
    from run_u4 import REGISTRY_SUB_DEFAULT
    _w(r, REGISTRY_SUB_DEFAULT, [
        {"dept_key": "monash_econ", "subfield_excluded": ["Finance"]},
        {"dept_key": "unsw_econ", "subfield_excluded": ["Finance"]}])
    _w(r, f"{EDGES}/fwci_baseline_pop/data.parquet", [    # read_derived_table contract layout
        {"subfield_id": ECON, "year": 1990, "work_type": "article",
         "citation_sum": 1000, "work_count": 10}])       # expected = 100.0
    (r / EDGES / "_manifest").mkdir(parents=True, exist_ok=True)
    (r / EDGES / "_manifest" / "run_manifest.json").write_text(
        json.dumps({"source_snapshot_merkle": "snap:FULLTEST", "config_sha": "cfg:u1"}),
        encoding="utf-8")
    # U2 person_map
    _w(r, "u2_person_map_2026-07-05/person_map/data.parquet", [
        {"author_id": ZID, "person_id": "P_Z"},
        {"author_id": BID, "person_id": "P_B"},
        {"author_id": NOARR, "person_id": "P_N"}])
    # U3 panel (NOARR has no row for the department -> the panel fallback cannot infer -> no_arrival) + affil_timeline
    _w(r, "u3_panel_2026-07-06/panel/data.parquet", [
        {"person_id": "P_Z", "year": 2016, "primary_affil_id": MON}])
    tl = [{"person_id": "P_Z", "year": y, "work_id": f"WT{y}",
           "raw_affil": "Stockholm University", "canonical_affil_id": SE,
           "is_modal": True} for y in (2013, 2014)]
    tl += [{"person_id": "P_Z", "year": y, "work_id": f"WT{y}",
            "raw_affil": "Monash University, Clayton, Australia",
            "canonical_affil_id": MON, "is_modal": True} for y in monash_years]
    if fake_au_year is not None:            # signal-discard fixture: a fake clean Monash row before arrival (part-time / mis-affiliated shape)
        tl.append({"person_id": "P_Z", "year": fake_au_year, "work_id": f"WTF{fake_au_year}",
                   "raw_affil": "Monash University, Clayton, Australia",
                   "canonical_affil_id": MON, "is_modal": False})
    _w(r, "u3_panel_2026-07-06/affil_timeline/data.parquet", tl)
    # wayback parsed record (diacritic spelling Zénou -> normalised and matched)
    _w(r, "u0p5_hist_raw/wayback_full_2026-07-06/parsed/wayback_staff_lines.parquet", [
        {"dept_key": "monash_econ", "display_name": "Yves Zénou", "snapshot_year": 2017},
        {"dept_key": "monash_econ", "display_name": "Ghost Person", "snapshot_year": 2007}])
    return r


def _frozen_dir(tmp_path, *, z_flags=None, z_arrival=2016, pct=(0.995, 0.75),
                b_arrival=2016):
    """Frozen-file fixture: same flags as the rebuild (default) - percentile deliberately uses the old formula's values (allowed to differ)."""
    from m7a_star.freeze import stars_set_hash
    zf = z_flags or {"is_star_1pct": True, "is_star_5pct": True, "age_eligible": True,
                     "is_foreign_poach": True}
    rows = [
        {"author_id": ZID, "name": "Yves Zenou", "dept": "monash_econ",
         "arrival": z_arrival, "subfield": ECON, "age_bin": cohort_bin(25),
         "academic_age": 25, "stock": 99999, "percentile": pct[0], "cell_n": 102,
         **zf},
        {"author_id": BID, "name": "Bob Benchmark", "dept": "monash_econ",
         "arrival": b_arrival, "subfield": ECON, "age_bin": cohort_bin(25),
         "academic_age": 25, "stock": 50, "percentile": pct[1], "cell_n": 102,
         "is_star_1pct": False, "is_star_5pct": False, "age_eligible": True,
         "is_foreign_poach": False},
    ]
    d = tmp_path / "u4_star_set_2026-07-08"
    d.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), str(d / "star_set.parquet"))
    (d / "manifest_header.json").write_text(json.dumps(
        {"table": "star_set",
         "stars_set_hash": stars_set_hash({r["author_id"]: r["arrival"] for r in rows}),
         "rule_version": "redlines_v4_signed_2026-07-05"}), encoding="utf-8")
    return d


def _run(tmp_path, **kw):
    from run_u4 import run_u4_full
    root = kw.pop("root", None) or _universe(tmp_path)
    frozen = kw.pop("frozen", None) or _frozen_dir(tmp_path)
    return run_u4_full(root, tmp_path / "ship", frozen_dir=frozen, **kw)


# ---- pass-through of the whole chain --------------------------------------------------------------------

def test_run_u4_full_lands_four_tables_with_gates(tmp_path):
    """happy path: four artifacts land in the ship root (fwci_baseline / paper_contrib / star_set / events);
    star flags 123/123 (here 2/2) agree with the frozen file; stars_set_hash idempotent == frozen file; events =
    a single Zenou row (5% and poach), arrival 2016 / t-1 2015 / wayback evidence tier strong; Zenou fwci raw value
    passes through (99999/100, no winsor); the old/new percentile difference goes into a report."""
    from m7a_star.freeze import stars_set_hash

    res = _run(tmp_path)
    out = tmp_path / "ship"
    assert res["status"] == "SHIPPED"

    # fwci_baseline: expected = 1000/10 = 100
    fb = pq.read_table(str(out / "fwci_baseline" / "data.parquet")).to_pylist()
    assert fb == [{"subfield_id": ECON, "year": 1990, "work_type": "article",
                   "expected_citations": 100.0}]

    # paper_contrib: two rows WZ/WB (single-author works, frac=1); fwci raw value passes through 99999/100=999.99
    pc_rows = []
    for p in sorted((out / "paper_contrib").rglob("part-*.parquet")):
        pc_rows += pq.read_table(str(p)).to_pylist()
    by_work = {r["work_id"]: r for r in pc_rows}
    assert by_work["WZ"]["fwci"] == pytest.approx(999.99)     # not clipped: the raw value is stored
    assert by_work["WZ"]["frac_credit"] == 1.0
    assert by_work["WZ"]["is_star_coauthored"] is True        # isc backfill: Zenou is in the star set
    assert by_work["WB"]["is_star_coauthored"] is False

    # star_set: both flags agree with the frozen file + fingerprint idempotent
    ss = {r["author_id"]: r
          for r in pq.read_table(str(out / "star_set" / "star_set.parquet")).to_pylist()}
    assert ss[ZID]["is_star_1pct"] is True and ss[ZID]["is_star_5pct"] is True
    assert ss[BID]["is_star_1pct"] is False and ss[BID]["is_star_5pct"] is False
    assert ss[ZID]["percentile"] == pytest.approx(1 - 1 / 102, abs=1e-4)  # new naive ranking
    hdr = json.loads((out / "star_set" / "manifest_header.json").read_text("utf-8"))
    assert hdr["stars_set_hash"] == stars_set_hash({ZID: 2016, BID: 2016})
    assert hdr["source_snapshot_merkle"] == "snap:FULLTEST"
    assert res["star_set"]["stars_set_hash"] == hdr["stars_set_hash"]

    # events: a single Zenou row (B is not a star), evidence tier = wayback (matched 2017, ranked above roster in the six-source order)
    ev = pq.read_table(str(out / "events" / "data.parquet")).to_pylist()
    assert len(ev) == 1 and ev[0]["star_person_id"] == ZID
    assert ev[0]["arrival_year"] == 2016 and ev[0]["t_minus_1"] == 2015
    assert ev[0]["dept_id"] == MON
    assert ev[0]["arrival_source"] == "wayback"
    assert ev[0]["arrival_evidence_strength"] == "strong"
    assert ev[0]["modal_inst_year"] is True

    # percentile old/new difference report (frozen 0.995/0.75 vs new 1-1/102 / 1-51/102)
    diff_csv = (out / "_reports" / "percentile_diff.csv").read_text("utf-8")
    assert ZID in diff_csv and BID in diff_csv
    assert res["percentile_diff"]["n_compared"] == 2
    assert res["percentile_diff"]["max_abs_diff"] > 0


def test_run_u4_full_tally_ledger_and_manifest(tmp_path):
    """Accounting triple: each stage tally has six keys balanced=True (reconciled by reading back from disk); ledger events
    status=ok; run_summary/_manifest complete (shares + FWCI NA + n_dropped_null_pub_year accounting present)."""
    res = _run(tmp_path)
    out = tmp_path / "ship"
    for stage in ("fwci_baseline", "paper_contrib", "star_set", "events"):
        t = json.loads((out / "_tally" / f"{stage}.json").read_text("utf-8"))
        assert t["balanced"] is True and t["stage"] == f"u4_ship:{stage}"
        assert t["expected"] == t["kept"] + t["failed"] + t["skipped"]
    lines = [json.loads(l) for l in
             (out / "_ledger" / "events.jsonl").read_text("utf-8").splitlines()]
    assert {l["op_id"] for l in lines} >= {
        "u4_ship:fwci_baseline", "u4_ship:paper_contrib", "u4_ship:star_set",
        "u4_ship:events"}
    assert all(l["status"] == "ok" for l in lines)
    summary = json.loads((out / "_manifest" / "run_summary.json").read_text("utf-8"))
    assert summary["status"] == "SHIPPED"
    assert summary["paper_contrib"]["inferred_ratio"] == 0.0       # share accounting
    assert "n_dropped_null_pub_year" in summary["star_set"]        # dropped-row accounting present
    assert summary["paper_contrib"]["pk_unique"] is True
    assert summary["events"]["n_events"] == 1


def test_run_u4_full_star_flag_drift_halts_with_report(tmp_path):
    """Star-flag consistency gate (default mode halt): the frozen file says Zenou is not a 1% star (inconsistent with
    the rebuilt flags) -> StarSetDrift HALT; the difference report goes to _reports/star_flag_mismatch.json (who /
    which field / what the frozen file says / what the rebuild says); star_set/events are not written at all.
    In the current stage order, the star_set gate comes before paper_contrib -> if the gate fails, paper_contrib is not
    written either (the already written fwci_baseline is kept)."""
    from run_u4 import StarSetDrift

    frozen = _frozen_dir(tmp_path, z_flags={
        "is_star_1pct": False, "is_star_5pct": True, "age_eligible": True,
        "is_foreign_poach": True})
    with pytest.raises(StarSetDrift):
        _run(tmp_path, frozen=frozen)
    out = tmp_path / "ship"
    rep = json.loads((out / "_reports" / "star_flag_mismatch.json").read_text("utf-8"))
    assert rep["n_mismatch"] == 1
    d = rep["diff"][0]
    assert d["author_id"] == ZID and d["field"] == "is_star_1pct"
    assert d["frozen"] is False and d["rebuilt"] is True
    assert not (out / "star_set").exists()          # the gate fails -> the star set is not written at all
    assert not (out / "events").exists()
    assert not (out / "paper_contrib").exists()     # reordered: isc consumes only a star set that passed the gate
    assert (out / "fwci_baseline").exists()         # earlier artifacts are kept
    summary = json.loads((out / "_manifest" / "run_summary.json").read_text("utf-8"))
    assert summary["status"] == "HALT_STAR_FLAG_DRIFT"


def test_run_u4_full_frozen_binding_halts_before_any_write(tmp_path):
    """Frozen-file fingerprint binding check fails -> HALT at the orchestration entry (FrozenStarSetMismatch),
    no artifact is written (the three shipped tables cannot be bound to a corrupted star set)."""
    from run_u4 import FrozenStarSetMismatch

    root = _universe(tmp_path)
    frozen = _frozen_dir(tmp_path)
    hdr = json.loads((frozen / "manifest_header.json").read_text("utf-8"))
    hdr["stars_set_hash"] = "deadbeef"
    (frozen / "manifest_header.json").write_text(json.dumps(hdr), encoding="utf-8")
    with pytest.raises(FrozenStarSetMismatch):
        _run(tmp_path, root=root, frozen=frozen)
    assert not (tmp_path / "ship" / "fwci_baseline").exists()
    assert not (tmp_path / "ship" / "paper_contrib").exists()


def test_run_u4_full_events_arrival_mismatch_halts(tmp_path):
    """Arrival-year consistency hard gate propagates through the orchestration: Monash years in the timeline changed to
    2017/2018 -> detect_arrival=2017 != frozen 2016 -> ArrivalMismatch HALT; the difference report is in _reports;
    events are not written at all; the three earlier tables are kept (intermediates stay in the new directory);
    run_summary records the HALT status.
    (Under the supplementary events rule: in this universe Zenou's roster row is **not hand-verified**
    (zenou_hv=False) -> no hand-verification evidence + the two routes disagree = HALT as before; this test covers
    the "no hand-verified evidence" side.)"""
    from m7a_star.events_pipeline import ArrivalMismatch

    root = _universe(tmp_path, monash_years=(2017, 2018), zenou_hv=False)
    with pytest.raises(ArrivalMismatch):
        _run(tmp_path, root=root)
    out = tmp_path / "ship"
    rep = json.loads((out / "_reports" / "arrival_mismatch_report.json").read_text("utf-8"))
    assert rep["n_mismatch"] == 1
    assert rep["diff"][0]["star_set_arrival"] == 2016
    assert rep["diff"][0]["events_arrival_year"] == 2017
    assert not (out / "events").exists()
    assert (out / "star_set" / "star_set.parquet").exists()    # earlier artifacts are kept
    summary = json.loads((out / "_manifest" / "run_summary.json").read_text("utf-8"))
    assert summary["status"] == "HALT_EVENTS_ARRIVAL_MISMATCH"


def test_run_u4_full_missing_input_halts_before_write(tmp_path):
    """preflight: a required input table is absent (works) -> ValueError naming it, no artifact written."""
    import shutil

    root = _universe(tmp_path)
    shutil.rmtree(root / EDGES / "works")
    with pytest.raises(ValueError, match="works"):
        _run(tmp_path, root=root)
    assert not (tmp_path / "ship" / "fwci_baseline").exists()


def test_run_u4_full_resume_skips_unchanged(tmp_path):
    """resume anchor: upstream content hash + rule_version/config_sha + frozen fingerprint unchanged, the real artifacts
    present with matching sha -> all four stages skipped (status skipped_resume, ledger records status=skip);
    artifact bytes untouched. Artifact tampered with -> that stage is not skipped (rebuilt)."""
    import hashlib

    root = _universe(tmp_path)
    frozen = _frozen_dir(tmp_path)
    res1 = _run(tmp_path, root=root, frozen=frozen)
    out = tmp_path / "ship"
    ss = out / "star_set" / "star_set.parquet"
    sha_before = hashlib.sha256(ss.read_bytes()).hexdigest()

    res2 = _run(tmp_path, root=root, frozen=frozen)
    assert res2["status"] == "SHIPPED"
    for stage in ("fwci_baseline", "paper_contrib", "star_set", "events"):
        assert res2[stage]["resume"] == "skipped_resume", stage
    assert hashlib.sha256(ss.read_bytes()).hexdigest() == sha_before
    lines = [json.loads(l) for l in
             (out / "_ledger" / "events.jsonl").read_text("utf-8").splitlines()]
    assert [l["status"] for l in lines if l["op_id"] == "u4_ship:star_set"] == ["ok", "skip"]

    # artifact tampered with -> sha mismatch -> not skipped, rebuilt back to the correct bytes
    ss.write_bytes(b"tampered")
    res3 = _run(tmp_path, root=root, frozen=frozen)
    assert res3["star_set"]["resume"] == "rebuilt"
    assert hashlib.sha256(ss.read_bytes()).hexdigest() == sha_before


# ====== hand-review adjudication file required + diff mode (the list is allowed to change) ======

def test_run_u4_full_missing_adjudication_file_halts(tmp_path):
    """Hand-review adjudication file absent -> ValueError naming it (the star-selection production path never silently skips
    the adjudications), no artifact written."""
    root = _universe(tmp_path)
    (root / ADJUDICATIONS_SUB).unlink()
    with pytest.raises(ValueError, match="roster_fix_2026-07-10"):
        _run(tmp_path, root=root)
    assert not (tmp_path / "ship" / "fwci_baseline").exists()


def test_run_u4_full_stale_roster_vs_year_fixes_halts(tmp_path):
    """Guard gate: the adjudication says B's arrival year = 2015 while the roster (the version read) still says 2016 ->
    verify blocks and stops, no artifact written (prevents silent definition drift when "the adjudication changed but the
    roster version did not")."""
    root = _universe(tmp_path, year_fixes={
        BID: {"dept_key": "monash_econ", "year_start": 2015,
              "evidence": "human_verified_web:CV"}})
    with pytest.raises(ValueError, match="verify_roster_matches_fixes"):
        _run(tmp_path, root=root)
    assert not (tmp_path / "ship" / "fwci_baseline").exists()


def test_run_u4_full_diff_mode_ships_star_change_with_report(tmp_path):
    """diff mode (rerun where the list is allowed to change): frozen B arrival=2015 != rebuilt 2016 ->
    no HALT; instead writes _reports/star_set_diff.json (person by person, field by field) + the idempotency key is
    no longer forced equal (both values recorded); the Zenou golden gate is unchanged (inside freeze); events are
    still shipped (Zenou's two routes agree on the year)."""
    root = _universe(tmp_path)
    frozen = _frozen_dir(tmp_path, b_arrival=2015)
    res = _run(tmp_path, root=root, frozen=frozen, star_change_mode="diff")
    out = tmp_path / "ship"
    assert res["status"] == "SHIPPED"
    rep = json.loads((out / "_reports" / "star_set_diff.json").read_text("utf-8"))
    assert rep["n_mismatch"] == 1
    assert rep["diff"][0] == {"author_id": BID, "field": "arrival",
                              "frozen": 2015, "rebuilt": 2016}
    # idempotency key: the list changed -> the hash may differ, both values are recorded in the summary
    summary = json.loads((out / "_manifest" / "run_summary.json").read_text("utf-8"))
    assert summary["star_change_mode"] == "diff"
    assert summary["star_set"]["stars_set_hash_matches_frozen"] is False
    # star_set/events both written (Zenou golden gate passes + both arrival-year routes say 2016)
    assert (out / "star_set" / "star_set.parquet").exists()
    assert (out / "events" / "data.parquet").exists()


def test_run_u4_full_diff_mode_zenou_change_still_halts(tmp_path):
    """diff mode anchor: if Zenou's row changes, stop immediately. Frozen Zenou arrival=2015 !=
    rebuilt 2016 -> even in diff mode StarSetDrift HALT + a difference report."""
    from run_u4 import StarSetDrift
    root = _universe(tmp_path)
    frozen = _frozen_dir(tmp_path, z_arrival=2015)
    with pytest.raises(StarSetDrift, match="Zenou"):
        _run(tmp_path, root=root, frozen=frozen, star_change_mode="diff")
    out = tmp_path / "ship"
    assert not (out / "star_set").exists()
    summary = json.loads((out / "_manifest" / "run_summary.json").read_text("utf-8"))
    assert summary["status"] == "HALT_STAR_FLAG_DRIFT"


def test_run_u4_full_diff_mode_events_mismatch_reports_without_raise(tmp_path):
    """diff mode, events consistency gate fails (detect=2017 != star set 2016, **no hand-verification evidence**) ->
    does not raise: events are not written at all + difference report written + status SHIPPED_EVENTS_HALTED (the
    first three tables are shipped). The HALT discipline is not loosened - the events table is still never written
    with a disagreement, but the whole run does not blow up (the report goes to hand review)."""
    root = _universe(tmp_path, monash_years=(2017, 2018), zenou_hv=False)
    res = _run(tmp_path, root=root, star_change_mode="diff")
    out = tmp_path / "ship"
    assert res["status"] == "SHIPPED_EVENTS_HALTED"
    assert not (out / "events").exists()
    rep = json.loads((out / "_reports" / "arrival_mismatch_report.json").read_text("utf-8"))
    assert rep["n_mismatch"] == 1
    assert rep["diff"][0]["star_set_arrival"] == 2016
    assert rep["diff"][0]["events_arrival_year"] == 2017
    assert (out / "star_set" / "star_set.parquet").exists()   # the star set is shipped as usual
    summary = json.loads((out / "_manifest" / "run_summary.json").read_text("utf-8"))
    assert summary["status"] == "SHIPPED_EVENTS_HALTED"


def test_run_u4_full_diff_mode_exclusion_flows_to_landed_star_set(tmp_path):
    """Adjudication exclusion end to end (Q3): the adjudication file excludes B -> the rebuilt star set has no B (membership diff
    in the report), the written star_set contains only Zenou; summary records excluded_candidates; isc consumes the
    **rebuilt** rows (Zenou's work WZ is still star-coauthored; B's WB is not)."""
    root = _universe(tmp_path, exclude={BID: "baseline candidate excluded under Q3 (test)"})
    res = _run(tmp_path, root=root, star_change_mode="diff")
    out = tmp_path / "ship"
    assert res["status"] == "SHIPPED"
    ss = pq.read_table(str(out / "star_set" / "star_set.parquet")).to_pylist()
    assert [r["author_id"] for r in ss] == [ZID]              # B does not enter the star call
    rep = json.loads((out / "_reports" / "star_set_diff.json").read_text("utf-8"))
    assert {"author_id": BID, "field": "membership",
            "frozen": "present", "rebuilt": "missing"} in rep["diff"]
    summary = json.loads((out / "_manifest" / "run_summary.json").read_text("utf-8"))
    assert summary["star_set"]["excluded_candidates"] == [BID]
    # isc consumes the rebuilt rows: WZ is authored by Zenou (a star) -> True; WB has only B (not a star) -> False
    pc_rows = []
    for p in sorted((out / "paper_contrib").rglob("part-*.parquet")):
        pc_rows += pq.read_table(str(p)).to_pylist()
    by_work = {r["work_id"]: r for r in pc_rows}
    assert by_work["WZ"]["is_star_coauthored"] is True
    assert by_work["WB"]["is_star_coauthored"] is False


# ====== signal discard + events hand-verification pass + disambiguation register ======

def test_run_u4_full_explained_mismatch_ships_events(tmp_path):
    """Supplementary events rule end to end (green side): detect=2017 != frozen 2016, but Zenou's roster row is
    hand-verified (hv=True, year_start == frozen year) -> the disagreement is downgraded to a diagnostic record, the
    event row is written with the authoritative year 2016, the whole run is SHIPPED; the report marks explained +
    summary records n_explained_mismatch."""
    root = _universe(tmp_path, monash_years=(2017, 2018))     # zenou_hv defaults to True
    res = _run(tmp_path, root=root)
    out = tmp_path / "ship"
    assert res["status"] == "SHIPPED"
    ev = pq.read_table(str(out / "events" / "data.parquet")).to_pylist()
    assert len(ev) == 1 and ev[0]["star_person_id"] == ZID
    assert ev[0]["arrival_year"] == 2016 and ev[0]["t_minus_1"] == 2015   # authoritative frozen year
    rep = json.loads((out / "_reports" / "arrival_mismatch_report.json").read_text("utf-8"))
    assert rep["n_explained"] == 1 and rep["n_halt"] == 0
    assert rep["diff"][0]["explained"] == "human_verified evidence prevails"
    assert rep["diff"][0]["hv_basis"] == "roster:human_verified"
    summary = json.loads((out / "_manifest" / "run_summary.json").read_text("utf-8"))
    assert summary["events"]["n_explained_mismatch"] == 1
    assert summary["events"]["explained_ids"] == [ZID]


def test_run_u4_full_signal_discard_restores_poach_end_to_end(tmp_path):
    """Signal discard end to end (red -> green): add a fake clean Monash row before arrival (2015) to Zenou's timeline
    -> poach organically flips to False != frozen True -> the Zenou anchor stops the run (red);
    the adjudication file registers that row as discarded (institution + year window + evidence + URL) -> poach
    organically returns to True -> SHIPPED (green);
    diagnostic counts are written to _reports/signal_discards_applied.json + summary."""
    from run_u4 import StarSetDrift

    root_red = _universe(tmp_path / "red", fake_au_year=2015)
    with pytest.raises(StarSetDrift, match="Zenou"):
        _run(tmp_path / "red", root=root_red)

    discards = {ZID: [{"dept_key": "monash_econ", "institution_id": MON,
                       "year_from": 2015, "year_to": 2015,
                       "reason": "false pre-arrival Monash row (adjunct or misattributed) (test fixture)",
                       "evidence": "human_verified_web:CV (test fixture)",
                       "url": "https://example.org/cv"}]}
    root_green = _universe(tmp_path / "green", fake_au_year=2015,
                           signal_discards=discards)
    res = _run(tmp_path / "green", root=root_green)
    out = tmp_path / "green" / "ship"
    assert res["status"] == "SHIPPED"
    ss = {r["author_id"]: r
          for r in pq.read_table(str(out / "star_set" / "star_set.parquet")).to_pylist()}
    assert ss[ZID]["is_foreign_poach"] is True
    rep = json.loads((out / "_reports" / "signal_discards_applied.json").read_text("utf-8"))
    assert rep["applied"][ZID]["n_rows_discarded"] == 1
    summary = json.loads((out / "_manifest" / "run_summary.json").read_text("utf-8"))
    assert summary["adjudications"]["n_signal_discards"] == 1
    assert summary["star_set"]["signal_discards_applied"][ZID]["n_rows_discarded"] == 1


def test_run_u4_full_registers_openalex_disambig_review(tmp_path):
    """Register of the OpenAlex disambiguation review list (register only, no fix): every run writes
    _reports/openalex_disambig_review.json, containing the two canonical mis-affiliations confirmed earlier
    (Zenou 2005 raw CEPR->Monash / A5044501609 2017/2019 CESifo->Monash)."""
    _run(tmp_path)
    rep = json.loads((tmp_path / "ship" / "_reports" / "openalex_disambig_review.json")
                     .read_text("utf-8"))
    assert rep["register_only"] is True
    ids = {e["author_id"] for e in rep["entries"]}
    assert {"A5017376589", "A5044501609"} <= ids
    raws = " ".join(e["raw_affil"] for e in rep["entries"])
    assert "CEPR" in raws and "CESifo" in raws


# ---- production-semantics wiring: discipline gate / stock folding / affiliation gate -------------------------------------

def test_run_u4_full_missing_registry_fails_loud(tmp_path):
    """Discipline gate: registry table A absent -> ValueError fail-loud (a discipline gate with no input = the
    dead-config bug recurring, never silent)."""
    from run_u4 import REGISTRY_SUB_DEFAULT
    root = _universe(tmp_path)
    (root / REGISTRY_SUB_DEFAULT).unlink()
    with pytest.raises(ValueError, match="registry"):
        _run(tmp_path, root=root)


def test_run_u4_full_writes_e5_gate_reports(tmp_path):
    """The three production reports are always written: discipline_excluded.json (discipline gate, 0 people in a clean
    universe) + stock_fold_report.csv (one row per candidate) + human_adjudication_queue.csv (affiliation gate +
    sanity gate)."""
    res = _run(tmp_path)
    assert res["status"] == "SHIPPED"
    rep = tmp_path / "ship" / "_reports"
    de = json.loads((rep / "discipline_excluded.json").read_text(encoding="utf-8"))
    assert de["n_excluded"] == 0 and de["excluded"] == []
    sfr = (rep / "stock_fold_report.csv").read_text(encoding="utf-8")
    assert "null_stock_reason" in sfr.splitlines()[0]
    assert ZID in sfr                                     # Zenou has a folded row (singleton, folded)
    adjq = (rep / "human_adjudication_queue.csv").read_text(encoding="utf-8")
    assert adjq.splitlines()[0].startswith("author_id")   # clean universe -> header only
    assert len(adjq.splitlines()) == 1
    # the stage summary is recorded
    assert res["star_set"]["n_discipline_excluded"] == 0
    assert res["star_set"]["n_human_adjudication_rows"] == 0


def test_run_u4_full_discipline_exclusion_flows_to_star_set(tmp_path):
    """Discipline gate end to end: a Finance-modal candidate is excluded by default - not in the written star_set,
    listed in the discipline_excluded report; Zenou/B as before (zero drift on the Zenou anchor)."""
    root = _universe(tmp_path)
    _w(root, ROSTER_FILES[0], [
        _roster_row("monash_econ", ZID, "Yves Zenou", 2016),
        _roster_row("monash_econ", BID, "Bob Benchmark", 2016),
        _roster_row("monash_econ", "A_FINP", "Fin Person", 2016),
    ], schema=_ROSTER_SCHEMA)
    _w(root, f"{EDGES}/works/part_fin.parquet", [
        {"work_id": "WF1", "publication_year": 1990, "subfield_id": "2003",
         "work_type": "article", "cited_by_count": 5, "is_paratext": False, "fwci": None}])
    _w(root, f"{EDGES}/authorship_edges/part_fin.parquet",
       [{"author_id": "A_FINP", "work_id": "WF1"}])
    res = _run(tmp_path, root=root)
    assert res["status"] == "SHIPPED"                     # exclusion does not change the Z/B list -> the consistency gate passes
    assert res["star_set"]["n_discipline_excluded"] == 1
    assert res["star_set"]["discipline_excluded_ids"] == ["A_FINP"]
    landed = pq.read_table(
        str(tmp_path / "ship" / "star_set" / "star_set.parquet")).to_pylist()
    assert "A_FINP" not in {r["author_id"] for r in landed}
    assert {r["author_id"] for r in landed} >= {ZID, BID}


def test_run_u4_full_nominal_flag_lands_in_adjudication_queue(tmp_path):
    """Affiliation gate end to end: all of B's works are affiliated elsewhere (share 0, zero-home-affiliation type) ->
    goes into the hand-review list csv; **the star set does not move** (flags do not hard-drop) -> SHIPPED as
    usual."""
    root = _universe(tmp_path)
    _w(root, f"{EDGES}/works_affil/part.parquet", [
        {"work_id": "WZ", "author_id": ZID, "institution_id": MON,
         "raw_affiliation_strings": ["Monash University"]},
        {"work_id": "WB", "author_id": BID, "institution_id": SE,
         "raw_affiliation_strings": ["Stockholm University"]}])
    res = _run(tmp_path, root=root)
    assert res["status"] == "SHIPPED"                     # flags do not hard-drop: shipping proceeds
    adjq = (tmp_path / "ship" / "_reports" / "human_adjudication_queue.csv"
            ).read_text(encoding="utf-8")
    assert BID in adjq and "nominal_affiliation" in adjq
    assert ZID not in adjq                                # Zenou share 1.0, not flagged
    assert res["star_set"]["n_human_adjudication_rows"] >= 1
