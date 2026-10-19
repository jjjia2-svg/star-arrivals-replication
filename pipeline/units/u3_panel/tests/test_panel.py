"""U3 panel TDD red tests: all 49 tests, grown task by task.

Naming: test_<behaviour>_<condition>. Fixtures are inline module-level dicts (as in U2; no separate fixtures/ directory).
importorskip is pinned at the top: a missing duckdb/polars/pyarrow skips automatically (not a failure).

Note: fixtures are built to the upstream REAL schemas:
  WORKS_AFFIL 4 cols / AUTHORSHIP_EDGES 3 cols / WORK_FIRST_PUB 3 cols / PERSON_MAP reads 2 cols /
  CANONICAL_ID_MAP 4 keys (author + inst rows) / INSTITUTIONS 7 cols. Otherwise a green run would be fake.
"""
import pytest

# Note: the original spec header listed importorskip("polars"), but the real codebase has no polars dependency
#   (grep over the whole units tree: 0 hits; U1/U2 use only pyarrow + duckdb). polars is removed to match.
pytest.importorskip("duckdb")
pytest.importorskip("pyarrow")

from common.schema import (  # noqa: E402
    PANEL,
    AFFIL_TIMELINE,
    WORKS_AFFIL,
    AUTHORSHIP_EDGES,
    WORK_FIRST_PUB,
    PERSON_MAP,
    CANONICAL_ID_MAP,
    INSTITUTIONS,
    assert_matches_schema,
)
from m1_ingest._writer_util import write_rows_parquet  # noqa: E402
from identity.exit_codes import EXIT_CANONICAL_SPACE_SPLIT  # noqa: E402  (U3-E guard=22)

# Table -> (schema, on-disk pk_cols). pk_cols follow the real U1 on-disk convention.
_TABLE_SPEC = {
    "works_affil": (WORKS_AFFIL, ["work_id", "author_id", "institution_id"]),
    "authorship_edges": (AUTHORSHIP_EDGES, ["work_id", "author_id"]),
    "work_first_pub": (WORK_FIRST_PUB, ["author_id"]),
    "person_map": (PERSON_MAP, ["author_id"]),
    "canonical_id_map": (CANONICAL_ID_MAP, ["raw_id"]),
    "institutions": (INSTITUTIONS, ["institution_id"]),
}


def _write_real(data_root, table, rows):
    """Write rows as real parquet with the real U1 writer (schema drift raises, so the fixture cannot be falsely green).

    data_root = SSD root; path derived/<unit>/<table>/data.parquet (U2 convention).
    """
    unit = "u2_resolve" if table == "person_map" else "u1_edges"
    target = data_root / "derived" / unit / table / "data.parquet"
    schema, pk_cols = _TABLE_SPEC[table]
    write_rows_parquet(rows, target, schema=schema, pk_cols=pk_cols, label=table)
    return target


# ──────────────────────────────────────────────────────────────────────────
# Test 1: test_panel_schema_exact_8_cols
# Contract smoke: shows the conftest 4-path bridge works and PANEL is closed (U3-D STALE).
# This tests the existing U0 PANEL schema and is expected to be green already (not a U3-logic RED).
# Invariant: PANEL has exactly 8 columns, incl. first_pub_year_is_full_history + in_au_econ_dept_modal_hint.
# ──────────────────────────────────────────────────────────────────────────
def _valid_panel_row_keys():
    """Build a row with exactly the 8 PANEL keys (values arbitrary; assert_matches_schema checks only the key set)."""
    return {
        "person_id": "P_A1",
        "year": 2016,
        "primary_affil_id": "I56590836",
        "raw_affil": "Monash University",
        "in_au_econ_dept_modal_hint": True,
        "n_works_year": 3,
        "first_pub_year": 1985,
        "first_pub_year_is_full_history": True,
    }


def test_panel_schema_exact_8_cols():
    # PANEL has exactly 8 columns.
    assert len(PANEL) == 8
    assert "first_pub_year_is_full_history" in PANEL
    assert "in_au_econ_dept_modal_hint" in PANEL

    # A row with exactly the 8 keys -> no raise.
    assert_matches_schema(_valid_panel_row_keys(), PANEL, label="panel")

    # Missing flag -> raise.
    missing = _valid_panel_row_keys()
    del missing["first_pub_year_is_full_history"]
    with pytest.raises(Exception):
        assert_matches_schema(missing, PANEL, label="panel")

    # One extra column -> raise.
    extra = _valid_panel_row_keys()
    extra["bogus_col"] = 1
    with pytest.raises(Exception):
        assert_matches_schema(extra, PANEL, label="panel")


# ──────────────────────────────────────────────────────────────────────────
# Guard-type fixture helpers: real on-disk layout derived/<unit>/<table>/data.parquet
# ──────────────────────────────────────────────────────────────────────────
# Upstream table -> (unit subdir, table subdir). Upstream-read rule: read only data.parquet.
_UPSTREAM_LAYOUT = {
    "works_affil": ("u1_edges", "works_affil"),
    "authorship_edges": ("u1_edges", "authorship_edges"),
    "work_first_pub": ("u1_edges", "work_first_pub"),
    "canonical_id_map": ("u1_edges", "canonical_id_map"),
    "institutions": ("u1_edges", "institutions"),
    "person_map": ("u2_resolve", "person_map"),
}


def _upstream_path(data_root, table):
    # data_root = SSD root (without derived), as in U2; the code builds derived/<unit>/<table>/data.parquet.
    unit, tbl = _UPSTREAM_LAYOUT[table]
    return data_root / "derived" / unit / tbl / "data.parquet"


def _touch_upstream(data_root, *, omit=()):
    """For existence-guard tests: touch every upstream data.parquet (empty file); tables listed in omit are not created.

    Enough for guards that only check Path.exists() (G1); fixtures with content (J1+) write real parquet separately.
    """
    for table in _UPSTREAM_LAYOUT:
        if table in omit:
            continue
        p = _upstream_path(data_root, table)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"")  # Empty placeholder; the existence guard only checks exists()
    return data_root


def _real_empty_works_affil(data_root):
    """A 0-row works_affil with the real schema (the column check must pass; touching empty bytes is not enough)."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    p = _upstream_path(data_root, "works_affil")
    p.parent.mkdir(parents=True, exist_ok=True)
    t = pa.table({"work_id": pa.array([], type=pa.string()),
                  "author_id": pa.array([], type=pa.string()),
                  "institution_id": pa.array([], type=pa.string()),
                  "raw_affiliation_strings": pa.array([], type=pa.list_(pa.string()))})
    pq.write_table(t, str(p))


def test_canonical_id_map_provenance_only_is_legal_empty_table(tmp_path):
    """Shape caught by the first real-data U3 run: for a 0-row table U1 writes only provenance.json and no part, so
    canonical_id_map alone is treated as a legitimate empty table (0 rows = no merge mapping, every id is already canonical);
    reading the table returns []. Other tables with the same shape are not accepted (the rule applies only to cmap)."""
    from m3_panel.panel import _assert_upstream_present, _read_table

    data_root = _touch_upstream(tmp_path / "dr", omit=("canonical_id_map", "works_affil"))
    _real_empty_works_affil(data_root)
    cm_dir = data_root / "derived" / "u1_edges" / "canonical_id_map"
    cm_dir.mkdir(parents=True, exist_ok=True)
    # Real U1 provenance format carries row_count (F1: only ==0 counts as legitimately empty; a lost part is not accepted)
    (cm_dir / "provenance.json").write_text('{"row_count": 0}')

    _assert_upstream_present(data_root, econ_dept_ids={"I1"}, registry_by_id={"I1": {}})
    assert _read_table(data_root, "canonical_id_map",
                       ["raw_id", "canonical_id", "id_type", "is_deleted"]) == []


def test_cmap_legal_empty_content_hash_is_stable_sentinel(tmp_path):
    """The resume fingerprint must not blow up on a legitimately empty cmap: it returns a deterministic sentinel string (equal across two calls);
    other missing tables still raise (strict semantics are not relaxed)."""
    from m3_panel.panel import _upstream_content_hash

    data_root = _touch_upstream(tmp_path / "dr", omit=("canonical_id_map",))
    cm_dir = data_root / "derived" / "u1_edges" / "canonical_id_map"
    cm_dir.mkdir(parents=True, exist_ok=True)
    (cm_dir / "provenance.json").write_text('{"row_count": 0}')

    h1 = _upstream_content_hash(data_root, "canonical_id_map")
    h2 = _upstream_content_hash(data_root, "canonical_id_map")
    assert h1 == h2 and "empty" in h1

    import pytest as _pt
    with _pt.raises(FileNotFoundError):
        # Is institutions a touched empty-bytes file? No: touching makes it present; delete it, then test missing-table strictness
        import shutil
        shutil.rmtree(data_root / "derived" / "u1_edges" / "institutions")
        _upstream_content_hash(data_root, "institutions")


def test_other_table_provenance_only_still_halts(tmp_path):
    from m3_panel.panel import _assert_upstream_present

    data_root = _touch_upstream(tmp_path / "dr", omit=("institutions",))
    ins_dir = data_root / "derived" / "u1_edges" / "institutions"
    ins_dir.mkdir(parents=True, exist_ok=True)
    (ins_dir / "provenance.json").write_text("{}")
    with pytest.raises(SystemExit):
        _assert_upstream_present(data_root, econ_dept_ids={"I1"}, registry_by_id={"I1": {}})


# ──────────────────────────────────────────────────────────────────────────
# Test 2: test_missing_works_affil_exits_2  (Task G1)
# First real RED: build_panel does not exist yet.
# Invariant: a missing table fails loudly (no inline workaround); a missing works_affil exits with code 2 directly.
# ──────────────────────────────────────────────────────────────────────────
def test_missing_works_affil_exits_2(tmp_path):
    from m3_panel.panel import build_panel

    data_root = tmp_path / "derived"
    _touch_upstream(data_root, omit=("works_affil",))  # Everything else present; only works_affil missing
    out_dir = tmp_path / "out"

    with pytest.raises(SystemExit) as ei:
        build_panel(
            data_root,
            out_dir,
            econ_dept_ids={"I56590836"},
            registry_by_id={"I56590836": {"openalex_id": "I56590836", "type": "education"}},
        )
    assert ei.value.code == 2


_GOOD_REG = {"I56590836": {"openalex_id": "I56590836", "type": "education"}}


def _write_bad_works_affil(data_root):
    """Write a works_affil real parquet with a WRONG schema (one extra column) -> the schema guard must catch it."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    p = _upstream_path(data_root, "works_affil")
    p.parent.mkdir(parents=True, exist_ok=True)
    bad = pa.table({"work_id": ["W1"], "author_id": ["A1"], "BOGUS_COL": [1]})
    pq.write_table(bad, p)


