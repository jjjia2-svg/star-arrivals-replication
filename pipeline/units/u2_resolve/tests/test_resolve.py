"""TDD red tests for U2 resolve.py (R1-R5). Fixtures are inline at module level (following the U1 pattern)."""
import pytest
from identity.exit_codes import EXIT_INPUT_NOT_CANONICAL
from m2_resolve.resolve import (
    apply_manual_review_overrides,
    assign_merge_reason,
    build_blocks,
    build_manual_required_queue,
    calibrate_thresholds,
    collect_orcid_conflicts,
    resolve_block_partition,
    run_overmerge_probe,
    run_resolve,
    tag_orcid_merges,
    _assert_author_id_canonical_space,
    _MERGE_REASON_PRIORITY,
)

# --- mini_u1 author fragments (3 columns of the U1 authors table {author_id, display_name, orcid}) ---
# A1/A2/A3 = 3 fragments of the same real person, Yves Zenou (all had_orcid=False, #11-a path)
# A4 = same name_key but conflicting downstream affil/topic = a truly different person (counterexample; still in the same bucket at the blocking stage)
# A5 = the namesake fixture, different name_key (same-name counterexample seed)
# A6 = a star with a real ORCID (had_orcid=True, for R2 orcid_prior; not Yves Zenou)
# Note: GT-ORCID 0000-0001-6516-0812 must never appear in any fixture (#11-a).
MINI_AUTHORS = [
    {"author_id": "A1", "display_name": "Yves Zenou", "orcid": None},
    {"author_id": "A2", "display_name": "Y Zenou", "orcid": None},
    {"author_id": "A3", "display_name": "Yves Zénou", "orcid": None},
    {"author_id": "A4", "display_name": "Yves Zenou", "orcid": None},
    {"author_id": "A5", "display_name": "Namesake Example", "orcid": None},
    {"author_id": "A6", "display_name": "Jane Smith", "orcid": "0000-0002-0000-0001"},
]


def test_blocks_partition_by_name_key():
    """build_blocks coarsely buckets by name_key (first initial + surname, accents folded): same-name fragments in the same bucket, different names in different buckets."""
    blocks = build_blocks(MINI_AUTHORS)
    key_a1 = next(k for k, recs in blocks.items() if any(r["author_id"] == "A1" for r in recs))
    zenou_block = {r["author_id"] for r in blocks[key_a1]}
    # A1/A2/A3/A4 share a name_key (Y + zenou, "Zénou" accent-folded): same bucket
    assert zenou_block == {"A1", "A2", "A3", "A4"}, f"Yves Zenou's name bucket should be A1-A4, got {zenou_block}"
    # A5 (the namesake fixture) has a different name_key -> a different bucket
    assert "A5" not in zenou_block


def test_block_partition_order_independent():
    """resolve_block_partition: the person_id partition is order-independent + person_id carries the 'P_' prefix (reproducibility)."""
    recs = [a for a in MINI_AUTHORS if a["author_id"] in {"A1", "A2", "A3", "A4"}]
    forward = resolve_block_partition(recs)
    backward = resolve_block_partition(list(reversed(recs)))
    assert forward == backward, "person_id partition should be order-independent (cluster_block union-find + min root)"
    assert all(pid.startswith("P_") for pid in forward.values()), "person_id should carry the P_ prefix"
    # root = smallest author_id in the cluster (cluster_block convention), with the prefix added; always falls in the input id set
    assert all(pid[2:] in {"A1", "A2", "A3", "A4"} for pid in forward.values())


def test_canonical_input_passes_assertion():
    """All author_ids canonical (none in the redirect source set) -> the entry assertion lets them through, no exit."""
    recs = [a for a in MINI_AUTHORS if a["author_id"] in {"A1", "A2"}]
    # cmap has a redirect, but it points to an unrelated id (not in records) -> A1/A2 are still canonical -> pass
    cmap_rows = [{"raw_id": "Z_OLD", "canonical_id": "Z_NEW"}]
    _assert_author_id_canonical_space(recs, cmap_rows)  # should not exit, returns normally


