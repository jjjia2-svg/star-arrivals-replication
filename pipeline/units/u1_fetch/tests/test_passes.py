"""Tests for passes.py: fixture works check the seed-driven multi-pass scan, full capture of edges, and the piggy-backed accumulation.

Behaviour covered:
  - pass_a_seed_authors: scan the snapshot; a work whose author institutions, once folded, land in
    econ_dept_ids is a seed work, and its authors enter seeds.
    Piggy-back: every work's (author, year) is fed to FirstPubAccumulator (the accumulator closure passed in).
  - pass_b: for seed-related works, write works/refs_edges and cache ALL authorship edges of that work
    (key case: edges of non-seed authors inside a seed work must be cached too, never only the seed
    authors), accumulate fwci, and write work_text/works_affil/institutions (through injected sinks);
    returns the frontier (the set of extension works cited by seed works).
  - pass_c: re-scan the extension set; hits >= frontier_count, otherwise exit(EXIT_FRONTIER_MISS=20).
  - Institution folding uses U0 inst_lineage.fold_to_canonical + in_au_econ_dept (the real U0, not injected).

Discipline: all tests use small fixture works JSON to test logic and never download from S3. The concrete
field mapping for row-level flattening, inversion and writing belongs to the sibling modules
(schema_map/works_affil/...); their extract/write closures are injected here, and only orchestration,
full edge capture and the piggy-backed accumulation are tested.
"""
from __future__ import annotations

import pytest

from m1_ingest import passes as P
from identity.exit_codes import EXIT_FRONTIER_MISS


# ---------------------------------------------------------------------------
# fixture: registry (U0.5 table A) + econ_dept_ids + small sample of works
# ---------------------------------------------------------------------------
# registry_by_id: {bare openalex_id: record}; here I_ECON is a valid canonical edu parent institution.
_REGISTRY = [{"openalex_id": "I_ECON", "type": "education"}]
_ECON_DEPT_IDS = {"I_ECON"}


def _inst(inst_id, *, lineage=None, assoc=None, itype="education"):
    """Build one in-memory INSTITUTIONS-shaped institution (the minimal fields fold_to_canonical needs)."""
    return {
        "openalex_id": inst_id,
        "type": itype,
        "lineage": lineage or [],
        "associated_institutions": assoc or [],
    }


def _authorship(author_id, *, institutions):
    return {"author": {"id": f"https://openalex.org/{author_id}"}, "institutions": institutions}


# work S1: has one in-department author A_SEED (institution I_ECON matches directly) + one outside
# collaborator A_COAUTH (institution I_FOREIGN).
#   -> S1 is a seed work; key case: the edge of A_COAUTH must be cached too.
_WORK_S1 = {
    "id": "https://openalex.org/W_S1",
    "publication_year": 2010,
    "referenced_works": ["https://openalex.org/W_REF1"],
    "authorships": [
        _authorship("A_SEED", institutions=[_inst("I_ECON")]),
        _authorship("A_COAUTH", institutions=[_inst("I_FOREIGN", itype="education")]),
    ],
}
# work N1: entirely outside the department (no author lands in econ_dept_ids) -> not a seed.
_WORK_N1 = {
    "id": "https://openalex.org/W_N1",
    "publication_year": 2011,
    "referenced_works": [],
    "authorships": [_authorship("A_OTHER", institutions=[_inst("I_FOREIGN")])],
}


class _FakeFirstPub:
    """Capture the (author_id, year) pairs fed in by the piggy-back, imitating FirstPubAccumulator.add."""

    def __init__(self):
        self.calls: list[tuple[str, int]] = []

    def add(self, author_id, year):
        self.calls.append((author_id, year))


# ---------------------------------------------------------------------------
# pass_a_seed_authors: seed identification + piggy-back feed of first_pub
# ---------------------------------------------------------------------------
def test_pass_a_identifies_seed_authors_via_fold():
    """The institution I_ECON of A_SEED is in econ_dept_ids -> S1 is a seed and A_SEED enters seeds; a work entirely outside the department yields no seed."""
    fp = _FakeFirstPub()
    result = P.pass_a_seed_authors(
        [_WORK_S1, _WORK_N1],
        econ_dept_ids=_ECON_DEPT_IDS,
        registry_by_id=P.build_registry(_REGISTRY),
        first_pub=fp,
    )
    assert "A_SEED" in result.seed_authors
    # A_OTHER is entirely outside the department -> not a seed author
    assert "A_OTHER" not in result.seed_authors


def test_pass_a_rides_first_pub_for_every_author_year():
    """Piggy-back: every (author, year) of every work is fed to FirstPubAccumulator (including non-seed authors, full history)."""
    fp = _FakeFirstPub()
    P.pass_a_seed_authors(
        [_WORK_S1, _WORK_N1],
        econ_dept_ids=_ECON_DEPT_IDS,
        registry_by_id=P.build_registry(_REGISTRY),
        first_pub=fp,
    )
    # S1: (A_SEED,2010) (A_COAUTH,2010); N1: (A_OTHER,2011): the full set, not only seeds
    assert ("A_SEED", 2010) in fp.calls
    assert ("A_COAUTH", 2010) in fp.calls
    assert ("A_OTHER", 2011) in fp.calls


def test_pass_a_seen_authors_counts_all():
    """seen_authors = all distinct authors scanned (used to reconcile counts), including non-seed authors."""
    fp = _FakeFirstPub()
    result = P.pass_a_seed_authors(
        [_WORK_S1, _WORK_N1],
        econ_dept_ids=_ECON_DEPT_IDS,
        registry_by_id=P.build_registry(_REGISTRY),
        first_pub=fp,
    )
    assert {"A_SEED", "A_COAUTH", "A_OTHER"} <= result.seen_authors