def test_missing_institutions_exits_2(tmp_path):
    from m3_panel.panel import build_panel

    data_root = tmp_path / "derived_root"
    _touch_upstream(data_root, omit=("institutions",))  # Only institutions missing (U3-B)
    with pytest.raises(SystemExit) as ei:
        build_panel(data_root, tmp_path / "out",
                    econ_dept_ids={"I56590836"}, registry_by_id=_GOOD_REG)
    assert ei.value.code == 2


def test_works_affil_wrong_schema_exits_2(tmp_path):
    from m3_panel.panel import build_panel

    data_root = tmp_path / "derived_root"
    _touch_upstream(data_root, omit=("works_affil",))  # The other 5 tables are empty placeholders
    _write_bad_works_affil(data_root)  # works_affil written as a real parquet with the wrong schema
    with pytest.raises(SystemExit) as ei:
        build_panel(data_root, tmp_path / "out",
                    econ_dept_ids={"I56590836"}, registry_by_id=_GOOD_REG)
    assert ei.value.code == 2


def test_empty_econ_dept_ids_exits_2(tmp_path):
    from m3_panel.panel import build_panel

    data_root = tmp_path / "derived_root"
    _touch_upstream(data_root)  # All present
    with pytest.raises(SystemExit) as ei:
        build_panel(data_root, tmp_path / "out",
                    econ_dept_ids=set(), registry_by_id=_GOOD_REG)  # Empty econ
    assert ei.value.code == 2


def test_econ_dept_id_not_in_registry_exits_2(tmp_path):
    from m3_panel.panel import build_panel

    data_root = tmp_path / "derived_root"
    _touch_upstream(data_root, omit=("works_affil",))
    _write_real(data_root, "works_affil", [  # Valid works_affil -> passes the schema guard
        {"work_id": "W1", "author_id": "A1", "institution_id": "I1",
         "raw_affiliation_strings": ["x"]},
    ])
    with pytest.raises(SystemExit) as ei:
        build_panel(data_root, tmp_path / "out",
                    econ_dept_ids={"I_NOT_IN_REG"}, registry_by_id=_GOOD_REG)  # econ not in registry
    assert ei.value.code == 2


# ──────────────────────────────────────────────────────────────────────────
# Test 3: test_join_uses_person_id_not_author_id  (Task J1)
# Real RED: _load_person_works does not exist yet.
# Invariant: fold to person_id first, then compute (computing per author_id for one real person with several author_ids hits the Yves Zenou 16-ID problem).
# ──────────────────────────────────────────────────────────────────────────
def test_join_uses_person_id_not_author_id(tmp_path):
    from m3_panel.panel import _load_person_works

    data_root = tmp_path
    _write_real(data_root, "works_affil", [
        {"work_id": "W1", "author_id": "A1", "institution_id": "I1",
         "raw_affiliation_strings": ["Monash University"]},
        {"work_id": "W2", "author_id": "A2", "institution_id": "I1",
         "raw_affiliation_strings": ["Monash University"]},
    ])
    _write_real(data_root, "authorship_edges", [
        {"work_id": "W1", "author_id": "A1", "publication_year": 2010},
        {"work_id": "W2", "author_id": "A2", "publication_year": 2011},
    ])
    person_map = {"A1": "P1", "A2": "P1"}  # Same real person, 2 author_ids -> 1 person_id

    rows = _load_person_works(data_root, person_map=person_map)

    # Fold to person_id first, then compute -> distinct person = {P1} (not {A1, A2})
    assert {r["person_id"] for r in rows} == {"P1"}
    # Each row of the long table carries person_id / work_id / publication_year / institution_id / raw_affiliation_strings
    assert all(
        {"person_id", "work_id", "publication_year", "institution_id", "raw_affiliation_strings"}
        <= set(r)
        for r in rows
    )


# ──────────────────────────────────────────────────────────────────────────
# Test 4: test_armi_folds_to_monash  (Task J2; HIGH-10)
# Real RED: _fold_institution does not exist yet.
# Invariant: key remap institution_id -> openalex_id (without it, folding of foreign/complex institutions always misses = the Yves Zenou killer case).
# The fixture follows the real OpenAlex shape of U0 test_inst_lineage T27 (lineage/assoc are URL-shaped).
# ──────────────────────────────────────────────────────────────────────────
_MONASH = "I56590836"
_ARMI = "I2801239119"


def _armi_inst_row():
    """One in-memory INSTITUTIONS row (ARMI facility, two parents [GovVic government, Monash education])."""
    return {
        "institution_id": _ARMI,  # Note: the column is named institution_id (not openalex_id), so a key remap is required
        "display_name": "Australian Regenerative Medicine Institute",
        "country_code": "AU",
        "type": "facility",
        "lineage": [f"https://openalex.org/{_ARMI}", f"https://openalex.org/{_MONASH}"],
        "associated_institutions": [
            {"id": "https://openalex.org/I2801037857", "relationship": "parent", "type": "government"},
            {"id": f"https://openalex.org/{_MONASH}", "relationship": "parent", "type": "education"},
        ],
        "ror": "",
    }


def _monash_registry():
    """registry_by_id = {bare openalex_id : record}; holds only canonical education anchors."""
    return {_MONASH: {"openalex_id": _MONASH, "type": "education",
                      "lineage": [f"https://openalex.org/{_MONASH}"], "associated_institutions": []}}


def test_armi_folds_to_monash():
    from m3_panel.panel import _fold_institution

    canon = _fold_institution(_armi_inst_row(), _monash_registry())
    # ARMI -> Monash (lineage ancestor / assoc parent-education), not GovVic / lineage[-1]
    assert canon == _MONASH


# ──────────────────────────────────────────────────────────────────────────
# Task G2 (U3-E author-space guard): tests 4b/4c
# Invariant: the canonical space fails loudly; no silent inner join that drops people (the Yves Zenou 16-ID counter-case).
# Note: U3 uses "normalise + break cycles": a clean redirect -> canonicalize normalises it and keeps the person; a merge cycle = corrupt space -> exit(22).
#   (An "incomplete cmap" cannot be built cleanly; the constructible "merge cycle = corrupt space" case guards the same invariant.)
# ──────────────────────────────────────────────────────────────────────────
def test_author_id_canonical_space_cycle_exits():
    from m3_panel.panel import _build_author_cmap

    # Merge cycle A_OLD->A_CANON->A_OLD = corrupt canonical space -> exit(22), not handled silently
    cmap_rows = [
        {"raw_id": "A_OLD", "canonical_id": "A_CANON", "id_type": "author", "is_deleted": False},
        {"raw_id": "A_CANON", "canonical_id": "A_OLD", "id_type": "author", "is_deleted": False},
    ]
    with pytest.raises(SystemExit) as ei:
        _build_author_cmap(cmap_rows)
    assert ei.value.code == EXIT_CANONICAL_SPACE_SPLIT


def test_author_id_redirect_remapped_before_join(tmp_path):
    from m3_panel.panel import _build_author_cmap, _load_person_works

    data_root = tmp_path
    _write_real(data_root, "works_affil", [
        {"work_id": "W1", "author_id": "A_OLD", "institution_id": "I1",
         "raw_affiliation_strings": ["Monash University"]},
    ])
    _write_real(data_root, "authorship_edges", [
        {"work_id": "W1", "author_id": "A_OLD", "publication_year": 2016},
    ])
    # Clean redirect A_OLD->A_CANON; person_map holds only canonical A_CANON
    cmap_rows = [{"raw_id": "A_OLD", "canonical_id": "A_CANON",
                  "id_type": "author", "is_deleted": False}]
    author_cmap = _build_author_cmap(cmap_rows)
    rows = _load_person_works(data_root, person_map={"A_CANON": "P1"}, author_cmap=author_cmap)

    # A_OLD normalises to A_CANON -> P1, not dropped, the work is present (same convention as U1 open_item 2)
    assert {r["person_id"] for r in rows} == {"P1"}
    assert {r["work_id"] for r in rows} == {"W1"}


# ──────────────────────────────────────────────────────────────────────────
# Task J1, remaining 3 tests: year taken from edges / missing year fails loudly / orphans are not dropped silently
# ──────────────────────────────────────────────────────────────────────────
def test_year_comes_from_edges(tmp_path):
    from m3_panel.panel import _load_person_works

    data_root = tmp_path
    _write_real(data_root, "works_affil", [
        {"work_id": "W1", "author_id": "A1", "institution_id": "I1",
         "raw_affiliation_strings": ["x"]},
    ])
    _write_real(data_root, "authorship_edges", [
        {"work_id": "W1", "author_id": "A1", "publication_year": 2010},
    ])
    rows = _load_person_works(data_root, person_map={"A1": "P1"})
    assert [r["publication_year"] for r in rows] == [2010]  # Year taken from edges


def test_missing_year_fail_loud(tmp_path):
    from m3_panel.panel import _load_person_works

    data_root = tmp_path
    out_dir = tmp_path / "out"
    _write_real(data_root, "works_affil", [
        {"work_id": "W9", "author_id": "A1", "institution_id": "I1",
         "raw_affiliation_strings": ["x"]},  # W9 is in works_affil
    ])
    _write_real(data_root, "authorship_edges", [
        {"work_id": "W1", "author_id": "A1", "publication_year": 2010},  # edges lack W9
    ])
    with pytest.raises(SystemExit) as ei:
        _load_person_works(data_root, person_map={"A1": "P1"}, out_dir=out_dir)
    assert ei.value.code == 2
    assert (out_dir / "_reports" / "u3_missing_year.csv").exists()  # Missing-year detail written to csv