def test_input_not_canonical_halts():
    """An author_id is still a redirect source -> exit(EXIT_INPUT_NOT_CANONICAL), never silently accepted."""
    recs = [{"author_id": "A_redirect", "display_name": "Yves Zenou", "orcid": None}]
    cmap_rows = [{"raw_id": "A_redirect", "canonical_id": "A1"}]  # A_redirect -> A1 (not normalized)
    with pytest.raises(SystemExit) as exc:
        _assert_author_id_canonical_space(recs, cmap_rows)
    # assert the constant name, not the integer 24 (following the U0 exit-code convention)
    assert exc.value.code == EXIT_INPUT_NOT_CANONICAL


def test_run_resolve_emits_person_map_schema(tmp_path):
    """run_resolve reads the mini U1 tables -> writes person_map.parquet: 7-column schema / merge_reason all block_cluster / had_orcid correct."""
    import pyarrow.parquet as pq
    from common.schema import AUTHORS, CANONICAL_ID_MAP, PERSON_MAP
    from m1_ingest._writer_util import write_rows_parquet

    edges = tmp_path / "derived" / "u1_edges"
    # Build the mini tables with the real U1 writer -> the fixture schema cannot drift (extra/missing keys raise)
    write_rows_parquet(
        MINI_AUTHORS, edges / "authors" / "data.parquet",
        schema=AUTHORS, pk_cols=["author_id"], label="authors",
    )
    cmap = [{"raw_id": "Z_OLD", "canonical_id": "Z_NEW", "id_type": "author", "is_deleted": False}]
    write_rows_parquet(
        cmap, edges / "canonical_id_map" / "data.parquet",
        schema=CANONICAL_ID_MAP, pk_cols=["raw_id"], label="canonical_id_map",
    )

    out_dir = tmp_path / "derived" / "u2_resolve"
    run_resolve(tmp_path, out_dir)

    pm = out_dir / "person_map" / "data.parquet"
    assert pm.exists(), "person_map.parquet should be written"
    t = pq.read_table(pm)
    assert t.column_names == list(PERSON_MAP.keys()), "person_map column order should == the 7 columns of the PERSON_MAP schema"
    rows = t.to_pylist()
    assert {r["author_id"] for r in rows} == {a["author_id"] for a in MINI_AUTHORS}, "one row per author"
    assert all(r["merge_reason"] == "block_cluster" for r in rows), "In stage R1 every merge_reason is block_cluster"
    had = {r["author_id"]: r["had_orcid"] for r in rows}
    assert had["A6"], "A6 has an ORCID → had_orcid True"
    assert not had["A1"], "A1 has no ORCID → had_orcid False"


# ===================== R2: three ORCID states + red line #11-a =====================

def test_no_hardcoded_ground_truth_orcid_in_production():
    """#11-a: the ground-truth ORCID is never written into any production module (src/, not tests/); grep finds zero hits."""
    import pathlib

    gt_orcid = "0000-0001-6516-0812"
    src = pathlib.Path(__file__).resolve().parents[1] / "src"
    hits = [str(p) for p in src.rglob("*.py") if gt_orcid in p.read_text(encoding="utf-8")]
    assert hits == [], f"GT-ORCID appears in a production module: {hits}"


def test_ground_truth_orcid_never_in_pipeline_input():
    """#11-a: in the fixtures the Yves Zenou fragments (A1/A2/A3) all have orcid None (never equal to the GT-ORCID) and do not enter the pipeline input."""
    zenou = [a for a in MINI_AUTHORS if a["author_id"] in {"A1", "A2", "A3"}]
    assert all(a["orcid"] is None for a in zenou)


def test_zenou_had_orcid_false_no_orcid_prior():
    """#11-a: the Yves Zenou cluster is all had_orcid=False -> tag_orcid_merges does not mark orcid_prior."""
    recs = [a for a in MINI_AUTHORS if a["author_id"] in {"A1", "A2", "A3"}]
    person_of = resolve_block_partition(recs)
    tags = tag_orcid_merges(person_of, recs)
    assert tags == {}, f"Yves Zenou has no orcid → should have no orcid_prior, got {tags}"


def test_orcid_prior_tagged_for_real_orcid_star():
    """A non-Yves-Zenou star with a real ORCID: two fragments with the same orcid -> cluster_block hard-merges them -> marked orcid_prior."""
    recs = [
        {"author_id": "S1", "display_name": "Jane Smith", "orcid": "0000-0002-1825-0097"},
        {"author_id": "S2", "display_name": "J Smith", "orcid": "0000-0002-1825-0097"},
    ]
    person_of = resolve_block_partition(recs)
    assert person_of["S1"] == person_of["S2"], "The same orcid should be hard-merged by cluster_block"
    tags = tag_orcid_merges(person_of, recs)
    assert tags == {"S1": "orcid_prior", "S2": "orcid_prior"}


