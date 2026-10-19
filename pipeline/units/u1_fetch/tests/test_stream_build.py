"""M1 full-scale streaming orchestration stream_build TDD red tests - three guardrails pinned down: no blow-up + efficient (parallel) + deterministic.

Why this file is separate (complementary to test_run_m1_assembly.py / test_run_m1.py):
  Those two files check the behaviour/determinism of the old path (run_slice_tables accumulates in memory first -> write_tables_bucketed writes buckets).
  This file checks the **new streaming entry run_m1_streaming**, which turns "accumulate a list, then bucket" into "route into buckets while parsing":
    ① equivalence (a refactor keeps behaviour): same fixture, old path write_tables_bucketed vs streaming n_workers=1
       -> the (rel_path, sha256) of every bucket part of every table is equal exactly. "The refactor does not change the output" is pinned as a red test.
    ② parallel = serial (parallelism does not break determinism): run_m1_streaming(n_workers=4) vs n_workers=1 -> bucket part sha exactly equal.
    ③ two-pass sha (deterministic reproduction): run with n_workers=4 twice -> sha equal.
    ④ no blow-up (streaming does not accumulate everything): the streaming path never appends all rows into one in-memory list before handing it to the writer
       - a monkeypatch counter asserts that "streaming never calls the old path's write_tables_bucketed / full materialisation".
    ⑤ HIGH-4 / canonical-before-dedup / frontier / closure item 4 / reconcile each get one check on the streaming path.

* Discipline: all fixtures/small-sample works JSON, never a real S3 download and never a real SSD write (output goes to tmp_path).
  Convention-neutral: only checks the equivalence and determinism of output shape / memory strategy / concurrency, and touches no identification placeholder.
  Parallelism uses multiprocessing (spawn-safe); in a bare environment without pyarrow -> importorskip SKIP.
"""
from __future__ import annotations

import hashlib

import pytest

pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")

from m1_ingest import run_m1 as R
from m1_ingest import stream_build as S
from identity.golden import MONASH_CANONICAL_ID
from common._redlines import RedlineUnsigned


# ---------------------------------------------------------------------------
# fixture: Monash (in the department, AU) + Stockholm (outside, SE), with refs frontier.
# Reproduces the data setup of test_run_m1_assembly so the two files cross-check the output of the same shape.
# ---------------------------------------------------------------------------
_REGISTRY = [{"openalex_id": MONASH_CANONICAL_ID, "type": "education"}]
_ECON_DEPT_IDS = {MONASH_CANONICAL_ID}

_MONASH_ID = MONASH_CANONICAL_ID
_STOCKHOLM_ID = "I_STOCKHOLM"

_TEN_TABLES = (
    "works", "authorship_edges", "refs_edges", "works_affil", "institutions",
    "authors", "work_text", "work_first_pub", "fwci_baseline_pop", "canonical_id_map",
)


def _inst(inst_id, *, country, itype="education", lineage=None):
    return {
        "id": f"https://openalex.org/{inst_id}",
        "display_name": inst_id,
        "country_code": country,
        "type": itype,
        "lineage": lineage or [f"https://openalex.org/{inst_id}"],
    }


def _au(author_id, *, institutions, raw_affil, orcid=None):
    return {
        "author": {
            "id": f"https://openalex.org/{author_id}",
            "display_name": author_id,
            "orcid": orcid,
        },
        "institutions": institutions,
        "raw_affiliation_strings": raw_affil,
    }


def _work(wid, *, year, refs=None, authorships=None, subfield="2002",
          wtype="article", title=None, inverted=None):
    w = {
        "id": f"https://openalex.org/{wid}",
        "publication_year": year,
        "type": wtype,
        "cited_by_count": 11,
        "referenced_works": [f"https://openalex.org/{r}" for r in (refs or [])],
        "primary_topic": {"subfield": {"id": f"https://openalex.org/subfields/{subfield}"}},
        "authorships": authorships or [],
    }
    if title is not None:
        w["title"] = title
    if inverted is not None:
        w["abstract_inverted_index"] = inverted
    return w


def _monash_stockholm_works():
    w_ms = _work(
        "W_MS", year=2016, refs=["W_REF"],
        title="Network spillovers in economics",
        inverted={"Network": [0], "spillovers": [1]},
        authorships=[
            _au("A5017376589",
                institutions=[_inst(_MONASH_ID, country="AU")],
                raw_affil=["Monash University, Department of Economics"],
                orcid="0000-0001-6516-0812"),
            _au("A_STK",
                institutions=[_inst(_STOCKHOLM_ID, country="SE")],
                raw_affil=["Stockholm University"]),
        ],
    )
    w_ref = _work(
        "W_REF", year=2009, title="Prior network paper",
        authorships=[_au("A_OTHER", institutions=[_inst(_STOCKHOLM_ID, country="SE")],
                         raw_affil=["Stockholm University"])],
    )
    return [w_ms], [w_ref]


def _bigger_works(n_seed_works=12):
    """Build a wider fixture: many in-department works + spread over many buckets (so parallelism really assigns different workers).

    Each seed work has one Monash author + one Stockholm coauthor; it cites one frontier.
    Work ids differ -> sha1 scatters them over many buckets, and after batching across workers they must still merge into the same bytes.
    """
    seed = []
    refz = []
    for i in range(n_seed_works):
        seed.append(_work(
            f"W{i:03d}", year=2010 + (i % 7), refs=[f"R{i:03d}"],
            title=f"paper {i}",
            inverted={"alpha": [0], "beta": [1]},
            authorships=[
                _au(f"AM{i:03d}",
                    institutions=[_inst(_MONASH_ID, country="AU")],
                    raw_affil=[f"Monash University, Department of Economics #{i}"]),
                _au(f"AS{i:03d}",
                    institutions=[_inst(_STOCKHOLM_ID, country="SE")],
                    raw_affil=[f"Stockholm University #{i}"]),
            ],
        ))
        refz.append(_work(f"R{i:03d}", year=2000 + (i % 5),
                          title=f"ref {i}",
                          authorships=[_au(f"AR{i:03d}",
                                           institutions=[_inst(_STOCKHOLM_ID, country="SE")],
                                           raw_affil=[f"Stockholm University ref {i}"])]))
    return seed, refz


def _sig(manifest_for_table):
    """Compress the part manifest of one table into an ordered signature [(rel_path, sha256), ...] (compared after sorting)."""
    return sorted((p["rel_path"], p["sha256"]) for p in manifest_for_table)


def _manifest_works(n):
    """Top-level manifest fixture (observed shape): the sum of the works entity record_count == n (A2 external true-value anchor)."""
    return {
        "date": "2026-06-26",
        "format": "jsonl",
        "meta": {"record_count": n, "content_length": 1},
        "entities": [{
            "entity": "works",
            "record_count": n,
            "content_length": 1,
            "files": [{
                "url": "s3://openalex/data/jsonl/works/updated_date=2016-01-01/part_0000.gz",
                "meta": {"content_length": 1, "record_count": n},
            }],
        }],
    }


