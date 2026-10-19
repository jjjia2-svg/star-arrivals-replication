"""m7a stock_fold_diag — U4 stock folding by person, "double-computation diagnostic", TDD red tests (root cause B, fix 2).

Root problem: U4 stock was computed on the bare author_id without joining person_map (U3 folds clusters, U4 does not = inconsistent definition;
this is the direct mechanism by which A5008470795/A5086383420, attached to empty ids, were missed). This diagnostic: for the frozen star_set candidates, compute twice
  (a) the current bare-id stock (recomputation of the production definition, parity gate: must equal the frozen artifact person by person)
  (b) stock after folding by person_id (sibling ids in the same flagA person_map cluster merged in)
Hard rules: diagnose only, do not change the production star-picking path, do not freeze; suspected_overmerge clusters are not folded (they absorb others' citations) and are listed separately;
Zenou comparison has zero drift (bare side = frozen artifact, equal field by field).
"""
import duckdb
import pytest

from identity.cohort import cohort_bin
from m7a_star.stock_fold_diag import (
    DIAG_CELL_SQL,
    assemble_diff_rows,
    build_fold_plan,
    diag_cells,
    folded_stocks,
    tier_label,
)
from run_u4 import _STAR_CELL_SQL

ECON = "2002"


def _con(aw_rows):
    """In-memory duckdb + cbin + aw temporary tables. aw_rows: [(aid, yr, c, sf)]."""
    con = duckdb.connect()
    con.create_function("cbin", lambda a: cohort_bin(int(a)), ["INTEGER"], "VARCHAR")
    con.execute("CREATE TEMP TABLE aw (aid VARCHAR, yr INTEGER, c BIGINT, sf VARCHAR)")
    con.executemany("INSERT INTO aw VALUES (?,?,?,?)", aw_rows)
    return con


def _pool(Y, specs):
    """specs: [(aid, stock, age)] → aw rows (one paper per person, yr=Y-age, c=stock, sf=ECON)."""
    return [(aid, Y - age, stock, ECON) for aid, stock, age in specs]


# ============ fold plan: three states ============

def test_fold_plan_statuses_folded_missing_overmerge():
    """C1 in person_map and the cluster is clean → folded (all sibling ids listed, including self);
    C2 not in person_map → not_in_person_map (only itself);
    C3 cluster flagged suspected_overmerge → not folded, listed separately (sibling ids still recorded for manual review)."""
    author_to_person = {"C1": "P1", "S1a": "P1", "S1b": "P1",
                        "C3": "P3", "S3": "P3"}
    members_by_person = {"P1": ["C1", "S1a", "S1b"], "P3": ["C3", "S3"]}
    plan = build_fold_plan(["C1", "C2", "C3"], author_to_person, members_by_person,
                           overmerge_person_ids={"P3"})
    assert plan["C1"] == {"person_id": "P1", "sibling_ids": ["C1", "S1a", "S1b"],
                          "fold_status": "folded"}
    assert plan["C2"] == {"person_id": None, "sibling_ids": ["C2"],
                          "fold_status": "not_in_person_map"}
    assert plan["C3"]["fold_status"] == "suspected_overmerge"
    assert plan["C3"]["sibling_ids"] == ["C3", "S3"]


def test_fold_plan_single_member_cluster_is_folded_noop():
    """Single-member cluster: folding = unchanged (sibling set = itself), status still folded — folding has zero effect on it (a Zenou-safe base)."""
    plan = build_fold_plan(["Z"], {"Z": "PZ"}, {"PZ": ["Z"]}, overmerge_person_ids=set())
    assert plan["Z"] == {"person_id": "PZ", "sibling_ids": ["Z"], "fold_status": "folded"}


# ============ DIAG_CELL_SQL: derived from the production SQL + stock override ============

def test_diag_sql_derived_from_production_sql():
    """Promoted to production (E5): the SOV fold-by-person override is already a native CTE of the production SQL → DIAG and production
    share the same one (single source of truth); production must carry its own sov CTE + LEFT JOIN sov (if lost = the folding silently stops working)."""
    assert "sov(aid, stock) AS (VALUES {SOV})" in _STAR_CELL_SQL
    assert "LEFT JOIN sov" in _STAR_CELL_SQL
    assert DIAG_CELL_SQL is _STAR_CELL_SQL
    assert "RANK() OVER (PARTITION BY subfield, age_bin ORDER BY stock DESC)" in DIAG_CELL_SQL