def test_orcid_conflict_detected():
    """collect_orcid_conflicts: one orcid attached to incompatible names = dirty ORCID; a unique orcid does not count."""
    recs = [
        {"author_id": "D1", "display_name": "Bob Lee", "orcid": "0000-0003-1111-2222"},
        {"author_id": "D2", "display_name": "Bob Smith", "orcid": "0000-0003-1111-2222"},
        {"author_id": "C1", "display_name": "Ann Park", "orcid": "0000-0003-3333-4444"},
    ]
    dirty = collect_orcid_conflicts(recs)
    assert "0000-0003-1111-2222" in dirty       # same orcid, incompatible names (two different surnames)
    assert "0000-0003-3333-4444" not in dirty   # unique orcid, clean


def test_run_resolve_r2_orcid_handling(tmp_path):
    """run_resolve wires in R2: orcid-hard-merged clusters get merge_reason=orcid_prior + dirty orcids go into review_queue.csv."""
    import csv as _csv
    import pyarrow.parquet as pq
    from common.schema import AUTHORS, CANONICAL_ID_MAP
    from m1_ingest._writer_util import write_rows_parquet

    authors = [
        {"author_id": "S1", "display_name": "Jane Smith", "orcid": "0000-0002-1825-0097"},
        {"author_id": "S2", "display_name": "J Smith", "orcid": "0000-0002-1825-0097"},
        {"author_id": "D1", "display_name": "Bob Lee", "orcid": "0000-0003-1111-2222"},
        {"author_id": "D2", "display_name": "Bob Smith", "orcid": "0000-0003-1111-2222"},
        {"author_id": "A1", "display_name": "Yves Zenou", "orcid": None},
    ]
    edges = tmp_path / "derived" / "u1_edges"
    write_rows_parquet(authors, edges / "authors" / "data.parquet",
                       schema=AUTHORS, pk_cols=["author_id"], label="authors")
    write_rows_parquet([], edges / "canonical_id_map" / "data.parquet",
                       schema=CANONICAL_ID_MAP, pk_cols=["raw_id"], label="canonical_id_map")

    out_dir = tmp_path / "derived" / "u2_resolve"
    run_resolve(tmp_path, out_dir)

    pm = pq.read_table(out_dir / "person_map" / "data.parquet").to_pylist()
    reason = {r["author_id"]: r["merge_reason"] for r in pm}
    assert reason["S1"] == "orcid_prior" and reason["S2"] == "orcid_prior"
    assert reason["A1"] == "block_cluster"  # Yves Zenou has no orcid

    rq_path = out_dir / "review_queue.csv"
    assert rq_path.exists(), "review_queue.csv should be written (even when empty)"
    with open(rq_path, newline="", encoding="utf-8") as f:
        flagged = {row["author_id"] for row in _csv.DictReader(f)}
    assert {"D1", "D2"} <= flagged, "An author with a dirty orcid should enter review_queue"
    assert "S1" not in flagged and "A1" not in flagged, "Clean / no-orcid authors do not enter review_queue"


# ===================== R3: cluster purity + over-merge probe =====================

def test_clean_cluster_no_overmerge():
    """Homogeneous cluster (compatible names + a single subfield + clean orcid): overmerge_suspect False, nothing ejected."""
    records = [
        {"author_id": "A1", "display_name": "Yves Zenou", "orcid": None},
        {"author_id": "A2", "display_name": "Y Zenou", "orcid": None},
    ]
    works = [
        {"work_id": "W1", "subfield_id": "S_econ", "institution_id": "I_monash"},
        {"work_id": "W2", "subfield_id": "S_econ", "institution_id": "I_monash"},
    ]
    probe = run_overmerge_probe(records, works)
    assert probe["overmerge_suspect"] is False
    assert probe["ejected_work_ids"] == []


