"""Red test for wiring (b): leavers with an empty institution are merged into the U1 pass-A seeds.

Design:
  A byline whose institution is empty but which hits an author_id is merged into the pass-A
  seeds (minimal set: only rows with institution=None whose department name matches).
  Without the merge, these departed authors are permanently missing.
  Population: hits with an empty institution that can only be recovered from the raw strings
  are 389 rows / 83 authors.

Behaviour pinned down:
  - Extractor: take only the author_id of the rows in byline_dept_hits with institution_id=None
    (each such row is itself a department-name hit, because build_dept_hits writes only hit
    rows); never merge the whole table (keeps the byline->seed coupling minimal).
  - run_m1_streaming/run_full open an extra_seed_authors port: once merged into the pass-A
    seeds, the works of these authors are judged relevant in pass-B (works/authorship_edges
    are written).
  - id space: seed matching uses the snapshot's bare ids; the extra seeds are expanded back
    through U1's own author cmap (terminal -> all raw aliases), so that "hits are canonical
    terminal ids while the snapshot byline carries an old raw id" is not missed.
Rule-neutral: only the data-gathering wiring changes; no identification choices.
"""
from __future__ import annotations

import pytest

pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")

from identity.golden import MONASH_CANONICAL_ID

_REGISTRY = [{"openalex_id": MONASH_CANONICAL_ID, "type": "education"}]
_ECON = {MONASH_CANONICAL_ID}


# ---------------------------------------------------------------------------
# Extractor: byline_dept_hits -> author_ids of hit rows with an empty institution (minimal set)
# ---------------------------------------------------------------------------
def _write_hits(tmp_path, rows):
    cols = {
        "work_id": pa.array([r[0] for r in rows], type=pa.string()),
        "author_id": pa.array([r[1] for r in rows], type=pa.string()),
        "dept_key": pa.array([r[2] for r in rows], type=pa.string()),
        "matched_phrase": pa.array([r[3] for r in rows], type=pa.string()),
        "institution_id": pa.array([r[4] for r in rows], type=pa.string()),
        "match_style": pa.array([r[5] for r in rows], type=pa.string()),
    }
    target = tmp_path / "byline_dept_hits.parquet"
    pq.write_table(pa.table(cols), str(target))
    return target


def test_extractor_takes_only_institution_none_hit_authors(tmp_path):
    """Minimal set: merge only the author_id of hit rows with institution_id=None; never merge hit
    rows that carry an institution id."""
    from m1_ingest import run_m1_full as F

    hits = _write_hits(tmp_path, [
        ("W1", "A_LEAVER1", "monash_econ", "department of economics", None, "printed"),
        ("W2", "A_STAYS", "monash_econ", "department of economics", MONASH_CANONICAL_ID, "printed"),
        ("W3", "A_LEAVER1", "monash_econ", "dept of economics", None, "stamped"),
        ("W4", "A_LEAVER2", "unsw_econ", "school of economics", None, "printed"),
    ])
    out = F.byline_empty_inst_seed_authors(hits)
    assert out == {"A_LEAVER1", "A_LEAVER2"}, (
        "Merge only rows with institution=None whose department name matches (the minimal set), deduplicated"
    )


def test_extractor_empty_none_rows_gives_empty_set(tmp_path):
    from m1_ingest import run_m1_full as F

    hits = _write_hits(tmp_path, [
        ("W1", "A_STAYS", "monash_econ", "department of economics", MONASH_CANONICAL_ID, "printed"),
    ])
    assert F.byline_empty_inst_seed_authors(hits) == set()


# ---------------------------------------------------------------------------
# Wiring: extra_seed_authors merged into the pass-A seeds -> the leavers' works are actually written
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
            "cited_by_count": 3, "referenced_works": [],
            "primary_topic": {"subfield": {"id": "https://openalex.org/subfields/2002"}},
            "authorships": aus, "title": wid}


def _leaver_fixture():
    """Leaver A_LEAVER: has only a raw unit string and no resolved institution (exactly the
    population wiring (b) is meant to catch); add one ordinary Monash seed work so the pipeline is
    not empty."""
    w_seed = _work("W_SEED", 2016, [
        _au("A_M", [_inst(MONASH_CANONICAL_ID, "AU")],
            ["Monash University, Department of Economics"]),
    ])
    w_leaver = _work("W_LEAVER", 1998, [
        _au("A_LEAVER", [], ["Department of Economics, Monash University"]),
    ])
    return [w_seed, w_leaver]


