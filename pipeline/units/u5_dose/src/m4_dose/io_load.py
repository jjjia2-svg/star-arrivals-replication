"""m4_dose/io_load.py — step 1: input loading and precondition checks.

Job (read the frozen upstream tables -> contract gate -> in-memory handle + validation report; **writes no new table and never writes to the SSD**):
  1. assert_matches_schema contract gate, table by table — the key sets must be exactly equal, and extra or missing
     columns both raise (contract as code; all schema constants are imported from u0 common/schema.py, never re-copied locally).
  2. star_set (currently 14 columns, **keyed by author_id**, as frozen) -> minimal column projection
     {author_id, is_star_1pct, is_star_5pct} -> folded to person_id through the U2 person_map
     (the ranking reference pool is all author_ids; the person key is mapped through person_map).
     Stars whose fragment has no mapping are counted with a WARN, never silently skipped,
     and author_id is never used as a placeholder (#33, the same old defect).
  3. paper_contrib entry assertion on the article+review domain (caveat#4: inherited, not re-filtered; precondition layer of #40c):
     PAPER_CONTRIB has 8 columns and no work_type -> the domain check goes through works.work_type;
     included_types is read from RED fwci.included_types (=[article, review]), not hard-coded.
  4. events.t_minus_1 non-null assertion on direct read (B-EVENTS-T1; the loading-side precondition of #1, that the freeze point is never computed here).
  5. Upstream provenance four-tuple comparison — through common.manifest.verify_provenance;
     any inequality or missing header -> ProvenanceMismatch (HALT, not WARN).

Blocking note: the full freeze of events/paper_contrib still waits for the end of U4 (star_set is frozen) —
  the related tests are marked @depends_on_u4 (B-U4-FROZEN); this module is TDD'd on synthetic fixtures.
"""
from __future__ import annotations

import json
import pathlib
import warnings
from dataclasses import dataclass, field

from common._redlines import require
from common.manifest import ProvenanceMismatch, verify_provenance
from common.schema import (
    AUTHORSHIP_EDGES,
    EVENTS,
    PAPER_CONTRIB,
    PERSON_MAP,
    REFS_EDGES,
    STAR_SET,
    WORKS,
    WORK_TEXT,
    assert_matches_schema,
)

# Fixed mapping between the internal p_level label and the star_set boolean flag column:
# p01/p05 are U5 internal file names / scope labels, not star_set columns; an unknown p_level raises.
_P_LEVEL_FLAG: dict[str, str] = {
    "p01": "is_star_1pct",
    "p05": "is_star_5pct",
}


class DomainViolation(ValueError):
    """paper_contrib contains a work outside the article/review domain (or with no type found) — caveat#4 precondition assertion."""


@dataclass
class U5Inputs:
    """Step 1 product: in-memory handle + precondition validation report (no new table written)."""

    authorship_edges: list = field(default_factory=list)
    refs_edges: list = field(default_factory=list)
    works: list = field(default_factory=list)
    work_text: list = field(default_factory=list)
    person_map: list = field(default_factory=list)
    star_set: list = field(default_factory=list)
    events: list = field(default_factory=list)
    paper_contrib: list = field(default_factory=list)
    star_pids: dict = field(default_factory=dict)          # {"p01": set, "p05": set}
    n_unmapped_star_authors: int = 0
    report: dict = field(default_factory=dict)             # diagnostics go into the report, not mixed into data rows


def load_table(path, schema: dict, *, label: str) -> list[dict]:
    """Read parquet -> contract gate (column set exactly equal to the schema key set) -> list[dict] rows.

    Loading path for synthetic/unit-scale data (the out-of-core path at real-data scale goes through
    the persistent DuckDB database of degree2_closure and is not materialised by this function).
    """
    import pyarrow.parquet as pq

    table = pq.read_table(str(path))
    assert_matches_schema(table.column_names, schema, label=label)
    return table.to_pylist()


def fold_star_person_ids(star_rows, person_map_rows, *, p_level: str):
    """star_set (keyed by author_id) -> set of star person_ids (folded through person_map).

    Rules:
      - p_level accepts only "p01"/"p05" (fixed mapping; anything else -> ValueError);
      - a flag counts as a star only if it is True (thin circle None != True; schema [22] note: those not in the pool are None);
      - fragment with no mapping: counted + UserWarning (**never silent**), and author_id is never used as a
        person_id placeholder (old defect #33: neither skipping a fragment fold nor falling back to canonical_id_map is allowed).

    Returns: (star_person_ids: set[str], n_unmapped: int)
    """
    if p_level not in _P_LEVEL_FLAG:
        raise ValueError(
            f"fold_star_person_ids: unknown p_level={p_level!r} — only {sorted(_P_LEVEL_FLAG)} accepted "
            "(p01⟺is_star_1pct / p05⟺is_star_5pct, fixed mapping)"
        )
    flag_col = _P_LEVEL_FLAG[p_level]

    pid_by_author = {r["author_id"]: r["person_id"] for r in person_map_rows}
    star_pids: set[str] = set()
    unmapped: list[str] = []
    for row in star_rows:
        if row.get(flag_col) is not True:  # None (thin circle) and False are both non-stars
            continue
        author_id = row["author_id"]
        person_id = pid_by_author.get(author_id)
        if person_id is None:
            unmapped.append(author_id)
            continue
        star_pids.add(person_id)

    if unmapped:
        warnings.warn(
            f"fold_star_person_ids[{p_level}]: {len(unmapped)} star author_ids have no "
            f"person_map mapping (unmapped; neither silent nor placeholder): {sorted(unmapped)[:5]}",
            UserWarning,
            stacklevel=2,
        )
    return star_pids, len(unmapped)


