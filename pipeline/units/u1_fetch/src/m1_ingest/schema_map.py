"""M1-T1 schema_map.py — anchor mapping snapshot works JSON fields → U0 schema columns (the single source of truth for field mapping).

What it does (following the official field mapping):
  - bare(oid): strip the OpenAlex URL prefix to get the bare id; idempotent; None/"" → None (reuses _writer_util, single source of truth).
  - assert_snapshot_fields_present: sample n records and probe the required keys; a missing key → sys.exit(EXIT_FIELDS_MISSING=19)
    (a drift safety net; all measured fields are present, so it normally PASSES).
  - flatten_work: one work → a WORKS 12-column row (missing fields get a None placeholder, no row is dropped).
      subfield_id is taken from primary_topic.subfield.id as the URL tail segment (★not ==int; int→str breaking change).
  - iter_authorship_edges: each authorship is flattened into exactly 3 AUTHORSHIP_EDGES columns (★never contains raw_affil/institution_id, HIGH-4).
  - iter_referenced_edges: each referenced_works entry is flattened into REFS_EDGES (★column name referenced_work_id follows the official anchor, not ref_work_id).
  - iter_works_affil_rows (Gate 3): each authorship×institution is flattened into WORKS_AFFIL 4 columns;
      an empty institutions list still yields one row with institution_id=None (raw_affil is kept for disambiguation).
  - iter_institutions / flatten_institution (Gate 1): each institution inside each authorship yields an INSTITUTIONS 7-column row
      (foreign ones included, no Australia filter; C-A: country_code is what decides whether an institution is foreign, as in the Yves Zenou case; associated_institutions keeps list<dict>).
  - re-export reconstruct_abstract (implemented in abstract_reverse.py).

Official usage notes:
  Work fields (work-object README) + authorship (authorship-object.md) +
  topic/subfield id int→str (take the tail of the URL string) + institution is often None/empty + related_works ≠ references.

Neutral on identification criteria: pure field copying/shaping, no identification threshold, no network; it faithfully writes bare values and
  does not apply the economics-department whitelist (that filter is the keep_pred in run_m1/passes; G5 whitelist: include 2002 / exclude 2003 + field14).
"""
from __future__ import annotations

from typing import Iterator, Optional

from identity.exit_codes import EXIT_FIELDS_MISSING

# bare-id normalisation + URL prefix: reuses the _writer_util single source of truth (the same implementation as the five new table writers, not rewritten).
from m1_ingest._writer_util import bare, OPENALEX_URL_PREFIX  # noqa: F401  (re-export)

# Abstract inversion: re-exports the abstract_reverse implementation (schema_map is the unified entry point and does not duplicate the inversion logic).
from m1_ingest.abstract_reverse import reconstruct_abstract  # noqa: F401  (re-export)

# Institution flattening, INSTITUTIONS 7 columns: re-exports the [single authoritative implementation] in institutions.py (DRY, Gate 1).
#   schema_map used to carry its own flatten_institution/iter_institutions that behaved differently from institutions.py:
#   here associated_institutions was only passed through as list(...) (ids stay in URL form, non-dict entries are not filtered), while there _norm_assoc
#   normalises it to the fixed keys {id(bare), relationship, type} (which fold_to_canonical path3 depends on). Two copies side by side = a bug.
#   The authority is institutions.py (it reads relationship/type/id correctly + bare institution ids + is consistent with fold path3);
#   schema_map now re-exports it, which removes the behavioural divergence.
from m1_ingest.institutions import (  # noqa: F401  (re-export, single source of truth)
    flatten_institution,
    iter_institutions,
)


# Required snapshot keys that are measured to be present (the drift probe asserts these; missing = snapshot drift → exit loudly).
SNAPSHOT_REQUIRED_FIELDS = (
    "id",
    "publication_year",
    "type",
    "cited_by_count",
    "referenced_works",
    "authorships",
    "primary_topic",
)

# Optional keys (missing = normal, stored as None, no exit; FWCI/percentile/paratext/abstract can be absent because they are too new or paratext may be missing).
SNAPSHOT_OPTIONAL_FIELDS = (
    "fwci",
    "citation_normalized_percentile",
    "is_paratext",
    "is_retracted",
    "abstract_inverted_index",
)


def assert_snapshot_fields_present(records, *, n: int = 200) -> None:
    """Sample the first n snapshot records and probe whether all of SNAPSHOT_REQUIRED_FIELDS are present.

    Any missing required key → sys.exit(EXIT_FIELDS_MISSING=19) (a drift safety net, not a BLOCKER;
    all measured fields are present, so it normally PASSES). A missing key is never waved through silently.
    """
    import sys

    for i, rec in enumerate(records):
        if i >= n:
            break
        missing = [k for k in SNAPSHOT_REQUIRED_FIELDS if k not in rec]
        if missing:
            sys.stderr.write(
                f"[schema_map] snapshot record lacks required keys {missing} (rec id={rec.get('id')!r}); "
                f"suspected snapshot drift -> exit({EXIT_FIELDS_MISSING})\n"
            )
            sys.exit(EXIT_FIELDS_MISSING)