def _kept_work_ids(out_root):
    import pathlib

    ids = set()
    for part in pathlib.Path(out_root, "works").rglob("*.parquet"):
        ids |= set(pq.read_table(str(part), columns=["work_id"])["work_id"].to_pylist())
    return ids


def test_streaming_without_extra_seeds_leaver_missing(tmp_path):
    """Baseline (reproduces the engineering fact): without the wiring, the works of leavers with an
    empty institution are systematically missing."""
    from m1_ingest import stream_build as S

    S.run_m1_streaming(
        _leaver_fixture(), [], registry=_REGISTRY, econ_dept_ids=_ECON,
        out_root=tmp_path / "out", n_workers=1,
    )
    kept = _kept_work_ids(tmp_path / "out")
    assert "W_SEED" in kept
    assert "W_LEAVER" not in kept, "Baseline check: without merging into the seeds, these people are indeed permanently missing"


def test_streaming_extra_seed_authors_lands_leaver_works(tmp_path):
    """Wiring (b) main path: extra_seed_authors={A_LEAVER} -> their works land in works +
    authorship_edges."""
    from m1_ingest import stream_build as S

    out = tmp_path / "out"
    S.run_m1_streaming(
        _leaver_fixture(), [], registry=_REGISTRY, econ_dept_ids=_ECON,
        out_root=out, n_workers=1,
        extra_seed_authors={"A_LEAVER"},
    )
    kept = _kept_work_ids(out)
    assert "W_LEAVER" in kept, "After merging into the seeds, the leavers' works must be written out"

    import pathlib
    edge_authors = set()
    for part in pathlib.Path(out, "authorship_edges").rglob("*.parquet"):
        edge_authors |= set(pq.read_table(str(part), columns=["author_id"])["author_id"].to_pylist())
    assert "A_LEAVER" in edge_authors


def test_streaming_extra_seed_terminal_id_expands_to_raw_aliases(tmp_path):
    """id-space guard: the extra seed is a canonical terminal id while the snapshot byline carries
    an old raw id (already mapped by a U1 merge) -> after the reverse expansion it must still be
    found (the hits table is in canonical space, the snapshot in raw space)."""
    from m1_ingest import stream_build as S

    works = [
        _work("W_SEED", 2016, [
            _au("A_M", [_inst(MONASH_CANONICAL_ID, "AU")],
                ["Monash University, Department of Economics"]),
        ]),
        _work("W_OLDID", 2001, [
            _au("A_RAW_OLD", [], ["Department of Economics, Monash University"]),
        ]),
    ]
    out = tmp_path / "out"
    S.run_m1_streaming(
        works, [], registry=_REGISTRY, econ_dept_ids=_ECON,
        out_root=out, n_workers=1,
        author_merged_rows=[{"raw_id": "A_RAW_OLD", "canonical_id": "A_TERMINAL"}],
        extra_seed_authors={"A_TERMINAL"},      # hits only know the terminal id
    )
    kept = _kept_work_ids(out)
    assert "W_OLDID" in kept, "Final-state seeds must be expanded back to raw aliases, otherwise works signed with an old id are missed"


def test_run_full_passes_extra_seed_authors_through(monkeypatch, tmp_path):
    """run_full passes extra_seed_authors through to run_m1_streaming; the plan echoes the count
    (the operator can check it before launch)."""
    from m1_ingest import run_m1_full as F

    captured = {}

    def _spy(_seed, _passc, **kw):
        captured.update(kw)
        return {}

    monkeypatch.setattr(F, "run_m1_streaming", _spy)
    snap = tmp_path / "snap"
    (snap / "works" / "updated_date=2016-01-01").mkdir(parents=True)
    (snap / "works" / "updated_date=2016-01-01" / "part_000.gz").write_bytes(b"")
    F.run_full(
        snap, tmp_path / "out", registry=_REGISTRY, econ_dept_ids=_ECON,
        execute=True, extra_seed_authors={"A_L1", "A_L2"},
        source_snapshot_merkle="M", config_sha="C", rule_version="r", code_version="c",
    )
    assert captured.get("extra_seed_authors") == {"A_L1", "A_L2"}


