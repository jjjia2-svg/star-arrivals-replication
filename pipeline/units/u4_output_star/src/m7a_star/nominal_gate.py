"""nominal_gate: production nominal-affiliation gate + assembly of the human-review queue.

In plain words (root cause C, "real employment gate"): the roster only checks "name ↔ id",
not real employment (A5044618645 with hv=True still slipped through). Behavioural evidence
adds a production gate: if a candidate's share of own works that carry the home-university
institution (lineage folded) is < the red-line threshold (star.nominal_affiliation_min_share
= 0.05), the row gets nominal_affiliation_flag.

Rules:
  - **A flag only enters the human-review queue and never removes anyone automatically**:
    who is dropped and who stays is decided person by person by a human; cases that overlap
    with the T1/T3 handling follow the T1/T3 outcome; the borderline A5019255415 (0.0468,
    confirmed as a poach) stays, and the flag table carries a note;
  - The flag decision = the shared pure function u0 identity/nominal_affil.flag_member
    (single source of truth; it absorbs the u0p5 diagnostic prototype, and where the two
    disagree the differences are only listed);
  - Counting follows the same rule as the audit: works_affil DISTINCT work_id; the home
    institution set = {canonical} ∪ {institution: canonical ∈ lineage} (lineage folded).

Human-review queue: ② nominal-affiliation flag + ③ academic-age ≤ 1 sanity gate
(sanity_age_flags) are merged into one human_adjudication_queue, one row per flag
with its source, and disposition is always human_review.
"""
from __future__ import annotations

from typing import Mapping, Sequence

from identity.nominal_affil import flag_member


def build_nominal_affil_flags(derived_root, candidates: Sequence[Mapping], *,
                              edges_sub="u1_edges_full_2026-07-05",
                              dept_inst: Mapping[str, str],
                              threshold=None) -> list[dict]:
    """Candidates → nominal-affiliation flag rows (count on real works_affil data + the shared pure function decides the flag).

    candidates: [{author_id, name, dept}] (the stars rows of build_star_set are enough).
    dept_inst: {dept_key: canonical institution_id} (injected by run_u4.DEPT_INST).
    threshold: None → read the red line star.nominal_affiliation_min_share (0.05).
    - candidate dept not in dept_inst → ValueError (a misspelt university fails loudly and is never silently left unscored);
    - a candidate with zero works in the corpus still gets a row (reason=no_works_in_corpus, goes to human review: cannot be evaluated, never silent).
    Deterministic order: not evaluable first → share ascending → author_id (mirrors the audit report).
    """
    from pathlib import Path
    import duckdb
    from common._redlines import require

    if threshold is None:
        threshold = require("star", "nominal_affiliation_min_share")
    unknown = sorted({c["dept"] for c in candidates} - set(dept_inst))
    if unknown:
        raise ValueError(
            f"build_nominal_affil_flags: candidate dept {unknown} is not in the dept_inst map "
            f"{sorted(dept_inst)} — misspelled university or out of scope; fail-loud")
    if not candidates:
        return []

    root = Path(derived_root)
    wa = (root / edges_sub / "works_affil").as_posix()
    inst = (root / edges_sub / "institutions").as_posix()
    con = duckdb.connect()
    try:
        con.execute("CREATE TEMP TABLE members(author_id VARCHAR, dept_key VARCHAR)")
        con.executemany("INSERT INTO members VALUES (?, ?)",
                        sorted({(c["author_id"], c["dept"]) for c in candidates}))
        con.execute("CREATE TEMP TABLE schools(dept_key VARCHAR, canonical_id VARCHAR)")
        con.executemany("INSERT INTO schools VALUES (?, ?)", sorted(dept_inst.items()))
        # Home institution set (lineage folded): canonical itself ∪ institutions whose lineage contains canonical.
        con.execute(f"""
            CREATE TEMP TABLE school_insts AS
            SELECT s.dept_key, s.canonical_id AS institution_id FROM schools s
            UNION
            SELECT s.dept_key, i.institution_id
            FROM (SELECT DISTINCT institution_id, lineage
                  FROM read_parquet('{inst}/**/*.parquet')) i
            JOIN schools s ON list_contains(i.lineage, s.canonical_id)
        """)
        rows = con.execute(f"""
            WITH wa AS (
                SELECT w.work_id, w.author_id, w.institution_id, m.dept_key
                FROM read_parquet('{wa}/**/*.parquet') w
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

    counts = {(aid, dk): (int(nt), int(ns)) for aid, dk, nt, ns in rows}
    out = []
    for c in candidates:
        nt, ns = counts.get((c["author_id"], c["dept"]), (0, 0))
        r = flag_member(c["author_id"], n_works_total=nt, n_works_school=ns,
                        threshold=threshold)
        r["name"] = c.get("name")
        r["dept"] = c["dept"]
        out.append(r)
    out.sort(key=lambda r: (r["school_share"] is not None,
                            r["school_share"] if r["school_share"] is not None else -1.0,
                            r["author_id"]))
    return out


def human_adjudication_queue(sanity_age_flags, nominal_rows) -> list[dict]:
    """Human-review queue assembly (pure function): the True rows of the ③ academic-age ≤ 1 flag and the ② nominal-affiliation flag are merged into one queue.

    One row per flag (one person with both flags = two rows, so the source is distinguishable); False/None (checked and fine / cannot be evaluated but reported elsewhere)
    do not enter the queue. disposition is always human_review — **this queue never removes anyone automatically**.
    Order: (author_id, source), deterministic.
    """
    rows: list[dict] = []
    for s in sanity_age_flags or ():
        if s.get("sanity_flag_age") is True:
            rows.append({
                "author_id": s["author_id"], "name": s.get("name"),
                "dept": s.get("dept"), "source": "sanity_age_le1",
                "detail": (f"academic_age={s.get('academic_age')} "
                           f"(arrival={s.get('arrival')}) — 错号/错到任年信号 (根因 E)"),
                "disposition": "human_review (旗不硬剔, 剔留=人工签)"})
    for n in nominal_rows or ():
        if n.get("nominal_affiliation_flag") is True:
            rows.append({
                "author_id": n["author_id"], "name": n.get("name"),
                "dept": n.get("dept"), "source": "nominal_affiliation",
                "detail": (f"school_share={n.get('school_share')} "
                           f"({n.get('n_works_school')}/{n.get('n_works_total')}) "
                           f"reason={n.get('reason')} threshold={n.get('threshold')}"),
                "disposition": "human_review (旗不硬剔, 剔留=人工签)"})
    rows.sort(key=lambda r: (r["author_id"], r["source"]))
    return rows