def _n_monash_works(n):
    """n distinct in-department Monash works (all seed-related, no refs -> no frontier/pass-C): kept==seen==n.

    Feeds the A2 silent-data-loss injection test: the manifest says n works, only n-D are fed in -> the actual scan seen shrinks -> the reconciliation must be out of balance.
    """
    return [
        _work(
            f"WD{i:03d}", year=2016, refs=[],
            title=f"drop-fixture {i}",
            authorships=[_au(f"AM{i:03d}",
                             institutions=[_inst(_MONASH_ID, country="AU")],
                             raw_affil=[f"Monash University, Department of Economics {i}"])],
        )
        for i in range(n)
    ]


# ===========================================================================
# ① equivalence: old path (run_slice_tables + write_tables_bucketed) vs streaming n_workers=1
#    -> the (rel_path, sha256) of every bucket part of every table is exactly equal (a refactor keeps behaviour).
# ===========================================================================
def test_streaming_serial_byte_equals_old_materialized_path(tmp_path):
    seed, refz = _monash_stockholm_works()

    # Old path: accumulate the 10 tables in memory first, then write them bucketed.
    tables = R.run_slice_tables(seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS)
    old_mf = R.write_tables_bucketed(tables, tmp_path / "old")

    # New path: streaming (route into buckets while parsing), n_workers=1.
    new_mf = S.run_m1_streaming(
        seed, refz,
        registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
        out_root=tmp_path / "new",
        n_workers=1,
    )

    assert set(new_mf.keys()) == set(_TEN_TABLES)
    for name in _TEN_TABLES:
        assert _sig(old_mf[name]) == _sig(new_mf[name]), (
            f"Table {name}: streaming n_workers=1 differs from the old path in bucketed part sha (the refactor broke behaviour)"
        )


def test_streaming_serial_byte_equals_old_on_bigger_fixture(tmp_path):
    seed, refz = _bigger_works()
    tables = R.run_slice_tables(seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS)
    old_mf = R.write_tables_bucketed(tables, tmp_path / "old")
    new_mf = S.run_m1_streaming(
        seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
        out_root=tmp_path / "new", n_workers=1,
    )
    for name in _TEN_TABLES:
        assert _sig(old_mf[name]) == _sig(new_mf[name]), f"Table {name}: large-fixture equivalence broken"


def _shared_author_conflicting_names_works():
    """Adversarial fixture: the same author A_SHARED carries **different display_name** values in **different works**, and these works
    are split consecutively into **different worker batches** -> triggers the order dependence of AuthorTable's 'first display_name seen wins'.

    This is the only point under streaming parallelism that could differ from serial byte for byte. This fixture pins it as a red test:
    A_SHARED is an in-department seed (Monash); W0..W7 each give A_SHARED a different display_name (Name0..Name7);
    serial processes in global order -> 'Name0' arrives first and wins; parallel must reproduce the same order -> also 'Name0'.
    """
    seed = []
    for i in range(8):
        seed.append(_work(
            f"WC{i:03d}", year=2010 + i, refs=[],
            title=f"c{i}",
            authorships=[
                {
                    "author": {
                        "id": "https://openalex.org/A_SHARED",
                        "display_name": f"Name{i}",   # same person, different names -> order dependence
                        "orcid": None,
                    },
                    "institutions": [_inst(_MONASH_ID, country="AU")],
                    "raw_affiliation_strings": [f"Monash University, Department of Economics c{i}"],
                },
            ],
        ))
    return seed, []


# ===========================================================================
# ② parallel = serial: n_workers=4 vs n_workers=1 -> bucket part sha exactly equal (parallelism does not break determinism).
# ===========================================================================
def test_streaming_parallel_byte_equals_serial(tmp_path):
    seed, refz = _bigger_works()
    mf1 = S.run_m1_streaming(
        seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
        out_root=tmp_path / "w1", n_workers=1,
    )
    mf4 = S.run_m1_streaming(
        seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
        out_root=tmp_path / "w4", n_workers=4,
    )
    for name in _TEN_TABLES:
        assert _sig(mf1[name]) == _sig(mf4[name]), (
            f"Table {name}: parallel(4) differs from serial(1) in part sha (parallelism broke determinism)"
        )


def test_streaming_parallel_equals_serial_on_shared_author_name_conflict(tmp_path):
    """Adversarial (the one dangerous point of streaming parallelism): the same person carries different display_name across workers -> parallel must match serial byte for byte.

    Serial global order: 'Name0' arrives first and wins; parallel consecutive batching + replay merged in worker order -> reproduces the same order, also 'Name0'.
    If the parallel merge of authors depended on the worker completion order, this test would go red."""
    seed, refz = _shared_author_conflicting_names_works()
    mf1 = S.run_m1_streaming(seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
                             out_root=tmp_path / "w1", n_workers=1)
    mf4 = S.run_m1_streaming(seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
                             out_root=tmp_path / "w4", n_workers=4)
    for name in _TEN_TABLES:
        assert _sig(mf1[name]) == _sig(mf4[name]), (
            f"Table {name}: parallel != serial when the same person's names conflict across workers (display_name order dependence broke determinism)"
        )
    # Serial itself must also reproduce the old path (global order, Name0 wins).
    tables = R.run_slice_tables(seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS)
    old_mf = R.write_tables_bucketed(tables, tmp_path / "old")
    for name in _TEN_TABLES:
        assert _sig(old_mf[name]) == _sig(mf1[name]), f"Table {name}: serial != old path under name conflicts"
    # Pinned explicitly: the display_name of A_SHARED in the authors table == 'Name0' (the first in global order wins).
    a_rows = _read_table_rows(tmp_path / "w4", "authors")
    shared = [r for r in a_rows if r["author_id"] == "A_SHARED"]
    assert shared and shared[0]["display_name"] == "Name0", "The globally first-seen display_name should be Name0"


# ===========================================================================
# ③ two-pass sha: run in parallel twice -> byte-level sha equal (deterministic reproduction).
# ===========================================================================
def test_streaming_parallel_two_runs_identical(tmp_path):
    seed, refz = _bigger_works()
    a = S.run_m1_streaming(seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
                           out_root=tmp_path / "a", n_workers=4)
    b = S.run_m1_streaming(seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
                           out_root=tmp_path / "b", n_workers=4)
    for name in _TEN_TABLES:
        assert _sig(a[name]) == _sig(b[name]), f"Table {name}: sha differs between two parallel runs (non-deterministic)"


def test_streaming_serial_two_runs_identical(tmp_path):
    seed, refz = _bigger_works()
    a = S.run_m1_streaming(seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
                           out_root=tmp_path / "a", n_workers=1)
    b = S.run_m1_streaming(seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
                           out_root=tmp_path / "b", n_workers=1)
    for name in _TEN_TABLES:
        assert _sig(a[name]) == _sig(b[name]), f"Table {name}: sha differs between two serial runs (non-deterministic)"