# ---------------------------------------------------------------------------
# U1 seed top-up arm: roster author_id injected directly into the pass-A seeds
# Root cause (whole-person miss): the roster person was manually verified with an author_id,
# but the institution fold of their snapshot byline never hit the department boundary ->
# pass-A cannot recognise the seed -> all of that person's works are permanently missing.
# Fix: a roster author_id is a manually verified in-department author -> merge it straight
# into the seeds (no longer relying on the byline-hit arm alone).
# This arm takes effect on the full AWS rerun.
# ---------------------------------------------------------------------------
def _write_roster(tmp_path, name, author_ids):
    rows = [{"dept_key": "monash_econ", "author_id": a, "display_name": str(a)}
            for a in author_ids]
    target = tmp_path / name
    pq.write_table(pa.Table.from_pylist(rows), str(target))
    return target


def test_roster_seed_extractor_reads_author_ids_dedup_skip_none(tmp_path):
    """Extractor: union across rosters, drop None (roster members without an id cannot enter the
    author pool, so they are not injected), dedupe."""
    from m1_ingest import run_m1_full as F

    r1 = _write_roster(tmp_path, "monash.parquet", ["A_R1", "A_R2", None])
    r2 = _write_roster(tmp_path, "unsw.parquet", ["A_R2", "A_R3"])
    assert F.roster_seed_author_ids([r1, r2]) == {"A_R1", "A_R2", "A_R3"}


def test_streaming_roster_seed_lands_missed_person_works(tmp_path):
    """End to end (whole-person miss): the works of roster person A_LEAVER have bylines with no
    resolved institution -> missed at baseline; after the roster id is injected directly into
    the seeds, their works/edges are written (reuses the extra_seed_authors mechanism)."""
    from m1_ingest import run_m1_full as F
    from m1_ingest import stream_build as S

    roster = _write_roster(tmp_path, "monash.parquet", ["A_LEAVER"])
    out = tmp_path / "out"
    S.run_m1_streaming(
        _leaver_fixture(), [], registry=_REGISTRY, econ_dept_ids=_ECON,
        out_root=out, n_workers=1,
        extra_seed_authors=F.roster_seed_author_ids([roster]),
    )
    assert "W_LEAVER" in _kept_work_ids(out)


def test_run_full_roster_seed_paths_arm_merges_and_reports(monkeypatch, tmp_path):
    """New run_full arm roster_seed_paths: extract -> union with the byline extra seeds -> pass
    through; the plan echoes each arm (roster_seed_author_count + the union's
    extra_seed_author_count), checkable before launch."""
    from m1_ingest import run_m1_full as F

    captured = {}

    def _spy(_seed, _passc, **kw):
        captured.update(kw)
        return {}

    monkeypatch.setattr(F, "run_m1_streaming", _spy)
    roster = _write_roster(tmp_path, "monash.parquet", ["A_R1", "A_R2"])
    snap = tmp_path / "snap"
    (snap / "works" / "updated_date=2016-01-01").mkdir(parents=True)
    (snap / "works" / "updated_date=2016-01-01" / "part_000.gz").write_bytes(b"")
    F.run_full(
        snap, tmp_path / "out", registry=_REGISTRY, econ_dept_ids=_ECON,
        execute=True, extra_seed_authors={"A_BYLINE", "A_R2"},
        roster_seed_paths=[roster],
        source_snapshot_merkle="M", config_sha="C", rule_version="r", code_version="c",
    )
    assert captured.get("extra_seed_authors") == {"A_BYLINE", "A_R2", "A_R1"}


def test_run_full_dry_run_plan_reports_roster_arm(tmp_path):
    """dry_run also echoes each arm (reads no full data, writes nothing):
    roster_seed_author_count=2, union=3."""
    from m1_ingest import run_m1_full as F

    roster = _write_roster(tmp_path, "monash.parquet", ["A_R1", "A_R2"])
    snap = tmp_path / "snap"
    (snap / "works").mkdir(parents=True)
    plan = F.run_full(
        snap, tmp_path / "out", registry=_REGISTRY, econ_dept_ids=_ECON,
        execute=False, extra_seed_authors={"A_BYLINE", "A_R2"},
        roster_seed_paths=[roster],
    )
    assert plan["roster_seed_author_count"] == 2
    assert plan["extra_seed_author_count"] == 3         # union (byline ∪ roster)