def test_diag_sql_empty_sov_matches_production_sql():
    """Empty SOV placeholder → DIAG equals production _STAR_CELL_SQL row by row (parity base; always true after promotion, kept as a guard)."""
    Y = 2015
    specs = [("CAND", 100, 5)] + [(f"B{i}", i, 5) for i in range(40)]
    ids = "'CAND'"
    ov = f"('CAND','{ECON}')"
    fpov = "('__none__',0)"
    con = _con(_pool(Y, specs))
    prod = con.execute(_STAR_CELL_SQL.format(Y=Y, IDS=ids, OV=ov, FPOV=fpov,
                                             SOV="('__none__',0)", GAP=10)).fetchall()
    diag = con.execute(DIAG_CELL_SQL.format(Y=Y, IDS=ids, OV=ov, FPOV=fpov,
                                            SOV="('__none__',0)", GAP=10)).fetchall()
    assert sorted(prod) == sorted(diag)


def test_diag_sql_stock_override_changes_rank_not_cell():
    """SOV lifts the candidate's stock 100→1000 (above the whole pool) → rank 1; cell_n unchanged (the pool does not move, only the candidate)."""
    Y = 2015
    specs = [("CAND", 100, 5)] + [(f"B{i}", 200 + i, 5) for i in range(40)]  # bare id sits at the bottom
    con = _con(_pool(Y, specs))
    kw = dict(Y=Y, IDS="'CAND'", OV=f"('CAND','{ECON}')", FPOV="('__none__',0)", GAP=10)
    bare = diag_cells(con, sov="('__none__',0)", **kw)["CAND"]
    fold = diag_cells(con, sov="('CAND',1000)", **kw)["CAND"]
    # row = (aid, subfield, age_bin, aage, stock, pct, cell_n, rnk)
    assert bare[7] == 41 and bare[4] == 100          # bare id: at the bottom, rank 41
    assert fold[4] == 1000 and fold[7] == 1          # after folding: stock=override, rank 1
    assert bare[6] == fold[6] == 41                  # cell_n unchanged
    assert bare[2] == fold[2]                        # age_bin frozen (fp does not take SOV)


# ============ folded_stocks: sum of sibling ids + cutoff + not-folded list ============

def test_folded_stocks_sums_siblings_up_to_year():
    """Folded = Σ works of all sibling ids in the cluster (yr ≤ Y); papers of a sibling id after Y do not count (t−1 cutoff, same as production)."""
    aw = [("C1", 2010, 100, ECON), ("S1", 2012, 50, ECON), ("S1", 2020, 999, ECON)]
    con = _con(aw)
    plan = {"C1": {"person_id": "P1", "sibling_ids": ["C1", "S1"], "fold_status": "folded"}}
    got = folded_stocks(con, plan, Y=2015, aids=["C1"])
    assert got == {"C1": 150}                        # 100+50; the 999 in 2020 does not count


def test_folded_stocks_skips_overmerge_and_unmapped():
    """suspected_overmerge / not_in_person_map are never folded → they do not appear in the folded result."""
    aw = [("C3", 2010, 10, ECON), ("S3", 2010, 10000, ECON), ("C2", 2010, 5, ECON)]
    con = _con(aw)
    plan = {
        "C3": {"person_id": "P3", "sibling_ids": ["C3", "S3"], "fold_status": "suspected_overmerge"},
        "C2": {"person_id": None, "sibling_ids": ["C2"], "fold_status": "not_in_person_map"},
    }
    assert folded_stocks(con, plan, Y=2015, aids=["C3", "C2"]) == {}


def test_folded_stocks_no_works_at_cutoff_absent():
    """Sibling set has no works ≤Y → no row (no cell ≠ 0; same semantics as the production discipline of cell_n=None)."""
    aw = [("S1", 2020, 999, ECON)]
    con = _con(aw)
    plan = {"C1": {"person_id": "P1", "sibling_ids": ["C1", "S1"], "fold_status": "folded"}}
    assert folded_stocks(con, plan, Y=2015, aids=["C1"]) == {}


# ============ tier_label ============