# ===========================================================================
# ④ no blow-up (streaming does not accumulate everything): the streaming path never calls the old path's full materialisation write_tables_bucketed,
#    and rows go straight into HashBucketWriter (flushed when a bucket is full) - memory is bounded only by the bucket buffers and does not grow linearly with total rows.
# ===========================================================================
def test_streaming_never_calls_full_materialize(monkeypatch, tmp_path):
    """The streaming entry never takes the old path run_slice_tables / write_tables_bucketed (that accumulates all rows in a list first)."""
    seed, refz = _bigger_works()

    calls = {"run_slice_tables": 0, "write_tables_bucketed": 0}
    orig_rst = R.run_slice_tables
    orig_wtb = R.write_tables_bucketed

    def _spy_rst(*a, **k):
        calls["run_slice_tables"] += 1
        return orig_rst(*a, **k)

    def _spy_wtb(*a, **k):
        calls["write_tables_bucketed"] += 1
        return orig_wtb(*a, **k)

    monkeypatch.setattr(R, "run_slice_tables", _spy_rst)
    monkeypatch.setattr(R, "write_tables_bucketed", _spy_wtb)

    S.run_m1_streaming(
        seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
        out_root=tmp_path / "s", n_workers=1,
    )
    assert calls["run_slice_tables"] == 0, "Streaming must not call the old path run_slice_tables (which first accumulates all rows in a list)"
    assert calls["write_tables_bucketed"] == 0, "Streaming must not call the old path write_tables_bucketed (full materialization)"


def test_streaming_routes_rows_into_buckets_not_one_list(monkeypatch, tmp_path):
    """Streaming: as each work flows by, writer.add() routes it into a bucket, and a full bucket is **flushed immediately** (no in-memory list held back).

    Uses a tiny bucket_row_cap=1 + a spy on HashBucketWriter.flush_shard: if it were "accumulate everything in a list, then pour it in at once",
    flush_shard would be called only once per bucket at the end (= number of buckets); with true incremental flushing, a full bucket is flushed at once -> the number of flush_shard calls
    far exceeds the number of buckets (≈ rows written). Asserting flush count >> bucket count = rows really are flushed as they stream, not held in one in-memory list.
    """
    from m1_ingest import hash_bucket_writer as hbw

    flush_count = {"n": 0}
    orig_flush = hbw.HashBucketWriter.flush_shard

    def _spy_flush(self, bucket):
        if self._buffers.get(bucket):   # Count only flushes with content (empty flushes do not count)
            flush_count["n"] += 1
        return orig_flush(self, bucket)

    monkeypatch.setattr(hbw.HashBucketWriter, "flush_shard", _spy_flush)

    seed, refz = _bigger_works(n_seed_works=12)
    mf = S.run_m1_streaming(
        seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
        out_root=tmp_path / "s", n_workers=1,
        n_buckets=4, bucket_row_cap=1,   # cap=1 -> flush as soon as a bucket is full (=1 row), forcing incremental flushing
    )
    # Final authorship_edges row count = 12 works × 2 authors = 24 (HIGH-4).
    edge_rows = sum(p["row_count"] for p in mf["authorship_edges"])
    assert edge_rows == 24, "HIGH-4: 12 works × 2 authors = 24 edges"
    # cap=1 incremental flushing: the flush count should be >> bucket count (4) - if everything were accumulated in a list first and then poured in, it would be only ~bucket-count times.
    # Each of the 5 local streaming-table writers flushes at cap=1, so the total flush count far exceeds 4.
    assert flush_count["n"] >= 24, (
        f"cap=1 should trigger many incremental flushes (rows are not held in a memory list); measured flush={flush_count['n']} times"
    )


def test_streaming_addrow_call_count_bounded_by_rows_not_buffered(monkeypatch, tmp_path):
    """Mock HashBucketWriter.add: the number of add calls under streaming == the sum of the real row counts of all tables (one add per row,
    routed into buckets as they stream), not "append to a list first, then pour in at once". Proves the memory strategy is incremental and does not grow with a materialised list."""
    from m1_ingest import hash_bucket_writer as hbw

    seed, refz = _bigger_works(n_seed_works=10)

    add_count = {"n": 0}
    orig_add = hbw.HashBucketWriter.add

    def _counting_add(self, row):
        add_count["n"] += 1
        return orig_add(self, row)

    monkeypatch.setattr(hbw.HashBucketWriter, "add", _counting_add)

    mf = S.run_m1_streaming(
        seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
        out_root=tmp_path / "s", n_workers=1,
    )
    total_rows = sum(sum(p["row_count"] for p in mf[name]) for name in _TEN_TABLES)
    # Each row is add-ed exactly once (streaming: one add per row); there is no extra/missing add caused by "accumulate everything in a list, then pour in in batches".
    assert add_count["n"] == total_rows, (
        f"Streaming add call count {add_count['n']} != total rows written {total_rows} (memory strategy not purely incremental?)"
    )


# ===========================================================================
# ⑤ One check each for the convention guardrails on the streaming path (HIGH-4 / canonical-before-dedup / frontier / closure item 4 / reconcile).
# ===========================================================================
def _read_table_rows(out_root, name):
    """Read back all bucket parts of a table -> list[dict] (all parts merged)."""
    rows = []
    base = out_root / name
    for f in sorted(base.rglob("*.parquet")):
        rows.extend(pq.read_table(str(f)).to_pylist())
    return rows


def test_streaming_high4_foreign_coauthor_edge_kept(tmp_path):
    """HIGH-4: the edges of a non-seed Stockholm coauthor A_STK inside a seed work are also written to authorship_edges."""
    seed, refz = _monash_stockholm_works()
    out = tmp_path / "s"
    S.run_m1_streaming(seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
                       out_root=out, n_workers=1)
    edge_authors = {r["author_id"] for r in _read_table_rows(out, "authorship_edges")}
    assert "A5017376589" in edge_authors
    assert "A_STK" in edge_authors, "Losing non-seed foreign collaborator edges = the HIGH-4 killer regression (streaming)"


def test_streaming_frontier_refs_work_landed(tmp_path):
    """pass-C backfill: the cited W_REF is added to the works table (frontier fully hit, nothing dangling)."""
    seed, refz = _monash_stockholm_works()
    out = tmp_path / "s"
    S.run_m1_streaming(seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
                       out_root=out, n_workers=1)
    work_ids = {r["work_id"] for r in _read_table_rows(out, "works")}
    assert "W_MS" in work_ids
    assert "W_REF" in work_ids, "The frontier work should be added back to the works table by pass-C (streaming)"


