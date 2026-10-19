"""Historical roster, byline line, steps 3-6 - strict subfield filter (label, do not delete) / fold to persons /
threshold / interval.

In plain words: take the "person X in department Y in year Z" evidence points of steps 1-2, first attach a share
label by the discipline definition (2002 Economics and Econometrics; a miss is labelled, not deleted), then use
the U2 person map to fold fragment ids into real persons and apply, at the **person** level, the threshold
"at least 2 distinct years in the department" (so that a split-up star is not filtered out by mistake), and finally
build a [start year, end year] candidate interval for every raw id - the end year of a leaver = the last byline year
(never filled with 2025), a missing year only records a gap and creates no row. Output = a candidate skeleton shaped
like Table B (everyone confidence=low + human_verified=False) + stats for all candidates (those that fail the
threshold stay visible, nothing is dropped silently).

Where the rules come from:
  - membership_min: the caller reads the value from require("roster","dept_membership_min") and passes it in.
  - evidence_rule: required, "all" / "printed_only" - how to use stamped strings is undecided, so both
    variants are produced in parallel and no default is given.
  - Main subfield setting "2002": a miss only enters the stats share and no row is deleted.
"""
from __future__ import annotations

import pathlib
import re

import pyarrow.parquet as pq

from common._redlines import require
from common.schema import BYLINE_ROSTER_SKELETON, assert_matches_schema
from roster.byline import _write_det

# The subfield whitelist is read from redlines (single source of truth: when the YAML is edited, this follows automatically).
ECON_SUBFIELDS: frozenset[str] = frozenset(require("subfield_whitelist", "include"))
_EVIDENCE_RULES = ("all", "printed_only")

_STATS_SCHEMA: dict[str, str] = {
    "author_id": "str",
    "dept_key": "str",
    "person_id": "str",
    "in_person_map": "bool",
    "qualified": "bool",
    "n_years": "int32",
    "person_n_years": "int32",
    "n_works": "int32",
    "n_works_printed": "int32",
    "subfield_2002_works": "int32",
    "subfield_2002_share": "float32",
    "gap_years": "list<int16>",
}


def norm_subfield_id(v) -> str | None:
    """Normalize both subfield formats: int 2002 / '2002' / 'subfields/2002' / URL -> '2002'."""
    if v is None:
        return None
    s = str(v)
    m = re.search(r"(\d+)$", s)
    return m.group(1) if m else s


def year_by_pair_from_evidence(evidence_path) -> dict[tuple[str, str], int]:
    """Rebuild (work_id, author_id) -> year from the byline_year_evidence already on disk,
    without rescanning 79 million edges (the source_work_ids provenance column serves exactly this purpose here)."""
    out: dict[tuple[str, str], int] = {}
    for r in pq.read_table(str(evidence_path)).to_pylist():
        for w in r["source_work_ids"]:
            out[(w, r["author_id"])] = int(r["year"])
    return out


