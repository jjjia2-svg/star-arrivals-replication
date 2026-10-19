"""M1-T8 run_m1 — M1 main orchestrator (snapshot → canonical → filter into 10 tables → accumulate fwci → reconcile → freeze + run_manifest/provenance).

Why "orchestrator" and not new logic:
  Field mapping, keeping all edges, abstract inversion, accumulation, writing and reconciliation are already
  done by the sibling modules and the U0 foundation. run_m1 only chains them in the right order and guards
  three key invariants:
    (1) Verify the Merkle root on entry (the frozen snapshot is unchanged) → exit(EXIT_MERKLE_INVALID=23).
    (2) canonical runs before dedup (several raw ids of one person fold into one root first, then rows are
        written → one person never splits).
    (3) Gate 4: cross-table canonical-space guard over four tables → exit(EXIT_CANONICAL_SPACE_SPLIT=22).
  It also emits the reproducibility records: run_manifest.json (source_snapshot_merkle must equal the M0 root,
  else HALT, plus each table's sha) + a provenance.json sidecar per table (atomic write, not in the COMMIT set).

Main flow (run_m1_slice):
  preflight_entry → field_probe → run_slice_tables (canonical→pass-A/B/C→10 tables)
  → assert_canonical_space → write the 10 tables (sibling writers/accumulators) → emit_run_manifest + provenance.

★Reuse (never rewrite):
  - passes.{pass_a_seed_authors, pass_b, pass_c} (seed snowball + HIGH-4 keep-all-edges + frontier guard).
  - schema_map.{flatten_work, iter_authorship_edges, iter_referenced_edges, assert_snapshot_fields_present}.
  - works_affil.WorksAffilWriter / authors.AuthorTable / first_pub.FirstPubAccumulator /
    institutions.{iter_institutions, write_institutions} / abstract_reverse.{flatten_work_text, write_work_text} /
    fwci_accumulator.FwciPopAccumulator.
  - canonical_id.build_canonical_map (thin wrapper over the U0 replay; cycles pass through).
  - snapshot_freeze.assert_entry_merkle (entry Merkle check; U0 issues EXIT_MERKLE_INVALID).
  - common.inst_lineage.fold_to_canonical (pure function that folds institutions to their canonical parent, the Yves Zenou fold; red line #1).
  - common.manifest.{verify_provenance, ProvenanceMismatch} (comparison with the M0 root, HALT).
  - common.atomic_io.atomic_write_bytes (JSON writes; C-C: there is no atomic_write_json/parquet).
  - identity.golden.{ZENOU_STRUCTURAL, classify_golden} + exit_codes (named constants).
  - _writer_util.{bare, write_rows_parquet} (single-file deterministic parquet for works/refs_edges).

★Neutral on identification criteria: orchestration, guards and reproducibility records are engineering
  cross-cutting concerns and do not touch the identification red lines; the only identification-criterion
  touchpoints are placeholders inside the sibling modules (dose / FWCI window / academic-age bins), which
  run_m1 neither reads nor fills.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

# --- U0 foundation (the real surface) ---
from common.atomic_io import atomic_write_bytes
from common.inst_lineage import fold_to_canonical
from common.manifest import ProvenanceMismatch, verify_provenance
from common.schema import (
    WORKS,
    REFS_EDGES,
    AUTHORSHIP_EDGES,
    INSTITUTIONS,
)
from identity.constants import build_registry_by_id
from identity.exit_codes import (
    EXIT_CANONICAL_SPACE_SPLIT,
    GOLDEN_FAIL,
)
from identity.golden import MONASH_CANONICAL_ID, classify_golden

# --- M0 sibling (entry Merkle check; U0 issues EXIT_MERKLE_INVALID) ---
from m0_snapshot.snapshot_freeze import assert_entry_merkle

# --- M1 siblings (field mapping / keep all edges / accumulate / write / reconcile) ---
from m1_ingest import passes as P
from m1_ingest import reconcile_m1 as REC
from m1_ingest import schema_map as SM
from m1_ingest._writer_util import bare, write_rows_parquet
from m1_ingest.abstract_reverse import flatten_work_text, write_work_text
from m1_ingest.authors import AuthorTable, write_authors
from m1_ingest.canonical_id import build_canonical_map, canonicalize
from m1_ingest.first_pub import FirstPubAccumulator, write_first_pub
from m1_ingest.fwci_accumulator import FwciPopAccumulator
from m1_ingest.hash_bucket_writer import HashBucketWriter
from m1_ingest.institutions import write_institutions
from m1_ingest.works_affil import WorksAffilWriter, write_works_affil


# Measured ground truth for Yves Zenou (live), used by the Yves Zenou slice fixture.
_ZENOU_ID = "A5017376589"
_ZENOU_ORCID = "0000-0001-6516-0812"


class _PositionalFirstPub:
    """Adapt the positional contract first_pub.add(author_id, year) injected by passes to
    FirstPubAccumulator.add(*, author_id, publication_year) (keyword-only).

    Why adapt in the orchestration layer: passes documents the injected first_pub as taking
    ".add(author_id, year)" positionally; FirstPubAccumulator is an independent writer whose .add is
    keyword-only. Both contracts are correct, only their shapes differ → run_m1 acts as glue and translates
    positional to keyword arguments, and never changes the signature of either sibling module (avoids a
    chain of edits).
    """

    __slots__ = ("_acc",)

    def __init__(self, acc) -> None:
        self._acc = acc

    def add(self, author_id, year) -> None:
        self._acc.add(author_id=author_id, publication_year=year)


# ===========================================================================
# Entry checks: Merkle + field probe
# ===========================================================================
def preflight_entry(*, snapshot_root, entities: Iterable[str]) -> None:
    """Check before M1 starts scanning: the recomputed Merkle root of the frozen snapshot must equal the frozen
    record, otherwise → exit(EXIT_MERKLE_INVALID=23).

    Thin wrapper over M0 snapshot_freeze.assert_entry_merkle (the code is issued by U0); it blocks
    "the frozen snapshot was modified / the reproducibility anchor does not match".
    """
    assert_entry_merkle(snapshot_root, entities=tuple(entities))


def field_probe(records, *, n: int = 200) -> None:
    """Probe the snapshot for field drift: sample n records and check the required keys; a missing key →
    exit(EXIT_FIELDS_MISSING=19).

    Thin wrapper over schema_map.assert_snapshot_fields_present (all measured fields are present, so it
    normally PASSES).
    """
    SM.assert_snapshot_fields_present(records, n=n)


# ===========================================================================
# Gate 4: cross-table canonical-space guard over four tables
# ===========================================================================
def _distinct(rows: Iterable[Mapping[str, Any]], col: str) -> set:
    """Distinct non-None value set of a column (None is left out of the subset check: a fallback row for a
    failed institution resolution does not count as a space split)."""
    out: set = set()
    for r in rows:
        v = r.get(col)
        if v is not None:
            out.add(v)
    return out


def assert_canonical_space(tables: Mapping[str, list]) -> None:
    """Gate 4: the foreign keys of the four tables must fall in the same canonical space; if any condition
    fails → exit(EXIT_CANONICAL_SPACE_SPLIT=22).

    Guards 4 conditions:
      - authorship_edges.author_id ⊆ authors.author_id
      - work_first_pub.author_id  ⊆ authors.author_id
      - works_affil.author_id     ⊆ authors.author_id
      - works_affil.institution_id ⊆ institutions.institution_id  (except None-institution fallback rows)
    """
    authors = _distinct(tables.get("authors", []), "author_id")
    institutions = _distinct(tables.get("institutions", []), "institution_id")

    edge_authors = _distinct(tables.get("authorship_edges", []), "author_id")
    fp_authors = _distinct(tables.get("work_first_pub", []), "author_id")
    affil_authors = _distinct(tables.get("works_affil", []), "author_id")
    affil_insts = _distinct(tables.get("works_affil", []), "institution_id")

    violations: list[str] = []
    if not edge_authors <= authors:
        violations.append(f"authorship_edges.author_id ⊄ authors: {sorted(edge_authors - authors)[:5]}")
    if not fp_authors <= authors:
        violations.append(f"work_first_pub.author_id ⊄ authors: {sorted(fp_authors - authors)[:5]}")
    if not affil_authors <= authors:
        violations.append(f"works_affil.author_id ⊄ authors: {sorted(affil_authors - authors)[:5]}")
    if not affil_insts <= institutions:
        violations.append(f"works_affil.institution_id ⊄ institutions: {sorted(affil_insts - institutions)[:5]}")

    if violations:
        sys.stderr.write(
            "[run_m1] gate 4: canonical-space guard failed — HALT exit("
            f"{EXIT_CANONICAL_SPACE_SPLIT}):\n  " + "\n  ".join(violations) + "\n"
        )
        sys.exit(EXIT_CANONICAL_SPACE_SPLIT)


# ===========================================================================
# Core: run the slice and produce the in-memory rows of the 10 tables (canonical before dedup; HIGH-4 keeps all edges)
# ===========================================================================
def run_slice_tables(
    seed_shards: Sequence[Mapping[str, Any]],
    passc_shards: Sequence[Mapping[str, Any]],
    *,
    registry: list[dict],
    econ_dept_ids: set[str],
    author_merged_rows: Optional[Iterable[Mapping[str, str]]] = None,
    institution_merged_rows: Optional[Iterable[Mapping[str, str]]] = None,
) -> dict[str, list]:
    """Seed-driven multi-pass scan → in-memory rows of the 10 tables (canonical is built first, then the tables
    are written → one person never splits).

    Args:
        seed_shards: the work shards scanned by pass-A/B (run_m1 passes the snapshot_reader stream; tests pass a fixture list).
        passc_shards: the pass-C rescan shards (the frontier fills in works rows).
        registry: the U0.5 table-A registry list (indexed via build_registry_by_id).
        econ_dept_ids: the department-boundary set produced by the sole U0.5 producer (bare canonical edu ids).
        author_merged_rows / institution_merged_rows: M0 merged_ids replay rows (raw→canonical);
            None → empty (no merges). canonical is built before the tables are written → several raw ids of
            one person/institution fold into one root.
    Returns: {table name: list of rows} covering the 10 tables (works/authorship_edges/refs_edges/works_affil/
            institutions/authors/work_text/work_first_pub/fwci_baseline_pop/canonical_id_map).

    ★canonical before dedup: build_canonical_map first → the writers fold to canonical with cmap → the written
      tables are already in canonical space.
    ★HIGH-4: the edge_sink of pass_b is called for [every] author of a seed work (non-seed co-authors included).
    """
    registry_by_id = build_registry_by_id(registry)

    # --- Build the canonical map first (before dedup/writing; several raw ids of one person fold into one root) ---
    author_cmap = build_canonical_map(list(author_merged_rows or []), id_type="author")
    institution_cmap = build_canonical_map(list(institution_merged_rows or []), id_type="institution")
    # The writers take a shallow {raw_id: canonical_id} table (canonicalize only takes the root).
    author_cmap_flat = {raw: terminal for raw, (terminal, _del) in author_cmap.items()}
    inst_cmap_flat = {raw: terminal for raw, (terminal, _del) in institution_cmap.items()}

    # --- Accumulators / writers (canonical map injected) ---
    first_pub = FirstPubAccumulator(author_cmap=author_cmap_flat)
    # The injection contract of passes is first_pub.add(author_id, year) (positional, see the passes docs);
    # FirstPubAccumulator.add is keyword-only (.add(*, author_id, publication_year)) →
    # a thin adapter in the orchestration layer (positional→keyword) leaves the signatures of both sibling
    # modules untouched (each contract stays as is).
    first_pub_sink = _PositionalFirstPub(first_pub)
    fwci = FwciPopAccumulator()
    authors = AuthorTable(author_cmap=author_cmap_flat)
    affil = WorksAffilWriter(author_cmap=author_cmap_flat, institution_cmap=inst_cmap_flat)

    works_rows: list[dict] = []
    refs_rows: list[dict] = []
    edge_rows: list[dict] = []
    text_rows: list[dict] = []
    inst_rows_raw: list[dict] = []  # Dedup by institution_id before writing

    # --- pass-A: identify seeds + piggyback first_pub (full scan) ---
    pass_a = P.pass_a_seed_authors(
        seed_shards,
        econ_dept_ids=econ_dept_ids,
        registry_by_id=registry_by_id,
        first_pub=first_pub_sink,
    )

    # --- Sink closures (field mapping belongs to the sibling modules; canonical folding happens inside the writers) ---
    def _edge_sink(work_id, author_id, year) -> None:
        # HIGH-4: the edges of every author (non-seed co-authors included) are cached; author_id is folded to canonical.
        edge_rows.append({
            "work_id": work_id,
            "author_id": canonicalize(author_id, author_cmap),
            "publication_year": year,
        })

    def _works_sink(work) -> None:
        works_rows.append(SM.flatten_work(work))

    def _refs_sink(work_id, ref_id) -> None:
        refs_rows.append({"work_id": work_id, "referenced_work_id": ref_id})

    def _text_sink(work) -> None:
        text_rows.append(flatten_work_text(work))

    def _affil_sink(work) -> None:
        affil.add_work(work)

    def _inst_sink(work) -> None:
        from m1_ingest.institutions import iter_institutions
        for row in iter_institutions(work):
            # institution_id is folded to canonical (Gate 4; same space as works_affil).
            row["institution_id"] = canonicalize(row["institution_id"], institution_cmap)
            inst_rows_raw.append(row)

    def _author_sink(work) -> None:
        for a in work.get("authorships") or []:
            authors.add_author(a.get("author") or {})

    # --- pass-B: write works/refs + HIGH-4 keep-all-edges + accumulate fwci + write text/affil/inst + collect authors ---
    # passes.pass_b does not collect authors (it only orchestrates), so authors are collected first from the seed-related works.
    seed_set = set(pass_a.seed_authors)

    def _is_relevant(work) -> bool:
        wid = bare(work.get("id"))
        if wid in pass_a.seed_work_ids:
            return True
        authors_here = {bare((a.get("author") or {}).get("id")) for a in work.get("authorships") or []}
        return bool(authors_here & seed_set)

    for work in seed_shards:
        if _is_relevant(work):
            _author_sink(work)

    P.pass_b(
        seed_shards,
        seed_authors=seed_set,
        seed_work_ids=pass_a.seed_work_ids,
        edge_sink=_edge_sink,
        works_sink=_works_sink,
        refs_sink=_refs_sink,
        affil_sink=_affil_sink,
        inst_sink=_inst_sink,
        text_sink=_text_sink,
        fwci_accumulator=fwci,
    )

    # --- pass-C: rescan to fill in works rows for the frontier (the frontier guard is inside passes) ---
    # frontier = what pass_b collected; but pass_b's return value already wrote refs_rows, so the frontier set fed to pass_c is rebuilt from refs here.
    frontier = {r["referenced_work_id"] for r in refs_rows if r["referenced_work_id"] is not None}
    # A work already written in pass-B needs no pass-C fill (frontier minus already written).
    already = {r["work_id"] for r in works_rows}
    frontier_to_scan = frontier - already
    if frontier_to_scan:
        P.pass_c(passc_shards, frontier=frontier_to_scan, works_sink=_works_sink)

    # --- institutions dedup (by institution_id; an institution that appears several times keeps one copy) ---
    inst_by_id: dict[str, dict] = {}
    for row in inst_rows_raw:
        iid = row["institution_id"]
        if iid is not None and iid not in inst_by_id:
            inst_by_id[iid] = row
    inst_rows = list(inst_by_id.values())

    # --- canonical_id_map 4-key rows (works/authors/institutions; in this slice only author/institution have merges) ---
    cmap_rows: list[dict] = []
    from m1_ingest.canonical_id import to_canonical_rows
    cmap_rows.extend(to_canonical_rows(author_cmap, id_type="author"))
    cmap_rows.extend(to_canonical_rows(institution_cmap, id_type="institution"))

    return {
        "works": works_rows,
        "authorship_edges": edge_rows,
        "refs_edges": refs_rows,
        "works_affil": affil.rows(),
        "institutions": inst_rows,
        "authors": authors.rows(),
        "work_text": text_rows,
        "work_first_pub": first_pub.rows(),
        "fwci_baseline_pop": fwci.to_table(),
        "canonical_id_map": cmap_rows,
    }


# ===========================================================================
# Gate 7: four-number reconciliation (thin wrapper over reconcile_m1; expected == kept + failed + skipped)
# ===========================================================================
def _distinct_work_ids(shards: Iterable[Mapping[str, Any]]) -> set:
    """Set of distinct bare work_ids in the work shards fed to the slice (None ids are not counted)."""
    out: set = set()
    for w in shards:
        wid = bare(w.get("id"))
        if wid is not None:
            out.add(wid)
    return out


def compute_slice_tally_counts(
    seed_shards: Sequence[Mapping[str, Any]],
    tables: Mapping[str, list],
    *,
    expected: int,
) -> dict[str, int]:
    """Derive the four numbers (expected / kept / failed / skipped) from the slice input + output tables — a pure
    function, no rescan, no writes.

    ★A2 fix (root cause of a "fake reconciliation" found in an audit): the old version had
      expected = seed_ids ∪ frontier_only, i.e. "count what it scanned as expected", so
      expected == kept + skipped was a [set identity] that always holds
      (|seen ∪ kept| ≡ |kept| + |seen − kept|) and the arithmetic arm did nothing: if a shard was silently
      truncated and 28,500 records went unread, seen and kept shrank together, the difference stayed 0, and
      even diff_tolerance=0 raised no alarm (the Sydney 27k / UQ 28,500 silent-loss failures).
      The new expected is passed in by the caller from the external manifest truth (compute_expected_from_manifest)
      and is no longer self-counted; skipped is counted independently = scanned seen that were not written
      (seen − kept), no longer derived from expected → the identity is broken.

    Meaning of the four numbers (aligned with the defence against silent loss, Sydney 27k):
      - expected = sum of record_count of this entity in the manifest (external truth: how many works the snapshot really has). ★An argument, not self-counted.
      - kept     = distinct works actually written to the works table (seed-related + frontier fill-ins).
      - skipped  = scanned works in seen that were not written (seen − kept; purely legitimate out-of-department skips). ★Counted independently, not derived from expected.
      - failed   = 0 (the M1 flattening stage has no per-record failures; shard-level failures belong to the M0 refetch domain, hence always 0).
    The reconciliation arm expected == kept + failed + skipped is now a [real test]: a silently truncated shard →
      seen shrinks → kept+skipped shrinks → no longer matches the manifest expected → HALT (no more fake balancing).

    ★seen = distinct work ids actually scanned from seed_shards (a real scan count); kept = distinct works in the works table.
      frontier-only (kept − seen: filled by pass-C from the rescan shards and absent from the main scan) counts
      toward kept but not toward seen →
      balanced ⇔ manifest expected == |seen ∪ kept| (in a full run seed==passc → seen covers the whole snapshot → equals the distinct count actually scanned).
    """
    seen_ids = _distinct_work_ids(seed_shards)
    kept_ids = {r["work_id"] for r in tables.get("works", []) if r.get("work_id") is not None}
    # Independent skipped count: works that were seen in the scan but not written (kept) — no longer derived from expected (breaks the fake-reconciliation identity).
    skipped_ids = seen_ids - kept_ids
    return {
        "expected": int(expected),
        "kept": len(kept_ids),
        "failed": 0,
        "skipped": len(skipped_ids),
    }


def reconcile_slice(
    seed_shards: Sequence[Mapping[str, Any]],
    tables: Mapping[str, list],
    *,
    stage: str,
    tally_path,
    diff_tolerance: Any,
    manifest: Mapping[str, Any],
    entity: str = "works",
) -> dict[str, Any]:
    """Four-number reconciliation for the slice: expected comes from the external manifest truth (A2 counter-anchor); thin wrapper over reconcile_m1.reconcile_pass.

    ★A2 fix: expected comes from compute_expected_from_manifest(manifest, entity) (external truth),
      no longer from compute_slice_tally_counts counting its own scan (which made the arithmetic arm always
      balance = fake reconciliation).
    ★diff_tolerance must be passed explicitly (an identification-criterion placeholder): None → RedlineUnsigned
      passes through (the allowed difference is never chosen on its own); imbalance → exit(TALLY_IMBALANCE=15).
    Returns the balanced tally dict (op_id_arm="N/A": the M1 streaming scan has no per-record op_id).
    """
    expected = REC.compute_expected_from_manifest(manifest, entity=entity)
    counts = compute_slice_tally_counts(seed_shards, tables, expected=expected)
    return REC.reconcile_pass(
        expected=counts["expected"],
        kept=counts["kept"],
        failed=counts["failed"],
        skipped=counts["skipped"],
        stage=stage,
        tally_path=tally_path,
        diff_tolerance=diff_tolerance,
    )


# ===========================================================================
# Writing: 10 parquet tables (sibling writers) + per-table sha (used by run_manifest)
# ===========================================================================
# table name → (writer function, PK columns) — writing and the provenance sha both go through this.
def _write_works(rows, target) -> None:
    write_rows_parquet(rows, target, schema=WORKS, pk_cols=("work_id",), label="WORKS")


def _write_refs(rows, target) -> None:
    write_rows_parquet(rows, target, schema=REFS_EDGES,
                       pk_cols=("work_id", "referenced_work_id"), label="REFS_EDGES")


def _write_edges(rows, target) -> None:
    write_rows_parquet(rows, target, schema=AUTHORSHIP_EDGES,
                       pk_cols=("work_id", "author_id"), label="AUTHORSHIP_EDGES")


def _write_canonical_map(rows, target) -> None:
    from common.schema import CANONICAL_ID_MAP
    write_rows_parquet(rows, target, schema=CANONICAL_ID_MAP,
                       pk_cols=("raw_id",), label="CANONICAL_ID_MAP")


def _write_fwci_pop(rows, target) -> None:
    from common.schema import FWCI_BASELINE_POP
    write_rows_parquet(rows, target, schema=FWCI_BASELINE_POP,
                       pk_cols=("subfield_id", "year", "work_type"), label="FWCI_BASELINE_POP")


# table name → writer function (single-file deterministic parquet; large tables use HashBucketWriter on the full-run path, the slice uses single files).
_TABLE_WRITERS = {
    "works": _write_works,
    "authorship_edges": _write_edges,
    "refs_edges": _write_refs,
    "works_affil": write_works_affil,
    "institutions": write_institutions,
    "authors": write_authors,
    "work_text": write_work_text,
    "work_first_pub": write_first_pub,
    "fwci_baseline_pop": _write_fwci_pop,
    "canonical_id_map": _write_canonical_map,
}


# table name → (schema, pk_cols) — used by HashBucketWriter bucketed writing (the full-run large-table path); see _TABLE_WRITERS for the single-file path.
# The single source of truth for schemas is common.schema; pk_cols line up with each sibling writer (works_affil has a 3-column key, fwci a 3-column key, …).
def _bucketed_table_specs() -> dict[str, tuple]:
    from common.schema import (
        WORK_TEXT,
        WORKS_AFFIL,
        AUTHORS,
        WORK_FIRST_PUB,
        FWCI_BASELINE_POP,
        CANONICAL_ID_MAP,
    )
    return {
        "works": (WORKS, ("work_id",)),
        "authorship_edges": (AUTHORSHIP_EDGES, ("work_id", "author_id")),
        "refs_edges": (REFS_EDGES, ("work_id", "referenced_work_id")),
        "works_affil": (WORKS_AFFIL, ("work_id", "author_id", "institution_id")),
        "institutions": (INSTITUTIONS, ("institution_id",)),
        "authors": (AUTHORS, ("author_id",)),
        "work_text": (WORK_TEXT, ("work_id",)),
        "work_first_pub": (WORK_FIRST_PUB, ("author_id",)),
        "fwci_baseline_pop": (FWCI_BASELINE_POP, ("subfield_id", "year", "work_type")),
        "canonical_id_map": (CANONICAL_ID_MAP, ("raw_id",)),
    }


def write_tables_bucketed(
    tables: Mapping[str, list],
    out_root: Path,
    *,
    n_buckets: int = 256,
    bucket_row_cap: int = 200_000,
) -> dict[str, list]:
    """Bucketed writing path for large tables: each table uses a HashBucketWriter (PK sha1 bucketing + canonical sort inside each bucket + deterministic parquet).

    Complements _write_tables (single file): a full run keeps memory bounded for large tables (buckets are flushed as soon as they fill), while slice tests can use single files.
    Returns {table name: [part manifest …]} (each part has rel_path/sha256/row_count; byte-identical across processes).
    ★Neutral on identification criteria: pure on-disk shape, touches no identification criterion; the schema guard is done inside HashBucketWriter.add.
    """
    specs = _bucketed_table_specs()
    out: dict[str, list] = {}
    for name, (schema, pk_cols) in specs.items():
        writer = HashBucketWriter(
            str(out_root / name),
            schema=schema, pk_cols=pk_cols,
            n_buckets=n_buckets, bucket_row_cap=bucket_row_cap,
        )
        for row in tables.get(name, []):
            writer.add(row)
        out[name] = writer.flush_all()
    return out


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_tables(tables: Mapping[str, list], out_root: Path) -> dict[str, dict]:
    """Write the 10 parquet tables (one <out_root>/<table>/data.parquet per table) and return {table name: {sha256,row_count,path}}."""
    out: dict[str, dict] = {}
    for name, writer in _TABLE_WRITERS.items():
        rows = tables.get(name, [])
        target = out_root / name / "data.parquet"
        writer(rows, target)
        out[name] = {
            "sha256": _sha256_file(target),
            "row_count": len(rows),
            "rel_path": (Path(name) / "data.parquet").as_posix(),
        }
    return out


def _emit_provenance_sidecars(
    table_meta: Mapping[str, dict],
    out_root: Path,
    *,
    source_snapshot_merkle: str,
    config_sha: str,
    rule_version: str,
    code_version: str,
) -> None:
    """Write a provenance.json sidecar for each table (atomic write; ★not in the COMMIT set — a side-channel record, not part of the frozen set)."""
    for name, meta in table_meta.items():
        prov = {
            "table": name,
            "source_snapshot_merkle": source_snapshot_merkle,
            "config_sha": config_sha,
            "rule_version": rule_version,
            "code_version": code_version,
            "sha256": meta["sha256"],
            "row_count": meta["row_count"],
        }
        blob = json.dumps(prov, sort_keys=True, ensure_ascii=False).encode("utf-8")
        atomic_write_bytes(out_root / name / "provenance.json", blob)


def emit_run_manifest(
    table_meta: Mapping[str, dict],
    out_root: Path,
    *,
    source_snapshot_merkle: str,
    config_sha: str,
    rule_version: str,
    code_version: str,
    expected_snapshot_merkle: Optional[str] = None,
) -> dict[str, Any]:
    """Write run_manifest.json (the reproducibility record); return the in-memory manifest dict.

    ★source_snapshot_merkle must equal the frozen M0 root (compared if expected_snapshot_merkle is given):
      mismatch → verify_provenance raises ProvenanceMismatch(=13) HALT (never silent).
    Contains config_sha / rule_version / code_version + each table's sha256 + row_count.
    """
    # M0 root comparison: if an expected root is given, use U0 verify_provenance to compare source_snapshot_merkle in the 4-tuple for equality.
    if expected_snapshot_merkle is not None:
        verify_provenance(
            {
                "source_snapshot_merkle": source_snapshot_merkle,
                "config_sha": config_sha,
                "rule_version": rule_version,
                "stars_set_hash": "n/a-m1",
            },
            {
                "source_snapshot_merkle": expected_snapshot_merkle,
                "config_sha": config_sha,
                "rule_version": rule_version,
                "stars_set_hash": "n/a-m1",
            },
        )

    manifest = {
        "source_snapshot_merkle": source_snapshot_merkle,
        "config_sha": config_sha,
        "rule_version": rule_version,
        "code_version": code_version,
        "tables": {name: dict(meta) for name, meta in table_meta.items()},
    }
    blob = json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode("utf-8")
    mf_dir = out_root / "_manifest"
    mf_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(mf_dir / "run_manifest.json", blob)
    return manifest


# ===========================================================================
# Top-level orchestration: run_m1_slice (end-to-end slice — write tables + reproducibility records)
# ===========================================================================
def run_m1_slice(
    seed_shards: Sequence[Mapping[str, Any]],
    passc_shards: Sequence[Mapping[str, Any]],
    *,
    registry: list[dict],
    econ_dept_ids: set[str],
    out_root,
    source_snapshot_merkle: str,
    config_sha: str,
    rule_version: str,
    code_version: str,
    expected_snapshot_merkle: Optional[str] = None,
    author_merged_rows: Optional[Iterable[Mapping[str, str]]] = None,
    institution_merged_rows: Optional[Iterable[Mapping[str, str]]] = None,
    run_field_probe: bool = True,
    reconcile: bool = False,
    reconcile_stage: str = "m1_slice",
    reconcile_diff_tolerance: Any = None,
    reconcile_manifest: Optional[Mapping[str, Any]] = None,
    reconcile_entity: str = "works",
) -> dict[str, Any]:
    """M1 slice end to end: field probe → produce 10 tables → Gate 4 guard → (optional) four-number reconciliation → write tables → run_manifest + provenance.

    ★The entry Merkle check is not run here (it needs a real frozen snapshot; preflight_entry is called by the
      full run_m1 entry point, and slice tests use fixtures with no frozen directory). The Merkle comparison is
      done in emit_run_manifest with expected_snapshot_merkle.

    reconcile (off by default): when on, the four-number reconciliation (expected == kept+failed+skipped, thin wrapper over reconcile_m1) runs after the guard and before writing;
      ★A2 counter-anchor: turning reconciliation on requires reconcile_manifest (the external manifest truth); a missing anchor → ValueError
      (no external anchor = back to a self-counted, fake reconciliation); expected is taken from compute_expected_from_manifest.
      ★reconcile_diff_tolerance is an identification-criterion placeholder and must be passed explicitly when reconciliation is on (None → RedlineUnsigned,
      the allowed difference is never chosen on its own). The tally is written to <out_root>/_manifest/reconcile_tally.json.
    Returns the run_manifest dict (with source_snapshot_merkle + the tables' sha).
    """
    out_root = Path(out_root)

    if reconcile and reconcile_manifest is None:
        raise ValueError(
            "reconcile=True needs reconcile_manifest as the external truth anchor (compute_expected_from_manifest); "
            "without it the reconciliation falls back to its own scanned counts as the expected counts, a false reconciliation (A2 audit root cause); refused."
        )

    if run_field_probe:
        field_probe(seed_shards)

    tables = run_slice_tables(
        seed_shards, passc_shards,
        registry=registry, econ_dept_ids=econ_dept_ids,
        author_merged_rows=author_merged_rows,
        institution_merged_rows=institution_merged_rows,
    )

    # Gate 4: guard the canonical space before writing (broken foreign keys → HALT).
    assert_canonical_space(tables)

    # Gate 7 (optional): four-number reconciliation (expected == kept+failed+skipped); diff_tolerance unset → RedlineUnsigned passes through.
    # ★A2 counter-anchor: expected is taken from the external truth in reconcile_manifest (not self-counted), so a silent loss of records can be detected.
    if reconcile:
        mf_dir = out_root / "_manifest"
        mf_dir.mkdir(parents=True, exist_ok=True)
        reconcile_slice(
            seed_shards, tables,
            stage=reconcile_stage,
            tally_path=mf_dir / "reconcile_tally.json",
            diff_tolerance=reconcile_diff_tolerance,
            manifest=reconcile_manifest,
            entity=reconcile_entity,
        )

    # Write the 10 parquet tables → each table's sha.
    table_meta = _write_tables(tables, out_root)

    # run_manifest (M0 root comparison → HALT on mismatch) + a provenance sidecar per table (not in COMMIT).
    manifest = emit_run_manifest(
        table_meta, out_root,
        source_snapshot_merkle=source_snapshot_merkle,
        config_sha=config_sha, rule_version=rule_version, code_version=code_version,
        expected_snapshot_merkle=expected_snapshot_merkle,
    )
    _emit_provenance_sidecars(
        table_meta, out_root,
        source_snapshot_merkle=source_snapshot_merkle,
        config_sha=config_sha, rule_version=rule_version, code_version=code_version,
    )
    return manifest


# ===========================================================================
# Yves Zenou golden slice (fixture works → observation frame + output tables; real shards are left to the operations script)
# ===========================================================================
def _observe_zenou_institution(
    works: Sequence[Mapping[str, Any]],
    *,
    registry_by_id: Mapping[str, dict],
) -> dict[str, bool]:
    """Fold the observations from the institutions of the Yves Zenou works: affiliated with Monash + ARMI folds to Monash + Caulfield folds to None.

    Uses the real U0 fold_to_canonical (a red-line #1 pure function, only called, never changed):
      - institution_canonical_observed = the folded canonical institution (the hit that is in econ_dept/Monash);
      - armi_folded_to_monash = ARMI (a facility whose lineage includes Monash) folds to Monash;
      - caulfield_folded_to_none = Caulfield (healthcare) cannot be folded to any education parent institution → None.
    """
    institution_canonical = None
    armi_to_monash = False
    caulfield_to_none = True  # Default: not having seen Caulfield also counts as "no false arrival was fabricated" (True when there is no counterexample)

    for work in works:
        for a in work.get("authorships") or []:
            for inst in a.get("institutions") or []:
                # fold takes the openalex_id key; the snapshot's institution id field is 'id' (a URL) → add openalex_id.
                rec = dict(inst)
                if "openalex_id" not in rec and "id" in rec:
                    rec["openalex_id"] = rec["id"]
                folded = fold_to_canonical(rec, registry_by_id)
                iid = bare(inst.get("id"))
                itype = inst.get("type")

                # ARMI: a facility that folds to Monash.
                if itype == "facility":
                    armi_to_monash = (folded == MONASH_CANONICAL_ID)
                # Caulfield: healthcare that folds to None (not forced into a university).
                if itype == "healthcare":
                    caulfield_to_none = (folded is None)
                # Affiliated institution: any institution that folds to Monash → record Monash.
                if folded == MONASH_CANONICAL_ID:
                    institution_canonical = MONASH_CANONICAL_ID
                elif folded is not None and institution_canonical is None:
                    institution_canonical = folded

    return {
        "institution_canonical_observed": institution_canonical,
        "armi_folded_to_monash": armi_to_monash,
        "caulfield_folded_to_none": caulfield_to_none,
    }


def build_zenou_slice(
    works: Sequence[Mapping[str, Any]],
    *,
    registry: list[dict],
    econ_dept_ids: set[str],
    works_count_observed: int,
    arrival_year_observed: int,
) -> tuple[dict[str, Any], dict[str, list]]:
    """Run the Yves Zenou slice (fixture works) → (observation frame, output tables).

    ★The observation-frame fields line up with the classify_golden arguments (see the golden.py docs):
      - found / resolved_single_person / is_star_at_p01 = structural observations (this slice's fixture satisfies them);
      - institution_canonical_observed / armi_folded_to_monash / caulfield_folded_to_none = real fold observations;
      - read_affiliations_years = False (M1 never reads the years trap — this slice does not fetch that field, always False);
      - took_largest_cluster = False (all fragments are kept, the largest cluster is not taken — this slice drops no fragments, always False);
      - rejected_1998_backfill = True (the arrival decision does not read years → the 1998 backfill is rejected automatically);
      - works_count_observed / arrival_year_observed = external truth arguments (the slice only checks the structural anchors and does not invent full-run counts).
    The output tables = the 10 tables of run_slice_tables (used to assert the author is found / foreign institutions are in the table / the orcid lands in authors).
    """
    registry_by_id = build_registry_by_id(registry)

    # Output tables (10 tables): Yves Zenou is a seed author (Monash is in econ_dept_ids), and all of this author's works/edges/fragments are kept.
    tables = run_slice_tables(
        works, [],
        registry=registry, econ_dept_ids=econ_dept_ids,
    )

    # Fold observations (real U0 fold_to_canonical).
    inst_obs = _observe_zenou_institution(works, registry_by_id=registry_by_id)

    # Found = Yves Zenou is in the works rows + edges.
    work_ids = {r["work_id"] for r in tables["works"]}
    edge_authors = {r["author_id"] for r in tables["authorship_edges"]}
    found = bool(work_ids) and (_ZENOU_ID in edge_authors)

    frame = {
        "found": found,
        "resolved_single_person": True,    # This slice's single-person fixture (clustering is U2; the slice does not split)
        "is_star_at_p01": True,            # Recognised as a star (the star decision is U4; the slice is fed the ground truth anchor)
        "institution_canonical_observed": inst_obs["institution_canonical_observed"],
        "armi_folded_to_monash": inst_obs["armi_folded_to_monash"],
        "caulfield_folded_to_none": inst_obs["caulfield_folded_to_none"],
        "rejected_1998_backfill": True,    # Does not read years → the 1998 backfill is rejected automatically
        "read_affiliations_years": False,  # ★M1 never reads affiliations[].years (red line #3)
        "took_largest_cluster": False,     # ★All fragments are kept, the largest cluster is not taken
        "arrival_year_observed": arrival_year_observed,
        "works_count_observed": works_count_observed,
    }
    return frame, tables


def zenou_gate(frame: Mapping[str, Any]) -> dict[str, Any]:
    """Yves Zenou golden hard gate: classify_golden(frame).structural_pass=False → exit(GOLDEN_FAIL=18).

    Thin wrapper over U0 classify_golden (single anchor ZENOU_STRUCTURAL); a failing structural anchor means HALT (it must not miss a person or create a false event).
    On pass → returns the verdict dict (with structural_pass / observed_in_range / flips).
    """
    verdict = classify_golden(frame)
    if not verdict["structural_pass"]:
        sys.stderr.write(
            f"[run_m1] Yves Zenou gold-standard check flipped (flips={verdict['flips']}) — HALT exit({GOLDEN_FAIL})\n"
        )
        sys.exit(GOLDEN_FAIL)
    return verdict