def test_streaming_canonical_applied_before_write_merges_split_ids(tmp_path):
    """The same person merged A_OLD->A_NEW -> after writing, authors has only one row A_NEW (canonical comes before dedup, streaming).
    first_pub takes the min after folding: the first publication year of A_NEW = 2010 (the earlier paper), not 2012."""
    w = _work("W1", year=2010, authorships=[
        _au("A_OLD", institutions=[_inst(_MONASH_ID, country="AU")], raw_affil=["Econ"]),
    ])
    w2 = _work("W2", year=2012, authorships=[
        _au("A_NEW", institutions=[_inst(_MONASH_ID, country="AU")], raw_affil=["Econ"]),
    ])
    merged_rows = [{"raw_id": "A_OLD", "canonical_id": "A_NEW"}]
    out = tmp_path / "s"
    S.run_m1_streaming(
        [w, w2], [],
        registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
        out_root=out, n_workers=1,
        author_merged_rows=merged_rows,
    )
    author_ids = {r["author_id"] for r in _read_table_rows(out, "authors")}
    assert "A_NEW" in author_ids
    assert "A_OLD" not in author_ids, "A_OLD should already be folded into A_NEW (canonical before dedup, streaming)"
    fp = {r["author_id"]: r["first_pub_year"] for r in _read_table_rows(out, "work_first_pub")}
    assert fp["A_NEW"] == 2010, "After folding, first_pub takes the min (streaming)"


def test_streaming_canonical_space_guard_fires_on_split(tmp_path, monkeypatch):
    """Closure item 4: if the foreign keys split on the streaming path -> exit(EXIT_CANONICAL_SPACE_SPLIT=22).
    Uses monkeypatch to make the institutions table be written empty (creating affil.institution_id ⊄ institutions)."""
    from identity.exit_codes import EXIT_CANONICAL_SPACE_SPLIT

    seed, refz = _monash_stockholm_works()
    # Tamper: force the streaming guard to meet an inconsistency of "edge author not in authors" -> it blows up through the internal distinct-set version of the guard.
    # An injection hook lets streaming see the split space during the closing guard.
    monkeypatch.setattr(S, "_FORCE_CANONICAL_SPLIT_FOR_TEST", True, raising=False)
    with pytest.raises(SystemExit) as ei:
        S.run_m1_streaming(seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
                           out_root=tmp_path / "s", n_workers=1)
    assert ei.value.code == EXIT_CANONICAL_SPACE_SPLIT


def test_streaming_full_topology_fp_superset_does_not_halt(tmp_path):
    """Full topology: first_pub contains non-seed authors (pass-A full history #9) -> fp_authors ⊋ authors.
    This is by design (not a bug); the closure item 4 guard must not halt because of it.
    Reproduces a BLOCKER (audit): the old guard checked fp_authors ⊆ authors, which is necessarily false at full scale -> wrongly exit(22) and not one row could be written."""
    w_seed = _work("W_SEED", year=2016, authorships=[
        _au("A_MONASH", institutions=[_inst(_MONASH_ID, country="AU")],
            raw_affil=["Monash University, Department of Economics"]),
    ])
    # Unrelated non-seed work: an out-of-department author, not cited by a seed -> pass-A feeds first_pub but it does not enter authors.
    w_outside = _work("W_OUT", year=2001, authorships=[
        _au("A_OUTSIDER", institutions=[_inst(_STOCKHOLM_ID, country="SE")],
            raw_affil=["Stockholm University"]),
    ])
    out = tmp_path / "s"
    S.run_m1_streaming(
        [w_seed, w_outside], [],
        registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
        out_root=out, n_workers=1, run_pass_c=False, run_space_guard=True,
    )
    fp_authors = {r["author_id"] for r in _read_table_rows(out, "work_first_pub")}
    author_ids = {r["author_id"] for r in _read_table_rows(out, "authors")}
    assert "A_OUTSIDER" in fp_authors, "A non-seed author should have the full first-publication year"
    assert "A_OUTSIDER" not in author_ids, "A non-seed author should not enter the main authors table"
    assert "A_MONASH" in author_ids


def test_passb_local_skips_seen_when_collect_seen_false(tmp_path):
    """S3 (memory): when reconcile is off, seen is not accumulated (saves ~6GB of IPC/pickle at full scale); kept still works as usual (pass-C frontier needs it).
    New behaviour: _run_passb_local gains a collect_seen switch; run_m1_streaming passes collect_seen=bool(reconcile).
    Since C20, seen goes to spill run files - when off, the assertion changes to "no spill is produced"
    (same meaning as the old assertion `seen_work_ids == set()`: off = not one seen is recorded)."""
    w = _work("W1", year=2016, authorships=[
        _au("A_M", institutions=[_inst(_MONASH_ID, country="AU")], raw_affil=["Econ"]),
    ])
    lr = S._run_passb_local(
        [w],
        seed_authors={"A_M"}, seed_work_ids={"W1"},
        author_cmap_pair={}, author_cmap_flat={}, inst_cmap_flat={},
        local_dir=str(tmp_path / "w0"),
        collect_seen=False,
    )
    assert lr.seen_spill_paths == [], "collect_seen=False → seen is not accumulated (no spill either)"
    assert not (tmp_path / "w0" / "_seen_runs").exists(), "When off, not even the spill directory is created"
    assert "W1" in lr.kept_work_ids, "kept is unaffected (pass-C frontier still needs it)"


def test_streaming_reconcile_balanced_with_explicit_tolerance(tmp_path):
    """Streaming reconcile: explicit diff_tolerance=0 + external manifest anchor -> balanced, writes reconcile_tally.json."""
    seed, refz = _monash_stockholm_works()
    out = tmp_path / "s"
    S.run_m1_streaming(
        seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
        out_root=out, n_workers=1,
        reconcile=True, reconcile_diff_tolerance=0,
        reconcile_manifest=_manifest_works(2),   # A2: W_MS + W_REF = 2 (external true value)
    )
    assert (out / "_manifest" / "reconcile_tally.json").is_file()


def test_streaming_reconcile_unsigned_tolerance_raises(tmp_path):
    """Streaming reconcile: diff_tolerance=None (redline placeholder not set) -> RedlineUnsigned (never a quiet default)."""
    seed, refz = _monash_stockholm_works()
    with pytest.raises(RedlineUnsigned):
        S.run_m1_streaming(
            seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
            out_root=tmp_path / "s", n_workers=1,
            reconcile=True, reconcile_diff_tolerance=None,
            reconcile_manifest=_manifest_works(2),
        )


def test_streaming_reconcile_requires_manifest_anchor(tmp_path):
    """* A2: streaming reconcile=True without reconcile_manifest -> ValueError (no external anchor = a fake reconciliation, fail fast)."""
    works = _n_monash_works(3)
    with pytest.raises(ValueError):
        S.run_m1_streaming(
            works, [], registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
            out_root=tmp_path / "x", n_workers=1,
            reconcile=True, reconcile_diff_tolerance=0,   # Missing reconcile_manifest -> refuse to pass
        )