def test_null_year_work_arbitrated_by_works_table(tmp_path):
    """Checked on real data: 3,199 papers have no publication year themselves (works.publication_year=null,
    an OpenAlex data fact). The works table arbitrates: truly no year -> drop + write u3_null_year_works.csv (not silent);
    works has a year but the edge row is null -> still HALT (real corruption). With no works arbitration table, HALT conservatively (behaviour unchanged)."""
    from m3_panel.panel import _load_person_works

    data_root = tmp_path
    out_dir = tmp_path / "out"
    _write_real(data_root, "works_affil", [
        {"work_id": "W_ok", "author_id": "A1", "institution_id": "I1",
         "raw_affiliation_strings": ["x"]},
        {"work_id": "W_noyear", "author_id": "A1", "institution_id": "I1",
         "raw_affiliation_strings": ["x"]},
    ])
    _write_real(data_root, "authorship_edges", [
        {"work_id": "W_ok", "author_id": "A1", "publication_year": 2010},
        {"work_id": "W_noyear", "author_id": "A1", "publication_year": None},
    ])
    # works arbitration table (soft source, not a hard prerequisite): W_noyear truly has no year
    import pyarrow as pa
    import pyarrow.parquet as pq
    wdir = data_root / "derived" / "u1_edges" / "works"
    wdir.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({
        "work_id": pa.array(["W_ok", "W_noyear"], type=pa.string()),
        "publication_year": pa.array([2010, None], type=pa.int16()),
    }), str(wdir / "data.parquet"))

    rows = _load_person_works(data_root, person_map={"A1": "P1"}, out_dir=out_dir)
    assert [r["work_id"] for r in rows] == ["W_ok"], "Truly year-less rows are dropped, the rest normal"
    assert (out_dir / "_reports" / "u3_null_year_works.csv").exists(), "The drop is not silent"


def test_null_year_with_year_in_works_still_halts(tmp_path):
    """works says the paper has a year but the edge row is null -> real corruption, HALT as before."""
    from m3_panel.panel import _load_person_works

    data_root = tmp_path
    out_dir = tmp_path / "out"
    _write_real(data_root, "works_affil", [
        {"work_id": "W_broken", "author_id": "A1", "institution_id": "I1",
         "raw_affiliation_strings": ["x"]},
    ])
    _write_real(data_root, "authorship_edges", [
        {"work_id": "W_broken", "author_id": "A1", "publication_year": None},
    ])
    import pyarrow as pa
    import pyarrow.parquet as pq
    wdir = data_root / "derived" / "u1_edges" / "works"
    wdir.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({
        "work_id": pa.array(["W_broken"], type=pa.string()),
        "publication_year": pa.array([2011], type=pa.int16()),
    }), str(wdir / "data.parquet"))

    with pytest.raises(SystemExit) as ei:
        _load_person_works(data_root, person_map={"A1": "P1"}, out_dir=out_dir)
    assert ei.value.code == 2


def test_orphan_heavy_table_filter_pushdown_semantics(tmp_path):
    """OOM fix (exit=137 confirmed): the panel needs only the rows of person_map authors.
    When orphans are the vast majority the output still contains only relevant rows; the orphan count stays exact and the detail csv (sample-capped) is kept."""
    from m3_panel.panel import _load_person_works

    data_root = tmp_path
    out_dir = tmp_path / "out"
    wa = [{"work_id": f"W{i}", "author_id": f"A_orphan{i}", "institution_id": "I1",
           "raw_affiliation_strings": ["x"]} for i in range(50)]
    wa.append({"work_id": "W_keep", "author_id": "A1", "institution_id": "I1",
               "raw_affiliation_strings": ["Monash"]})
    ae = [{"work_id": r["work_id"], "author_id": r["author_id"], "publication_year": 2010}
          for r in wa]
    _write_real(data_root, "works_affil", wa)
    _write_real(data_root, "authorship_edges", ae)

    rows = _load_person_works(data_root, person_map={"A1": "P1"}, out_dir=out_dir)
    assert [r["person_id"] for r in rows] == ["P1"], "Only rows of person_map authors are materialized"
    import csv
    with (out_dir / "_reports" / "u3_unmapped_authors.csv").open() as f:
        orphan_rows = list(csv.DictReader(f))
    assert len(orphan_rows) == 50, "Orphan detail present (full at fixture level; sampled and capped with a count on real data)"