def test_tier_label_mapping():
    """Tier label: 1pct > 5pct > below; both flags None (thin cell / not in pool) → NA."""
    assert tier_label(True, True) == "1pct"
    assert tier_label(False, True) == "5pct"
    assert tier_label(None, True) == "5pct"          # thin cell at the 1% tier None + 5% True
    assert tier_label(False, False) == "below"
    assert tier_label(None, None) == "NA"


# ============ assemble_diff_rows: report assembly (pure function) ============

def _frozen(aid, *, arrival=2016, stock=100, cell_n=200, aage=10, age_bin="10-13",
            pct=0.5, s1=False, s5=False):
    return {"author_id": aid, "name": f"N_{aid}", "dept": "monash_econ",
            "arrival": arrival, "subfield": ECON, "age_bin": age_bin,
            "academic_age": aage, "stock": stock, "percentile": pct, "cell_n": cell_n,
            "is_star_1pct": s1, "is_star_5pct": s5, "age_eligible": True,
            "is_foreign_poach": False}


def test_assemble_diff_rows_delta_and_tier_change():
    """After folding the rank rises into the top 5% → delta>0 + tier below→5pct + tier_changed=True;
    unchanged after folding: delta=0 + tier_changed=False (Zenou type)."""
    frozen = [_frozen("C1", stock=100, cell_n=200, pct=1 - 150 / 200),
              _frozen("Z", stock=9968, cell_n=200, pct=1 - 1 / 200, s1=True, s5=True)]
    plan = {"C1": {"person_id": "P1", "sibling_ids": ["C1", "S1"], "fold_status": "folded"},
            "Z": {"person_id": "PZ", "sibling_ids": ["Z"], "fold_status": "folded"}}
    folded_stock = {"C1": 5000, "Z": 9968}
    # cell row after folding: (aid, subfield, age_bin, aage, stock, pct, cell_n, rnk)
    folded_cells = {"C1": ("C1", ECON, "10-13", 10, 5000, 1 - 4 / 200, 200, 4),
                    "Z": ("Z", ECON, "10-13", 10, 9968, 1 - 1 / 200, 200, 1)}
    rows, summary = assemble_diff_rows(
        frozen, plan, folded_stock, folded_cells,
        gate1=100, gate5=30, min_academic_age=2, p1=0.01, p5=0.05)
    by = {r["author_id"]: r for r in rows}
    c1 = by["C1"]
    assert c1["stock_bare"] == 100 and c1["stock_folded"] == 5000 and c1["stock_delta"] == 4900
    assert c1["tier_frozen"] == "below" and c1["tier_folded"] == "5pct"
    assert c1["tier_changed"] is True
    z = by["Z"]
    assert z["stock_delta"] == 0 and z["tier_changed"] is False   # Zenou type: zero drift after folding
    assert z["tier_frozen"] == "1pct" and z["tier_folded"] == "1pct"
    assert summary["n_stock_changed"] == 1
    assert summary["n_tier_changed"] == 1


def test_assemble_diff_rows_overmerge_and_nopool_buckets():
    """suspected_overmerge candidate: not folded (folded=None), listed separately in the report;
    not in the pool when frozen (stock=None) but a sibling has works → would_enter_pool bucket (tier not judged by force)."""
    frozen = [
        _frozen("C3", stock=50),
        {**_frozen("C4"), "stock": None, "cell_n": None, "percentile": None,
         "academic_age": None, "age_bin": None, "is_star_1pct": None,
         "is_star_5pct": None, "age_eligible": None},
    ]
    plan = {"C3": {"person_id": "P3", "sibling_ids": ["C3", "S3"],
                   "fold_status": "suspected_overmerge"},
            "C4": {"person_id": "P4", "sibling_ids": ["C4", "S4"], "fold_status": "folded"}}
    rows, summary = assemble_diff_rows(
        frozen, plan, {"C4": 777}, {},
        gate1=100, gate5=30, min_academic_age=2, p1=0.01, p5=0.05)
    by = {r["author_id"]: r for r in rows}
    assert by["C3"]["fold_status"] == "suspected_overmerge"
    assert by["C3"]["stock_folded"] is None and by["C3"]["tier_changed"] is None
    assert by["C4"]["stock_bare"] is None and by["C4"]["stock_folded"] == 777
    assert by["C4"]["would_enter_pool"] is True
    assert by["C4"]["tier_folded"] == "NA"           # no cell when frozen → tier not judged by force
    assert summary["n_overmerge_skipped"] == 1
    assert summary["n_would_enter_pool"] == 1
