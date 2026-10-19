"""Three assemblers that build the real-data inputs of events: U3 / table B / wayback → the same shapes ship_events takes as synthetic supply.

In plain words: the four inputs of ship_events were fed with synthetic data at first;
this layer assembles real data into the same shapes:
  ① evidence_by_star: affil_timeline rows are merged by (work, raw_affil) → the
     pollution_guard input shape. attributes_to_au = **reuses the country_code route of
     run_u4._foreign_poach_flags** (canonical JOIN institutions → country_code=='AU';
     reuse, no new rule); the sentinels __NONE__/AFFIL_NONE/None do not enter
     canonical_ids (mirrors is_foreign_poach).
  ② truth_evidence_by_star: table B rows are taken by author_id → the tested
     evidence_assembly parts (human_verified → official_roster tier); wayback on-roster
     rows are matched by (dept_key, normalised name) **exact match only** (case /
     whitespace / diacritic normalisation is fine, fuzzy matching is forbidden); no match
     or ambiguous → counted in the report, never guessed (wayback is a supplementary
     source; the human_verified rosters of the two universities are already strong
     supply, so the gap is acceptable).
  ③ modal_inst_year_by_star: affil_timeline.is_modal real value, consume-only —
     (person, arrival year, event-department institution) has an is_modal=True row →
     True; no row / all False → False (what is read is the absence of a U3 value; this
     layer never recomputes the mode to stand in for it).

IO is only a read-only DuckDB/parquet scan; it never writes to the SSD (writing belongs to run_u4).
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Mapping

# Unresolved sentinels (mirror the exclusion set of m7a_star.foreign_poach.is_foreign_poach, one rule).
_AFFIL_SENTINELS = frozenset({"__NONE__", "AFFIL_NONE"})

# Default locations of the real-data tables (relative to derived_root; same source as run_u4.U4_INPUTS).
# ★ The single source of truth for the roster version = run_u4.ROSTER_FILES (the human-corrected
#   roster); bound by import, do not scatter literals here (two drifting paths are a hazard).
#   run_u4 does not import m7a_star.* at top level (all inside functions) → this import direction has no cycle.
from run_u4 import ROSTER_FILES as _ROSTER_FILES

_PERSON_MAP_SUB = "u2_person_map_2026-07-05/person_map"
_TIMELINE_SUB = "u3_panel_2026-07-06/affil_timeline"
_EDGES_SUB = "u1_edges_full_2026-07-05"
_WAYBACK_SUB = "u0p5_hist_raw/wayback_full_2026-07-06/parsed/wayback_staff_lines.parquet"


def _author_person_for(derived_root, star_ids, *, person_map_sub=_PERSON_MAP_SUB,
                       label: str) -> dict[str, str]:
    """Star set → {author_id: person_id}; a missing mapping → ValueError naming the person (never silently skip anyone)."""
    import duckdb

    ids = sorted(set(star_ids))
    if not ids:
        return {}
    pm = (Path(derived_root) / person_map_sub).as_posix()
    idlist = ",".join("'" + a + "'" for a in ids)
    con = duckdb.connect()
    try:
        got = dict(con.execute(
            f"SELECT author_id, person_id FROM read_parquet('{pm}/**/*.parquet') "
            f"WHERE author_id IN ({idlist})").fetchall())
    finally:
        con.close()
    missing = sorted(set(ids) - set(got))
    if missing:
        raise ValueError(
            f"{label}: stars missing from person_map {missing} — no disambiguated identity, cannot assemble, "
            "fail-loud (never silently skip a person)")
    return got


# ---- ① evidence_by_star ----------------------------------------------------------

def evidence_rows_from_timeline(timeline_rows: Iterable[dict]) -> list[dict]:
    """One person's affil_timeline rows → the pollution_guard input shape (pure function).

    timeline_rows: each row {work_id, year, raw_affil, canonical_affil_id, country_code}
    (real-data shape: one raw string parsed into N institutions = N rows; country_code
    comes from the institutions JOIN).
    Merge (work_id, raw_affil) → {work_id, publication_year, raw_affil,
    canonical_ids (sentinels/None removed, sorted), attributes_to_au (any country=='AU' in the group)}.
    year is None → ValueError (U3 affil_timeline should not have an empty year; detect_arrival P-3 needs an int).
    Output sorted ascending by (publication_year, work_id, raw_affil) (deterministic).
    """
    grouped: dict[tuple, dict] = {}
    for r in timeline_rows:
        year = r["year"]
        if year is None:
            raise ValueError(
                f"evidence_rows_from_timeline: year of work {r.get('work_id')!r} is None "
                "— U3 affil_timeline must not have empty years (the detect_arrival contract requires int), "
                "upstream is broken; fail-loud")
        key = (r["work_id"], r["raw_affil"])
        g = grouped.setdefault(key, {"year": int(year), "canons": set(), "countries": set()})
        canon = r.get("canonical_affil_id")
        if canon is not None and canon not in _AFFIL_SENTINELS:
            g["canons"].add(canon)
            g["countries"].add(r.get("country_code"))
    out = [
        {"work_id": wid, "publication_year": g["year"], "raw_affil": raw,
         "canonical_ids": sorted(g["canons"]),
         # country_code route (reuses the _foreign_poach_flags rule): any AU institution in the group → attributed to Australia
         "attributes_to_au": "AU" in g["countries"]}
        for (wid, raw), g in grouped.items()
    ]
    out.sort(key=lambda r: (r["publication_year"], r["work_id"], r["raw_affil"] or ""))
    return out


def load_star_evidence(derived_root, star_ids, *, person_map_sub=_PERSON_MAP_SUB,
                       timeline_sub=_TIMELINE_SUB, edges_sub=_EDGES_SUB) -> dict:
    """Real read: star set → fold to person via person_map → **whole-career** affil_timeline rows
    JOIN institutions.country_code → evidence_rows_from_timeline.

    The arrival judgement needs the whole career (before and after arrival), so there is no
    year filter (unlike the year<arr window cut of _foreign_poach_flags; the country_code
    route is the same). A star with no timeline rows → key present, value [] (the
    consistency gate of ship_events takes the "no arrival found = disagreement" path). A
    missing person_map mapping → ValueError.
    Returns {"evidence_by_star": {author_id: rows}, "n_timeline_rows": int}.
    """
    import duckdb

    root = Path(derived_root)
    a2p = _author_person_for(derived_root, star_ids, person_map_sub=person_map_sub,
                             label="load_star_evidence")
    if not a2p:
        return {"evidence_by_star": {}, "n_timeline_rows": 0}
    atl = (root / timeline_sub).as_posix()
    inst = (root / edges_sub / "institutions").as_posix()
    vals = ",".join(f"('{a}','{p}')" for a, p in sorted(a2p.items()))
    con = duckdb.connect()
    try:
        rows = con.execute(f"""
            WITH sp(aid, person_id) AS (VALUES {vals})
            SELECT sp.aid, a.work_id, a.year, a.raw_affil, a.canonical_affil_id,
                   i.country_code
            FROM sp JOIN read_parquet('{atl}/**/*.parquet') a
                ON sp.person_id = a.person_id
            LEFT JOIN read_parquet('{inst}/**/*.parquet') i
                ON a.canonical_affil_id = i.institution_id
        """).fetchall()
    finally:
        con.close()
    by_star: dict[str, list] = defaultdict(list)
    for aid, wid, yr, raw, canon, cc in rows:
        by_star[aid].append({"work_id": wid, "year": yr, "raw_affil": raw,
                             "canonical_affil_id": canon, "country_code": cc})
    evidence = {aid: evidence_rows_from_timeline(by_star.get(aid, []))
                for aid in sorted(a2p)}
    return {"evidence_by_star": evidence, "n_timeline_rows": len(rows)}


# ---- ② truth_evidence_by_star ----------------------------------------------------

def normalize_display_name(name: str) -> str:
    """Name normalisation: NFKD splits diacritics → remove combining marks (é→e) → casefold → collapse whitespace.
    Only these three things: no whitespace deletion, no interpolation of abbreviation dots, no fuzzy transformation (exact-match discipline)."""
    n = unicodedata.normalize("NFKD", name)
    n = "".join(c for c in n if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", n).strip().casefold()


def match_wayback_to_roster(wayback_rows: Iterable[dict],
                            roster_rows: Iterable[dict]) -> dict:
    """Wayback on-roster rows ↔ roster author_id matching (exact / normalised-name match only).

    Key = (dept_key, normalize_display_name); exactly 1 author hit → attributed;
    0 hits → counted as unmatched; ≥2 hits (same department, same name) → counted as
    ambiguous and given to nobody (a non-match is never guessed; wayback is a
    supplementary source, so the gap is acceptable).
    Returns {"by_author": {author_id: [wayback rows]}, "n_lines", "n_matched",
    "n_unmatched", "n_ambiguous"}.
    """
    name_index: dict[tuple, set] = defaultdict(set)
    for r in roster_rows:
        if r.get("author_id") and r.get("display_name"):
            name_index[(r["dept_key"], normalize_display_name(r["display_name"]))].add(
                r["author_id"])
    by_author: dict[str, list] = defaultdict(list)
    n_lines = n_matched = n_unmatched = n_ambiguous = 0
    for w in wayback_rows:
        n_lines += 1
        hits = name_index.get((w["dept_key"], normalize_display_name(w["display_name"])), set())
        if len(hits) == 1:
            n_matched += 1
            by_author[next(iter(hits))].append(w)
        elif not hits:
            n_unmatched += 1
        else:
            n_ambiguous += 1        # Same department, same name, ambiguous → not attributed (not guessed)
    return {"by_author": dict(by_author), "n_lines": n_lines, "n_matched": n_matched,
            "n_unmatched": n_unmatched, "n_ambiguous": n_ambiguous}


def load_star_truth_evidence(derived_root, star_ids, *, roster_files=_ROSTER_FILES,
                             wayback_sub=_WAYBACK_SUB, orcid_by_star=None) -> dict:
    """Real read: table B rosters of the two universities + the wayback on-roster parsed file → per-star truth_dates input {source: year}.

    - official_roster tier: the star's roster rows (taken by author_id) → evidence_assembly.
      assemble_arrival_evidence (human_verified year_start; unverified never passes as strong).
    - wayback tier: after match_wayback_to_roster, take the star's matched rows (the earliest
      on-roster year is taken inside evidence_assembly). Wayback parsed file absent → empty
      tier + a report note (a supplementary source may be missing).
    - orcid_employment tier: orcid_by_star={author_id: year}, the ORCID employment years
      confirmed by the human arrival verifications; it goes through the existing ORCID
      parameter channel of evidence_assembly ("later increments; enter only when a year is
      passed explicitly"), so stars whose roster carries no hv (A5062087249/A5001034699
      type) get a literature-grade ground-truth tier this way. None = not supplied (the
      original behaviour).
    Returns {"truth_evidence_by_star": {author_id: {source: year}},
          "wayback_report": {...match report + present}}.
    """
    import pyarrow.parquet as pq

    from m7a_star.evidence_assembly import assemble_arrival_evidence

    root = Path(derived_root)
    orcid = dict(orcid_by_star or {})
    roster_rows: list[dict] = []
    for rf in roster_files:
        roster_rows += pq.read_table(str(root / rf)).to_pylist()
    wb_path = root / wayback_sub
    wayback_present = wb_path.is_file()
    wayback_rows = pq.read_table(str(wb_path)).to_pylist() if wayback_present else []
    match = match_wayback_to_roster(wayback_rows, roster_rows)

    roster_by_author: dict[str, list] = defaultdict(list)
    for r in roster_rows:
        if r.get("author_id"):
            roster_by_author[r["author_id"]].append(r)

    truth = {
        aid: assemble_arrival_evidence(
            roster_rows=roster_by_author.get(aid, []),
            wayback_rows=match["by_author"].get(aid, []),
            orcid_employment_year=orcid.get(aid))
        for aid in sorted(set(star_ids))
    }
    report = {k: match[k] for k in ("n_lines", "n_matched", "n_unmatched", "n_ambiguous")}
    report["wayback_present"] = wayback_present
    report["star_hits"] = {aid: sorted(w["snapshot_year"] for w in match["by_author"][aid])
                           for aid in sorted(set(star_ids))
                           if aid in match["by_author"]}
    return {"truth_evidence_by_star": truth, "wayback_report": report}


# ---- ③ modal_inst_year_by_star ---------------------------------------------------

def load_star_modal_flags(derived_root, star_arrival_dept: Mapping[str, tuple], *,
                          dept_inst_map: Mapping[str, str],
                          person_map_sub=_PERSON_MAP_SUB,
                          timeline_sub=_TIMELINE_SUB) -> dict[str, bool]:
    """Real read: each star's (arrival year, dept_key) → the U3 affil_timeline.is_modal real value (consume-only).

    star_arrival_dept: {author_id: (arrival_year, dept_key)}.
    Returns {author_id: bool}: a row with is_modal=True exists for (person, arrival year, event-department institution) → True;
    rows exist but all False / no row → False (absence = no modal evidence for that department in that year; every star's key is always present, so supply has no gaps).
    A missing person_map mapping / a dept_key not in the mapping → ValueError naming it.
    """
    import duckdb

    unknown = sorted({dept for _, dept in star_arrival_dept.values()}
                     - set(dept_inst_map))
    if unknown:
        raise ValueError(
            f"load_star_modal_flags: dept_key not in the DEPT_INST map {unknown} "
            "(outside the two-university smoke-test scope) — fail-loud")
    a2p = _author_person_for(derived_root, star_arrival_dept.keys(),
                             person_map_sub=person_map_sub,
                             label="load_star_modal_flags")
    if not a2p:
        return {}
    atl = (Path(derived_root) / timeline_sub).as_posix()
    vals = ",".join(
        f"('{aid}','{a2p[aid]}',{int(arr)},'{dept_inst_map[dept]}')"
        for aid, (arr, dept) in sorted(star_arrival_dept.items()))
    con = duckdb.connect()
    try:
        got = dict(con.execute(f"""
            WITH sp(aid, person_id, arr, inst) AS (VALUES {vals})
            SELECT sp.aid, BOOL_OR(a.is_modal)
            FROM sp JOIN read_parquet('{atl}/**/*.parquet') a
                ON sp.person_id = a.person_id AND a.year = sp.arr
                AND a.canonical_affil_id = sp.inst
            GROUP BY sp.aid
        """).fetchall())
    finally:
        con.close()
    # No (person, year, department) row → SQL has no group → absence = False (the key is still present, so supply has no gaps).
    return {aid: bool(got.get(aid, False)) for aid in sorted(star_arrival_dept)}