def test_orphan_author_dropped_and_counted(tmp_path):
    from m3_panel.panel import _load_person_works

    data_root = tmp_path
    out_dir = tmp_path / "out"
    _write_real(data_root, "works_affil", [
        {"work_id": "W1", "author_id": "A1", "institution_id": "I1",
         "raw_affiliation_strings": ["x"]},
        {"work_id": "W2", "author_id": "A9", "institution_id": "I1",
         "raw_affiliation_strings": ["x"]},  # A9 is not in person_map = orphan
    ])
    _write_real(data_root, "authorship_edges", [
        {"work_id": "W1", "author_id": "A1", "publication_year": 2010},
        {"work_id": "W2", "author_id": "A9", "publication_year": 2011},
    ])
    rows = _load_person_works(data_root, person_map={"A1": "P1"}, out_dir=out_dir)
    # Orphan A9 does not enter the panel; A1->P1 does
    assert {r["person_id"] for r in rows} == {"P1"}
    assert "A9" not in {r.get("author_id") for r in rows}
    # Orphans written to csv (not dropped silently)
    orphan_csv = out_dir / "_reports" / "u3_unmapped_authors.csv"
    assert orphan_csv.exists()
    assert "A9" in orphan_csv.read_text(encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────────
# Task J2 (inst normalisation + three-way fold): 7 tests
# Invariant: null-id != no Australian affiliation (counted separately); a missing coverage domain fails loudly; fold None writes no institution row.
# ──────────────────────────────────────────────────────────────────────────
_CAULFIELD = "I4210114009"
_STOCKHOLM = "I93936609"


def _caulfield_inst_row():
    """Caulfield (healthcare, no Monash in lineage): the killer counter-example for folding to None (real U0 T28 shape)."""
    return {
        "institution_id": _CAULFIELD,
        "display_name": "Caulfield Hospital",
        "country_code": "AU",
        "type": "healthcare",
        "lineage": [f"https://openalex.org/{_CAULFIELD}"],
        "associated_institutions": [
            {"id": "https://openalex.org/I4210163178", "relationship": "parent", "type": "healthcare"},
        ],
        "ror": "",
    }


def _stockholm_inst_row():
    """Stockholm (foreign education, itself in the registry): foreign institutions fold via the institutions table."""
    return {
        "institution_id": _STOCKHOLM,
        "display_name": "Stockholm University",
        "country_code": "SE",
        "type": "education",
        "lineage": [f"https://openalex.org/{_STOCKHOLM}"],
        "associated_institutions": [],
        "ror": "",
    }


def _foreign_registry():
    return {
        _MONASH: {"openalex_id": _MONASH, "type": "education"},
        _STOCKHOLM: {"openalex_id": _STOCKHOLM, "type": "education"},
    }


def test_caulfield_healthcare_folds_to_none():
    from m3_panel.panel import _fold_institution

    assert _fold_institution(_caulfield_inst_row(), _monash_registry()) is None


def test_foreign_inst_folds_non_none_from_table():
    from m3_panel.panel import _canonicalize_affils

    rows = [{"person_id": "P1", "publication_year": 2016, "work_id": "W1",
             "institution_id": _STOCKHOLM, "raw_affiliation_strings": ["Stockholm University"]}]
    institutions_by_id = {_STOCKHOLM: _stockholm_inst_row()}  # Feed from the table, not hand-built inline
    affil_rows, _ = _canonicalize_affils(rows, institutions_by_id, _foreign_registry())
    assert [r["canonical_affil_id"] for r in affil_rows] == [_STOCKHOLM]  # Foreign education folds to non-None


def test_inst_not_in_institutions_fail_loud(tmp_path):
    from m3_panel.panel import _canonicalize_affils

    rows = [{"person_id": "P1", "publication_year": 2016, "work_id": "W1",
             "institution_id": "I_MISSING", "raw_affiliation_strings": ["x"]}]
    affil_rows, counts = _canonicalize_affils(rows, {}, _monash_registry(), out_dir=tmp_path)
    assert counts["rows_inst_not_in_institutions"] >= 1  # Not silently zeroed
    assert (tmp_path / "_reports" / "u3_inst_not_in_institutions.csv").exists()
    assert affil_rows == []  # An id missing from the coverage domain gets no institution row (audit)


def test_null_inst_with_raw_not_silently_zeroed(tmp_path):
    from m3_panel.panel import _canonicalize_affils

    rows = [{"person_id": "P1", "publication_year": 2016, "work_id": "W1",
             "institution_id": None, "raw_affiliation_strings": ["Monash University (email: )"]}]
    affil_rows, counts = _canonicalize_affils(rows, {}, _monash_registry(), out_dir=tmp_path)
    assert counts["rows_null_inst_with_raw"] >= 1
    # raw-only rows are kept (missing-id != no Australian affiliation); canonical=__NONE__ sentinel
    assert len(affil_rows) == 1
    assert affil_rows[0]["canonical_affil_id"] == "__NONE__"


def test_two_null_inst_rows_same_work_both_kept():
    from m3_panel.panel import _canonicalize_affils

    rows = [
        {"person_id": "P1", "publication_year": 2016, "work_id": "W1",
         "institution_id": None, "raw_affiliation_strings": ["Dept A"]},
        {"person_id": "P1", "publication_year": 2016, "work_id": "W1",
         "institution_id": None, "raw_affiliation_strings": ["Dept B, email"]},
    ]
    affil_rows, _ = _canonicalize_affils(rows, {}, _monash_registry())
    # Two null-inst rows with different raw for the same (person, work): both are kept (they do not swallow each other)
    assert len(affil_rows) == 2


def test_redirect_inst_id_remapped():
    from m3_panel.panel import _remap_inst_ids

    rows = [{"person_id": "P1", "publication_year": 2016, "work_id": "W1",
             "institution_id": "I_OLD", "raw_affiliation_strings": ["x"]}]
    inst_cmap = {"I_OLD": (_MONASH, False)}  # redirect I_OLD → Monash
    remapped, n_deleted = _remap_inst_ids(rows, inst_cmap)
    assert remapped[0]["institution_id"] == _MONASH  # Normalised to canonical, not the redirect's old id
    assert n_deleted == 0


def test_deleted_sentinel_inst_excluded():
    from m3_panel.panel import _remap_inst_ids

    rows = [
        {"person_id": "P1", "publication_year": 2016, "work_id": "W1",
         "institution_id": "I_DEL", "raw_affiliation_strings": ["x"]},
        {"person_id": "P1", "publication_year": 2016, "work_id": "W2",
         "institution_id": _MONASH, "raw_affiliation_strings": ["x"]},
    ]
    inst_cmap = {"I_DEL": ("I_DEL", True)}  # is_deleted=True
    remapped, n_deleted = _remap_inst_ids(rows, inst_cmap)
    assert n_deleted == 1
    assert {r["institution_id"] for r in remapped} == {_MONASH}  # Signatures of deleted institutions are dropped


# ──────────────────────────────────────────────────────────────────────────
# Task M1 (modal institution + determinism): 5 tests
# Invariant: modal votes count distinct work_id (one work, one vote); is_modal != U4 arrival; fully deterministic.
# ──────────────────────────────────────────────────────────────────────────
def _canon(pid, year, work, raw_inst, canon, raws):
    """Build a canon_row in the output format of _canonicalize_affils."""
    return {"person_id": pid, "year": year, "work_id": work,
            "raw_inst_id": raw_inst, "canonical_affil_id": canon, "raw_affil_strings": raws}


def test_modal_picks_max_then_smallest_id():
    from m3_panel.panel import _build_affil_timeline

    rows = [
        _canon("P1", 2016, "W1", "I_M", _MONASH, ["Monash"]),
        _canon("P1", 2016, "W2", "I_M", _MONASH, ["Monash"]),
        _canon("P1", 2016, "W3", "I_M", _MONASH, ["Monash"]),
        _canon("P1", 2016, "W4", "I_IFN", "I_IFN", ["IFN"]),
    ]
    tl = _build_affil_timeline(rows)
    assert {r["canonical_affil_id"] for r in tl if r["is_modal"]} == {_MONASH}  # 3 > 1

    # Tie (1 work each) -> lexicographically smallest canonical id
    tie = [_canon("P2", 2016, "WA", "I_B", "I_B", ["x"]),
           _canon("P2", 2016, "WB", "I_A", "I_A", ["x"])]
    tl_tie = _build_affil_timeline(tie)
    assert {r["canonical_affil_id"] for r in tl_tie if r["is_modal"]} == {"I_A"}


def test_modal_tiebreak_order_independent():
    from m3_panel.panel import _build_affil_timeline

    rows = [_canon("P1", 2016, "WA", "I_B", "I_B", ["x"]),
            _canon("P1", 2016, "WB", "I_A", "I_A", ["x"])]
    fwd = {r["canonical_affil_id"] for r in _build_affil_timeline(rows) if r["is_modal"]}
    bwd = {r["canonical_affil_id"] for r in _build_affil_timeline(list(reversed(rows))) if r["is_modal"]}
    assert fwd == bwd == {"I_A"}  # Tie-break does not depend on input order


def test_modal_dedup_within_work():
    from m3_panel.panel import _build_affil_timeline

    # One work W1 listed under ARMI + Monash (both fold to Monash) -> Monash gets 1 vote (distinct work_id, not 2)
    rows = [_canon("P1", 2016, "W1", "I_ARMI", _MONASH, ["ARMI"]),
            _canon("P1", 2016, "W1", "I_MON", _MONASH, ["Monash"])]
    tl = _build_affil_timeline(rows)
    monash = [r for r in tl if r["canonical_affil_id"] == _MONASH]
    assert all(r["n_works_at_affil"] == 1 for r in monash)  # Counter-example: raw_inst granularity would give 2


def test_raw_affil_min_deterministic_flattened():
    from m3_panel.panel import _build_affil_timeline

    rows = [_canon("P1", 2016, "W1", "I_M", _MONASH, ["Zzz", "Aaa"]),
            _canon("P1", 2016, "W2", "I_M", _MONASH, ["Mmm", "Bbb"])]
    fwd = {r["raw_affil"] for r in _build_affil_timeline(rows)}
    # Shuffling across entries and within lists leaves raw_affil unchanged (= global lexicographic min of the flattened list = "Aaa")
    shuffled = [_canon("P1", 2016, "W2", "I_M", _MONASH, ["Bbb", "Mmm"]),
                _canon("P1", 2016, "W1", "I_M", _MONASH, ["Aaa", "Zzz"])]
    bwd = {r["raw_affil"] for r in _build_affil_timeline(shuffled)}
    assert fwd == bwd == {"Aaa"}


def test_n_works_at_affil_distinct_work_count():
    from m3_panel.panel import _build_affil_timeline

    rows = [
        _canon("P1", 2016, "W1", "I_M", _MONASH, ["Monash"]),
        _canon("P1", 2016, "W2", "I_M", _MONASH, ["Monash"]),
        _canon("P1", 2016, "W3", "I_M", _MONASH, ["Monash"]),
        _canon("P1", 2016, "W4", "I_IFN", "I_IFN", ["IFN"]),
    ]
    tl = _build_affil_timeline(rows)
    nw = {r["canonical_affil_id"]: r["n_works_at_affil"] for r in tl}
    assert nw[_MONASH] == 3 and nw["I_IFN"] == 1  # per-(person,year,affil) distinct work
    # Non-modal rows (IFN) must also have this column, filled correctly
    ifn = [r for r in tl if r["canonical_affil_id"] == "I_IFN"]
    assert ifn and ifn[0]["n_works_at_affil"] == 1


# ──────────────────────────────────────────────────────────────────────────
# Task A1 (threshold #9 + true first-publication year #9->#7 + assembling the unbalanced panel): 8 tests
# Invariant: #9 has a single definition, >=2 distinct years; first_pub is only passed through, never frozen; the sentinel does not enter contract functions.
# ──────────────────────────────────────────────────────────────────────────
def test_population_threshold_two_distinct_years(tmp_path):
    from m3_panel.panel import _apply_population_threshold

    rows = [
        {"person_id": "P_single", "publication_year": 2016, "work_id": "W1"},
        {"person_id": "P_single", "publication_year": 2016, "work_id": "W2"},  # Several papers in a single year
        {"person_id": "P_single", "publication_year": 2016, "work_id": "W3"},
        {"person_id": "P_multi", "publication_year": 2015, "work_id": "W4"},
        {"person_id": "P_multi", "publication_year": 2016, "work_id": "W5"},  # One paper in each of 2 years
    ]
    eligible = _apply_population_threshold(rows, out_dir=tmp_path)
    assert "P_multi" in eligible  # >=2 distinct years passes
    assert "P_single" not in eligible  # A single year does not qualify even with many papers (the threshold is years, not paper count)
    assert (tmp_path / "_reports" / "u3_below_threshold_persons.csv").exists()


def test_pop_min_works_no_longer_gates():
    from m3_panel.panel import _apply_population_threshold

    # 1 paper in each of 2 years (low n_works) -> still eligible (shows n_works is no longer a threshold, only distinct_years)
    rows = [{"person_id": "P", "publication_year": 2015, "work_id": "W1"},
            {"person_id": "P", "publication_year": 2016, "work_id": "W2"}]
    assert "P" in _apply_population_threshold(rows)


def test_n_works_year_dedup_across_author_ids():
    from m3_panel.panel import _assemble_panel

    # Person P co-authors the same work W1 under A1/A2 -> person_works has 2 rows for one work -> n_works_year==1
    pw = [{"person_id": "P", "publication_year": 2016, "work_id": "W1"},
          {"person_id": "P", "publication_year": 2016, "work_id": "W1"}]
    panel = _assemble_panel(pw, [], {"P"}, {}, set())
    assert len(panel) == 1 and panel[0]["n_works_year"] == 1  # distinct work_id


def test_in_au_econ_dept_modal_hint_flag():
    from m3_panel.panel import _assemble_panel

    pw = [{"person_id": "P", "publication_year": 2015, "work_id": "W1"},
          {"person_id": "P", "publication_year": 2016, "work_id": "W2"}]
    tl = [
        {"person_id": "P", "year": 2015, "work_id": "W1", "raw_inst_id": "I_M",
         "raw_affil_slot": 0, "canonical_affil_id": _MONASH, "n_works_at_affil": 1,
         "is_modal": True, "raw_affil": "Monash"},
        {"person_id": "P", "year": 2016, "work_id": "W2", "raw_inst_id": "I_X",
         "raw_affil_slot": 0, "canonical_affil_id": "I_OTHER", "n_works_at_affil": 1,
         "is_modal": True, "raw_affil": "Other"},
    ]
    panel = _assemble_panel(pw, tl, {"P"}, {}, {_MONASH})
    by_year = {r["year"]: r for r in panel}
    assert by_year[2015]["in_au_econ_dept_modal_hint"] is True   # Monash ∈ econ
    assert by_year[2016]["in_au_econ_dept_modal_hint"] is False  # Non-econ


def test_sentinel_never_passed_to_in_au_econ_dept(monkeypatch):
    import m3_panel.panel as panel_mod

    def guard(canonical_id, econ_dept_ids):
        assert canonical_id != "AFFIL_NONE", "The sentinel string must never enter in_au_econ_dept"
        return canonical_id in econ_dept_ids

    monkeypatch.setattr(panel_mod, "in_au_econ_dept", guard)
    pw = [{"person_id": "P", "publication_year": 2015, "work_id": "W1"},
          {"person_id": "P", "publication_year": 2016, "work_id": "W2"}]
    # Person-year with all-None institutions (affil_timeline has no modal) -> primary=PANEL_AFFIL_NONE
    panel = panel_mod._assemble_panel(pw, [], {"P"}, {}, {_MONASH})
    assert all(r["in_au_econ_dept_modal_hint"] is False for r in panel)  # call-site passes None
    assert len(panel) == 2  # Still in the panel


def test_first_pub_year_from_u1_table_not_panel():
    """Semantics: first_pub = robust({U1 full-history fragment min} ∪ corpus publication years).
    A single fragment with no corpus year -> still takes the U1 value (full history kept)."""
    from m3_panel.panel import _compute_first_pub_year

    fp = _compute_first_pub_year(
        {"A1": "P"},
        [{"author_id": "A1", "first_pub_year": 1985, "first_pub_year_is_full_history": True}],
        max_leading_gap=10,
    )
    assert fp["P"] == (1985, True)  # From the U1 work_first_pub table


def test_first_pub_full_history_flag_passthrough():
    from m3_panel.panel import _compute_first_pub_year

    single = _compute_first_pub_year(
        {"A1": "P"},
        [{"author_id": "A1", "first_pub_year": 1990, "first_pub_year_is_full_history": True}],
        max_leading_gap=10,
    )
    assert single["P"][1] is True
    # Several fragments, one True and one False -> AND -> False; year takes the fragment min (1985->1990 gap 5 <= 10, continuous -> kept)
    multi = _compute_first_pub_year(
        {"A1": "P", "A2": "P"},
        [{"author_id": "A1", "first_pub_year": 1990, "first_pub_year_is_full_history": True},
         {"author_id": "A2", "first_pub_year": 1985, "first_pub_year_is_full_history": False}],
        max_leading_gap=10,
    )
    assert multi["P"] == (1985, False)


def test_first_pub_year_feeds_gen_pk_freeze_input():
    from m3_panel.panel import _assemble_panel, _compute_first_pub_year

    # A senior person whose true first publication is in the 1980s (1985->1990->... continuous in the corpus) and who arrives at Monash in 2016: first_pub=1985
    fp = _compute_first_pub_year(
        {"A1": "P_senior"},
        [{"author_id": "A1", "first_pub_year": 1985, "first_pub_year_is_full_history": True}],
        person_years={"P_senior": [1990, 1995, 2000, 2005, 2010, 2016, 2017]},
        max_leading_gap=10,
    )
    pw = [{"person_id": "P_senior", "publication_year": 2016, "work_id": "W1"},
          {"person_id": "P_senior", "publication_year": 2017, "work_id": "W2"}]
    panel = _assemble_panel(pw, [], {"P_senior"}, fp, set())
    # U3 supplies the true first-publication year -> downstream #7 freezes the generation at the arrival year without treating a senior person as new (U3 neither freezes nor groups)
    assert all(r["first_pub_year"] == 1985 for r in panel)


# ──────────────────────────────────────────────────────────────────────────
# Panel first_pub switches from a bare min to the shared robust debut year: 3 new tests
# Definition: candidate year set = {U1 full-history fragment min} ∪ the person's corpus publication years -> identity.first_pub.robust_first_pub
# (gap = 10). Measured: namesake contamination pulls 15.25% of the panel's debut years earlier by >10 years (median 23 years).
# ──────────────────────────────────────────────────────────────────────────
def test_first_pub_robust_drops_polluted_isolated_u1_min():
    """Must be red: the U1 full-history min=1960 is an isolated leading year from namesake contamination (45>10 years before the corpus career starts in 2005)
    -> robust drops it -> first_pub=2005 (cures systematically inflated academic ages of the 54 / 49 type)."""
    from m3_panel.panel import _compute_first_pub_year

    fp = _compute_first_pub_year(
        {"A1": "P"},
        [{"author_id": "A1", "first_pub_year": 1960, "first_pub_year_is_full_history": True}],
        person_years={"P": [2005, 2008, 2010]},
        max_leading_gap=10,
    )
    assert fp["P"] == (2005, True)


def test_first_pub_robust_keeps_continuous_u1_min():
    """Counter-guard for #9 (the Yves Zenou 1991 type): U1 min is continuous with the corpus career (gap <= 10) -> the early full-history years are **kept**
    (robust does not "throw away the full history"; it drops only an isolated leading year, so the contamination-resistant version stays faithful to #9)."""
    from m3_panel.panel import _compute_first_pub_year

    fp = _compute_first_pub_year(
        {"A1": "P"},
        [{"author_id": "A1", "first_pub_year": 1991, "first_pub_year_is_full_history": True}],
        person_years={"P": [1998, 2005, 2010]},   # 1991->1998 gap 7 <= 10 -> continuous
        max_leading_gap=10,
    )
    assert fp["P"] == (1991, True)


def test_first_pub_robust_drops_polluted_fragment_min():
    """Several fragments: the contaminated fragment (A2 min=1955, isolated) is dropped, the true fragment counts from 1990; the flag is still ANDed."""
    from m3_panel.panel import _compute_first_pub_year

    fp = _compute_first_pub_year(
        {"A1": "P", "A2": "P"},
        [{"author_id": "A1", "first_pub_year": 1990, "first_pub_year_is_full_history": True},
         {"author_id": "A2", "first_pub_year": 1955, "first_pub_year_is_full_history": False}],
        person_years={"P": [1992, 1995]},
        max_leading_gap=10,
    )
    assert fp["P"] == (1990, False)


# ──────────────────────────────────────────────────────────────────────────
# Task R1 (derived-class invariant reconciliation, strict equality): 4 tests
# Invariant: a missing year is never filled with 0 and no person is ever deleted; strict == rather than monotone (monotone would miss drift).
# ──────────────────────────────────────────────────────────────────────────
def test_unbalanced_no_zero_fill():
    from m3_panel.panel import _assemble_panel

    # P1 publishes in 2010/2013 (not 2011/2012) -> panel has only these two years, no 0-filled gap rows
    pw = [{"person_id": "P1", "publication_year": 2010, "work_id": "W1"},
          {"person_id": "P1", "publication_year": 2013, "work_id": "W2"}]
    panel = _assemble_panel(pw, [], {"P1"}, {}, set())
    assert {r["year"] for r in panel} == {2010, 2013}  # Missing years are not filled with rows


def test_panel_year_subset_of_works_years():
    from m3_panel.panel import _reconcile_panel

    pw = [{"person_id": "P1", "publication_year": 2010, "work_id": "W1"}]
    bad_panel = [{"person_id": "P1", "year": 2099, "primary_affil_id": "AFFIL_NONE"}]  # Year invented from nothing
    with pytest.raises(SystemExit) as ei:
        _reconcile_panel(bad_panel, [], {"P1"}, pw)
    assert ei.value.code == 2


def test_no_redirect_id_in_output():
    from m3_panel.panel import _reconcile_panel

    pw = [{"person_id": "P1", "publication_year": 2010, "work_id": "W1"}]
    panel = [{"person_id": "P1", "year": 2010, "primary_affil_id": "AFFIL_NONE"}]
    tl = [{"person_id": "P1", "year": 2010, "raw_inst_id": "I_OLD"}]  # Inject a redirect old id
    with pytest.raises(SystemExit) as ei:
        _reconcile_panel(panel, tl, {"P1"}, pw, redirect_ids={"I_OLD"})
    assert ei.value.code == 2


def test_row_count_strict_equality_not_monotone():
    from m3_panel.panel import _reconcile_panel

    # Strict equality is required here: monotone would miss a drift of one extra row
    pw = [{"person_id": "P1", "publication_year": 2010, "work_id": "W1"}]
    drifted = [{"person_id": "P1", "year": 2010, "primary_affil_id": "AFFIL_NONE"},
               {"person_id": "P1", "year": 2010, "primary_affil_id": "AFFIL_NONE"}]  # One extra row
    with pytest.raises(SystemExit) as ei:
        _reconcile_panel(drifted, [], {"P1"}, pw)
    assert ei.value.code == 2


# ──────────────────────────────────────────────────────────────────────────
# Task Z1 (deterministic write + COMMIT + resume + Yves Zenou golden test, shape-only): 12 tests
# The Yves Zenou tests are pinned at the top: they check only the panel/affil_timeline shape; star identification, arrival=2016 and
# departure from the previous home Stockholm are U4 classify_golden, not U3. Never use affiliations[].years.
# ──────────────────────────────────────────────────────────────────────────
def _url(iid):
    return f"https://openalex.org/{iid}"


def _inst_row(iid, type_, lineage_ids, assoc):
    return {"institution_id": iid, "display_name": iid, "country_code": "AU",
            "type": type_, "lineage": [_url(x) for x in lineage_ids],
            "associated_institutions": assoc, "ror": ""}


def _pm_row(aid, pid):
    """person_map with 7 columns (U3 reads only author_id/person_id; the rest get default placeholders)."""
    return {"author_id": aid, "person_id": pid, "merge_reason": "block_cluster",
            "cluster_homogeneity": 1.0, "completeness": 1.0, "purity_flag": "ok",
            "had_orcid": False}


def _lay_zenou(data_root):
    """Full Yves Zenou end-to-end fixture (6 upstream tables). Returns (econ_dept_ids, registry_by_id).

    P_Z = fragments A_Z1+A_Z2 folded into one person. 1998 previous home Stockholm (mode != Monash); 2016 arrives at Monash
    (Monash mode, incl. ARMI folded into Monash / Caulfield filtered / null-inst Monash raw not lost).
    """
    GOV = "I2801037857"
    # works_affil: (work_id, author_id, institution_id, raw_affiliation_strings)
    wa = [
        # 1998: previous home Stockholm has the majority (2 papers) vs 1 for Monash -> mode Stockholm
        {"work_id": "W98a", "author_id": "A_Z1", "institution_id": _STOCKHOLM,
         "raw_affiliation_strings": ["Stockholm University"]},
        {"work_id": "W98b", "author_id": "A_Z1", "institution_id": _STOCKHOLM,
         "raw_affiliation_strings": ["Stockholm University"]},
        {"work_id": "W98c", "author_id": "A_Z1", "institution_id": _MONASH,
         "raw_affiliation_strings": ["Monash University"]},
        # 2016 Monash mode (W16a/b/c distinct work=3); ARMI folds to Monash; Caulfield filtered; null-inst Monash raw
        {"work_id": "W16a", "author_id": "A_Z1", "institution_id": _MONASH,
         "raw_affiliation_strings": ["Monash University"]},
        {"work_id": "W16b", "author_id": "A_Z2", "institution_id": _MONASH,
         "raw_affiliation_strings": ["Monash University"]},
        {"work_id": "W16c", "author_id": "A_Z1", "institution_id": _ARMI,
         "raw_affiliation_strings": ["ARMI"]},
        {"work_id": "W16d", "author_id": "A_Z1", "institution_id": _CAULFIELD,
         "raw_affiliation_strings": ["Caulfield Hospital"]},
        {"work_id": "W16e", "author_id": "A_Z1", "institution_id": None,
         "raw_affiliation_strings": ["Monash University (email: )"]},
    ]
    edges = [
        {"work_id": "W98a", "author_id": "A_Z1", "publication_year": 1998},
        {"work_id": "W98b", "author_id": "A_Z1", "publication_year": 1998},
        {"work_id": "W98c", "author_id": "A_Z1", "publication_year": 1998},
        {"work_id": "W16a", "author_id": "A_Z1", "publication_year": 2016},
        {"work_id": "W16b", "author_id": "A_Z2", "publication_year": 2016},
        {"work_id": "W16c", "author_id": "A_Z1", "publication_year": 2016},
        {"work_id": "W16d", "author_id": "A_Z1", "publication_year": 2016},
        {"work_id": "W16e", "author_id": "A_Z1", "publication_year": 2016},
    ]
    _write_real(data_root, "works_affil", wa)
    _write_real(data_root, "authorship_edges", edges)
    _write_real(data_root, "person_map", [_pm_row("A_Z1", "P_Z"), _pm_row("A_Z2", "P_Z")])
    _write_real(data_root, "work_first_pub", [
        {"author_id": "A_Z1", "first_pub_year": 1998, "first_pub_year_is_full_history": True},
        {"author_id": "A_Z2", "first_pub_year": 1998, "first_pub_year_is_full_history": True},
    ])
    # canonical_id_map: 1 unrelated inst redirect (does not touch Yves Zenou); no author redirect
    _write_real(data_root, "canonical_id_map", [
        {"raw_id": "I_X_OLD", "canonical_id": "I_X_NEW", "id_type": "institution", "is_deleted": False},
    ])
    _write_real(data_root, "institutions", [
        _inst_row(_MONASH, "education", [_MONASH], []),
        _inst_row(_STOCKHOLM, "education", [_STOCKHOLM], []),
        _inst_row(_ARMI, "facility", [_ARMI, _MONASH],
                  [{"id": _url(GOV), "relationship": "parent", "type": "government"},
                   {"id": _url(_MONASH), "relationship": "parent", "type": "education"}]),
        _inst_row(_CAULFIELD, "healthcare", [_CAULFIELD],
                  [{"id": _url("I4210163178"), "relationship": "parent", "type": "healthcare"}]),
    ])
    econ_dept_ids = {_MONASH}
    registry_by_id = {_MONASH: {"openalex_id": _MONASH, "type": "education"},
                      _STOCKHOLM: {"openalex_id": _STOCKHOLM, "type": "education"}}
    return econ_dept_ids, registry_by_id


def _run_zenou(data_root, out_dir, **kw):
    from m3_panel.panel import build_panel

    econ, reg = _lay_zenou(data_root)
    return build_panel(data_root, out_dir, econ_dept_ids=econ, registry_by_id=reg, **kw)


def _read_output(out_dir, name):
    import pyarrow.parquet as pq

    return pq.read_table(out_dir / name / "data.parquet").to_pylist()


# ---- determinism 5 ----
def test_pk_dedup_before_write(tmp_path):
    _run_zenou(tmp_path / "d", tmp_path / "out")
    panel = _read_output(tmp_path / "out", "panel")
    pks = [(r["person_id"], r["year"]) for r in panel]
    assert len(pks) == len(set(pks))  # No duplicate PK on disk


def test_build_panel_two_run_byte_identical(tmp_path):
    import hashlib

    _run_zenou(tmp_path / "dA", tmp_path / "outA")
    _run_zenou(tmp_path / "dB", tmp_path / "outB")
    for name in ("panel", "affil_timeline"):
        a = (tmp_path / "outA" / name / "data.parquet").read_bytes()
        b = (tmp_path / "outB" / name / "data.parquet").read_bytes()
        assert hashlib.sha256(a).hexdigest() == hashlib.sha256(b).hexdigest()  # Byte-level idempotent


def test_run_commit_valid(tmp_path):
    from common.manifest import dataset_is_valid

    _run_zenou(tmp_path / "d", tmp_path / "out")
    assert dataset_is_valid(tmp_path / "out") is True  # _frozen/COMMIT present


def test_resume_skips_via_dataset_valid(tmp_path):
    econ, reg = _lay_zenou(tmp_path / "d")
    from m3_panel.panel import build_panel

    build_panel(tmp_path / "d", tmp_path / "out", econ_dept_ids=econ, registry_by_id=reg)
    again = build_panel(tmp_path / "d", tmp_path / "out", econ_dept_ids=econ,
                        registry_by_id=reg, resume=True)
    assert again.get("status") == "skipped"  # Upstream sha unchanged -> skip the whole U3


def test_resume_rebuilds_on_upstream_change(tmp_path):
    econ, reg = _lay_zenou(tmp_path / "d")
    from m3_panel.panel import build_panel

    build_panel(tmp_path / "d", tmp_path / "out", econ_dept_ids=econ, registry_by_id=reg)
    # Change upstream person_map (add a row -> new sha) -> resume does not skip, rebuilds
    _write_real(tmp_path / "d", "person_map",
                [_pm_row("A_Z1", "P_Z"), _pm_row("A_Z2", "P_Z"), _pm_row("A_NEW", "P_NEW")])
    again = build_panel(tmp_path / "d", tmp_path / "out", econ_dept_ids=econ,
                        registry_by_id=reg, resume=True)
    assert again.get("status") == "built"  # Upstream changed -> rebuild


# ---- Yves Zenou golden test 7 (shape-only) ----
def test_zenou_author_ids_collapse_to_one_person(tmp_path):
    _run_zenou(tmp_path / "d", tmp_path / "out")
    panel = _read_output(tmp_path / "out", "panel")
    assert {r["person_id"] for r in panel} == {"P_Z"}  # 2 fragments fold into 1 person


def test_zenou_1998_modal_not_monash(tmp_path):
    _run_zenou(tmp_path / "d", tmp_path / "out")
    panel = {(r["person_id"], r["year"]): r for r in _read_output(tmp_path / "out", "panel")}
    # 1998 mode institution is not Monash (previous home Stockholm has the majority); arrival is decided in U4, never from affiliations.years
    assert panel[("P_Z", 1998)]["primary_affil_id"] != _MONASH


def test_zenou_armi_year_no_independent_row(tmp_path):
    _run_zenou(tmp_path / "d", tmp_path / "out")
    tl = _read_output(tmp_path / "out", "affil_timeline")
    # ARMI folds into Monash -> affil_timeline has no separate row with canonical==ARMI
    assert _ARMI not in {r["canonical_affil_id"] for r in tl}


def test_zenou_caulfield_filtered(tmp_path):
    _run_zenou(tmp_path / "d", tmp_path / "out")
    tl = _read_output(tmp_path / "out", "affil_timeline")
    # Caulfield (healthcare) filtered by the whitelist -> no Caulfield institution row
    assert _CAULFIELD not in {r["canonical_affil_id"] for r in tl}
    assert _CAULFIELD not in {r["raw_inst_id"] for r in tl}


def test_zenou_null_id_monash_not_dropped(tmp_path):
    _run_zenou(tmp_path / "d", tmp_path / "out")
    panel = {(r["person_id"], r["year"]): r for r in _read_output(tmp_path / "out", "panel")}
    tl = _read_output(tmp_path / "out", "affil_timeline")
    # Single paper with no ORCID, null-inst Monash raw -> person-year 2016 does not vanish + the raw-only row is present
    assert ("P_Z", 2016) in panel
    assert any(r["canonical_affil_id"] == "__NONE__" for r in tl)  # raw-only row kept


def test_zenou_panel_unbalanced_shape(tmp_path):
    _run_zenou(tmp_path / "d", tmp_path / "out")
    years = {r["year"] for r in _read_output(tmp_path / "out", "panel") if r["person_id"] == "P_Z"}
    assert years == {1998, 2016}  # Unbalanced: only years with a real work, no row for missing years


def test_zenou_2016_monash_present(tmp_path):
    _run_zenou(tmp_path / "d", tmp_path / "out")
    panel = {(r["person_id"], r["year"]): r for r in _read_output(tmp_path / "out", "panel")}
    row = panel[("P_Z", 2016)]
    # Prepares input for U4 arrival; this column is only a hint, the arrival decision and membership authority stay in U4/table B
    assert row["primary_affil_id"] == _MONASH
    assert row["in_au_econ_dept_modal_hint"] is True


# ──────────────────────────────────────────────────────────────────────────
# Review fixes: 2 real-bug red tests (neither touches the identification definition)
# ──────────────────────────────────────────────────────────────────────────
def test_first_pub_year_canonicalizes_redirect_author():
    """MEDIUM: _compute_first_pub_year skipped normalisation -> a redirect author silently lost the first-publication year.

    Invariant: first_pub normalisation must use the same definition as _load_person_works, otherwise a senior person from the 1980s is treated as new
    (contaminating the #9->#7 generation freeze, "the most dangerous Yves Zenou case").
    """
    from m3_panel.panel import _build_author_cmap, _compute_first_pub_year

    cmap_rows = [{"raw_id": "A_OLD", "canonical_id": "A_CANON",
                  "id_type": "author", "is_deleted": False}]
    author_cmap = _build_author_cmap(cmap_rows)
    person_map = {"A_CANON": "P"}  # The list holds only canonical ids
    wfp = [{"author_id": "A_OLD", "first_pub_year": 1985,  # work_first_pub still contains a redirect
            "first_pub_year_is_full_history": True}]
    fp = _compute_first_pub_year(person_map, wfp, author_cmap=author_cmap,
                                 max_leading_gap=10)
    assert fp["P"] == (1985, True)  # Normalise A_OLD->A_CANON->P; the true 1985 first publication is not lost


def test_resume_rebuilds_on_missing_output(tmp_path):
    """HIGH: resume does not verify the real artifact -> deleting the parquet still reports skipped."""
    econ, reg = _lay_zenou(tmp_path / "d")
    from m3_panel.panel import build_panel

    build_panel(tmp_path / "d", tmp_path / "out", econ_dept_ids=econ, registry_by_id=reg)
    # COMMIT is still there but panel/data.parquet was deleted -> resume must rebuild, not skip
    (tmp_path / "out" / "panel" / "data.parquet").unlink()
    again = build_panel(tmp_path / "d", tmp_path / "out", econ_dept_ids=econ,
                        registry_by_id=reg, resume=True)
    assert again.get("status") == "built"  # Real artifact missing -> do not skip, rebuild
    assert (tmp_path / "out" / "panel" / "data.parquet").exists()  # Rebuilt


# ──────────────────────────────────────────────────────────────────────────
# Integration: with the U1 full-run BUCKETED layout (bucket=*/part-*) U3 still reads correctly (via common.derived_table).
# Crux = _load_person_works goes through read_derived_arrow (concatenating buckets) + duckdb.register -> join + fold persons.
# ──────────────────────────────────────────────────────────────────────────
def _write_bucketed(data_root, table, rows, n_parts=2):
    """Split rows into n_parts and write them in the bucketed layout <unit>/<tbl>/bucket=NNN/part-00000.parquet (the U1 full-run layout)."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    unit, tbl = _UPSTREAM_LAYOUT[table]
    base = data_root / "derived" / unit / tbl
    for b in range(n_parts):
        chunk = rows[b::n_parts]
        if not chunk:
            continue
        p = base / f"bucket={b:03d}" / "part-00000.parquet"
        p.parent.mkdir(parents=True, exist_ok=True)
        cols = list(chunk[0].keys())
        pq.write_table(pa.table({c: [r[c] for r in chunk] for c in cols}), str(p))


def test_load_person_works_reads_bucketed_layout(tmp_path):
    """works_affil + authorship_edges are written in the BUCKETED layout -> _load_person_works via
    read_derived_arrow (concatenating buckets) + duckdb.register still does the LEFT JOIN and person folding correctly.
    Locks in that the full bucketed output can be consumed by U3's duckdb path (a seam a single-file fixture cannot test)."""
    from m3_panel.panel import _load_person_works

    data_root = tmp_path / "derived"
    _write_bucketed(data_root, "works_affil", [
        {"work_id": "W1", "author_id": "A1", "institution_id": "I1", "raw_affiliation_strings": ["Econ"]},
        {"work_id": "W2", "author_id": "A1", "institution_id": "I1", "raw_affiliation_strings": ["Econ"]},
        {"work_id": "W3", "author_id": "A2", "institution_id": "I1", "raw_affiliation_strings": ["Econ"]},
    ])
    _write_bucketed(data_root, "authorship_edges", [
        {"work_id": "W1", "author_id": "A1", "publication_year": 2016},
        {"work_id": "W2", "author_id": "A1", "publication_year": 2017},
        {"work_id": "W3", "author_id": "A2", "publication_year": 2018},
    ])
    rows = _load_person_works(data_root, person_map={"A1": "P_A1", "A2": "P_A2"})
    by_person = {}
    for r in rows:
        by_person.setdefault(r["person_id"], set()).add(r["work_id"])
    assert by_person == {"P_A1": {"W1", "W2"}, "P_A2": {"W3"}}, (
        "The bucketed layout must join and fold people correctly via read_derived_arrow(concat)+duckdb (the crux of the full-scale layout)"
    )


def test_zero_byte_works_affil_exits_2_not_arrow_crash(tmp_path):
    """Hardening: works_affil is a 0-byte (corrupt parquet) file while econ/registry are complete -> clean sys.exit(2),
    no ArrowInvalid traceback. _assert_upstream_present must fail loudly when reading the schema, just like the existing schema check."""
    from m3_panel.panel import build_panel

    data_root = tmp_path / "derived"
    _touch_upstream(data_root)  # All 6 tables written as 0-byte placeholders (incl. works_affil = 0-byte corrupt parquet)
    with pytest.raises(SystemExit) as ei:
        build_panel(data_root, tmp_path / "out",
                    econ_dept_ids={"I56590836"}, registry_by_id=_GOOD_REG)
    assert ei.value.code == 2













# ──────────────────────────────────────────────────────────────────────────
# Narrow fixes F1/F2/F3 after the first real-data run (the real output was independently recomputed and is intact)
# ──────────────────────────────────────────────────────────────────────────
def test_cmap_provenance_claims_rows_but_no_part_halts(tmp_path):
    """F1 (HIGH): legitimately empty != lost part. provenance claims row_count>=1 but the part is absent
    = corrupt upstream, must HALT (silently accepting it -> all redirects lost = the revival path of the Yves Zenou 16-ID problem).
    Only row_count==0 is legitimately empty (real U1 provenance carries this field)."""
    from m3_panel.panel import _assert_upstream_present, _upstream_content_hash

    data_root = _touch_upstream(tmp_path / "dr", omit=("canonical_id_map", "works_affil"))
    _real_empty_works_affil(data_root)
    cm_dir = data_root / "derived" / "u1_edges" / "canonical_id_map"
    cm_dir.mkdir(parents=True, exist_ok=True)
    (cm_dir / "provenance.json").write_text(
        '{"row_count": 1, "table": "canonical_id_map"}')

    with pytest.raises(SystemExit):
        _assert_upstream_present(data_root, econ_dept_ids={"I1"},
                                 registry_by_id={"I1": {}})
    with pytest.raises(Exception):
        _upstream_content_hash(data_root, "canonical_id_map")


def test_null_author_rows_counted_not_swallowed(tmp_path):
    """F2 (and the sentinel check): author_id=NULL rows (3,116,514 rows in the real data) are swallowed by SQL three-valued logic:
    they cannot enter via IN to be kept, nor via NOT IN to be orphans = a black hole in the books. The behaviour itself is right (NULL maps to no person),
    but the audit accounting needs a category: write u3_null_author_rows_count.csv, with a three-way conservation."""
    from m3_panel.panel import _load_person_works

    data_root = tmp_path
    out_dir = tmp_path / "out"
    _write_real(data_root, "works_affil", [
        {"work_id": "W1", "author_id": "A1", "institution_id": "I1",
         "raw_affiliation_strings": ["x"]},
        {"work_id": "W2", "author_id": None, "institution_id": "I1",
         "raw_affiliation_strings": ["x"]},   # NULL author: the three-valued-logic black-hole row
        {"work_id": "W3", "author_id": "A9", "institution_id": "I1",
         "raw_affiliation_strings": ["x"]},   # Orphan
    ])
    _write_real(data_root, "authorship_edges", [
        {"work_id": "W1", "author_id": "A1", "publication_year": 2010},
    ])
    rows = _load_person_works(data_root, person_map={"A1": "P1"}, out_dir=out_dir)
    assert {r["person_id"] for r in rows} == {"P1"}

    import csv
    cpath = out_dir / "_reports" / "u3_null_author_rows_count.csv"
    assert cpath.exists(), "NULL-author rows must have an accounting category (not silently swallowed)"
    with cpath.open() as f:
        rec = list(csv.DictReader(f))[0]
    assert int(rec["n_null_author_rows"]) == 1  # kept 1 + orphan 1 + null 1 = 3 conserved


def test_reports_dir_cleared_on_rebuild_kept_on_skip(tmp_path):
    """F3: _reports files left over from an old run (failed / pre-fix) pollute this run's audit
    (seen on real data: the u3_missing_year.csv left by a HALT run is easily misread as corrupt rows in this run)
    -> a true rebuild clears _reports first; a resume-skip is not a rebuild and leaves the reports alone."""
    out_dir = tmp_path / "out"
    rep = out_dir / "_reports"
    rep.mkdir(parents=True)
    (rep / "u3_missing_year.csv").write_text("stale,garbage\n")

    _run_zenou(tmp_path / "d", out_dir)
    assert not (rep / "u3_missing_year.csv").exists(), "A true rebuild must clear old leftovers (F3)"

    (rep / "later_note.csv").write_text("post-build note\n")
    r = _run_zenou(tmp_path / "d", out_dir, resume=True)
    assert r["status"] == "skipped"
    assert (rep / "later_note.csv").exists(), "skip is not a rebuild; _reports is untouched"


# ──────────────────────────────────────────────────────────────────────────
# Review fixes A9 + A16 (u3_panel)
# Neither touches the identification definition: pure resume tracking (A9) + affil_timeline PK uniqueness guard (A16).
# ──────────────────────────────────────────────────────────────────────────
def _write_works(data_root, rows):
    """Write the u1_edges/works arbitration soft source (work_id, publication_year) as a single-file parquet.

    works = null-year arbitration table (_load_person_works uses it to decide "legitimately no year: drop" vs "edge lacks year: HALT").
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    wdir = data_root / "derived" / "u1_edges" / "works"
    wdir.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({
        "work_id": pa.array([r["work_id"] for r in rows], type=pa.string()),
        "publication_year": pa.array([r["publication_year"] for r in rows], type=pa.int16()),
    }), str(wdir / "data.parquet"))


def test_a9_resume_rebuilds_on_works_arbitration_change(tmp_path):
    """A9 (red test): the works table used for null-year arbitration must be part of the resume upstream hash. Changing works content ->
    resume must rebuild, not return a stale panel arbitrated by the OLD works just because the 6 table shas are unchanged.
    Before the fix: works untracked -> silently skipped (RED). After: works enters up_hashes -> rebuild (GREEN)."""
    from m3_panel.panel import build_panel

    econ, reg = _lay_zenou(tmp_path / "d")
    _write_works(tmp_path / "d", [{"work_id": "W_arb", "publication_year": 2020}])
    r1 = build_panel(tmp_path / "d", tmp_path / "out", econ_dept_ids=econ, registry_by_id=reg)
    assert r1["status"] == "built"
    # Change works content (new sha) -> resume must not skip
    _write_works(tmp_path / "d", [{"work_id": "W_arb", "publication_year": 1999}])
    r2 = build_panel(tmp_path / "d", tmp_path / "out", econ_dept_ids=econ,
                     registry_by_id=reg, resume=True)
    assert r2["status"] == "built", "Changing works → resume should rebuild (works is part of up_hashes)"


def test_a9_works_hash_in_manifest_and_provenance_merkle(tmp_path):
    """A9 (red test): the works content_hash must enter manifest.upstream_hashes + the provenance merkle
    (consumed but untracked = provenance claims to lock the source snapshot while missing the works actually read)."""
    import hashlib
    import json as _json
    from m3_panel.panel import build_panel

    econ, reg = _lay_zenou(tmp_path / "d")
    _write_works(tmp_path / "d", [{"work_id": "W_arb", "publication_year": 2020}])
    build_panel(tmp_path / "d", tmp_path / "out", econ_dept_ids=econ, registry_by_id=reg)

    man = _json.loads((tmp_path / "out" / "_frozen" / "manifest.json").read_text("utf-8"))
    assert "works" in man["upstream_hashes"], "works must be in the resume anchor upstream_hashes"
    # provenance merkle = sha256(json.dumps(upstream_hashes, sort_keys=True)) -> including works covers it
    header = _json.loads(
        (tmp_path / "out" / "_frozen" / "manifest_header.json").read_text("utf-8"))
    expected_merkle = hashlib.sha256(
        _json.dumps(man["upstream_hashes"], sort_keys=True).encode("utf-8")).hexdigest()
    assert header["source_snapshot_merkle"] == expected_merkle, "merkle must be derived from up_hashes that include works"


def test_a9_works_absent_is_stable_sentinel_resume_still_skips(tmp_path):
    """A9 guard: works is a soft arbitration source (may be absent); absence must give a deterministic sentinel (no FileNotFoundError),
    and with works absent in both runs nothing changes -> resume still skips correctly (the sentinel is stable; the fix must not treat absence as a change)."""
    from m3_panel.panel import build_panel

    econ, reg = _lay_zenou(tmp_path / "d")  # Do not write works -> absent
    build_panel(tmp_path / "d", tmp_path / "out", econ_dept_ids=econ, registry_by_id=reg)
    again = build_panel(tmp_path / "d", tmp_path / "out", econ_dept_ids=econ,
                        registry_by_id=reg, resume=True)
    assert again["status"] == "skipped", "works absent and unchanged → resume still skips (sentinel stable)"


def test_a16_byte_identical_dup_dedup_not_halt():
    """A16: byte-identical rows (all columns equal) that collide on the PK = lossless duplicates
    (measured: all 9 columns identical; modal/vote counts do not change at all after dedup)
    -> no longer HALT; fold them into 1 row and return it. This test is the deliberate reversal of the old
    test_a16_affil_timeline_duplicate_pk_halts. The guard is not weakened: real collisions that are not identical still HALT (see next test)."""
    from m3_panel.panel import _reconcile_panel

    pw = [{"person_id": "P1", "publication_year": 2016, "work_id": "W1"}]
    panel = [{"person_id": "P1", "year": 2016, "primary_affil_id": "AFFIL_NONE"}]
    dup = {"person_id": "P1", "year": 2016, "work_id": "W1",
           "raw_inst_id": "I_M", "raw_affil_slot": 0}
    tl = [dict(dup), dict(dup)]  # Two identical 5-PK rows (over-merge double-counting source, byte-identical)
    deduped = _reconcile_panel(panel, tl, {"P1"}, pw)  # Does not raise
    assert deduped == [dup], "Byte-identical duplicates must collapse to exactly 1 row (lossless dedup)"


def test_a16_true_collision_still_halts():
    """A16 guard not weakened: same 5-PK but some non-PK column differs (= a real collision that is not byte-identical) -> dedup cannot fold it
    -> HALT exit(2) as before. Rule: after dedup the PK must be unique, otherwise still HALT."""
    from m3_panel.panel import _reconcile_panel

    pw = [{"person_id": "P1", "publication_year": 2016, "work_id": "W1"}]
    panel = [{"person_id": "P1", "year": 2016, "primary_affil_id": "AFFIL_NONE"}]
    base = {"person_id": "P1", "year": 2016, "work_id": "W1",
            "raw_inst_id": "I_M", "raw_affil_slot": 0}
    tl = [{**base, "canonical_affil_id": "I_M"},
          {**base, "canonical_affil_id": "I_OTHER"}]  # Same 5-PK, non-PK column differs -> real collision
    with pytest.raises(SystemExit) as ei:
        _reconcile_panel(panel, tl, {"P1"}, pw)
    assert ei.value.code == 2


def test_a16_collision_report_written(tmp_path):
    """A16 is not silent: when folding byte-identical rows, the collision detail must be written to
    _reports/u3_affil_timeline_pk_collisions.csv (the over-merge signal goes into the report, not lost)."""
    import csv
    from m3_panel.panel import _reconcile_panel

    pw = [{"person_id": "P1", "publication_year": 2016, "work_id": "W1"}]
    panel = [{"person_id": "P1", "year": 2016, "primary_affil_id": "AFFIL_NONE"}]
    dup = {"person_id": "P1", "year": 2016, "work_id": "W1",
           "raw_inst_id": "I_M", "raw_affil_slot": 0}
    tl = [dict(dup), dict(dup), dict(dup)]  # 3 identical rows -> 1 group, 2 rows folded away
    _reconcile_panel(panel, tl, {"P1"}, pw, out_dir=tmp_path)
    rep = tmp_path / "_reports" / "u3_affil_timeline_pk_collisions.csv"
    assert rep.exists(), "The collision detail report must be written (no silent dedup)"
    rows = list(csv.DictReader(rep.open(encoding="utf-8")))
    assert len(rows) == 1
    assert rows[0]["person_id"] == "P1" and rows[0]["work_id"] == "W1"
    assert rows[0]["n_rows_before_dedup"] == "3"
    assert rows[0]["n_rows_after_dedup"] == "1"


def test_a16_end_to_end_overmerge_dedup_invariant(tmp_path):
    """A16 end to end, lossless / invariant (TDD stress fixture): the same real person with two U2 author_ids
    (A_Z1/A_Z2->P_Z) co-signs the same paper W16f at the same institution -> before the fix A16 HALTs; after the fix the on-disk PK is unique, and
    panel + affil_timeline are byte-for-byte equal to the "single-id signature" control (dedup = lossless fold, results do not change at all)."""
    import hashlib
    from m3_panel.panel import build_panel

    # Control: W16f signed by A_Z1 only (no duplicate)
    econ, reg = _lay_zenou(tmp_path / "d_single")
    _append_w16f(tmp_path / "d_single", authors=["A_Z1"])
    build_panel(tmp_path / "d_single", tmp_path / "out_single",
                econ_dept_ids=econ, registry_by_id=reg)
    # Stress group: W16f co-signed by A_Z1+A_Z2 at the same institution -> after folding to the person, byte-identical rows collide on the PK
    econ2, reg2 = _lay_zenou(tmp_path / "d_dup")
    _append_w16f(tmp_path / "d_dup", authors=["A_Z1", "A_Z2"])
    r = build_panel(tmp_path / "d_dup", tmp_path / "out_dup",
                    econ_dept_ids=econ2, registry_by_id=reg2)
    assert r["status"] == "built"

    for name in ("panel", "affil_timeline"):
        a = (tmp_path / "out_single" / name / "data.parquet").read_bytes()
        b = (tmp_path / "out_dup" / name / "data.parquet").read_bytes()
        assert hashlib.sha256(a).hexdigest() == hashlib.sha256(b).hexdigest(), (
            f"{name}: after dedup, dual-id co-signing must be byte-identical to single-id signing (lossless, result unchanged)")
    # PK unique (re-checked after writing) + collision report present
    tl = _read_output(tmp_path / "out_dup", "affil_timeline")
    pks = [(x["person_id"], x["year"], x["work_id"], x["raw_inst_id"], x["raw_affil_slot"])
           for x in tl]
    assert len(pks) == len(set(pks))
    assert (tmp_path / "out_dup" / "_reports" / "u3_affil_timeline_pk_collisions.csv").exists()
    # Yves Zenou golden-test shape unchanged: 2016 mode is still Monash
    panel = _read_output(tmp_path / "out_dup", "panel")
    p2016 = next(x for x in panel if x["person_id"] == "P_Z" and x["year"] == 2016)
    assert p2016["primary_affil_id"] == _MONASH


def _append_w16f(data_root, *, authors):
    """Append W16f@Monash (signed by authors) to the laid-out Yves Zenou fixture and rewrite the works_affil +
    authorship_edges tables (fixture-level helper for the A16 end-to-end comparison)."""
    import pyarrow.parquet as pq

    for table, extra in [
        ("works_affil", [{"work_id": "W16f", "author_id": a, "institution_id": _MONASH,
                          "raw_affiliation_strings": ["Monash University"]} for a in authors]),
        ("authorship_edges", [{"work_id": "W16f", "author_id": a, "publication_year": 2016}
                              for a in authors]),
    ]:
        path = data_root / "derived" / "u1_edges" / table / "data.parquet"
        rows = pq.read_table(str(path)).to_pylist() + extra
        _write_real(data_root, table, rows)


def test_a16_affil_timeline_unique_pk_passes():
    """A16 reverse guard: an affil_timeline whose 5-PK is unique (same work, different raw_inst_id) is not wrongly HALTed."""
    from m3_panel.panel import _reconcile_panel

    pw = [{"person_id": "P1", "publication_year": 2016, "work_id": "W1"}]
    panel = [{"person_id": "P1", "year": 2016, "primary_affil_id": "AFFIL_NONE"}]
    tl = [
        {"person_id": "P1", "year": 2016, "work_id": "W1",
         "raw_inst_id": "I_M", "raw_affil_slot": 0},
        {"person_id": "P1", "year": 2016, "work_id": "W1",
         "raw_inst_id": "I_N", "raw_affil_slot": 0},  # Same work, different raw_inst -> different PK
    ]
    _reconcile_panel(panel, tl, {"P1"}, pw)  # Does not raise