def _subfield_id(work: dict) -> Optional[str]:
    """primary_topic.subfield.id → bare tail segment (URL string ".../subfields/2002" → "2002"). Single source of truth.

    Pinned down: take the tail of the URL string and never compare it as an int (== 2002 would silently match 0 rows).
    Missing primary_topic / subfield / id (including the empty string "") → None.
    fwci_accumulator imports this function from here (DRY, no more private copies).
    """
    pt = work.get("primary_topic") or {}
    sf = pt.get("subfield") or {}
    sid = sf.get("id")
    if sid is None or sid == "":
        return None
    # URL form → tail segment; already a bare digit string → unchanged.
    return str(sid).rsplit("/", 1)[-1]


def _percentile_flags(work: dict):
    """citation_normalized_percentile → (is_in_top_1_percent, is_in_top_10_percent). Missing → (None, None)."""
    cnp = work.get("citation_normalized_percentile")
    if not cnp:
        return (None, None)
    return (cnp.get("is_in_top_1_percent"), cnp.get("is_in_top_10_percent"))


def flatten_work(work: dict) -> dict:
    """One work → a WORKS 12-column row (missing fields get a None placeholder, no row is dropped).

    Mapping (official anchor):
      id→work_id(bare) / publication_year / type→work_type /
      primary_topic.subfield.id→subfield_id(URL tail segment) / fwci / cited_by_count /
      len(referenced_works)→referenced_works_count / has_references / is_paratext /
      is_retracted / citation_normalized_percentile.is_in_top_1/10_percent.
    """
    refs = work.get("referenced_works") or []
    top1, top10 = _percentile_flags(work)
    has_refs = work.get("has_references")
    if has_refs is None:
        # Without an explicit has_references, True is not forced; it is inferred as True only when a reference list really exists, otherwise None/False keeps it truthful.
        has_refs = bool(refs) if refs else (False if "referenced_works" in work else None)
    return {
        "work_id": bare(work.get("id")),
        "publication_year": work.get("publication_year"),
        "work_type": work.get("type"),
        "subfield_id": _subfield_id(work),
        "fwci": work.get("fwci"),
        "cited_by_count": work.get("cited_by_count"),
        "referenced_works_count": len(refs),
        "has_references": has_refs,
        "is_paratext": work.get("is_paratext"),
        "is_retracted": work.get("is_retracted"),
        "is_in_top_1_percent": top1,
        "is_in_top_10_percent": top10,
    }


def iter_authorship_edges(work: dict) -> Iterator[dict]:
    """Each authorship → exactly 3 AUTHORSHIP_EDGES columns {work_id, author_id, publication_year}.

    ★HIGH-4: never add raw_affil / institution_id (that would break the 3 columns pinned by the contract; the raw institution data goes to the separate works_affil table).
    """
    wid = bare(work.get("id"))
    pub_year = work.get("publication_year")
    for a in work.get("authorships") or []:
        author = a.get("author") or {}
        yield {
            "work_id": wid,
            "author_id": bare(author.get("id")),
            "publication_year": pub_year,
        }


def iter_referenced_edges(work: dict) -> Iterator[dict]:
    """Each referenced_works entry → REFS_EDGES {work_id, referenced_work_id}.

    ★The column name is referenced_work_id (following the official anchor, not ref_work_id; DA-6b).
    ★related_works ≠ references; this function only reads referenced_works.
    """
    wid = bare(work.get("id"))
    for rw in work.get("referenced_works") or []:
        yield {
            "work_id": wid,
            "referenced_work_id": bare(rw),
        }


def iter_works_affil_rows(work: dict) -> Iterator[dict]:
    """Each authorship × institution → WORKS_AFFIL 4 columns (Gate 3).

    {work_id, author_id, institution_id, raw_affiliation_strings}:
      - raw_affiliation_strings keeps list<str> as is, not flattened (essential for disambiguation; the fallback when institutions are empty);
      - empty institutions → still one row with institution_id=None (raw_affil is left for U2 clustering);
      - several institutions → one row per institution (several rows for the same work×author).
    """
    wid = bare(work.get("id"))
    for a in work.get("authorships") or []:
        author = a.get("author") or {}
        aid = bare(author.get("id"))
        raw = a.get("raw_affiliation_strings") or []
        insts = a.get("institutions") or []
        if not insts:
            # A failed institution match still yields one row (institution_id=None), with raw_affil as the fallback.
            yield {
                "work_id": wid,
                "author_id": aid,
                "institution_id": None,
                "raw_affiliation_strings": list(raw),
            }
            continue
        for inst in insts:
            yield {
                "work_id": wid,
                "author_id": aid,
                "institution_id": bare(inst.get("id")),
                "raw_affiliation_strings": list(raw),
            }


# flatten_institution / iter_institutions: see the re-export at the top (the single authoritative implementation is in institutions.py).
