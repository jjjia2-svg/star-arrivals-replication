"""m7a discipline_gate: discipline gate (flag mode) + sanity gate (root causes D/E).

In plain words:
  (1) Discipline gate (root cause D / GAP-3): the registry table-A field subfield_excluded=[Finance] previously had
     **no consumer** anywhere in the pipeline (dead config that gave the false impression of screening). This module makes it a real consumer: at the U4 candidate cell,
     if the modal publication subfield of any member on staff falls in that university's excluded list -> set discipline_flag.
     **Flag only, no hard exclusion**: who is dropped or kept is an identification decision made by a human.
  (2) Sanity gate (root cause E fix 3): candidates with academic_age <= 1 get sanity_flag_age and go to the manual-review list
     (a senior professor with age 0/1 signals a wrong profile or wrong arrival year, e.g. types A5086383420/A5053503664; diagnostic, not a hard suppression).

The registry stores discipline **names** (Finance), works store subfield **ids** ("2003"), so the name -> id mapping table
is pinned here and fails loudly (a registry name outside the mapping raises, guarding against a silent recurrence of GAP-3).
Pure functions, zero IO; real-data orchestration is in run_discipline_gates_diag.
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

# Subfield name -> id under OpenAlex field 20 (Economics, Econometrics and Finance).
# The ids match the redlines subfield_whitelist: include=["2002"](Economics and Econometrics),
# exclude=["2003"](Finance). A registry name outside the table -> excluded_ids_by_dept raises.
SUBFIELD_NAME_TO_ID: dict[str, str] = {
    "Economics and Econometrics": "2002",
    "Finance": "2003",
}


def excluded_ids_by_dept(registry_rows) -> dict[str, frozenset]:
    """registry rows -> {dept_key: frozenset(excluded subfield_id)}; an unknown discipline name fails loudly."""
    out: dict[str, frozenset] = {}
    for r in registry_rows:
        ids = set()
        for name in (r.get("subfield_excluded") or []):
            if name not in SUBFIELD_NAME_TO_ID:
                raise ValueError(
                    f"discipline_gate: subfield_excluded of registry {r.get('dept_key')} "
                    f"contains an unmapped discipline name {name!r} — the name→id map has no entry for it, so the gate would silently miss it; "
                    f"fail-loud; add it to SUBFIELD_NAME_TO_ID first")
            ids.add(SUBFIELD_NAME_TO_ID[name])
        out[r["dept_key"]] = frozenset(ids)
    return out


def modal_subfield_from_counts(counts) -> str | None:
    """{subfield_id: n} -> modal subfield (ties take the smallest id = the same determinism as S8-3); no signal -> None."""
    c = Counter(counts)
    if not c:
        return None
    return sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def discipline_flag_rows(candidates, modal_by_author, excluded_by_dept):
    """One discipline diagnostic row per candidate: modal subfield in that university's excluded list -> discipline_flag=True.

    Flag only: all candidates stay in the rows, nobody is dropped (who is dropped is a human decision).
    - Candidate dept not in the registry -> ValueError (a GAP-4 scope mismatch is never silently let through);
    - Candidate with no modal signal (0 works) -> modal None, flag None (cannot be evaluated; False is never faked).
    """
    rows = []
    for c in sorted(candidates, key=lambda x: x["author_id"]):
        dept = c["dept"]
        if dept not in excluded_by_dept:
            raise ValueError(
                f"discipline_gate: candidate {c['author_id']} has dept {dept!r}, which is not in the registry — "
                f"scope mismatch, fail-loud; registry keys={sorted(excluded_by_dept)}")
        modal = modal_by_author.get(c["author_id"])
        flag = None if modal is None else (modal in excluded_by_dept[dept])
        rows.append({"author_id": c["author_id"], "name": c.get("name"), "dept": dept,
                     "modal_subfield": modal,
                     "excluded_subfields": sorted(excluded_by_dept[dept]),
                     "discipline_flag": flag})
    return rows


def sanity_age_flag_rows(star_rows, *, max_flag_age: int = 1):
    """Sanity gate: academic_age <= max_flag_age (default 1) -> sanity_flag_age=True, added to the manual-review list.

    Academic age None (not in the pool, cannot be evaluated) -> flag None, not False (never fake "checked and fine").
    """
    rows = []
    for s in sorted(star_rows, key=lambda x: x["author_id"]):
        age = s.get("academic_age")
        flag = None if age is None else (age <= max_flag_age)
        rows.append({"author_id": s["author_id"], "name": s.get("name"),
                     "dept": s.get("dept"), "arrival": s.get("arrival"),
                     "academic_age": age, "sanity_flag_age": flag})
    return rows


# ---------------------------------------------------------------------------
# Real-data orchestration: frozen star_set + registry -> two diagnostic reports (reads existing directories only, writes a new dated directory)
# ---------------------------------------------------------------------------
def run_discipline_gates_diag(derived_root, out_dir, *,
                              edges_sub="u1_edges_full_2026-07-05",
                              star_set_sub="u4_star_set_v3_2026-07-11/star_set/star_set.parquet",
                              registry_sub="u0p5_roster/registry_v3_2026-07-12/econ_dept_registry_11schools.parquet",
                              threads=6):
    """Discipline gate + sanity gate real-data diagnostics: the frozen 211 candidates -> two "who got flagged" reports.

    Modal computed two ways (the diagnostic gives one extra column; the main judgement uses the full period): modal_subfield_all (modal of all-period works; discipline is
    a property of the person) + modal_subfield_pre_arrival (modal up to t-1, consistent with the star-judging window). Which of the two definitions governs is
    an identification detail, so the report keeps both columns for manual review. Diagnostic only: no production path is changed, nothing is frozen.
    """
    import duckdb
    import pyarrow.parquet as pq

    root = Path(derived_root)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    frozen = pq.read_table(str(root / star_set_sub)).to_pylist()
    registry = pq.read_table(str(root / registry_sub)).to_pylist()
    excl = excluded_ids_by_dept(registry)

    ep = (root / edges_sub).as_posix()
    con = duckdb.connect()
    con.execute(f"PRAGMA threads={int(threads)}")
    ids = ",".join("'" + r["author_id"] + "'" for r in frozen)
    sf_rows = con.execute(
        f"SELECT e.author_id, w.subfield_id, w.publication_year, COUNT(*) n "
        f"FROM read_parquet('{ep}/authorship_edges/**/*.parquet') e "
        f"JOIN read_parquet('{ep}/works/**/*.parquet') w ON e.work_id=w.work_id "
        f"WHERE e.author_id IN ({ids}) AND w.subfield_id IS NOT NULL "
        f"AND w.publication_year IS NOT NULL "
        f"GROUP BY e.author_id, w.subfield_id, w.publication_year").fetchall()
    con.close()

    arrival = {r["author_id"]: r["arrival"] for r in frozen}
    counts_all: dict[str, Counter] = {}
    counts_pre: dict[str, Counter] = {}
    for aid, sf, yr, n in sf_rows:
        counts_all.setdefault(aid, Counter())[sf] += n
        if yr <= arrival[aid] - 1:
            counts_pre.setdefault(aid, Counter())[sf] += n
    modal_all = {aid: modal_subfield_from_counts(c) for aid, c in counts_all.items()}
    modal_pre = {aid: modal_subfield_from_counts(c) for aid, c in counts_pre.items()}

    cands = [{"author_id": r["author_id"], "name": r["name"], "dept": r["dept"]}
             for r in frozen]
    disc = discipline_flag_rows(cands, modal_all, excl)
    pre_by = {aid: modal_pre.get(aid) for aid in arrival}
    for r in disc:
        r["modal_subfield_pre_arrival"] = pre_by.get(r["author_id"])
    ages = sanity_age_flag_rows(frozen)

    with open(out / "discipline_flag_report.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(disc[0].keys()))
        w.writeheader()
        for r in disc:
            w.writerow({**r, "excluded_subfields": ";".join(r["excluded_subfields"])})
    with open(out / "sanity_age_report.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(ages[0].keys()))
        w.writeheader()
        for r in ages:
            w.writerow(r)
    summary = {
        "n_candidates": len(frozen),
        "n_discipline_flagged": sum(1 for r in disc if r["discipline_flag"] is True),
        "discipline_flagged": [
            {k: r[k] for k in ("author_id", "name", "dept", "modal_subfield",
                               "modal_subfield_pre_arrival")}
            for r in disc if r["discipline_flag"] is True],
        "n_modal_unassessable": sum(1 for r in disc if r["discipline_flag"] is None),
        "n_sanity_age_flagged": sum(1 for r in ages if r["sanity_flag_age"] is True),
        "sanity_age_flagged": [
            {k: r[k] for k in ("author_id", "name", "dept", "arrival", "academic_age")}
            for r in ages if r["sanity_flag_age"] is True],
        "n_age_unassessable": sum(1 for r in ages if r["sanity_flag_age"] is None),
    }
    (out / "report.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"discipline": disc, "ages": ages, "summary": summary, "out_dir": str(out)}