def test_namesake_work_ejected_as_topic_outlier():
    """A cluster with a strict majority of econ plus one paper from a different subfield (a same-name other person got in) -> that work goes into ejected_work_ids + overmerge_suspect."""
    records = [{"author_id": "A1", "display_name": "Yves Zenou", "orcid": None}]
    works = [
        {"work_id": "W1", "subfield_id": "S_econ", "institution_id": "I_monash"},
        {"work_id": "W2", "subfield_id": "S_econ", "institution_id": "I_monash"},
        {"work_id": "W3", "subfield_id": "S_econ", "institution_id": "I_monash"},
        {"work_id": "W_namesake", "subfield_id": "S_medicine", "institution_id": "I_hospital"},
    ]
    probe = run_overmerge_probe(records, works)
    assert "W_namesake" in probe["ejected_work_ids"]
    assert probe["topic_outlier_hit"] is True
    assert probe["overmerge_suspect"] is True


def test_zenou_five_affiliations_not_split_as_overmerge():
    """Yves Zenou spans 5 institutions but has the same subfield + compatible names + clean orcid: multi_inst_hit True but overmerge_suspect False (institution = weak signal)."""
    records = [
        {"author_id": "A1", "display_name": "Yves Zenou", "orcid": None},
        {"author_id": "A2", "display_name": "Y Zenou", "orcid": None},
    ]
    works = [
        {"work_id": "W1", "subfield_id": "S_econ", "institution_id": "I_stockholm"},
        {"work_id": "W2", "subfield_id": "S_econ", "institution_id": "I_iza"},
        {"work_id": "W3", "subfield_id": "S_econ", "institution_id": "I_cepr"},
        {"work_id": "W4", "subfield_id": "S_econ", "institution_id": "I_monash"},
        {"work_id": "W5", "subfield_id": "S_econ", "institution_id": "I_ifn"},
    ]
    probe = run_overmerge_probe(records, works)
    assert probe["multi_inst_hit"] is True, "5 institutions should be recorded as multi_inst_hit"
    assert probe["overmerge_suspect"] is False, "Many institutions ≠ over-merge (rule: institutions are only a weak signal)"
    assert probe["ejected_work_ids"] == []


def test_names_incompatible_in_cluster_flags_overmerge():
    """Two incompatible names in a cluster (different surnames) -> names_incompat_hit + overmerge_suspect."""
    records = [
        {"author_id": "X1", "display_name": "Bob Lee", "orcid": None},
        {"author_id": "X2", "display_name": "Bob Smith", "orcid": None},
    ]
    works = [{"work_id": "W1", "subfield_id": "S_econ", "institution_id": "I_a"}]
    probe = run_overmerge_probe(records, works)
    assert probe["names_incompat_hit"] is True
    assert probe["overmerge_suspect"] is True


# ===================== R4: threshold calibration (RL1/RL2 red-line placeholders) =====================

def test_thresholds_grid_none_never_runs_calibration():
    """Production mode (grid=None): once score_threshold is set (=0.8), require lets it through,
    but calibrate still refuses production clustering (NotImplementedError -> production goes through run_resolve);
    the sentinels for the other unset thresholds (homogeneity/completeness) are guarded by the parameterized U0 test_redlines."""
    authors = [{"author_id": "Z1", "display_name": "Y Zenou", "orcid": None}]
    with pytest.raises(NotImplementedError):
        calibrate_thresholds(authors, grid=None)


def test_calibration_sweep_finds_feasible_band():
    """Calibration mode sweeps thresholds: low thresholds merge, high thresholds split (cluster count is monotonically non-decreasing) + a feasible threshold exists that merges the 3 fragments into 1 person."""
    authors = [
        {"author_id": "Z1", "display_name": "Yves Zenou", "orcid": None},
        {"author_id": "Z2", "display_name": "Yves Zenou", "orcid": None},
        {"author_id": "Z3", "display_name": "Y Zenou", "orcid": None},
    ]
    rep = calibrate_thresholds(authors, grid=[0.5, 0.95], expected_clusters=1)
    n_lo = rep["grid_results"][0]["n_clusters"]
    n_hi = rep["grid_results"][-1]["n_clusters"]
    assert n_lo <= n_hi, "A higher threshold makes merging harder → cluster count is monotonically non-decreasing"
    assert rep["feasible_band"], "There should be a feasible threshold that merges 3 fragments into 1 person"