def test_streaming_reconcile_detects_silent_drop_via_manifest_anchor(tmp_path):
    """* A2 core red test (locks in the fake-reconciliation fix): the manifest says 5 works, the actual scan is fed only 3 -> the reconciliation must exit(15).

    The audit reproduced "5 works truly lost, still PASS": the old expected=seen∪kept was self-counted and always == kept+skipped, so silent data loss raised no alarm.
    This test has two arms:
      ① balanced: feed all 5 works + manifest(5) -> balanced, writes the tally (proves the manifest anchor does not wrongly hit a truly balanced run).
      ② dropped:  feed only the first 3 + manifest(5) (simulating a shard silently truncated, losing 2) -> expected(5) != kept(3)+skipped(0)
         -> exit(TALLY_IMBALANCE=15). If this does not exit, the fake-reconciliation bug is still there.
    """
    from identity.exit_codes import TALLY_IMBALANCE

    works = _n_monash_works(5)   # 5 distinct Monash seed works (all written to tables, no frontier)

    # ① balanced: feed all 5 + manifest 5 -> balanced.
    ok = tmp_path / "ok"
    S.run_m1_streaming(
        works, [], registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
        out_root=ok, n_workers=1,
        reconcile=True, reconcile_diff_tolerance=0,
        reconcile_manifest=_manifest_works(5),
    )
    assert (ok / "_manifest" / "reconcile_tally.json").is_file(), "A truly balanced ledger should write the tally (the manifest anchor must not misfire)"

    # ② dropped: feed only the first 3, the manifest still says 5 -> 2 silently lost -> the arithmetic arm does not match -> HALT.
    with pytest.raises(SystemExit) as ei:
        S.run_m1_streaming(
            works[:3], [], registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
            out_root=tmp_path / "drop", n_workers=1,
            reconcile=True, reconcile_diff_tolerance=0,
            reconcile_manifest=_manifest_works(5),   # External true value 5 vs actual scan 3 -> 2 missing -> exit 15
        )
    assert ei.value.code == TALLY_IMBALANCE, "Silently dropping 2 works must exit(15), otherwise the fake-reconciliation bug is still there"


def test_streaming_compact_dedup_wired_and_passes_clean(monkeypatch, tmp_path):
    """* A3: run_compact_dedup=True -> at the end run compact_dedup (with the correct pk_cols) on the parquet actually written for each table,
    a clean run has no duplicate PK -> everything passes (no false hits); a spy proves all 10 tables are dedup-checked and the paths point into out_root."""
    from m1_ingest import reconcile_m1 as REC

    calls = []
    orig = REC.compact_dedup

    def _spy(paths, *, pk_cols):
        calls.append((tuple(str(p) for p in paths), tuple(pk_cols)))
        return orig(paths, pk_cols=pk_cols)

    monkeypatch.setattr(REC, "compact_dedup", _spy)

    seed, refz = _bigger_works()
    out = tmp_path / "s"
    mf = S.run_m1_streaming(
        seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
        out_root=out, n_workers=1, run_compact_dedup=True,
    )
    # All 10 tables go through the dedup check (once per table).
    checked_pks = {pk for _paths, pk in calls}
    assert len(calls) == len(_TEN_TABLES), f"compact_dedup should run once per table, measured {len(calls)} times"
    # pk_cols agree with specs (spot check: works single key / works_affil three keys).
    assert ("work_id",) in checked_pks
    assert ("work_id", "author_id", "institution_id") in checked_pks
    # The parquet paths checked are indeed under out_root (real products, not an empty run).
    works_call = [c for c in calls if c[1] == ("work_id",)][0]
    assert works_call[0], "The works table should have real parts checked for dedup"
    assert all(str(out) in p for p in works_call[0])
    # A clean run returns the 10 tables as usual (dedup causes no false hits).
    assert set(mf.keys()) == set(_TEN_TABLES)


def test_streaming_compact_dedup_halts_on_duplicate_pk(monkeypatch, tmp_path):
    """* A3: if reduce creates a duplicate PK in the final product, compact_dedup must exit(EXIT_DEDUP_NONZERO=21).

    Inject a real duplicate: wrap _reduce_streaming_table and, for the works table, copy one extra part into the same bucket directory
    (the same work_id appearing twice = duplicate PK) -> the closing dedup arm scans it -> HALT. Proves the guard really blocks (an empty run passing does not count).
    """
    from identity.exit_codes import EXIT_DEDUP_NONZERO

    orig_reduce = S._reduce_streaming_table

    def _dup_reduce(name, schema, pk_cols, local_dirs, final_root, n_buckets, reduce_workers=1):
        parts = orig_reduce(name, schema, pk_cols, local_dirs, final_root, n_buckets,
                            reduce_workers=reduce_workers)
        if name == "works" and parts:
            import shutil
            first = final_root / name / parts[0]["rel_path"]
            shutil.copy2(first, first.parent / "part-99999.parquet")   # copy = duplicate PK
        return parts

    monkeypatch.setattr(S, "_reduce_streaming_table", _dup_reduce)

    seed, refz = _monash_stockholm_works()
    with pytest.raises(SystemExit) as ei:
        S.run_m1_streaming(
            seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
            out_root=tmp_path / "s", n_workers=1, run_compact_dedup=True,
        )
    assert ei.value.code == EXIT_DEDUP_NONZERO, "A duplicate PK in the final output must exit(21), otherwise dirty data goes bare into U2/U3"


def test_streaming_compact_dedup_default_on(monkeypatch, tmp_path):
    """When run_compact_dedup is not passed, the A3 dedup guard runs by default.

    The underlying run_m1_streaming and the full-scale entry run_full share the same default (True): no future driver that calls the streaming orchestration directly
    can "forget to turn it on"; turning it off must be an explicit False (tests/smoke runs follow the same rule). A spy proves the guard is called for every table."""
    from m1_ingest import reconcile_m1 as REC

    calls = []
    orig = REC.compact_dedup

    def _spy(paths, *, pk_cols):
        calls.append(tuple(pk_cols))
        return orig(paths, pk_cols=pk_cols)

    monkeypatch.setattr(REC, "compact_dedup", _spy)

    seed, refz = _monash_stockholm_works()
    S.run_m1_streaming(
        seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
        out_root=tmp_path / "s", n_workers=1,   # * run_compact_dedup not passed -> must be on by default
    )
    assert len(calls) == len(_TEN_TABLES), (
        f"The default path should run compact_dedup once per table, measured {len(calls)} times"
    )


def test_streaming_compact_dedup_explicit_false_skips(monkeypatch, tmp_path):
    """Explicit run_compact_dedup=False -> the whole guard does not run
    (the only way to turn the guard off = explicit False; the meaning is equivalent to the old behaviour, only "off" changed from the default to an explicit choice)."""
    from m1_ingest import reconcile_m1 as REC

    calls = []

    def _spy(paths, *, pk_cols):
        calls.append(tuple(pk_cols))
        return 0

    monkeypatch.setattr(REC, "compact_dedup", _spy)

    seed, refz = _monash_stockholm_works()
    S.run_m1_streaming(
        seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
        out_root=tmp_path / "s", n_workers=1, run_compact_dedup=False,
    )
    assert calls == [], "With an explicit False, no compact_dedup may run (can be turned off, but only explicitly)"


