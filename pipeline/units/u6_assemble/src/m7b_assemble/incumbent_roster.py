"""incumbent_roster: the C1 three-step folding chain + the fixed D2/D3/D5 values.

Chain (C1/B6-TABLEB-SHAPE):
  table B (author_id, interval) -> fold person_id via person_map -> expand the interval into years
  -> bridge table A openalex_inst_id dept_key -> events.dept_id space.

Employed-year derivation (late binding: table B employment interval + panel missing year = fact):
  - both interval ends known  -> closed interval [year_start, year_end] (roster_interval basis)
  - only one end known        -> the known end bounds, the unknown end is open (roster_partial basis)
  - both ends null            -> bind the years in which the panel primary affiliation
                                 (primary_affil_id == that department's university canonical id)
                                 holds (panel_bound basis). Membership authority is still table B;
                                 the panel only "binds the years", and modal_hint takes no part (never treated as authority).
  Counts per basis go into diag (for audit; for the two universities most rows are null-null: UNSW 49/54).

pop-min (D5/#9): the population inclusion threshold for incumbents is >=2 distinct publication years;
  a single definition, a sample-composition default, not an identification red line; the redundant old ">=1 paper" gate is removed.

nt-pool (D2/#6, plan B): never-treated pool = table B department set minus the departments that ever appear in events
  ("zero pure-foreign star arrivals over the whole 2000-2025 span"). For the two universities both departments appear in events ->
  the pool is empty -> record it and leave it open for the 11-university stage, without fabricating or raising; thin-arm fallback =
  report_not_yet_treated_only (RED groups_control).

CEM (D3/#2): matching variables = the 4 fixed ones (output trend / career length / output cadence / collaboration scale);
  field proximity is a bad control and is deliberately excluded (#2). Coarsening bins are an engineering-layer choice (inactive while the pool is empty,
  to be reviewed manually before the 11-university stage).
"""
from __future__ import annotations

from typing import Any, Callable, Iterable

from common._redlines import RED
from common.schema import DEPT_ROSTER_PANEL, ECON_DEPT_REGISTRY, \
    assert_matches_schema

# D5/#9: >=2 distinct publication years (see the pop_min_ok docstring for the token guard).
POP_MIN_DISTINCT_YEARS: int = 2

# D3/#2: the 4 matching variables (following the semantics of contracts/redlines.yaml groups_control.match_vars;
# the yaml uses short names, this module uses feature-row key names. Correspondence: output_trend/career_length/
# output_cadence/collaboration_scale).
CEM_VARS: tuple = ("output_trend", "career_length", "output_cadence",
                   "collaboration_scale")

# D3/#2: field proximity = bad control, deliberately excluded from matching (the fixed value is read at module level,
# with zero references inside the cem_match function body; the tests prove the exclusion by behavior).
_BAD_CONTROL_EXCLUDED: bool = bool(
    RED["groups_control"]["exclude_field_proximity_from_match"])

_PANEL_MAX_YEAR = 2026        # Cap for open intervals beyond the frame window's upper limit (engineering constant, the latest panel year)


# ---------------------------------------------------------------------------
# (a)+(b) table B -> person folding (unfolded rows are counted with a WARN, no crash)
# ---------------------------------------------------------------------------
def fold_roster_to_persons(roster_rows: Iterable[dict],
                           person_map_rows: Iterable[dict]) -> tuple[list, dict]:
    """Fold table B author_id into person_id via person_map.

    Returns (members, diag):
      members = [{person_id, dept_key, year_start, year_end, author_id}]
      diag    = {n_roster_rows, n_unmapped_author_rows, unmapped_author_ids,
                 n_persons}
    Unfolded rows (author_id has no mapping / author_id is None) are counted into diag (sidecar + WARN),
    neither silently dropped nor crashing.
    """
    pid_by_author = {r["author_id"]: r["person_id"] for r in person_map_rows}
    members: list[dict] = []
    unmapped: list = []
    n_rows = 0
    for r in roster_rows:
        assert_matches_schema(r.keys(), DEPT_ROSTER_PANEL, label="dept_roster")
        n_rows += 1
        author = r["author_id"]
        pid = pid_by_author.get(author) if author is not None else None
        if pid is None:
            unmapped.append(author)
            continue
        members.append({
            "person_id": pid, "dept_key": r["dept_key"],
            "year_start": r["year_start"], "year_end": r["year_end"],
            "author_id": author,
            "human_verified": bool(r.get("human_verified")),
        })
    diag = {
        "n_roster_rows": n_rows,
        "n_unmapped_author_rows": len(unmapped),
        "unmapped_author_ids": sorted(str(a) for a in unmapped),
        "n_persons": len({m["person_id"] for m in members}),
    }
    return members, diag