def test_calibration_report_external_must_sign():
    """Calibration output has source=external + must_author_sign=true + contains signal_availability (never fed back into redlines)."""
    authors = [{"author_id": "Z1", "display_name": "Yves Zenou", "orcid": None}]
    rep = calibrate_thresholds(authors, grid=[0.6])
    assert rep["source"] == "external"
    assert rep["must_author_sign"] is True
    assert "signal_availability" in rep


def test_calibration_monkeypatch_only_in_tests():
    """The threshold-injection monkeypatch belongs only in tests/; the production modules (src/) have zero grep hits."""
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[1] / "src"
    hits = [str(p) for p in src.rglob("*.py") if "monkeypatch" in p.read_text(encoding="utf-8")]
    assert hits == [], f"monkeypatch appears in a production module: {hits}"


# ===================== R5: traceable merge_reason + stars 100% human-reviewed (B1) =====================

def test_merge_reason_priority_order():
    """Priority orcid_prior > golden_manual > raw_affil_text > block_cluster."""
    assert assign_merge_reason({"orcid_prior", "golden_manual", "raw_affil_text"}) == "orcid_prior"
    assert assign_merge_reason({"golden_manual", "raw_affil_text"}) == "golden_manual"
    assert assign_merge_reason({"raw_affil_text"}) == "raw_affil_text"
    assert assign_merge_reason(set()) == "block_cluster"


def test_merge_reason_category_is_four_values():
    """The full set of merge_reason = the 4 values pinned by the PERSON_MAP schema (no other value ever appears)."""
    assert set(_MERGE_REASON_PRIORITY) == {"orcid_prior", "golden_manual", "raw_affil_text", "block_cluster"}


def test_manual_override_sets_golden_manual(tmp_path):
    """apply_manual_review_overrides reads a CSV (source=human) -> overrides person_id + sets merge_reason=golden_manual."""
    rows = [
        {"author_id": "A1", "person_id": "P_A1", "merge_reason": "block_cluster"},
        {"author_id": "A2", "person_id": "P_A2", "merge_reason": "block_cluster"},
    ]
    csv_path = tmp_path / "golden_manual_overrides.csv"
    csv_path.write_text("author_id,person_id,reason,source\nA2,P_A1,merge_fix,human\n", encoding="utf-8")
    out, overridden = apply_manual_review_overrides(rows, csv_path)
    by_id = {r["author_id"]: r for r in out}
    assert by_id["A2"]["person_id"] == "P_A1"
    assert by_id["A2"]["merge_reason"] == "golden_manual"
    assert overridden == {"A2"}
    assert by_id["A1"]["merge_reason"] == "block_cluster"  # not overridden: unchanged


def test_star_no_override_enters_manual_required_queue():
    """B1: a candidate star without an override -> goes into the 100% human-review queue (orchestration does not let it through)."""
    rows = [{"author_id": "STAR", "person_id": "P_STAR", "merge_reason": "block_cluster"}]
    edges = [{"work_id": "W1", "author_id": "STAR"}]
    q = build_manual_required_queue(rows, {"STAR"}, edges, overridden_ids=set())
    assert any(r["author_id"] == "STAR" for r in q)


def test_direct_collaborator_of_star_queued():
    """A star's direct coauthors (one hop via the same work) are also 100% queued; unrelated people are not."""
    rows = [
        {"author_id": "STAR", "person_id": "P_STAR", "merge_reason": "block_cluster"},
        {"author_id": "COLLAB", "person_id": "P_COLLAB", "merge_reason": "block_cluster"},
        {"author_id": "OTHER", "person_id": "P_OTHER", "merge_reason": "block_cluster"},
    ]
    edges = [
        {"work_id": "W1", "author_id": "STAR"},
        {"work_id": "W1", "author_id": "COLLAB"},   # same work as the star = direct coauthor
        {"work_id": "W2", "author_id": "OTHER"},     # unrelated work
    ]
    q = build_manual_required_queue(rows, {"STAR"}, edges, overridden_ids=set())
    ids = {r["author_id"] for r in q}
    assert {"STAR", "COLLAB"} <= ids
    assert "OTHER" not in ids