def assert_article_review_domain(paper_contrib_rows, works_rows) -> None:
    """caveat#4 precondition assertion (fwci column domain form): **a work with non-NA fwci must be in included_types**.

    Scope correction (following the frozen U4 output):
      the original caveat#4 text is "FWCI keeps only article+review". The domain constraint sits on the **fwci column**,
      not on the whole table's row set. The frozen U4 10c paper_contrib deliberately contains rows of all types
      (preprint/dataset/... all with fwci=NA — run_summary na_counts.excluded_type=4,734), because pub_count is defined as
      "the number of all authored papers, *including papers with missing fwci*". A whole-table domain assertion would
      judge the frozen authoritative anchor to be contaminated — the assertion would be wrong, not the data.
    What is asserted: for a pc work with non-NA fwci, its works.work_type must be in RED
      fwci.included_types ([article, review]); a work with no type found also raises (domain cleanliness
      cannot be proven = fail loud). Rows with fwci NA: any type passes (the count keys still count them).
    """
    included = set(require("fwci", "included_types"))  # [article, review]
    type_by_work = {w["work_id"]: w["work_type"] for w in works_rows}
    for row in paper_contrib_rows:
        fwci = row.get("fwci")
        if fwci is None or (isinstance(fwci, float) and fwci != fwci):
            continue   # NA rows: legitimate members of the count keys, no type gate
        wid = row["work_id"]
        wtype = type_by_work.get(wid)
        if wtype is None:
            raise DomainViolation(
                f"paper_contrib work {wid!r} has a non-NA fwci but no type in works — "
                f"cannot show it is in the article+review domain; fail-loud"
            )
        if wtype not in included:
            raise DomainViolation(
                f"paper_contrib contains a work outside {sorted(included)} with a non-NA fwci: "
                f"{wid!r} type={wtype!r} — U4's FWCI should count only article+review, "
                "upstream contamination"
            )


def assert_events_have_t_minus_1(event_rows) -> None:
    """B-EVENTS-T1: t_minus_1 is non-null on every row — it is the single source of the M4 freeze point, and arrival-1 is never computed as a fallback."""
    for row in event_rows:
        if row.get("t_minus_1") is None:
            raise ValueError(
                f"events row {row.get('event_id')!r} lacks t_minus_1 — the freeze point must be supplied by U4 "
                "EVENTS directly; M4 never falls back to computing arrival_year-1 itself"
            )


def check_upstream_provenance(header_path, expected: dict) -> None:
    """Compare the provenance four-tuple in the upstream artefact header — mismatch / missing header -> ProvenanceMismatch (HALT).

    header_path: manifest_header.json in the upstream output directory (the frozen star_set carries this header).
    expected:    the expected four-tuple (stars_set_hash etc. pinned in config).
    The comparison itself goes through common.manifest.verify_provenance (compares existing strings only, no merkle recomputation).
    """
    p = pathlib.Path(header_path)
    if not p.is_file():
        raise ProvenanceMismatch(
            f"upstream manifest_header missing: {p} — provenance cannot be shown, HALT (not WARN)",
            key="manifest_header",
        )
    header = json.loads(p.read_text(encoding="utf-8"))
    verify_provenance(header, expected)


def load_u5_inputs(paths: dict, *, expected_star_provenance: dict | None = None,
                   p_levels=("p01", "p05")) -> U5Inputs:
    """Load all U5 upstream inputs -> contract gate -> fold/assert -> U5Inputs handle.

    paths has eight keys: authorship_edges / refs_edges / works / work_text / person_map /
                star_set / events / paper_contrib (a missing key -> KeyError, no default).
    When expected_star_provenance is given: manifest_header.json in the star_set directory must be present
    and the four-tuple must match exactly (missing/unequal -> ProvenanceMismatch HALT).
    """
    inputs = U5Inputs()
    inputs.authorship_edges = load_table(paths["authorship_edges"], AUTHORSHIP_EDGES,
                                         label="authorship_edges")
    inputs.refs_edges = load_table(paths["refs_edges"], REFS_EDGES, label="refs_edges")
    inputs.works = load_table(paths["works"], WORKS, label="works")
    inputs.work_text = load_table(paths["work_text"], WORK_TEXT, label="work_text")
    inputs.person_map = load_table(paths["person_map"], PERSON_MAP, label="person_map")
    inputs.star_set = load_table(paths["star_set"], STAR_SET, label="star_set")
    inputs.events = load_table(paths["events"], EVENTS, label="events")
    inputs.paper_contrib = load_table(paths["paper_contrib"], PAPER_CONTRIB,
                                      label="paper_contrib")

    if expected_star_provenance is not None:
        header_path = pathlib.Path(paths["star_set"]).parent / "manifest_header.json"
        check_upstream_provenance(header_path, expected_star_provenance)

    total_unmapped = 0
    for p_level in p_levels:
        pids, n_unmapped = fold_star_person_ids(
            inputs.star_set, inputs.person_map, p_level=p_level
        )
        inputs.star_pids[p_level] = pids
        total_unmapped = max(total_unmapped, n_unmapped)  # the same fragment duplicated at two levels counts once
    inputs.n_unmapped_star_authors = total_unmapped

    assert_events_have_t_minus_1(inputs.events)
    assert_article_review_domain(inputs.paper_contrib, inputs.works)

    inputs.report = {
        "n_star_rows": len(inputs.star_set),
        "n_events": len(inputs.events),
        "n_unmapped_star_authors": total_unmapped,
        "n_paper_contrib": len(inputs.paper_contrib),
        "star_pids_n": {k: len(v) for k, v in inputs.star_pids.items()},
    }
    return inputs