def test_streaming_emits_run_manifest_and_provenance(tmp_path):
    """Streaming end to end: writes run_manifest.json (with the sha + row_count of each table) + a provenance sidecar for every table."""
    seed, refz = _monash_stockholm_works()
    out = tmp_path / "s"
    S.run_m1_streaming(
        seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
        out_root=out, n_workers=1,
        source_snapshot_merkle="MERKLE_S", config_sha="CFG", rule_version="v", code_version="z",
    )
    import json
    mf_path = out / "_manifest" / "run_manifest.json"
    assert mf_path.is_file()
    mf = json.loads(mf_path.read_text(encoding="utf-8"))
    assert mf["source_snapshot_merkle"] == "MERKLE_S"
    assert "tables" in mf and "works" in mf["tables"]
    assert "sha256" in mf["tables"]["works"]
    # A provenance sidecar for every table.
    assert (out / "works" / "provenance.json").is_file()


# ===========================================================================
# ⑥ Real-data smoke (@slow): a real shard run in streaming -> bounded RSS (< 4GB) + byte-identical sha on two passes.
#    Skips automatically when the SSD is absent; no full load (ShardPathSource opens a U0 streaming reader afresh on each pass).
# ===========================================================================
import pathlib as _pl

# --- M3 port: repo path resolution (legacy hard-coded the author's machine) — config/paths.yaml ---
import pathlib as _sar_pl, sys as _sar_sys
_sar_repo = next(p for p in _sar_pl.Path(__file__).resolve().parents if p.name == "units").parents[1]
if str(_sar_repo) not in _sar_sys.path:
    _sar_sys.path.append(str(_sar_repo))
from pipeline.lib.paths import snapshot_root as _sar_snapshot_root  # noqa: E402
_REAL_SHARD = _pl.Path(
    str(_sar_snapshot_root() / "works/updated_date=2016-06-24/part_0000.gz")
)


def _rss_mb() -> float:
    import resource
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)


@pytest.mark.slow
@pytest.mark.skipif(not _REAL_SHARD.is_file(), reason="Real shards: SSD not mounted → smoke test skipped")
def test_streaming_real_shard_bounded_mem_and_deterministic(tmp_path):
    """A real 3MB shard (2439 works) run in streaming twice -> byte-identical bucket part sha + bounded RSS.

    The seed is the education institution that appears most often in the real shard, McGill (I5023651) -> there is a real seed and real rows are routed into buckets,
    so the smoke covers the non-empty streaming path. * Read-only snapshot (ShardPathSource streams), never deleted and never fully loaded.
    """
    mcgill = "I5023651"
    registry = [{"openalex_id": mcgill, "type": "education"}]
    econ = {mcgill}

    src_a = S.ShardPathSource([str(_REAL_SHARD)])
    src_b = S.ShardPathSource([str(_REAL_SHARD)])

    # run_pass_c=False: in a single shard the McGill works cite ~1000 off-disk works -> the frontier cannot be fully hit
    # (a property that exists only with the full snapshot, not a bug). run_space_guard=False: work_first_pub holds the full pass-A authors,
    # and with one shard the authors table covers only seed-related authors -> fp ⊄ authors is also self-consistent only at full scale (the old path is the same).
    # The single-shard smoke checks only the streaming / memory / determinism of **pass-A + pass-B + flush**.
    mf_a = S.run_m1_streaming(
        src_a, [], registry=registry, econ_dept_ids=econ,
        out_root=tmp_path / "a", n_workers=1,
        run_field_probe=True, run_pass_c=False, run_space_guard=False,
    )
    rss_after_a = _rss_mb()

    mf_b = S.run_m1_streaming(
        src_b, [], registry=registry, econ_dept_ids=econ,
        out_root=tmp_path / "b", n_workers=1,
        run_field_probe=True, run_pass_c=False, run_space_guard=False,
    )

    # Byte-identical on two passes (real-data determinism).
    for name in _TEN_TABLES:
        assert _sig(mf_a[name]) == _sig(mf_b[name]), f"Real-shard table {name}: sha differs between the two runs"

    # There is a real seed -> the main table is non-empty (streaming really routed rows into buckets).
    assert sum(p["row_count"] for p in mf_a["works"]) > 0, "McGill should have works written to the table (streaming route)"
    assert sum(p["row_count"] for p in mf_a["authorship_edges"]) > 0

    # RSS bounded: a single 3MB shard is far below 4GB (streaming does not load everything; at full scale it is bounded the same way by flushing in buckets).
    assert rss_after_a < 4096, f"Real-shard streaming RSS should be < 4GB, measured {rss_after_a:.0f}MB"


@pytest.mark.slow
@pytest.mark.skipif(not _REAL_SHARD.is_file(), reason="Real shards: SSD not mounted → smoke test skipped")
def test_streaming_real_shard_parallel_equals_serial(tmp_path):
    """Real shard: parallel (2) vs serial (1) -> byte-identical bucket part sha (parallelism does not break determinism, real data).

    A single shard cannot be split further by file -> parallelism degrades to serial streaming (splittable=False), which must still equal the explicit serial run byte for byte.
    """
    mcgill = "I5023651"
    registry = [{"openalex_id": mcgill, "type": "education"}]
    econ = {mcgill}

    mf1 = S.run_m1_streaming(
        S.ShardPathSource([str(_REAL_SHARD)]), [],
        registry=registry, econ_dept_ids=econ, out_root=tmp_path / "w1", n_workers=1,
        run_pass_c=False, run_space_guard=False,
    )
    mf2 = S.run_m1_streaming(
        S.ShardPathSource([str(_REAL_SHARD)]), [],
        registry=registry, econ_dept_ids=econ, out_root=tmp_path / "w2", n_workers=2,
        run_pass_c=False, run_space_guard=False,
    )
    for name in _TEN_TABLES:
        assert _sig(mf1[name]) == _sig(mf2[name]), f"Real-shard table {name}: parallel != serial"


# ===========================================================================
# ⑦ Item 1 (S2 reduce memory fix): merging several parts inside a bucket becomes a lazy k-way merge (heapq.merge),
#    no longer gathering the whole bucket's to_pylist into one big list and then sorting. Byte equivalence is guaranteed by "stable merge == stable sort"
#    (each part is already sorted by the same PK key; merging in the old concat order -> equal row for row to the old sorted).
# ===========================================================================
def _write_sorted_part(path, rows):
    """Write rows already sorted by (work_id,author_id) as one parquet part (test fixture,
    reproducing the precondition that HashBucketWriter.flush_shard canonical-sorts before writing)."""
    import pyarrow as _pa
    import pyarrow.parquet as _pq
    cols = ["work_id", "author_id", "x"]
    table = _pa.table({c: [r[c] for r in rows] for c in cols})
    path.parent.mkdir(parents=True, exist_ok=True)
    _pq.write_table(table, str(path))