def test_star_with_override_not_in_queue():
    """A star already human-reviewed via an override no longer enters the queue (the human review is final)."""
    rows = [{"author_id": "STAR", "person_id": "P_STAR", "merge_reason": "golden_manual"}]
    edges = [{"work_id": "W1", "author_id": "STAR"}]
    q = build_manual_required_queue(rows, {"STAR"}, edges, overridden_ids={"STAR"})
    assert q == []


def test_run_resolve_writes_manual_required_queue_for_star(tmp_path):
    """run_resolve wires in candidate_star_author_ids -> a star without an override goes into manual_required_queue.csv."""
    import csv as _csv
    from common.schema import AUTHORS, CANONICAL_ID_MAP
    from m1_ingest._writer_util import write_rows_parquet

    authors = [
        {"author_id": "STAR", "display_name": "Big Name", "orcid": None},
        {"author_id": "OTHER", "display_name": "Small Fry", "orcid": None},
    ]
    edges_rows = [
        {"work_id": "W1", "author_id": "STAR", "publication_year": 2010},
        {"work_id": "W2", "author_id": "OTHER", "publication_year": 2011},
    ]
    edges_dir = tmp_path / "derived" / "u1_edges"
    write_rows_parquet(authors, edges_dir / "authors" / "data.parquet",
                       schema=AUTHORS, pk_cols=["author_id"], label="authors")
    write_rows_parquet([], edges_dir / "canonical_id_map" / "data.parquet",
                       schema=CANONICAL_ID_MAP, pk_cols=["raw_id"], label="canonical_id_map")
    from common.schema import AUTHORSHIP_EDGES
    write_rows_parquet(edges_rows, edges_dir / "authorship_edges" / "data.parquet",
                       schema=AUTHORSHIP_EDGES, pk_cols=["work_id", "author_id"], label="authorship_edges")

    out_dir = tmp_path / "derived" / "u2_resolve"
    run_resolve(tmp_path, out_dir, candidate_star_author_ids={"STAR"})

    mq = out_dir / "manual_required_queue.csv"
    assert mq.exists()
    with open(mq, newline="", encoding="utf-8") as f:
        ids = {row["author_id"] for row in _csv.DictReader(f)}
    assert "STAR" in ids and "OTHER" not in ids


# ===================== B1 fix: production clustering really uses works_affil (institution defense) =====================

def test_same_name_different_affil_not_merged(tmp_path):
    """B1: same name, compatible, but strongly conflicting institutions -> run_resolve does not merge (works_affil -> raw_affil -> the affil_conflict defense really takes effect)."""
    import pyarrow.parquet as pq
    from common.schema import AUTHORS, CANONICAL_ID_MAP, WORKS_AFFIL
    from m1_ingest._writer_util import write_rows_parquet

    authors = [
        {"author_id": "J1", "display_name": "John Smith", "orcid": None},
        {"author_id": "J2", "display_name": "J Smith", "orcid": None},
    ]
    works_affil = [
        {"work_id": "W1", "author_id": "J1", "institution_id": "I_h",
         "raw_affiliation_strings": ["Harvard University, Department of Economics"]},
        {"work_id": "W2", "author_id": "J2", "institution_id": "I_m",
         "raw_affiliation_strings": ["MIT, Department of Physics"]},
    ]
    edges = tmp_path / "derived" / "u1_edges"
    write_rows_parquet(authors, edges / "authors" / "data.parquet",
                       schema=AUTHORS, pk_cols=["author_id"], label="authors")
    write_rows_parquet([], edges / "canonical_id_map" / "data.parquet",
                       schema=CANONICAL_ID_MAP, pk_cols=["raw_id"], label="canonical_id_map")
    write_rows_parquet(works_affil, edges / "works_affil" / "data.parquet",
                       schema=WORKS_AFFIL, pk_cols=["work_id", "author_id"], label="works_affil")

    out_dir = tmp_path / "derived" / "u2_resolve"
    run_resolve(tmp_path, out_dir)
    pm = {r["author_id"]: r["person_id"]
          for r in pq.read_table(out_dir / "person_map" / "data.parquet").to_pylist()}
    assert pm["J1"] != pm["J2"], "Same name at different institutions (Harvard Econ vs MIT Physics) should not merge into one person"