# ---------------------------------------------------------------------------
# pass_b: write works/refs + cache ALL authorship edges + piggy-back sink
# ---------------------------------------------------------------------------
def test_pass_b_caches_all_authorship_edges_including_non_seed():
    """Key case: the edge of the non-seed collaborator A_COAUTH inside seed work S1 must be cached too."""
    captured_edges: list[tuple[str, str]] = []

    def edge_sink(work_id, author_id, year):
        captured_edges.append((author_id))

    result = P.pass_b(
        [_WORK_S1],
        seed_authors={"A_SEED"},
        edge_sink=lambda w, a, y: captured_edges.append(a),
    )
    # edges of both authors are present (seed A_SEED + non-seed A_COAUTH), never only the seed author
    assert "A_SEED" in captured_edges
    assert "A_COAUTH" in captured_edges


def test_pass_b_returns_frontier_from_referenced_works():
    """frontier = the set of extension works cited by seed works (bare ids); fed to the pass-C re-scan."""
    result = P.pass_b(
        [_WORK_S1],
        seed_authors={"A_SEED"},
        edge_sink=lambda w, a, y: None,
    )
    assert "W_REF1" in result.frontier


def test_pass_b_emits_works_and_refs_via_sinks():
    """works rows + refs edges are written through the injected sinks (this only checks that orchestration feeds the work to the sink; field mapping belongs to sibling modules)."""
    works_seen: list[str] = []
    refs_seen: list[tuple[str, str]] = []
    P.pass_b(
        [_WORK_S1],
        seed_authors={"A_SEED"},
        edge_sink=lambda w, a, y: None,
        works_sink=lambda work: works_seen.append(work["id"]),
        refs_sink=lambda wid, rid: refs_seen.append((wid, rid)),
    )
    assert "https://openalex.org/W_S1" in works_seen
    assert ("W_S1", "W_REF1") in refs_seen


# ---------------------------------------------------------------------------
# pass_c: re-scan the extension set; hits < frontier -> exit(EXIT_FRONTIER_MISS=20)
# ---------------------------------------------------------------------------
def _work(wid, year=2009):
    return {"id": f"https://openalex.org/{wid}", "publication_year": year,
            "referenced_works": [], "authorships": []}


def test_pass_c_all_frontier_hit_passes():
    """Every frontier work is hit in the re-scan shards -> no exit; returns the hit count."""
    result = P.pass_c(
        [_work("W_REF1")],
        frontier={"W_REF1"},
        works_sink=lambda work: None,
    )
    assert result.hits == 1


def test_pass_c_frontier_miss_exits_20():
    """Some frontier work is not hit in the re-scan shards (hits < frontier_count) -> exit(EXIT_FRONTIER_MISS=20)."""
    with pytest.raises(SystemExit) as ei:
        P.pass_c(
            [_work("W_REF1")],          # only W_REF1 is scanned
            frontier={"W_REF1", "W_REF2"},  # but the frontier also needs W_REF2 -> a missed hit
            works_sink=lambda work: None,
        )
    assert ei.value.code == EXIT_FRONTIER_MISS


# ---------------------------------------------------------------------------
# pass_c tolerance of dangling references:
#   <= threshold -> no HALT + the count is recorded + missing_sink receives the sorted ids;
#   > threshold -> still exit(20);
#   before a HALT the missing ids must still go to the sink, so a halted run leaves diagnostics.
# ---------------------------------------------------------------------------
def test_pass_c_tolerates_missing_below_threshold():
    got = {}
    result = P.pass_c(
        [_work(f"W_REF{i}") for i in range(1, 7)],       # REF1..6 are scanned
        frontier={f"W_REF{i}" for i in range(1, 8)},      # the frontier needs REF1..7 -> 1/7 = 14.3% missing
        works_sink=lambda work: None,
        missing_sink=lambda ids: got.setdefault("ids", list(ids)),
        missing_ratio_halt=0.15,
    )
    assert result.hits == 6 and result.frontier_count == 7
    assert result.missing_count == 1
    assert abs(result.missing_ratio - 1 / 7) < 1e-9
    assert got["ids"] == ["W_REF7"]


def test_pass_c_halts_above_threshold_but_sink_gets_missing_first():
    got = {}
    with pytest.raises(SystemExit) as ei:
        P.pass_c(
            [_work("W_REF1")],
            frontier={"W_REF1", "W_REF2", "W_REF3"},      # 2/3 = 67% missing > 15%
            works_sink=lambda work: None,
            missing_sink=lambda ids: got.setdefault("ids", list(ids)),
            missing_ratio_halt=0.15,
        )
    assert ei.value.code == EXIT_FRONTIER_MISS
    assert got["ids"] == ["W_REF2", "W_REF3"]


def test_pass_c_clean_run_never_calls_missing_sink():
    called = []
    result = P.pass_c(
        [_work("W_REF1")], frontier={"W_REF1"},
        works_sink=lambda work: None,
        missing_sink=lambda ids: called.append(1),
    )
    assert result.missing_count == 0 and result.missing_ratio == 0.0
    assert not called


def test_pass_c_threshold_default_reads_signed_redline():
    """Without missing_ratio_halt, read redlines.yaml pass_c.missing_ratio_halt (0.15)."""
    result = P.pass_c(
        [_work(f"W_REF{i}") for i in range(1, 8)],        # REF1..7 are scanned
        frontier={f"W_REF{i}" for i in range(1, 9)},       # 1/8 = 12.5% missing <= 0.15 -> no HALT
        works_sink=lambda work: None,
    )
    assert result.missing_count == 1