def test_merge_sorted_parts_equals_stable_global_sort(tmp_path):
    """Core new piece of item 1, _merge_sorted_parts: a lazy stable k-way merge of several parts that are **each already sorted by PK**,
    row for row == sorted(all rows concatenated in part order, key=_sort_key_for) - including None-PK sorted last + stable order of the same PK across parts.
    Pinning "merge order == old stable sort order" as a red test is the root of byte equivalence (the bytes depend only on the row set + this order)."""
    pk = ("work_id", "author_id")
    keyf = S._sort_key_for(pk)

    # Each part is already sorted by keyf internally (precondition: HashBucketWriter sorts before writing).
    p0 = [
        {"work_id": "W1", "author_id": "A1", "x": "p0-1"},
        {"work_id": "W2", "author_id": "A1", "x": "p0-2"},   # Same PK as p1 (W2,A1) -> stable: p0 first
        {"work_id": "W2", "author_id": None, "x": "p0-3"},   # None sorts last within that work
    ]
    p1 = [
        {"work_id": "W1", "author_id": "A2", "x": "p1-1"},
        {"work_id": "W2", "author_id": "A1", "x": "p1-2"},   # Same PK (W2,A1), should come after p0-2
        {"work_id": "W3", "author_id": "A1", "x": "p1-3"},
    ]
    assert p0 == sorted(p0, key=keyf) and p1 == sorted(p1, key=keyf), "Each fixture part must be sorted on its own"

    _write_sorted_part(tmp_path / "p0.parquet", p0)
    _write_sorted_part(tmp_path / "p1.parquet", p1)

    merged = list(S._merge_sorted_parts(
        [str(tmp_path / "p0.parquet"), str(tmp_path / "p1.parquet")], pk
    ))
    # Old-path equivalence = sorted(concatenation, key); concatenation order = part list order (p0 first, p1 after), sorted is stable -> (W2,A1) p0-2 comes before p1-2.
    expected = sorted(p0 + p1, key=keyf)
    assert merged == expected, "The lazy k-way merge must equal a stable global sort row for row (the root of byte equivalence)"


def test_reduce_merges_multipart_buckets_byte_equals_serial(tmp_path):
    """Item 1 characterisation guard: force parts from several workers into the same bucket (n_buckets=4 + n_workers=4 + 40 works),
    reduce must merge them into a single part whose bucket part sha equals the serial (single worker) one exactly.
    Directly locks the reduce path that "merges several parts" (the existing parallel==serial test uses 256 buckets, where cross-worker collisions are weak and not covered)."""
    seed, refz = _bigger_works(40)
    mf1 = S.run_m1_streaming(
        seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
        out_root=tmp_path / "w1", n_workers=1, n_buckets=4,
    )
    mf4 = S.run_m1_streaming(
        seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
        out_root=tmp_path / "w4", n_workers=4, n_buckets=4,
    )
    for name in _TEN_TABLES:
        assert _sig(mf1[name]) == _sig(mf4[name]), (
            f"Table {name}: after reduce merges multiple parts, parallel(4) != serial(1) (the merge broke the bytes)"
        )


# ===========================================================================
# S1 dangling-reference tolerance + P0.3 a failure does not delete the temp buckets (the 123GB lesson)
# ===========================================================================
def test_streaming_tolerates_dangling_frontier_and_writes_sidecar(tmp_path):
    """Dangling 1/7≈14.3% ≤ 0.15 -> all 10 tables are produced; _manifest/pass_c_missing.{json,parquet} is written;
    on the success path the temp buckets are cleaned up as before; the footer of the product part has no ARROW:schema (S2 integration surface)."""
    import json

    refs = [f"W_R{i}" for i in range(1, 8)]
    seed = [_work("W_MS2", year=2016, refs=refs, title="t2",
                  authorships=[_au("A5017376589",
                                   institutions=[_inst(_MONASH_ID, country="AU")],
                                   raw_affil=["Monash University, Department of Economics"])])]
    refz = [_work(w, year=2009, title="r",
                  authorships=[_au("A_OTHER",
                                   institutions=[_inst(_STOCKHOLM_ID, country="SE")],
                                   raw_affil=["Stockholm University"])])
            for w in refs[:-1]]                            # Deliberately missing W_R7 (dangling)
    out = tmp_path / "out"
    mf = S.run_m1_streaming(
        seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
        out_root=out, n_workers=1,
    )
    assert set(mf.keys()) == set(_TEN_TABLES)

    stats = json.loads((out / "_manifest" / "pass_c_missing.json").read_text(encoding="utf-8"))
    assert stats["missing_count"] == 1
    assert stats["frontier_scanned"] == 7
    assert abs(stats["missing_ratio"] - 1 / 7) < 1e-4

    ids = pq.read_table(str(out / "_manifest" / "pass_c_missing.parquet"))
    assert ids.column("work_id").to_pylist() == ["W_R7"]

    assert not list(tmp_path.glob("m1_stream_*")), "The success path must still clean up the temporary buckets as before"

    # S2 integration surface: the KV metadata of a real bucket part has no ARROW:schema
    a_part = sorted((out / "works").glob("bucket=*/part-*.parquet"))[0]
    md = pq.ParquetFile(str(a_part)).metadata.metadata
    assert not md or b"ARROW:schema" not in dict(md)


def test_streaming_halt_keeps_tmp_buckets_and_missing_sidecar(tmp_path):
    """Dangling 2/2=100% > 0.15 -> still exit(20); but ① the temp buckets are kept (no more unconditional rmtree in finally)
    ② the missing sidecar was written first (a HALT also leaves a diagnostic trail)."""
    seed = [_work("W_MS3", year=2016, refs=["W_RX", "W_RY"], title="t3",
                  authorships=[_au("A5017376589",
                                   institutions=[_inst(_MONASH_ID, country="AU")],
                                   raw_affil=["Monash University, Department of Economics"])])]
    out = tmp_path / "out"
    with pytest.raises(SystemExit) as ei:
        S.run_m1_streaming(
            seed, [], registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
            out_root=out, n_workers=1,
        )
    assert ei.value.code == 20
    assert list(tmp_path.glob("m1_stream_*")), (
        "Temporary buckets must be kept after HALT: destroying them on failure was the root cause of the 123GB incident (P0.3)")
    assert (out / "_manifest" / "pass_c_missing.json").exists(), "The missing statistics must have been written to disk before HALT"


def test_clean_rerun_removes_stale_missing_sidecar(tmp_path):
    """Adversarial review MED-2: when re-running on the same out_root, a leftover pass_c_missing.{json,parquet} from the previous run would mislead diagnosis.
    Semantics pinned: sidecar present ⇔ this run has dangling references. A clean run must remove a stale sidecar before entering pass-C."""
    seed, refz = _monash_stockholm_works()          # clean fixture where the frontier is fully hit
    out = tmp_path / "out"
    mf_dir = out / "_manifest"
    mf_dir.mkdir(parents=True)
    (mf_dir / "pass_c_missing.json").write_text('{"stale": true}', encoding="utf-8")
    (mf_dir / "pass_c_missing.parquet").write_bytes(b"stale")
    S.run_m1_streaming(
        seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
        out_root=out, n_workers=1,
    )
    assert not (mf_dir / "pass_c_missing.json").exists(), "A stale sidecar left uncleaned = misleading diagnostics"
    assert not (mf_dir / "pass_c_missing.parquet").exists()