def test_same_name_same_affil_still_merged(tmp_path):
    """Control: same full name + same institution -> still merged (when affil does not conflict, normal merging is not blocked).

    With the 0.8 threshold: soft linking goes through accept_pair (score>=0.8) - same full name + compatible institution = 1.0 merges as usual;
    given-name initial variants (score~0.65) are no longer merged automatically, but picked up by ORCID hard seeds / golden_manual / the human-review queue
    (a known residual of the calibration, a trade-off)."""
    import pyarrow.parquet as pq
    from common.schema import AUTHORS, CANONICAL_ID_MAP, WORKS_AFFIL
    from m1_ingest._writer_util import write_rows_parquet

    authors = [
        {"author_id": "K1", "display_name": "Kate Brown", "orcid": None},
        {"author_id": "K2", "display_name": "Kate Brown", "orcid": None},  # With the 0.8 threshold: full-name control (initial variants are no longer merged automatically; left to ORCID / human review)
    ]
    works_affil = [
        {"work_id": "W1", "author_id": "K1", "institution_id": "I_m",
         "raw_affiliation_strings": ["Monash University, Department of Economics"]},
        {"work_id": "W2", "author_id": "K2", "institution_id": "I_m",
         "raw_affiliation_strings": ["Monash University, Department of Economics"]},
    ]
    edges = tmp_path / "derived" / "u1_edges"
    write_rows_parquet(authors, edges / "authors" / "data.parquet",
                       schema=AUTHORS, pk_cols=["author_id"], label="authors")
    write_rows_parquet([], edges / "canonical_id_map" / "data.parquet",
                       schema=CANONICAL_ID_MAP, pk_cols=["raw_id"], label="canonical_id_map")
    write_rows_parquet(works_affil, edges / "works_affil" / "data.parquet",
                       schema=WORKS_AFFIL, pk_cols=["work_id", "author_id"], label="works_affil")

    out_dir = tmp_path / "derived" / "u2_resolve"
    run_resolve(tmp_path, out_dir)
    pm = {r["author_id"]: r["person_id"]
          for r in pq.read_table(out_dir / "person_map" / "data.parquet").to_pylist()}
    assert pm["K1"] == pm["K2"], "Same name at the same institution should merge into one person"


def test_raw_affil_text_reason_for_affil_merged_fragments(tmp_path):
    """raw_affil_text reason is now reachable in production: same-name same-institution fragments with no shared coauthor merge back -> merge_reason=raw_affil_text."""
    import pyarrow.parquet as pq
    from common.schema import AUTHORS, CANONICAL_ID_MAP, WORKS_AFFIL
    from m1_ingest._writer_util import write_rows_parquet

    authors = [
        {"author_id": "K1", "display_name": "Kate Brown", "orcid": None},
        {"author_id": "K2", "display_name": "Kate Brown", "orcid": None},  # With the 0.8 threshold: full-name control (initial variants are no longer merged automatically; left to ORCID / human review)
    ]
    works_affil = [
        {"work_id": "W1", "author_id": "K1", "institution_id": "I_m",
         "raw_affiliation_strings": ["Monash University, Department of Economics"]},
        {"work_id": "W2", "author_id": "K2", "institution_id": "I_m",
         "raw_affiliation_strings": ["Monash University, Department of Economics"]},
    ]
    edges = tmp_path / "derived" / "u1_edges"
    write_rows_parquet(authors, edges / "authors" / "data.parquet",
                       schema=AUTHORS, pk_cols=["author_id"], label="authors")
    write_rows_parquet([], edges / "canonical_id_map" / "data.parquet",
                       schema=CANONICAL_ID_MAP, pk_cols=["raw_id"], label="canonical_id_map")
    write_rows_parquet(works_affil, edges / "works_affil" / "data.parquet",
                       schema=WORKS_AFFIL, pk_cols=["work_id", "author_id"], label="works_affil")

    out_dir = tmp_path / "derived" / "u2_resolve"
    run_resolve(tmp_path, out_dir)
    pm = {r["author_id"]: r["merge_reason"]
          for r in pq.read_table(out_dir / "person_map" / "data.parquet").to_pylist()}
    assert pm["K1"] == "raw_affil_text" and pm["K2"] == "raw_affil_text"


