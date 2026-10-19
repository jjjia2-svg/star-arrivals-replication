"""M5-T3 write_paper_contrib — deterministic 256-bucket write + back-edge isolation.

In plain words: hash the paper_contrib rows spread by M5-T1 into 256 buckets by primary key and write them; two runs
on the same input are byte-equal; rows with a duplicate primary key are written once. Also guards that "the code
segments that compute the FWCI denominator never touch the star co-author column"
(isc#2 back-edge isolation, which keeps the regression clean).

Fixed rules (only consumed here):
  - 256-bucket HashBucketWriter (owner=U1): canonical sort + fixed parquet parameters → deterministic bytes.
  - Derived invariant: rows written = sum over works of distinct incumbent × person (a direct fidelity check on the M5-T1 row spreading).
  - isc#2 / back-edge: the FWCI/expected/winsorize sources of M5-T0/T2/T3 do not import aggregate_output
    and do not reference is_star_coauthored as a code symbol (a mention in a docstring does not count → judged by AST, not string search).
"""
import pytest


def _rows_two_works():
    """Real M5-T1 rows for two papers (no mock): W1 2 incumbents × 3 persons = 6 rows; W2 1×2 = 2 rows; 8 in total."""
    from m5_output.paper_contrib import build_paper_contrib_rows
    w1 = build_paper_contrib_rows(
        {"work_id": "W1", "author_ids": ["a_i1", "a_i2", "a_x"],
         "publication_year": 2010, "subfield_id": "2002", "fwci": 1.5},
        author_person={"a_i1": "I1", "a_i2": "I2", "a_x": "X"},
        incumbent_person_ids={"I1", "I2"},
    )
    w2 = build_paper_contrib_rows(
        {"work_id": "W2", "author_ids": ["a_i1", "a_y"],
         "publication_year": 2011, "subfield_id": "2002", "fwci": 0.8},
        author_person={"a_i1": "I1", "a_y": "Y"},
        incumbent_person_ids={"I1"},
    )
    return w1 + w2  # 6 + 2 = 8


# ---- bucket write + determinism + dedup -------------------------------------

def test_write_lands_buckets_and_commits(tmp_path):
    """Writes <out>/paper_contrib/bucket=NNN/part-*.parquet and returns a manifest (sha256 and row count per part)."""
    from m5_output.write_paper_contrib import write_paper_contrib
    res = write_paper_contrib(_rows_two_works(), tmp_path)
    parts = list((tmp_path / "paper_contrib").glob("bucket=*/part-*.parquet"))
    assert parts, "at least one bucket part should be written"
    assert res["manifest"], "a non-empty manifest should be returned"
    for m in res["manifest"]:
        assert set(m) >= {"rel_path", "sha256", "row_count"}


def test_write_is_byte_deterministic_two_runs(tmp_path):
    """Two runs on the same input → sha256 of every part equal (byte-deterministic, comparable across resumes)."""
    from m5_output.write_paper_contrib import write_paper_contrib
    r1 = write_paper_contrib(_rows_two_works(), tmp_path / "run1")
    r2 = write_paper_contrib(_rows_two_works(), tmp_path / "run2")
    sig1 = sorted((m["rel_path"], m["sha256"]) for m in r1["manifest"])
    sig2 = sorted((m["rel_path"], m["sha256"]) for m in r2["manifest"])
    assert sig1 == sig2


def test_write_dedups_within_bucket(tmp_path):
    """Rows with a duplicate primary key (work,incumbent,person) are written once (no double counting)."""
    from m5_output.write_paper_contrib import write_paper_contrib
    rows = _rows_two_works()
    res = write_paper_contrib(rows + rows, tmp_path)  # deliberately feed two copies
    assert res["n_rows"] == 8  # still 8 after dedup, not 16


# ---- derived invariant: rows = sum over works of distinct incumbent × person ----

def test_row_count_equals_incumbent_by_person(tmp_path):
    """Rows written = 6 + 2 = 8 (= sum over works of incumbents × persons, the M5-T3 invariant)."""
    from m5_output.write_paper_contrib import write_paper_contrib
    res = write_paper_contrib(_rows_two_works(), tmp_path)
    assert res["n_rows"] == 8
    assert sum(m["row_count"] for m in res["manifest"]) == 8