# ---------------------------------------------------------------------------
# (d) table A bridge: dept_key -> university-level canonical inst id (events.dept_id space)
# ---------------------------------------------------------------------------
def bridge_dept_to_inst(registry_rows: Iterable[dict]) -> dict[str, str]:
    """Table A `openalex_inst_id` = bridge from department-level dept_key to university-level canonical id (C1/T19).

    This column of table A is written by U0.5 after human checking and is already the canonical education parent (same space as
    events.dept_id), so no further institution folding is needed; U6 does not load the full institutions table (engineering note).
    """
    bridge: dict[str, str] = {}
    for r in registry_rows:
        assert_matches_schema(r.keys(), ECON_DEPT_REGISTRY, label="econ_registry")
        bridge[r["dept_key"]] = r["openalex_inst_id"]
    return bridge


# ---------------------------------------------------------------------------
# (c) interval year expansion + late binding -> employed-year index
# ---------------------------------------------------------------------------
class InDeptIndex:
    """person -> set of employed years (union across sample departments) + departure year (for the attrition diagnostic)."""

    def __init__(self) -> None:
        self._years: dict[str, set] = {}
        self._end: dict[str, Any] = {}
        self.basis_counts: dict[str, int] = {
            "roster_interval": 0, "roster_partial": 0, "panel_bound": 0,
            "unbound": 0,
        }
        # Roster conflict resolution diag (filled by build_in_dept_index)
        self.conflict_diag: dict = {}

    def years(self, person_id: str) -> frozenset:
        return frozenset(self._years.get(person_id, ()))

    def membership_end(self, person_id: str):
        """Latest known departure year (the maximum year_end over all member intervals); if any interval is open -> None
        (still employed). A person with no record -> None."""
        return self._end.get(person_id)

    def persons(self) -> list:
        return sorted(self._years)


def _intervals_overlap(a: dict, b: dict) -> bool:
    """Whether two roster-row intervals overlap; a None end counts as open (±inf), so an open row overlaps everything."""
    lo_a = a["year_start"] if a["year_start"] is not None else float("-inf")
    hi_a = a["year_end"] if a["year_end"] is not None else float("inf")
    lo_b = b["year_start"] if b["year_start"] is not None else float("-inf")
    hi_b = b["year_end"] if b["year_end"] is not None else float("inf")
    return max(lo_a, lo_b) <= min(hi_a, hi_b)


def resolve_roster_conflicts(members: Iterable[dict]) -> tuple[list, dict]:
    """Roster conflict resolution.

    Root cause: several roster rows for the same person in the same department were unioned indiscriminately into the employed interval, and human_verified was never consumed
    (overlap case: an unverified official_roster 2009-2024 widened a person's verified 2023-2025 interval, and
    zero-output years outside the interval were wrongly filled with 0 instead of NA).
    Rule (within the same person and the **same department**):
      - When a human-verified row exists: an unverified row whose interval overlaps any human-verified row is dropped (superseded);
        an unverified row that does not overlap is kept (another spell of employment, which the verified row does not contradict).
      - When there is no human-verified row: union as is. Never naively "use only verified rows" (that would turn a person with no verified rows entirely to NA).
    Returns (kept_members, diag); the keep/drop decision of each row is auditable.
    """
    members = list(members)
    ver_by_pd: dict[tuple, list] = {}
    for m in members:
        if m.get("human_verified"):
            ver_by_pd.setdefault((m["person_id"], m["dept_key"]), []).append(m)
    kept: list = []
    superseded: list = []
    for m in members:
        vs = ver_by_pd.get((m["person_id"], m["dept_key"]))
        if vs and not m.get("human_verified") \
                and any(_intervals_overlap(m, v) for v in vs):
            superseded.append(m)
        else:
            kept.append(m)
    diag = {
        "n_members_in": len(members),
        "n_superseded_unverified_rows": len(superseded),
        "superseded_rows": sorted(
            f"{m['person_id']}|{m['dept_key']}|{m['year_start']}-{m['year_end']}"
            for m in superseded),
    }
    return kept, diag