def build_skeleton_rows(hits, year_by_pair, subfield_by_work, person_of,
                        *, evidence_rule, membership_min):
    """Pure function: (hits records, year map, subfield map, person map) -> (skeleton rows, stats rows, summary).

    - evidence_rule="printed_only" -> use only printed-form hits (stamp-only years take no part in the threshold/interval);
      "all" -> all hits. How to use the rule is undecided; the runner runs both variants in parallel.
    - The threshold is judged at the person level (person_of folds to persons; an author not in the map counts as its
      own person + is flagged).
    - Skeleton rows are keyed by raw author_id (the Table B primary key); one person, one department, one row [min,max].
    """
    if evidence_rule not in _EVIDENCE_RULES:
        raise ValueError(f"evidence_rule must be one of {_EVIDENCE_RULES}, got {evidence_rule!r}")

    kept = [h for h in hits
            if evidence_rule == "all" or h["match_style"] == "printed"]

    # (author, dept) -> {work: printed?}; **pairs** with a missing year are counted in the summary (by pair, not by row);
    # author_id=None is rejected explicitly (do not rely on the upstream to happen to filter it).
    works_by_ad: dict[tuple[str, str], dict[str, bool]] = {}
    unyeared_pairs: set[tuple[str, str]] = set()
    n_null_author = 0
    for h in kept:
        if h["author_id"] is None:
            n_null_author += 1
            continue
        key = (h["work_id"], h["author_id"])
        if key not in year_by_pair:
            unyeared_pairs.add(key)
            continue
        wb = works_by_ad.setdefault((h["author_id"], h["dept_key"]), {})
        wb[h["work_id"]] = wb.get(h["work_id"], False) or (h["match_style"] == "printed")

    years_by_ad = {
        ad: sorted({year_by_pair[(w, ad[0])] for w in wb})
        for ad, wb in works_by_ad.items()
    }

    # Aggregate distinct years at the person level (judge the threshold after folding to persons)
    person_years: dict[tuple[str, str], set[int]] = {}
    outside_pm: set[str] = set()
    for (a, dk), years in years_by_ad.items():
        pid = person_of.get(a)
        if pid is None:
            pid = a
            outside_pm.add(a)
        person_years.setdefault((pid, dk), set()).update(years)

    skeleton, stats = [], []
    for (a, dk), years in years_by_ad.items():
        pid = person_of.get(a, a)
        p_years = person_years[(pid, dk)]
        qualified = len(p_years) >= membership_min
        wb = works_by_ad[(a, dk)]
        sf = [subfield_by_work.get(w) for w in wb]
        n2002 = sum(1 for s in sf if norm_subfield_id(s) in ECON_SUBFIELDS)
        stats.append({
            "author_id": a, "dept_key": dk, "person_id": pid,
            "in_person_map": a not in outside_pm,
            "qualified": qualified,
            "n_years": len(years), "person_n_years": len(p_years),
            "n_works": len(wb), "n_works_printed": sum(1 for v in wb.values() if v),
            "subfield_2002_works": n2002,
            "subfield_2002_share": (n2002 / len(wb)) if wb else 0.0,
            "gap_years": [y for y in range(years[0] + 1, years[-1]) if y not in set(years)],
        })
        if qualified:
            skeleton.append({
                "dept_key": dk, "author_id": a, "display_name": None,
                "year_start": years[0], "year_end": years[-1],
                "evidence": "raw_affil_year", "confidence": "low",
                "human_verified": False,
            })

    summary = {
        "evidence_rule": evidence_rule,
        "membership_min": membership_min,
        "n_candidates": len(years_by_ad),
        "n_skeleton_rows": len(skeleton),
        "n_qualified_persons": sum(
            1 for (pid, dk), ys in person_years.items() if len(ys) >= membership_min
        ),
        "n_authors_outside_person_map": len(outside_pm),
        "n_unyeared_pairs": len(unyeared_pairs),
        "n_null_author_hits": n_null_author,
    }
    return skeleton, stats, summary


def fill_display_names(skeleton_rows, name_of: dict) -> list[dict]:
    """Fill the name if found, leave None if not (never make up a name)."""
    return [dict(r, display_name=name_of.get(r["author_id"])) for r in skeleton_rows]


def write_skeleton(skeleton_rows, stats_rows, out_dir, *, suffix) -> None:
    """Deterministic write: the skeleton obeys the BYLINE_ROSTER_SKELETON schema (Table B, 8 columns) + stats for all candidates."""
    for r in skeleton_rows:
        assert_matches_schema(r.keys(), BYLINE_ROSTER_SKELETON, label="byline_roster_skeleton")
    out_dir = pathlib.Path(out_dir)
    _write_det(skeleton_rows, dict(BYLINE_ROSTER_SKELETON),
               out_dir / f"byline_roster_skeleton_{suffix}.parquet",
               ("dept_key", "author_id"))
    _write_det(stats_rows, dict(_STATS_SCHEMA),
               out_dir / f"byline_skeleton_stats_{suffix}.parquet",
               ("dept_key", "author_id"))
