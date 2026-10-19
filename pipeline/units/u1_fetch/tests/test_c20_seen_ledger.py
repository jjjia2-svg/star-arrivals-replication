"""Red test for C20: streaming the reconcile `seen` ledger (sorted runs on disk + merged counting).

Background:
  The cost of the reconcile ledger itself was not accounted for: the four-number reconcile `seen`
  ledger holds 510M work IDs, grows linearly and becomes a memory hog.
  The fix: make the ledger streaming / bucketed counting.

This implementation = a textbook external distinct: each worker accumulates a small batch
while scanning -> a full batch is sorted and written to a run file -> cleared; at settlement
all run files are k-way merged, and adjacent duplicates are dropped while counting as a stream.
The distinct / set-difference semantics equal the old set version's exactly, and the
zero-tolerance semantics are unchanged. The existing reconcile tests
(test_stream_build.py::test_streaming_reconcile_*) must stay green unmodified; that is the hard
acceptance criterion. The seen ledger no longer enters main-process memory and no longer
goes through IPC/pickle.
"""
from __future__ import annotations

import pytest

pa = pytest.importorskip("pyarrow")

from identity.golden import MONASH_CANONICAL_ID

_REGISTRY = [{"openalex_id": MONASH_CANONICAL_ID, "type": "education"}]
_ECON = {MONASH_CANONICAL_ID}


# ---------------------------------------------------------------------------
# _SeenSpill: sort and spill in batches (the ledger is not kept in memory)
# ---------------------------------------------------------------------------
def test_seen_spill_writes_sorted_runs_bounded_batches(tmp_path):
    """Spill on a full batch: feeding 5 ids with flush_every=2 -> at least 2 runs are already
    written midway (the ledger is never kept in memory as a whole); finalize merges this worker's
    runs into a single sorted, deduplicated file (the global merge fan-in = number of chunks, so
    510M ids at one run per million = hundreds of handles are not opened at once, which would hit
    the fd limit)."""
    from m1_ingest import stream_build as S

    sp = S._SeenSpill(tmp_path / "runs", flush_every=2)
    for wid in ["W9", "W1", "W5", "W3", "W7", "W1"]:   # W1 duplicate: cross-batch dedup is finalize's job
        sp.add(wid)
    assert len(sp._paths) >= 2, "A full batch must switch to a new run file (already spilled to disk midway; the ledger does not keep the whole batch in memory)"
    runs = sp.finalize()
    assert len(runs) == 1, "finalize must merge this worker's several runs into a single file (bounds the global fan-in)"
    content = open(runs[0], encoding="utf-8").read().splitlines()
    assert content == ["W1", "W3", "W5", "W7", "W9"], "The single file must be totally ordered and deduplicated"


def test_count_distinct_and_skipped_equals_set_semantics(tmp_path):
    """Streaming count == old set semantics (distinct + set difference); an id repeated across runs
    is counted once."""
    from m1_ingest import stream_build as S

    ids = [f"W{(i * 13) % 40:03d}" for i in range(120)]   # many duplicates (40 distinct)
    kept = {f"W{i:03d}" for i in range(0, 40, 3)}
    sp = S._SeenSpill(tmp_path / "runs", flush_every=7)
    for wid in ids:
        sp.add(wid)
    runs = sp.finalize()
    n_seen, n_skipped = S._count_distinct_and_skipped(runs, kept)

    truth_seen = set(ids)
    assert n_seen == len(truth_seen), "The distinct semantics must equal the old set-based version exactly"
    assert n_skipped == len(truth_seen - kept), "skipped=|seen−kept| semantics unchanged to the letter (tolerance 0)"


def test_count_distinct_empty_runs_zero(tmp_path):
    from m1_ingest import stream_build as S

    assert S._count_distinct_and_skipped([], {"W1"}) == (0, 0)


# ---------------------------------------------------------------------------
# _run_passb_local: seen goes through spill; the ledger set is no longer returned to memory/IPC
# ---------------------------------------------------------------------------
def _inst(iid, country):
    return {"id": f"https://openalex.org/{iid}", "display_name": iid,
            "country_code": country, "type": "education",
            "lineage": [f"https://openalex.org/{iid}"]}


def _au(aid, insts, raw):
    return {"author": {"id": f"https://openalex.org/{aid}", "display_name": aid, "orcid": None},
            "institutions": insts, "raw_affiliation_strings": raw}


def _work(wid, year, aus):
    return {"id": f"https://openalex.org/{wid}", "publication_year": year, "type": "article",
            "cited_by_count": 7, "referenced_works": [],
            "primary_topic": {"subfield": {"id": "https://openalex.org/subfields/2002"}},
            "authorships": aus, "title": wid}


def _n_works(n):
    return [_work(f"WD{i:03d}", 2016,
                  [_au(f"AM{i:03d}", [_inst(MONASH_CANONICAL_ID, "AU")],
                       [f"Monash University, Department of Economics {i}"])])
            for i in range(n)]


def test_passb_local_spills_seen_no_set_retained(tmp_path):
    """collect_seen=True -> seen goes to spill files (the paths are returned); the ledger set does
    not stay resident in _LocalResult."""
    from m1_ingest import stream_build as S

    lr = S._run_passb_local(
        _n_works(3),
        seed_authors={"AM000", "AM001", "AM002"}, seed_work_ids=set(),
        author_cmap_pair={}, author_cmap_flat={}, inst_cmap_flat={},
        local_dir=str(tmp_path / "w0"),
        collect_seen=True,
    )
    assert lr.seen_spill_paths, "collect_seen=True must produce seen spill run files"
    ids = []
    for r in lr.seen_spill_paths:
        ids += open(r, encoding="utf-8").read().splitlines()
    assert sorted(ids) == ["WD000", "WD001", "WD002"]
    assert not hasattr(lr, "seen_work_ids"), (
        "C20: the seen ledger set must no longer stay resident in _LocalResult (that was the big memory hog / IPC source for the 510 million IDs)"
    )


def test_streaming_reconcile_tally_values_unchanged_via_spill(tmp_path):
    """End-to-end semantic anchor: manifest=5 / 5 actually fed (3 in-department kept + 2
    out-of-department skipped) -> the six tally keys equal the old version's, verbatim."""
    import json

    from m1_ingest import stream_build as S

    works = _n_works(3) + [
        _work(f"WX{i}", 2016, [_au(f"AX{i}", [_inst("I_STK", "SE")], ["Stockholm"])])
        for i in range(2)                       # out of department -> seen but not kept -> skipped
    ]
    manifest = {
        "date": "2026-06-26", "format": "jsonl",
        "meta": {"record_count": 5, "content_length": 1},
        "entities": [{
            "entity": "works", "record_count": 5, "content_length": 1,
            "files": [{"url": "s3://openalex/data/jsonl/works/updated_date=2016-01-01/part_0000.gz",
                       "meta": {"content_length": 1, "record_count": 5}}],
        }],
    }
    out = tmp_path / "out"
    S.run_m1_streaming(
        works, [], registry=_REGISTRY, econ_dept_ids=_ECON,
        out_root=out, n_workers=2,              # parallel: merging spills across workers must also count correctly
        reconcile=True, reconcile_diff_tolerance=0,
        reconcile_manifest=manifest,
    )
    tally = json.loads((out / "_manifest" / "reconcile_tally.json").read_text("utf-8"))
    assert tally["expected"] == 5
    assert tally["kept"] == 3
    assert tally["skipped"] == 2
    assert tally["failed"] == 0
    assert tally["balanced"] is True
