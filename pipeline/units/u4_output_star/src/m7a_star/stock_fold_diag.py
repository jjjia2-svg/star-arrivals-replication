"""stock_fold_diag: U4 stock "double computation" diagnostic (root cause B, fix ②).

In plain words: production U4 computes the pre-arrival citation stock by the **bare
author_id** and does not join person_map (U3 folds clusters, U4 does not, so the rules
differ: A5008470795/A5086383420 had empty fragment ids pinned in the roster, so their stock
was computed on empty ids while the real person's citations sat in sibling ids of the same
cluster and were not taken). For the candidates of the frozen star_set this module
**computes twice**:
  (a) bare-id stock, exactly the production rule recomputed, with a parity gate: it must equal
      the frozen file person by person, otherwise HALT;
  (b) stock after folding to person_id: the works of all sibling ids in the flagA person_map
      cluster are merged in (same t−1 cut).
The folded stock is then fed back into **the same ranking machine** through SOV (stock
override) (DIAG_CELL_SQL = derived programmatically from the production _STAR_CELL_SQL) to see
whether the rank / tier changes → a diff report for human review.

Rules:
  - Diagnosis only: it changes no production star-picking path, freezes no new star set, and does not touch person_id;
  - suspected_overmerge clusters are **not folded** (that would absorb other people's citations); they are listed separately for human review;
  - The reference pool is the bare author_id of everybody, and the pool side is not folded (whether to fold the pool is an identification choice, pending human review);
  - Academic age / age_bin stay frozen (FPOV still takes the bare-id robust debut year; moving academic age with folded persons is another identification choice, listed as a clash point);
  - Yves Zenou (A5017376589): the bare side has zero drift against the frozen file (explicit assertion).
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from run_u4 import _STAR_CELL_SQL

# ---------------------------------------------------------------------------
# DIAG_CELL_SQL: the SOV person-fold override is built into the production SQL as a native CTE
#   (run_u4._STAR_CELL_SQL carries sov + LEFT JOIN sov), so the diagnostic SQL is no longer
#   derived separately and is the same text as production (single source of truth; if production
#   drops the sov CTE, the fail-loud anchor below blows up, preventing a silent fallback to the bare rule).
# ---------------------------------------------------------------------------
_SOV_ANCHOR = "sov(aid, stock) AS (VALUES {SOV})"
if _SOV_ANCHOR not in _STAR_CELL_SQL:  # fail-loud: if the production SQL lost the SOV arm, the folded rule would silently stop working
    raise RuntimeError(
        "stock_fold_diag: production _STAR_CELL_SQL lacks the sov CTE anchor — has the person-folded stock override "
        "been removed? Align first, then run (prevents silently falling back to the bare author_id basis)")
DIAG_CELL_SQL = _STAR_CELL_SQL


def diag_cells(con, *, Y, IDS, OV, FPOV, sov, GAP=10):
    """Run DIAG_CELL_SQL → {aid: row tuple (aid, subfield, age_bin, aage, stock, pct, cell_n, rnk)}.

    sov = a VALUES string "('aid',stock),..."; empty → the placeholder "('__none__',0)" (matches no aid,
    equivalent to no override: the parity base). GAP = the configured robust_first_pub_max_gap (pool-side robust rule).
    """
    rows = con.execute(DIAG_CELL_SQL.format(
        Y=Y, IDS=IDS, OV=OV, FPOV=FPOV, SOV=sov, GAP=int(GAP))).fetchall()
    return {r[0]: r for r in rows}


# ---------------------------------------------------------------------------
# fold plan: for each candidate, who to fold and whether to fold (three states)
# ---------------------------------------------------------------------------
def build_fold_plan(candidate_ids, author_to_person, members_by_person, *, overmerge_person_ids):
    """Each candidate → {"person_id", "sibling_ids" (canonical-sorted, including itself), "fold_status"}.

    Three fold_status values:
      folded              — in person_map and the cluster is not flagged → fold (sibling ids merged in);
      not_in_person_map   — not in person_map (bypassed U2 disambiguation, the 10/211 type) → cannot be folded, listed separately;
      suspected_overmerge — the cluster is in the flagA human-review queue → **not folded** (would absorb others' citations), listed separately for human review.
    """
    plan = {}
    for aid in candidate_ids:
        pid = author_to_person.get(aid)
        if pid is None:
            plan[aid] = {"person_id": None, "sibling_ids": [aid],
                         "fold_status": "not_in_person_map"}
            continue
        sibs = sorted(set(members_by_person.get(pid, [aid])) | {aid})
        status = "suspected_overmerge" if pid in overmerge_person_ids else "folded"
        plan[aid] = {"person_id": pid, "sibling_ids": sibs, "fold_status": status}
    return plan


def folded_stocks(con, fold_plan, *, Y, aids):
    """Stock after folding to person: Σ cited_by_count of the works of all sibling ids in the cluster (yr ≤ Y, aw table with the same rule as production).

    Only candidates with fold_status=="folded" are computed (over-merge-flagged ones / ones not in the map are never folded).
    If the sibling set has no work at all up to Y → no row (no circle ≠ 0; same semantics as the production cell_n=None rule).
    """
    pairs = [(aid, m)
             for aid in aids
             if fold_plan.get(aid, {}).get("fold_status") == "folded"
             for m in fold_plan[aid]["sibling_ids"]]
    if not pairs:
        return {}
    vals = ",".join(f"('{c}','{m}')" for c, m in pairs)
    q = (f"WITH fm(cand, member) AS (VALUES {vals}) "
         f"SELECT fm.cand, SUM(a.c) FROM fm JOIN aw a ON a.aid = fm.member "
         f"WHERE a.yr <= {int(Y)} GROUP BY fm.cand")
    return {c: int(s) for c, s in con.execute(q).fetchall()}


# ---------------------------------------------------------------------------
# Report assembly (pure functions)
# ---------------------------------------------------------------------------
def tier_label(is1, is5):
    """Two flags → tier label: 1pct / 5pct / below / NA (both flags None = thin circle or not in the pool, no forced call)."""
    if is1 is True:
        return "1pct"
    if is5 is True:
        return "5pct"
    if is1 is None and is5 is None:
        return "NA"
    return "below"


def assemble_diff_rows(frozen_rows, fold_plan, folded_stock, folded_cells, *,
                       gate1, gate5, min_academic_age, p1, p5):
    """Frozen rows + fold plan + folded stock/cell → (list of diff rows, summary). Pure function, zero IO.

    The tier is re-judged only for the "in the pool at freeze time" folded candidates: star_flags
    takes the folded rank + the same cell_n + the frozen academic age (same machine as
    production). Not in the pool at freeze time (stock=None) but has stock after folding →
    would_enter_pool=True, tier_folded=NA (no frozen circle to judge by; a circle is never forged).
    For candidates that are not folded (over-merge / not in the map) the folded side is all None.
    """
    from m7a_star.pctile_engine import star_flags

    rows, n_changed, n_tier, n_over, n_enter = [], 0, 0, 0, 0
    for f in sorted(frozen_rows, key=lambda r: r["author_id"]):
        aid = f["author_id"]
        plan = fold_plan.get(aid, {"person_id": None, "sibling_ids": [aid],
                                   "fold_status": "not_in_person_map"})
        status = plan["fold_status"]
        bare = f["stock"]
        tier_frozen = tier_label(f["is_star_1pct"], f["is_star_5pct"])
        fold = folded_stock.get(aid) if status == "folded" else None
        cell = folded_cells.get(aid) if status == "folded" else None

        delta = (fold - bare) if (fold is not None and bare is not None) else None
        would_enter = bool(status == "folded" and bare is None and fold is not None)
        if status == "suspected_overmerge":
            n_over += 1
        if would_enter:
            n_enter += 1

        if cell is not None and bare is not None:
            _, _, _, aage, _, pct_f, cn, rnk = cell
            s1, s5 = star_flags(rnk, cn, aage, gate1=gate1, gate5=gate5,
                                min_academic_age=min_academic_age, p1=p1, p5=p5)
            tier_folded = tier_label(s1, s5)
            rank_folded, pct_folded = int(rnk), round(pct_f, 4)
        elif would_enter:
            tier_folded, rank_folded, pct_folded = "NA", None, None
        elif status == "folded" and fold is not None:
            tier_folded, rank_folded, pct_folded = "NA", None, None
        else:
            tier_folded, rank_folded, pct_folded = None, None, None

        tier_changed = (tier_folded != tier_frozen) if (
            status == "folded" and tier_folded is not None and not would_enter
        ) else (None if status != "folded" else None)
        if would_enter:
            tier_changed = None                     # No frozen circle → whether it changed is not judged; goes to human review
        if delta is not None and delta != 0:
            n_changed += 1
        if tier_changed is True:
            n_tier += 1

        rows.append({
            "author_id": aid, "name": f.get("name"), "dept": f.get("dept"),
            "arrival": f.get("arrival"), "person_id": plan["person_id"],
            "fold_status": status,
            "n_siblings": len(plan["sibling_ids"]),
            "stock_bare": bare, "stock_folded": fold, "stock_delta": delta,
            "percentile_frozen": f.get("percentile"), "percentile_folded": pct_folded,
            "cell_n": f.get("cell_n"), "rank_folded": rank_folded,
            "tier_frozen": tier_frozen, "tier_folded": tier_folded,
            "tier_changed": tier_changed,
            "would_enter_pool": would_enter,
        })
    summary = {
        "n_candidates": len(rows),
        "n_folded": sum(1 for r in rows if r["fold_status"] == "folded"),
        "n_not_in_person_map": sum(1 for r in rows if r["fold_status"] == "not_in_person_map"),
        "n_overmerge_skipped": n_over,
        "n_stock_changed": n_changed,
        "n_tier_changed": n_tier,
        "n_would_enter_pool": n_enter,
        "tier_changed_author_ids": sorted(r["author_id"] for r in rows if r["tier_changed"] is True),
        "would_enter_pool_author_ids": sorted(r["author_id"] for r in rows if r["would_enter_pool"]),
    }
    return rows, summary


# ---------------------------------------------------------------------------
# Real-data orchestration (read the frozen file / flagA person_map / over-merge queue → compute twice → write to a new dated directory)
# ---------------------------------------------------------------------------
def run_stock_fold_diag(derived_root, out_dir, *,
                        edges_sub="u1_edges_full_2026-07-05",
                        star_set_sub="u4_star_set_v3_2026-07-11/star_set/star_set.parquet",
                        person_map_sub="u2_person_map_11school_2026-07-14_flagA/person_map",
                        overmerge_queue_sub="u2_person_map_11school_2026-07-14_flagA/suspected_overmerge_queue.csv",
                        adjudications_sub="u0p5_roster/roster_fix_2026-07-11_star_arrival_annotations.json",
                        threads=6):
    """Real-data orchestration of the double-computation diagnostic. Reads existing derived directories only; all output goes to out_dir (a new dated directory).

    Steps: ① read the frozen star_set (candidates + arrival + frozen values = the only anchor)
    ② flagA person_map fold plan (over-merge-flagged clusters are not folded) ③ the aw table
    with the same rule as production (including work_pollution_discards) ④ bare-side recompute
    → parity gate (equal to the frozen file person by person, Yves Zenou asserted explicitly;
    not equal → HALT and write a mismatch report) ⑤ folded-side SOV re-ranking → diff report.

    Note: the production build_star_set now folds persons natively and uses the pool-side robust
    debut year, so the bare-side parity gate of this orchestration against an older frozen file
    can legitimately HALT under the new SQL semantics (the pool's fp changed). This is
    **expected**: this one-off diagnostic has done its job and is kept only for audit replay;
    the production rule is build_star_set.
    """
    import duckdb
    import pyarrow.parquet as pq
    from collections import defaultdict
    from identity.cohort import cohort_bin
    from common._redlines import RED
    from m6_generation.academic_age import robust_first_pub
    from m7a_star.adjudications import load_star_adjudications
    from m7a_star.pctile_engine import star_flags

    root = Path(derived_root)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Red-line parameters (read the same way as the production build_star_set)
    cmn = RED["star"]["cell_min_n"]
    gate1 = max(cmn["pct_1"], cmn["floor"])
    gate5 = max(cmn["pct_5"], cmn["floor"])
    p1 = RED["star"]["percentile_primary"]
    p5 = max(RED["star"]["percentile_robustness"])
    econ_sf = RED["subfield_whitelist"]["include"][0]
    min_age = RED["star"]["min_academic_age"]
    min_gap = RED["academic_age"]["robust_first_pub_max_gap"]

    # ① the frozen star_set = the only candidate anchor
    frozen = pq.read_table(str(root / star_set_sub)).to_pylist()
    cand_ids = [r["author_id"] for r in frozen]

    # ② flagA person_map + over-merge queue → fold plan
    pm_dir = root / person_map_sub
    pm_files = [pm_dir] if pm_dir.is_file() else sorted(pm_dir.rglob("*.parquet"))
    author_to_person, members_by_person = {}, defaultdict(list)
    for fp_ in pm_files:
        for r in pq.read_table(str(fp_), columns=["author_id", "person_id"]).to_pylist():
            author_to_person[r["author_id"]] = r["person_id"]
            members_by_person[r["person_id"]].append(r["author_id"])
    with open(root / overmerge_queue_sub, newline="", encoding="utf-8") as fh:
        overmerge_pids = {row["person_id"] for row in csv.DictReader(fh)}
    plan = build_fold_plan(cand_ids, author_to_person, dict(members_by_person),
                           overmerge_person_ids=overmerge_pids)

    # ③ aw table (same as production build_star_set, word for word: missing citation count fails loudly / missing year dropped / polluted work dropped)
    adj = load_star_adjudications(root, sub=adjudications_sub)
    wpd = {aid: [e["work_id"] for e in entries]
           for aid, entries in adj["work_pollution_discards"].items()}
    excl_pairs = [(aid, wid) for aid, wids in wpd.items() for wid in wids]
    ep = (root / edges_sub).as_posix()
    con = duckdb.connect()
    con.execute(f"PRAGMA threads={int(threads)}")
    con.create_function("cbin", lambda a: cohort_bin(int(a)), ["INTEGER"], "VARCHAR")
    n_null_c = con.execute(
        f"SELECT COUNT(*) FROM read_parquet('{ep}/authorship_edges/**/*.parquet') e "
        f"JOIN read_parquet('{ep}/works/**/*.parquet') w ON e.work_id=w.work_id "
        f"WHERE w.cited_by_count IS NULL").fetchone()[0]
    if n_null_c:
        raise ValueError(f"stock_fold_diag: {n_null_c} rows lack cited_by_count — fail-loud, as in production")
    excl_clause = ""
    if excl_pairs:
        keyset = ",".join("'" + a + "|" + w + "'" for a, w in excl_pairs)
        excl_clause = f" AND (e.author_id||'|'||w.work_id) NOT IN ({keyset})"
    con.execute(
        f"CREATE TEMP TABLE aw AS SELECT e.author_id aid, w.publication_year yr, "
        f"w.cited_by_count c, w.subfield_id sf "
        f"FROM read_parquet('{ep}/authorship_edges/**/*.parquet') e "
        f"JOIN read_parquet('{ep}/works/**/*.parquet') w ON e.work_id=w.work_id "
        f"WHERE w.publication_year IS NOT NULL{excl_clause}")

    # ④+⑤ compute twice, grouped by arrival year
    by_year = defaultdict(list)
    for r in frozen:
        by_year[r["arrival"] - 1].append(r["author_id"])
    frozen_by = {r["author_id"]: r for r in frozen}

    mismatches = []
    folded_stock_all, folded_cells_all = {}, {}
    for Y in sorted(by_year):
        cids = by_year[Y]
        ids = ",".join("'" + a + "'" for a in cids)
        ov = ",".join(f"('{aid}','{econ_sf}')" for aid in cids)
        yrows = con.execute(f"SELECT aid, yr FROM aw WHERE yr <= {Y} AND aid IN ({ids})").fetchall()
        cand_years = defaultdict(list)
        for aid, yr in yrows:
            cand_years[aid].append(yr)
        fpov_map = {aid: robust_first_pub(cand_years[aid], max_leading_gap=min_gap)
                    for aid in cids if cand_years.get(aid)}
        fpov = ",".join(f"('{aid}',{fp})" for aid, fp in fpov_map.items()) or "('__none__',0)"

        # (a) bare-side recompute = equivalent to the production SQL (empty SOV placeholder) → parity gate
        bare = diag_cells(con, Y=Y, IDS=ids, OV=ov, FPOV=fpov, sov="('__none__',0)",
                          GAP=min_gap)
        for aid in cids:
            fz, got = frozen_by[aid], bare.get(aid)
            if got is None:
                if fz["stock"] is not None:
                    mismatches.append({"author_id": aid, "field": "in_pool",
                                       "frozen": fz["stock"], "recomputed": None})
                continue
            _, sf_, ab_, aage_, stock_, pct_, cn_, rnk_ = got
            s1, s5 = star_flags(rnk_, cn_, aage_, gate1=gate1, gate5=gate5,
                                min_academic_age=min_age, p1=p1, p5=p5)
            checks = [("stock", fz["stock"], int(stock_)),
                      ("cell_n", fz["cell_n"], int(cn_)),
                      ("academic_age", fz["academic_age"], int(aage_)),
                      ("age_bin", fz["age_bin"], ab_),
                      ("percentile", fz["percentile"], round(pct_, 4)),
                      ("is_star_1pct", fz["is_star_1pct"], s1),
                      ("is_star_5pct", fz["is_star_5pct"], s5)]
            mismatches.extend(
                {"author_id": aid, "field": k, "frozen": a, "recomputed": b}
                for k, a, b in checks if a != b)

        # (b) folded side: sum over sibling ids → SOV re-ranking (override only for those in the pool whose value changes after folding)
        fstock = folded_stocks(con, plan, Y=Y, aids=cids)
        folded_stock_all.update(fstock)
        sov_pairs = [(aid, s) for aid, s in fstock.items() if aid in bare]
        if sov_pairs:
            sov = ",".join(f"('{a}',{s})" for a, s in sov_pairs)
            fold = diag_cells(con, Y=Y, IDS=ids, OV=ov, FPOV=fpov, sov=sov, GAP=min_gap)
            folded_cells_all.update({aid: fold[aid] for aid, _ in sov_pairs if aid in fold})

    # parity gate: the bare side must equal the frozen file person by person (not equal → write a report + HALT)
    (out / "parity_mismatches.json").write_text(
        json.dumps(mismatches, ensure_ascii=False, indent=1), encoding="utf-8")
    if mismatches:
        raise RuntimeError(
            f"stock_fold_diag: bare-side recomputation differs from the frozen star_set in {len(mismatches)} places — "
            f"production basis not reproduced; diagnostic void, HALT (see {out / 'parity_mismatches.json'})")

    # Yves Zenou zero-drift explicit assertion (bare side)
    z = frozen_by.get("A5017376589")
    if z is None or z["stock"] is None:
        raise RuntimeError("stock_fold_diag: Yves Zenou not found in the frozen set — wrong input, HALT")

    rows, summary = assemble_diff_rows(frozen, plan, folded_stock_all, folded_cells_all,
                                       gate1=gate1, gate5=gate5, min_academic_age=min_age,
                                       p1=p1, p5=p5)
    summary["zenou"] = next(r for r in rows if r["author_id"] == "A5017376589")
    summary["parity"] = {"bare_recompute_equals_frozen": True, "n_mismatches": 0}
    # Coverage gap of the sibling ids in this works universe (11-university flagA clusters vs the two-university edge table) — recorded honestly
    sib_all = sorted({m for p in plan.values() if p["fold_status"] == "folded"
                      for m in p["sibling_ids"]})
    ids_s = ",".join("'" + a + "'" for a in sib_all)
    present = {r[0] for r in con.execute(
        f"SELECT DISTINCT aid FROM aw WHERE aid IN ({ids_s})").fetchall()}
    summary["n_sibling_ids_total"] = len(sib_all)
    summary["n_sibling_ids_no_rows_in_edges"] = len([a for a in sib_all if a not in present])

    with open(out / "stock_fold_diff.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow(r)
    with open(out / "overmerge_skipped.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["author_id", "name", "dept", "person_id", "n_siblings"])
        w.writeheader()
        for r in rows:
            if r["fold_status"] == "suspected_overmerge":
                w.writerow({k: r[k] for k in ("author_id", "name", "dept", "person_id", "n_siblings")})
    (out / "report.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    con.close()
    return {"rows": rows, "summary": summary, "out_dir": str(out)}
