"""m7a nominal_gate — nominal-affiliation gate + manual-review list assembly, TDD.

In plain words: productionising the nominal-affiliation flag (threshold 0.05, flag only, no hard removal) — a candidate whose own works are attached to their own school at a share below the
threshold gets nominal_affiliation_flag and goes on the manual-review list; the academic-age≤1 sanity gate goes on the same list. A flag never hard-removes.
"""
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from m7a_star.nominal_gate import build_nominal_affil_flags, human_adjudication_queue

ECON = "2002"
MON = "I56590836"
EDGES = "u1_edges_full_2026-07-05"


def _w(root, subpath, rows, schema=None):
    p = root / subpath
    p.parent.mkdir(parents=True, exist_ok=True)
    tbl = pa.Table.from_pylist(rows, schema=schema) if schema else pa.Table.from_pylist(rows)
    pq.write_table(tbl, str(p))


def _root(tmp_path):
    """Three candidates: A_OK 2/2 attached to Monash (share 1.0); A_ZSHARE 3 works all at other schools (share 0 → zero-attachment type);
    A_GHOST has zero works in the corpus (no_works_in_corpus). Includes lineage folding: I_CHILD ∈ Monash lineage,
    so A_OK's W2 attached to I_CHILD also counts as the school."""
    r = tmp_path
    _w(r, f"{EDGES}/works_affil/part.parquet", [
        {"work_id": "W1", "author_id": "A_OK", "institution_id": MON,
         "raw_affiliation_strings": ["Monash University"]},
        {"work_id": "W2", "author_id": "A_OK", "institution_id": "I_CHILD",
         "raw_affiliation_strings": ["Monash Business School"]},
        {"work_id": "W3", "author_id": "A_ZSHARE", "institution_id": "I_ELSE",
         "raw_affiliation_strings": ["Stanford"]},
        {"work_id": "W4", "author_id": "A_ZSHARE", "institution_id": "I_ELSE",
         "raw_affiliation_strings": ["Stanford"]},
        {"work_id": "W5", "author_id": "A_ZSHARE", "institution_id": None,
         "raw_affiliation_strings": []},
    ])
    _w(r, f"{EDGES}/institutions/part.parquet", [
        {"institution_id": MON, "country_code": "AU", "lineage": [MON]},
        {"institution_id": "I_CHILD", "country_code": "AU", "lineage": [MON, "I_CHILD"]},
        {"institution_id": "I_ELSE", "country_code": "US", "lineage": ["I_ELSE"]},
    ])
    return r


_CANDS = [
    {"author_id": "A_OK", "name": "Ok Person", "dept": "monash_econ"},
    {"author_id": "A_ZSHARE", "name": "Zero-share Type", "dept": "monash_econ"},
    {"author_id": "A_GHOST", "name": "Ghost", "dept": "monash_econ"},
]


def test_nominal_flags_share_and_reasons(tmp_path):
    """Share = DISTINCT work_id basis (same as the E1 audit): A_OK share 1.0 not flagged (lineage folding counted in);
    A_ZSHARE share 0 flagged (zero_school_works); A_GHOST zero works flagged (no_works_in_corpus)."""
    rows = build_nominal_affil_flags(
        _root(tmp_path), _CANDS, edges_sub=EDGES,
        dept_inst={"monash_econ": MON}, threshold=0.05)
    by = {r["author_id"]: r for r in rows}
    assert by["A_OK"]["nominal_affiliation_flag"] is False
    assert by["A_OK"]["school_share"] == 1.0                 # W2 folds into the school via lineage
    assert by["A_ZSHARE"]["nominal_affiliation_flag"] is True
    assert by["A_ZSHARE"]["reason"] == "zero_school_works"
    assert by["A_ZSHARE"]["n_works_total"] == 3
    assert by["A_GHOST"]["nominal_affiliation_flag"] is True
    assert by["A_GHOST"]["reason"] == "no_works_in_corpus"
    # pass-through fields (readable in the manual-review list)
    assert by["A_ZSHARE"]["name"] == "Zero-share Type" and by["A_ZSHARE"]["dept"] == "monash_econ"


def test_nominal_flags_threshold_from_signed_redline(tmp_path):
    """threshold omitted → read the configured star.nominal_affiliation_min_share=0.05, not scattered."""
    rows = build_nominal_affil_flags(
        _root(tmp_path), _CANDS, edges_sub=EDGES, dept_inst={"monash_econ": MON})
    assert all(r["threshold"] == 0.05 for r in rows)


def test_nominal_flags_unknown_dept_fails_loud(tmp_path):
    """Candidate dept not in the dept_inst mapping → ValueError (a misspelt school fails loudly, never silently left unevaluated)."""
    with pytest.raises(ValueError, match="dept"):
        build_nominal_affil_flags(
            _root(tmp_path), [{"author_id": "A_OK", "name": "x", "dept": "nowhere_econ"}],
            edges_sub=EDGES, dept_inst={"monash_econ": MON}, threshold=0.05)


# ============ Manual-review list assembly (nominal-affiliation flag + academic age ≤1 sanity gate; neither removes automatically) ============

def test_human_adjudication_queue_merges_both_gates():
    """List = academic-age≤1 flag (True rows) + nominal-affiliation flag (True rows), with a source column; False/None do not enter."""
    sanity = [
        {"author_id": "A_AGE0", "name": "Wrong-id Type", "dept": "monash_econ",
         "arrival": 2002, "academic_age": 0, "sanity_flag_age": True},
        {"author_id": "A_OK", "name": "Ok", "dept": "monash_econ",
         "arrival": 2016, "academic_age": 20, "sanity_flag_age": False},
        {"author_id": "A_NA", "name": "NoPool", "dept": "monash_econ",
         "arrival": 2016, "academic_age": None, "sanity_flag_age": None},
    ]
    nominal = [
        {"author_id": "A_ZSHARE", "name": "Zero-share Type", "dept": "monash_econ",
         "school_share": 0.0, "reason": "zero_school_works",
         "nominal_affiliation_flag": True, "n_works_total": 3, "n_works_school": 0,
         "threshold": 0.05},
        {"author_id": "A_OK", "name": "Ok", "dept": "monash_econ",
         "school_share": 1.0, "reason": None, "nominal_affiliation_flag": False,
         "n_works_total": 2, "n_works_school": 2, "threshold": 0.05},
    ]
    q = human_adjudication_queue(sanity, nominal)
    assert [(r["author_id"], r["source"]) for r in q] == [
        ("A_AGE0", "sanity_age_le1"), ("A_ZSHARE", "nominal_affiliation")]
    assert all(r["disposition"] == "human_review (旗不硬剔, 剔留=人工签)" for r in q)


def test_human_adjudication_queue_same_person_both_gates_two_rows():
    """Same person with both flags → two rows (sources distinguishable; the manual review goes through them by source)."""
    sanity = [{"author_id": "A_X", "name": "X", "dept": "unsw_econ",
               "arrival": 2020, "academic_age": 1, "sanity_flag_age": True}]
    nominal = [{"author_id": "A_X", "name": "X", "dept": "unsw_econ",
                "school_share": 0.01, "reason": "below_threshold",
                "nominal_affiliation_flag": True, "n_works_total": 100,
                "n_works_school": 1, "threshold": 0.05}]
    q = human_adjudication_queue(sanity, nominal)
    assert len(q) == 2
    assert {r["source"] for r in q} == {"sanity_age_le1", "nominal_affiliation"}
