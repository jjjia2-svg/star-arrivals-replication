"""Nominal-affiliation behavior flag (nominal_affiliation_flag) - mechanical diagnosis of nominal/honorary affiliation.

In plain words: roster inclusion used to rely only on a title-string filter (parse.py recognizes
adjunct/emeritus/visiting), so the A5044618645 type (real home at another university, listed in this university's
directory with a plain "Professor") slips through. This module adds a diagnosis based on **behavioral evidence**:
for roster members / star candidates with an author_id, use the U1 works_affil to compute "the share of the person's
own works that carry this university's institution id (lineage folded)" - a share of zero or below the threshold
-> flag.

Hard rules (no discretionary identification decisions):
  - **Only flag and list; never drop a person and never change the roster** - who is dropped and the final threshold
    are set by a human (same pattern as the auditable adjudications in signal_discards / exclude_candidates);
  - DEFAULT_NOMINAL_THRESHOLD = 0.05 is only a diagnostic default (the same criterion that gave "of 298
    candidates with an id, 21 have zero Australian works and 26 have a share < 0.05"), not a final value;
  - zero works in the corpus is not evidence of nominal affiliation -> its own reason=no_works_in_corpus (cannot be
    assessed, goes to human review);
  - school institution matching folds lineage: {canonical} ∪ {institution_id: canonical ∈ lineage}
    (same criterion as the stock/works prototype); several affiliations on one work count once
    (COUNT DISTINCT work_id).

Reminder on diagnostic semantics (the "hv semantics blind spot"): hv=True only checks "name <-> id", not real
employment - A5044618645 itself is hv=True. So this flag is raised on hv=True rows as well, with no exemption.
"""
from __future__ import annotations

from typing import Mapping, Optional, Sequence

DEFAULT_NOMINAL_THRESHOLD = 0.05   # Diagnostic default; not the final value

REASON_NO_WORKS = "no_works_in_corpus"
REASON_ZERO = "zero_school_works"
REASON_BELOW = "below_threshold"


# ═══ Pure functions ══════════════════════════════════════════════════════════════════
def flag_member(author_id: str, *, n_works_total: int, n_works_school: int,
                threshold: float = DEFAULT_NOMINAL_THRESHOLD) -> dict:
    """Counts for one person -> flag decision (pure function).

    Returns {author_id, n_works_total, n_works_school, school_share,
          nominal_affiliation_flag, reason, threshold}:
      - n_works_total == 0 -> share=None, flag=True, reason=no_works_in_corpus
        (cannot be assessed, not proof of nominal affiliation; classified separately for human review);
      - share == 0         -> flag=True, reason=zero_school_works (A5044618645 type);
      - 0 < share < threshold -> flag=True, reason=below_threshold;
      - share ≥ threshold     -> flag=False.
    """
    if n_works_school > n_works_total:
        raise ValueError(f"flag_member({author_id}): n_works_school={n_works_school} > "
                         f"n_works_total={n_works_total} — bad count, fail-loud")
    share: Optional[float]
    if n_works_total == 0:
        share, flag, reason = None, True, REASON_NO_WORKS
    else:
        share = n_works_school / n_works_total
        if share == 0.0:
            flag, reason = True, REASON_ZERO
        elif share < threshold:
            flag, reason = True, REASON_BELOW
        else:
            flag, reason = False, None
    return {"author_id": author_id, "n_works_total": n_works_total,
            "n_works_school": n_works_school, "school_share": share,
            "nominal_affiliation_flag": flag, "reason": reason,
            "threshold": threshold}


def build_flag_table(members: Sequence[Mapping], *,
                     threshold: float = DEFAULT_NOMINAL_THRESHOLD) -> list[dict]:
    """Member count rows -> flag table (deterministic order: not-assessable first, then share ascending, ties by id).

    Each member row: {author_id, display_name, dept_key, n_works_total, n_works_school,
    ...pass-through fields}; output row = flag_member decision + pass-through fields.
    """
    out = []
    for m in members:
        r = flag_member(m["author_id"], n_works_total=m["n_works_total"],
                        n_works_school=m["n_works_school"], threshold=threshold)
        for k, v in m.items():
            if k not in r:
                r[k] = v
        out.append(r)
    out.sort(key=lambda r: (r["school_share"] is not None,
                            r["school_share"] if r["school_share"] is not None else -1.0,
                            r["author_id"]))
    return out


# ═══ DuckDB counts (real data; lineage folded) ═══════════════════════════════════════
def count_author_school_works(*, members: Sequence[tuple[str, str]],
                              school_inst_ids: Mapping[str, str],
                              works_affil_glob: str,
                              institutions_glob: str) -> dict:
    """(author_id, dept_key) member list -> {(author_id, dept_key): {n_works_total, n_works_school}}.

    - n_works_total  = number of DISTINCT work_id of this author in works_affil (including rows without an institution);
    - n_works_school = of these, the DISTINCT work_id that carry an institution of "this school's institution set";
      school institution set = {canonical} ∪ {institution_id: canonical ∈ lineage} (lineage folded);
    - a member who never appears in the corpus -> both counts 0 (flag_member classifies it as no_works_in_corpus);
    - dept_key not in school_inst_ids -> ValueError (misspelled school, fail loudly).
    """
    unknown = sorted({d for _, d in members} - set(school_inst_ids))
    if unknown:
        raise ValueError(f"count_author_school_works: dept_key {unknown} is not in "
                         f"school_inst_ids {sorted(school_inst_ids)} — fail-loud")

    import duckdb

    con = duckdb.connect()
    try:
        con.execute("CREATE TEMP TABLE members(author_id VARCHAR, dept_key VARCHAR)")
        con.executemany("INSERT INTO members VALUES (?, ?)", list(members))
        con.execute("CREATE TEMP TABLE schools(dept_key VARCHAR, canonical_id VARCHAR)")
        con.executemany("INSERT INTO schools VALUES (?, ?)",
                        sorted(school_inst_ids.items()))

        # School institution set (lineage folded): canonical itself ∪ the institutions whose lineage contains canonical
        con.execute(f"""
            CREATE TEMP TABLE school_insts AS
            SELECT s.dept_key, s.canonical_id AS institution_id FROM schools s
            UNION
            SELECT s.dept_key, i.institution_id
            FROM (SELECT DISTINCT institution_id, lineage
                  FROM read_parquet('{institutions_glob}')) i
            JOIN schools s ON list_contains(i.lineage, s.canonical_id)
        """)

        rows = con.execute(f"""
            WITH wa AS (
                SELECT wa.work_id, wa.author_id, wa.institution_id, m.dept_key
                FROM read_parquet('{works_affil_glob}') wa
                JOIN members m USING (author_id)
            )
            SELECT wa.author_id, wa.dept_key,
                   COUNT(DISTINCT wa.work_id) AS n_total,
                   COUNT(DISTINCT CASE WHEN si.institution_id IS NOT NULL
                                       THEN wa.work_id END) AS n_school
            FROM wa
            LEFT JOIN school_insts si
              ON si.dept_key = wa.dept_key
             AND si.institution_id = wa.institution_id
            GROUP BY wa.author_id, wa.dept_key
        """).fetchall()
    finally:
        con.close()

    counts = {(aid, dk): {"n_works_total": int(nt), "n_works_school": int(ns)}
              for aid, dk, nt, ns in rows}
    for aid, dk in members:
        counts.setdefault((aid, dk), {"n_works_total": 0, "n_works_school": 0})
    return counts