# ---- back-edge isolation (AST, not string search) ---------------------------

def test_fwci_baseline_node_does_not_read_isc():
    """isc#2 / back-edge: the FWCI baseline/expected/winsorize sources (M5-T0/T2) + the writer (M5-T3)
    do not import aggregate_output and do not reference is_star_coauthored as a code symbol.
    Judged by AST on real symbol references — a docstring/comment saying "does not read is_star_coauthored" is not a violation."""
    import ast
    import inspect
    from m5_output import fwci_baseline_build, fwci_raw, write_paper_contrib

    forbidden = {"aggregate_output", "is_star_coauthored"}
    for mod in (fwci_baseline_build, fwci_raw, write_paper_contrib):
        tree = ast.parse(inspect.getsource(mod))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.ImportFrom):
                for a in node.names:
                    names.add(a.name)
                    if a.asname:
                        names.add(a.asname)
        hit = forbidden & names
        assert not hit, f"{mod.__name__}: the FWCI/write path must not reference {hit} (back-edge isolation)"


# ---- Rewriting into the same directory leaves no orphan part (disk == manifest) ----

def test_rewrite_same_dir_no_orphan_parts(tmp_path):
    """Rewrite into the same out_dir (fewer rows): no orphan parts from old buckets are left → reading back everything by glob gives rows == this manifest's
    n_rows. Guards against a repeat of the silent 28,500-row loss (a downstream that trusts only glob would read ghost rows)."""
    import pyarrow.parquet as pq
    from m5_output.paper_contrib import build_paper_contrib_rows
    from m5_output.write_paper_contrib import write_paper_contrib

    write_paper_contrib(_rows_two_works(), tmp_path)  # first write: 8 rows, spread over many buckets
    small = build_paper_contrib_rows(  # second write: same directory, only the 2 rows of W2
        {"work_id": "W2", "author_ids": ["a_i1", "a_y"],
         "publication_year": 2011, "subfield_id": "2002", "fwci": 0.8},
        author_person={"a_i1": "I1", "a_y": "Y"},
        incumbent_person_ids={"I1"},
    )
    res2 = write_paper_contrib(small, tmp_path)
    parts = list((tmp_path / "paper_contrib").glob("bucket=*/part-*.parquet"))
    disk_rows = sum(pq.ParquetFile(str(p)).metadata.num_rows for p in parts)
    assert res2["n_rows"] == 2
    assert disk_rows == 2, f"orphan rows left on disk: glob={disk_rows} != manifest={res2['n_rows']}"


# ---- Same PK but conflicting payload → fail loud, not a silent drop ----------

def test_dedup_raises_on_conflicting_payload():
    """Same primary key (work,incumbent,person) but different fwci → raise with work_id; never silently erase the disagreement
    (the write is the last gate; it catches an upstream giving inconsistent fwci/isc for the same work)."""
    from m5_output.write_paper_contrib import dedup_by_pk
    base = {"work_id": "W1", "incumbent_person_id": "I1", "person_id": "P1",
            "publication_year": 2010, "frac_credit": 0.5, "fwci": 1.5,
            "is_star_coauthored": False, "subfield_id": "2002"}
    conflict = dict(base, fwci=99.0)  # same PK, different fwci
    with pytest.raises(ValueError) as ei:
        dedup_by_pk([base, conflict])
    assert "W1" in str(ei.value)


def test_dedup_silent_on_identical_duplicate():
    """Same PK and identical payload → silent idempotent dedup (current correct behaviour; the conflict check must not break it)."""
    from m5_output.write_paper_contrib import dedup_by_pk
    row = {"work_id": "W1", "incumbent_person_id": "I1", "person_id": "P1",
           "publication_year": 2010, "frac_credit": 0.5, "fwci": 1.5,
           "is_star_coauthored": False, "subfield_id": "2002"}
    assert len(dedup_by_pk([row, dict(row)])) == 1