def build_in_dept_index(members: Iterable[dict], panel_rows: Iterable[dict],
                        bridge: dict) -> InDeptIndex:
    """Employed-year derivation (the late-binding rule in the module docstring; the basis is counted per interval).

    First runs resolve_roster_conflicts: human-verified rows take priority,
    and overlapping unverified rows no longer enter the union; the resolution diag is attached as idx.conflict_diag (written out in coverage).
    """
    members, conflict_diag = resolve_roster_conflicts(members)
    affil_years: dict[tuple, set] = {}
    for p in panel_rows:
        affil_years.setdefault((p["person_id"], p["primary_affil_id"]),
                               set()).add(p["year"])

    idx = InDeptIndex()
    idx.conflict_diag = conflict_diag
    closed_ends: dict[str, int] = {}
    open_ended: set = set()
    for m in members:
        pid = m["person_id"]
        ys, ye = m["year_start"], m["year_end"]
        years: set = set()
        if ys is not None and ye is not None:
            years = set(range(int(ys), int(ye) + 1))
            idx.basis_counts["roster_interval"] += 1
        elif ys is not None:                       # Known start, open end = still employed
            years = set(range(int(ys), _PANEL_MAX_YEAR + 1))
            idx.basis_counts["roster_partial"] += 1
        elif ye is not None:                       # Open start, known end
            inst = bridge.get(m["dept_key"])
            bound = affil_years.get((pid, inst), set())
            start = min(bound) if bound else int(ye)
            years = set(range(int(start), int(ye) + 1))
            idx.basis_counts["roster_partial"] += 1
        else:                                      # Both null -> panel late binding
            inst = bridge.get(m["dept_key"])
            bound = affil_years.get((pid, inst), set())
            if bound:
                years = set(bound)
                idx.basis_counts["panel_bound"] += 1
            else:
                idx.basis_counts["unbound"] += 1
        if years:
            idx._years.setdefault(pid, set()).update(years)
        # Departure-year material: a closed interval contributes its end; an open end (ye=None) = the person is still employed.
        # null-null = on the current roster (the scraped current roster has no history) -> treated as open (still employed).
        if ye is not None:
            closed_ends[pid] = max(closed_ends.get(pid, int(ye)), int(ye))
        else:
            open_ended.add(pid)
    for pid, end in closed_ends.items():
        if pid not in open_ended:                  # A definite departure year exists only if all intervals are closed
            idx._end[pid] = end
    return idx


# ---------------------------------------------------------------------------
# pop-min (D5/#9; single definition, redundant old gate removed)
# ---------------------------------------------------------------------------
def distinct_pub_years(panel_rows: Iterable[dict]) -> dict[str, int]:
    """person -> number of distinct publication years (years where the panel row has n_works_year>0)."""
    out: dict[str, set] = {}
    for p in panel_rows:
        if (p.get("n_works_year") or 0) > 0:
            out.setdefault(p["person_id"], set()).add(p["year"])
    return {k: len(v) for k, v in out.items()}


def pop_min_ok(n_distinct_years: int) -> bool:
    """>= 2 distinct publication years (D5/#9).

    The token comes from RED population_gate.pop_min == "ge_2_distinct_publication_years"
    (a drift sentinel is asserted in the tests); a sample-composition default, not an identification red line.
    """
    token = RED["population_gate"]["pop_min"]
    if token != "ge_2_distinct_publication_years":
        raise ValueError(f"pop-min token has drifted from the pinned value: {token!r}")
    return int(n_distinct_years) >= POP_MIN_DISTINCT_YEARS