# ===========================================================================
# reduce stage parallel by bucket (reduce_workers) - parallelised before the full run.
#   reduce = U1's closing single-threaded bucket-by-bucket merge of 256 buckets × 5 tables, ~45% of the tuned full run (the largest bottleneck, which sets the floor on total run time).
#   The 256 buckets are independent by nature (input parts disjoint, output target paths disjoint, no shared state) -> a multiprocessing pool works bucket by bucket in parallel,
#   byte-for-byte identical to serial. * Redline: parallel reduce output == serial reduce output **byte for byte**.
#   Convention-neutral: only turns "bucket by bucket" into "buckets in parallel"; result content / identification convention / reconciliation semantics / schema are all untouched.
# ===========================================================================
def test_resolve_reduce_workers_auto_cap_and_floor():
    """reduce concurrency resolver (a pure function, an engineering constant, not an identification convention): auto sentinel (<=0/None) -> min(cpu, number of buckets);
    an explicit value is capped at the number of buckets (the bucket count is the ceiling on useful parallelism; more workers would have no bucket to take); buckets<=0 -> 1 (no division by zero)."""
    import os as _os
    cpu = _os.cpu_count() or 1
    # auto sentinel: both 0 and None -> min(cpu, jobs)
    assert S._resolve_reduce_workers(0, 8) == min(cpu, 8)
    assert S._resolve_reduce_workers(None, 8) == min(cpu, 8)
    assert S._resolve_reduce_workers(0, 1000) == min(cpu, 1000)
    # explicit value: not above the bucket count (jobs=3 with 100 -> 3), but not below 1
    assert S._resolve_reduce_workers(100, 3) == 3
    assert S._resolve_reduce_workers(2, 8) == 2
    assert S._resolve_reduce_workers(1, 8) == 1        # explicit 1 = serial
    # no buckets -> 1 (no division by zero, no empty pool)
    assert S._resolve_reduce_workers(8, 0) == 1
    assert S._resolve_reduce_workers(0, 0) == 1


def test_reduce_workers_default_is_serial_byte_equal(tmp_path):
    """Engine default reduce_workers=1 (serial) -> zero behaviour change: the default run == explicit reduce_workers=1 byte for byte.
    Protects the existing 34 reduce determinism tests from being disturbed by a parallel default (parallel is an explicit opt-in)."""
    seed, refz = _bigger_works(16)
    mf_default = S.run_m1_streaming(
        seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
        out_root=tmp_path / "def", n_workers=1,
    )
    mf_serial = S.run_m1_streaming(
        seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
        out_root=tmp_path / "ser", n_workers=1, reduce_workers=1,
    )
    for name in _TEN_TABLES:
        assert _sig(mf_default[name]) == _sig(mf_serial[name]), (
            f"Table {name}: default (implicit serial) differs from explicit reduce_workers=1 = the default is not serial")


def test_reduce_workers_parallel_byte_equals_serial(tmp_path):
    """* Core redline: the 10-table parts (rel_path, sha256) of parallel reduce (reduce_workers=8)
    == serial (reduce_workers=1) byte for byte. pass-B uses n_workers=1 (serial) in both runs to **isolate** the reduce
    change: the only variable is serial vs parallel in the reduce stage; if the bytes are all equal, parallel reduce has not broken determinism."""
    seed, refz = _bigger_works(24)
    mf_ser = S.run_m1_streaming(
        seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
        out_root=tmp_path / "ser", n_workers=1, reduce_workers=1,
    )
    mf_par = S.run_m1_streaming(
        seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
        out_root=tmp_path / "par", n_workers=1, reduce_workers=8,
    )
    for name in _TEN_TABLES:
        assert _sig(mf_ser[name]) == _sig(mf_par[name]), (
            f"Table {name}: parallel reduce(8) != serial reduce(1) byte for byte (parallel reduce broke determinism)")


def test_reduce_workers_multipart_bucket_parallel_byte_equals_serial(tmp_path):
    """Merge path with many parts per bucket × parallel reduce: n_buckets=4 + n_workers=4 (forcing parts from many workers into the same bucket)
    + reduce_workers=4 (merging these many-part buckets in parallel) -> equal row for row to the serial baseline (n_workers=1/reduce_workers=1).
    Directly locks the path "merge several parts of one bucket in parallel", the one most likely to break the bytes (stable cross-part merge order + parallel scheduling)."""
    seed, refz = _bigger_works(40)
    mf_ser = S.run_m1_streaming(
        seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
        out_root=tmp_path / "ser", n_workers=1, n_buckets=4, reduce_workers=1,
    )
    mf_par = S.run_m1_streaming(
        seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
        out_root=tmp_path / "par", n_workers=4, n_buckets=4, reduce_workers=4,
    )
    for name in _TEN_TABLES:
        assert _sig(mf_ser[name]) == _sig(mf_par[name]), (
            f"Table {name}: parallel reduce merging multi-part buckets != serial (the merge broke the bytes)")


def test_reduce_workers_parallel_two_runs_identical(tmp_path):
    """Deterministic reproduction: run reduce_workers=8 twice -> the 10-table part sha is exactly equal (parallel scheduling has no hidden source of non-determinism)."""
    seed, refz = _bigger_works(24)
    mf_a = S.run_m1_streaming(
        seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
        out_root=tmp_path / "a", n_workers=2, reduce_workers=8,
    )
    mf_b = S.run_m1_streaming(
        seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
        out_root=tmp_path / "b", n_workers=2, reduce_workers=8,
    )
    for name in _TEN_TABLES:
        assert _sig(mf_a[name]) == _sig(mf_b[name]), (
            f"Table {name}: reduce_workers=8 gives different sha in two runs (parallel reduce is non-deterministic)")


def test_reduce_workers_auto_sentinel_byte_equals_serial(tmp_path):
    """The auto sentinel (reduce_workers=0 -> min(cpu, number of buckets)) end to end == serial byte for byte (the production default path also keeps the redline)."""
    seed, refz = _bigger_works(24)
    mf_ser = S.run_m1_streaming(
        seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
        out_root=tmp_path / "ser", n_workers=1, reduce_workers=1,
    )
    mf_auto = S.run_m1_streaming(
        seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
        out_root=tmp_path / "auto", n_workers=1, reduce_workers=0,
    )
    for name in _TEN_TABLES:
        assert _sig(mf_ser[name]) == _sig(mf_auto[name]), (
            f"Table {name}: auto reduce concurrency != serial byte for byte")