def test_person_map_byte_idempotent(tmp_path):
    """Run twice on the same input -> person_map.parquet is byte-identical (deterministic writer + canonical-sort)."""
    import hashlib
    import pyarrow.parquet as pq  # noqa: F401
    from common.schema import AUTHORS, CANONICAL_ID_MAP
    from m1_ingest._writer_util import write_rows_parquet

    def _run(root):
        edges = root / "derived" / "u1_edges"
        write_rows_parquet(MINI_AUTHORS, edges / "authors" / "data.parquet",
                           schema=AUTHORS, pk_cols=["author_id"], label="authors")
        write_rows_parquet([], edges / "canonical_id_map" / "data.parquet",
                           schema=CANONICAL_ID_MAP, pk_cols=["raw_id"], label="canonical_id_map")
        out_dir = root / "derived" / "u2_resolve"
        run_resolve(root, out_dir)
        return (out_dir / "person_map" / "data.parquet").read_bytes()

    h1 = hashlib.sha256(_run(tmp_path / "a")).hexdigest()
    h2 = hashlib.sha256(_run(tmp_path / "b")).hexdigest()
    assert h1 == h2, "Two runs of person_map should be byte-identical"


# ===================== Fix A: corroborated different-ORCID over-merge flag (probe raw signals) =====================
# Rule:
#   distinct_orcid_hit (>=2 different valid ORCIDs in a cluster) + orcid_field_conflict_hit (the subfield sets grouped
#   by ORCID are pairwise disjoint) = two RAW signals, returned by run_overmerge_probe; the corroborated combination
#   (distinct AND (field OR affil)) is assembled in gate.compute_cluster_purity. The probe's own
#   overmerge_suspect never changes because of ORCID signals (still = names OR dirty_orcid OR topic outlier).

def test_probe_distinct_orcid_hit_same_field_raw_signals():
    """2 different valid ORCIDs + same subfield: distinct_orcid_hit=True, orcid_field_conflict_hit=False;
    probe.overmerge_suspect stays False (ORCID corroboration is not folded into the probe; the gate assembles it)."""
    records = [
        {"author_id": "Z1", "display_name": "Yves Zenou", "orcid": "0000-0002-1111-1111"},
        {"author_id": "Z2", "display_name": "Yves Zenou", "orcid": "0000-0002-2222-2222"},
    ]
    works = [
        {"author_id": "Z1", "work_id": "W1", "subfield_id": "S_econ", "institution_id": "I_m"},
        {"author_id": "Z2", "work_id": "W2", "subfield_id": "S_econ", "institution_id": "I_m"},
    ]
    probe = run_overmerge_probe(records, works)
    assert probe["distinct_orcid_hit"] is True
    assert probe["orcid_field_conflict_hit"] is False
    assert probe["overmerge_suspect"] is False, "An ORCID signal must never on its own fold into probe.overmerge_suspect"


def test_probe_orcid_field_conflict_disjoint_subfields():
    """2 different ORCIDs + disjoint subfield sets (econ vs pulmonology) -> orcid_field_conflict_hit=True."""
    records = [
        {"author_id": "K1", "display_name": "John Namesake", "orcid": "0000-0003-1111-1111"},
        {"author_id": "K2", "display_name": "John Namesake", "orcid": "0000-0003-2222-2222"},
    ]
    works = [
        {"author_id": "K1", "work_id": "W1", "subfield_id": "S_econ", "institution_id": "I_ucd"},
        {"author_id": "K2", "work_id": "W2", "subfield_id": "S_pulmonology", "institution_id": "I_ucd"},
    ]
    probe = run_overmerge_probe(records, works)
    assert probe["distinct_orcid_hit"] is True
    assert probe["orcid_field_conflict_hit"] is True


def test_probe_single_orcid_no_distinct_hit():
    """One ORCID attached to two profiles (one person, several profiles) -> distinct_orcid_hit=False (only different codes count)."""
    records = [
        {"author_id": "S1", "display_name": "Sam Smith", "orcid": "0000-0005-1111-1111"},
        {"author_id": "S2", "display_name": "Sam Smith", "orcid": "0000-0005-1111-1111"},
    ]
    works = [
        {"author_id": "S1", "work_id": "W1", "subfield_id": "S_econ", "institution_id": "I_m"},
        {"author_id": "S2", "work_id": "W2", "subfield_id": "S_med", "institution_id": "I_m"},
    ]
    probe = run_overmerge_probe(records, works)
    assert probe["distinct_orcid_hit"] is False
    assert probe["orcid_field_conflict_hit"] is False