# ---------------------------------------------------------------------------
# (e) nt-pool plan B (D2/#6); empty for both universities -> record, do not fabricate
# ---------------------------------------------------------------------------
def never_treated_pool(members: Iterable[dict], events_rows: Iterable[dict],
                       bridge: dict) -> tuple[list, list, dict]:
    """Pool = table B department set minus the departments that appear in events (zero pure-foreign star arrivals over the whole span).

    Returns (pool_dept_keys, candidate_person_ids, diag). Empty pool -> empty table + diag record
    (nt_pool_empty=True + thin_arm_fallback); never raise and never fabricate.
    """
    members = list(members)
    treated_insts = {e["dept_id"] for e in events_rows}
    all_depts = sorted({m["dept_key"] for m in members})
    pool_depts = [d for d in all_depts if bridge.get(d) not in treated_insts]
    candidates = sorted({m["person_id"] for m in members
                         if m["dept_key"] in set(pool_depts)})
    diag = {
        "scheme": "B",
        "never_treated_definition": str(
            RED["groups_control"]["never_treated_definition"]),
        "table_b_depts": all_depts,
        "treated_dept_ids": sorted(treated_insts),
        "nt_pool_depts": pool_depts,
        "nt_pool_empty": not pool_depts,
        "thin_arm_fallback": str(RED["groups_control"]["thin_arm_fallback"]),
    }
    return pool_depts, candidates, diag


# ---------------------------------------------------------------------------
# (f) CEM matching (D3/#2, 4 variables; field proximity is a bad control and deliberately kept out of matching)
# ---------------------------------------------------------------------------
def _coarsen(feat: dict) -> tuple:
    """Coarsened key = coarsened tuple of the 4 fixed variables (reads only the four CEM_VARS keys and ignores every other key).

    Binning (engineering layer, inactive while the pool is empty; to be reviewed manually before the 11-university stage):
      output_trend -> sign (-1/0/1); career_length -> 5-year buckets;
      output_cadence -> 1 bucket; collaboration_scale -> 2 buckets.
    """
    trend = feat["output_trend"]
    sign = 0 if trend == 0 else (1 if trend > 0 else -1)
    return (
        sign,
        int(feat["career_length"]) // 5,
        int(feat["output_cadence"]) // 1,
        int(feat["collaboration_scale"]) // 2,
    )


def cem_match(treated_features: list, candidate_features: list) \
        -> tuple[list, dict]:
    """CEM coarsened exact matching -> C rows (GROUPS_ABC semantics: event_id = matched FK, not minted).

    treated_features row keys: incumbent_person_id/event_id/star_person_id + the 4 fixed variables;
    candidate_features row keys: person_id/control_star_person_id + the 4 fixed variables.
    A candidate may carry any number of extra keys; the implementation reads only the 4 fixed variables (the tests prove that the exclusion takes effect by behavior).
    """
    cands_by_key: dict[tuple, list] = {}
    for c in candidate_features:
        cands_by_key.setdefault(_coarsen(c), []).append(c)

    c_rows: list[dict] = []
    n_unmatched = 0
    for t in treated_features:
        pool = cands_by_key.get(_coarsen(t), [])
        if not pool:
            n_unmatched += 1
            continue
        for c in pool:
            c_rows.append({
                "incumbent_person_id": c["person_id"],
                "star_person_id": c["control_star_person_id"],
                "event_id": t["event_id"],          # matched FK, not silently minted
                "treated": False,
                "control_star_person_id": c["control_star_person_id"],
                "matched_treated_event_id": t["event_id"],
            })
    diag = {
        "cem_vars": list(CEM_VARS),
        "bad_control_excluded": _BAD_CONTROL_EXCLUDED,
        "n_treated_features": len(treated_features),
        "n_candidates": len(candidate_features),
        "n_c_rows": len(c_rows),
        "n_unmatched_treated": n_unmatched,
        "thin_arm_fallback_triggered": not c_rows,
    }
    return c_rows, diag
