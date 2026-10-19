"""m5b_aggregate/star_coauthored_works.py — exclusion-set export.

Definition:
  - **star_set is the single source** (#2/C1): the exclusion set is derived from the star_set boolean flags; the
    is_star_coauthored function is never imported and the same-named marker column of PAPER_CONTRIB is never read;
  - **the shipped-set definition matches events**: p01 <=> is_star_1pct AND is_foreign_poach /
    p05 <=> is_star_5pct AND is_foreign_poach (U4 10c real data: 28 people at 5pct, 12 of them with poach —
    non-poached stars do not enter the shipped exclusion set; source_filter=foreign_poach_only, set in the RED star section);
  - star_set is keyed by author_id -> folded to person_id through the U2 person_map (the linking layer);
    stars whose fragment has no mapping are counted with a WARN, not silent, and author_id is never used as a placeholder (old defect #33);
  - **whole-history exclusion** `star_coauthored_paper_alltime` (the output-side named window of #8): for each work,
    author person set intersecting star_pids is non-empty -> it enters the exclusion set; **never walk the co-authorship graph** (#35 first-order rule);
    it is a different function from the dose-side `coauthor_pre_arrival` (frozen at t-1), and they are never reused for each other (#48b).
"""
from __future__ import annotations

import warnings

# Shipped-set definition: p_level label <=> star_set boolean flag (fixed mapping; an unknown p_level -> raise).
SHIP_P_LEVEL_FLAG: dict[str, str] = {
    "p01": "is_star_1pct",
    "p05": "is_star_5pct",
}

# Output-side named-window constant of #8 (deliberately a different name and window from the dose-side coauthor_pre_arrival).
STAR_COAUTHORED_PAPER_ALLTIME = "star_coauthored_paper_alltime"


def ship_star_person_ids(star_rows, person_map_rows, *, p_level: str):
    """star_set -> person_id set of shipped-set stars (flag AND is_foreign_poach, folded through person_map).

    Rules:
      - p_level accepts only "p01"/"p05" (fixed by SHIP_P_LEVEL_FLAG; anything else -> ValueError);
      - the flag and is_foreign_poach must both be True (thin circle None != True; non-poached stars do not enter the shipped set);
      - fragment with no mapping: counted + UserWarning (not silent), and author_id is never used as person_id.

    Returns: (star_person_ids: set[str], n_unmapped: int)
    """
    if p_level not in SHIP_P_LEVEL_FLAG:
        raise ValueError(
            f"ship_star_person_ids: unknown p_level={p_level!r} — accepts only "
            f"{sorted(SHIP_P_LEVEL_FLAG)} (p01⟺is_star_1pct∧poach / "
            "p05⟺is_star_5pct∧poach; the ship-set definition is fixed)"
        )
    flag_col = SHIP_P_LEVEL_FLAG[p_level]

    pid_by_author = {r["author_id"]: r["person_id"] for r in person_map_rows}
    star_pids: set[str] = set()
    unmapped: list[str] = []
    for row in star_rows:
        if row.get(flag_col) is not True:            # None (thin circle) and False are both non-stars
            continue
        if row.get("is_foreign_poach") is not True:  # shipped-set definition: foreign poaching only
            continue
        author_id = row["author_id"]
        person_id = pid_by_author.get(author_id)
        if person_id is None:
            unmapped.append(author_id)
            continue
        star_pids.add(person_id)

    if unmapped:
        warnings.warn(
            f"ship_star_person_ids[{p_level}]: {len(unmapped)} shipped-star author_id(s) "
            f"lack a person_map mapping (neither silently skipped nor given a placeholder): {sorted(unmapped)[:5]}",
            UserWarning,
            stacklevel=2,
        )
    return star_pids, len(unmapped)


def star_coauthored_paper_alltime(star_pids, authorship_edges,
                                  person_map_rows) -> frozenset:
    """Output-side exclusion set (#8, whole history excluded): the set of works whose author person set intersects star_pids.

    Method = per-work intersection of author sets (**never a walk along the co-authorship graph**, #35):
      authorship_edges (author level) are folded to person through person_map -> aggregate each work's author
      person set -> non-empty intersection with star_pids -> the work enters the exclusion set.
    Whole history = no year truncation at all (deliberately unlike the dose-side coauthor_pre_arrival frozen at t-1, #48b).
    Edge authors with no mapping: counted + WARN (not silent; an author who cannot be matched to a person cannot be recognised as a star).
    Returns a frozenset — a work with several stars still enters only once (#34).
    """
    stars = set(star_pids)
    if not stars:
        return frozenset()
    pid_by_author = {r["author_id"]: r["person_id"] for r in person_map_rows}
    excluded: set[str] = set()
    unmapped: set[str] = set()
    for e in authorship_edges:
        pid = pid_by_author.get(e["author_id"])
        if pid is None:
            unmapped.add(e["author_id"])
            continue
        if pid in stars:
            excluded.add(e["work_id"])
    if unmapped:
        warnings.warn(
            f"star_coauthored_paper_alltime: {len(unmapped)} edge-table author_id(s) lack a "
            f"person_map mapping (not silently ignored): {sorted(unmapped)[:5]}",
            UserWarning,
            stacklevel=2,
        )
    return frozenset(excluded)
