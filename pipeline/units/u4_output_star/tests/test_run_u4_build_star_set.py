"""A6 - offline unit tests for the full assembly path of build_star_set / _STAR_CELL_SQL (no 4TB SSD needed).

Defect addressed: the real-data assembly path that produces the headline star set had no unit tests, only
smoke tests that need the real disk. If the in-cell percentile / COALESCE override / panel fallback / poach
join regress (DENSE_RANK written by mistake, a missing partition dimension, a mistyped override), pure-function
tests stay green and the bug reaches the headline star table.

Ranking formula: naive ranking (rank = 1 + #{strictly higher}, pct = 1-rank/N; star = rank <= p*N in exact
integer arithmetic; ties share a rank and enter or leave together). The earlier midpoint-rank method is no
longer used; its pinned-value tests were rewritten for the naive ranking.

This file runs _STAR_CELL_SQL directly in in-memory duckdb on miniature pool fixtures, and runs build_star_set's
no_arrival / panel-fallback / foreign_poach branches on a synthetic derived_root. Tests only; run_u4 logic is
untouched.

Red-line thresholds (as build_star_set reads them, redlines_v4): gate1=max(pct_1=100, floor=30)=100;
gate5=max(pct_5=20, floor=30)=30; min_academic_age=2; econ subfield="2002".
"""
import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from identity.cohort import cohort_bin
from m7a_star.pctile_engine import star_flags, fractional_percentiles
from run_u4 import _STAR_CELL_SQL, ROSTER_FILES, build_star_set

GATE1, GATE5, MIN_AGE, ECON = 100, 30, 2, "2002"
GAP = 10   # academic_age.robust_first_pub_max_gap (the pool side switches to the robust first year with the same value)


# ============ Group 1: direct tests of _STAR_CELL_SQL (in-memory duckdb + miniature Zenou pool) ============

def _run_cell_sql(aw_rows, Y, cand_ids, *, ov=None, fpov=None, sov=None):
    """In-memory duckdb + cbin -> run _STAR_CELL_SQL. aw_rows: [(aid, yr, c, sf)].
    ov/fpov default as in build_star_set: all candidates go to econ; fpov/sov are empty placeholders.
    Returns {aid: row tuple}.
    Row = (aid, subfield, age_bin, aage, stock, pct, cell_n, rnk) - rnk = in-cell competition rank
    (the star call uses exact integer arithmetic on rank; pct is only stored/displayed).
    The SQL also takes {GAP} (pool-side robust first-publication year) and {SOV} (per-person stock override).
    """
    con = duckdb.connect()
    con.create_function("cbin", lambda a: cohort_bin(int(a)), ["INTEGER"], "VARCHAR")
    con.execute("CREATE TEMP TABLE aw (aid VARCHAR, yr INTEGER, c BIGINT, sf VARCHAR)")
    con.executemany("INSERT INTO aw VALUES (?,?,?,?)", aw_rows)
    ids = ",".join("'" + a + "'" for a in cand_ids)
    if ov is None:
        ov = ",".join(f"('{a}','{ECON}')" for a in cand_ids)
    if fpov is None:
        fpov = "('__none__',0)"
    if sov is None:
        sov = "('__none__',0)"
    rows = con.execute(
        _STAR_CELL_SQL.format(Y=Y, IDS=ids, OV=ov, FPOV=fpov, SOV=sov, GAP=GAP)).fetchall()
    con.close()
    return {r[0]: r for r in rows}


def _pool(Y, specs):
    """specs: [(aid, stock, age)] -> aw rows (one paper per person, yr=Y-age, c=stock, sf='2002')."""
    return [(aid, Y - age, stock, ECON) for aid, stock, age in specs]


def test_percentile_matches_pure_function_and_cell_n():
    """Naive-rank percentile/rank/stock/cell_n agree row by row with the pure function fractional_percentiles.

    The fixture puts the "tie block" **above** the candidate (under DESC ranking, rank counts the **rows**
    strictly above me): RANK and DENSE_RANK (which counts distinct **values**) diverge here, which locks
    out the "DENSE_RANK written by mistake" regression (a fixture of purely distinct values would miss it).
    """
    Y = 2015
    specs = ([("CAND", 100, 5)]
             + [(f"T{i}", 1000, 5) for i in range(10)]        # tie block (above the candidate)
             + [(f"D{i}", 200 + i, 5) for i in range(20)]     # spread 200..219 (also above the candidate)
             + [(f"B{i}", i + 1, 5) for i in range(10)])      # bottom 10 people (below the candidate)
    got = _run_cell_sql(_pool(Y, specs), Y, ["CAND"])
    _, sf, ab, aage, stock, pct, cell_n, rnk = got["CAND"]
    assert (sf, ab, aage, stock, cell_n) == (ECON, "2-5", 5, 100, 41)
    assert rnk == 31                                  # 1 + 30 strictly higher; DENSE_RANK would give 22 -> fails
    exp = dict(zip([a for a, _, _ in specs], fractional_percentiles([s for _, s, _ in specs])))
    assert pct == pytest.approx(exp["CAND"])          # SQL and the pure function use the same formula
    assert pct == pytest.approx(1 - 31 / 41)


def test_naive_ties_share_rank():
    """Tied stock -> same rank and same percentile (naive ranking: ties share a rank and enter/leave together)."""
    Y = 2015
    specs = [("T1", 500, 5), ("T2", 500, 5)] + [(f"B{i}", i, 5) for i in range(29)]
    got = _run_cell_sql(_pool(Y, specs), Y, ["T1", "T2"])
    assert got["T1"][7] == got["T2"][7] == 1                   # the tie shares rank 1
    assert got["T1"][5] == pytest.approx(got["T2"][5])
    assert got["T1"][5] == pytest.approx(1 - 1 / 31)
    exp = dict(zip([a for a, _, _ in specs], fractional_percentiles([s for _, s, _ in specs])))
    assert got["T1"][5] == pytest.approx(exp["T1"])


def test_sql_tie_at_second_place_whole_group_at_quota():
    """Regression guard 1 (SQL side): a cell of 10 with 3 people tied at 2nd place: all three share rank 2,
    pct = 1-2/10 = 0.8 -> with 2 top slots, rank 2 <= 2, so the whole group enters. The old midpoint formula
    gives 0.75 (group stays out), so this test fails if the formula is changed back."""
    Y = 2015
    specs = ([("C1", 100, 5), ("C2A", 50, 5), ("C2B", 50, 5), ("C2C", 50, 5)]
             + [(f"B{i}", i, 5) for i in range(6)])
    got = _run_cell_sql(_pool(Y, specs), Y, ["C1", "C2A", "C2B", "C2C"])
    assert got["C2A"][7] == got["C2B"][7] == got["C2C"][7] == 2
    for aid in ("C2A", "C2B", "C2C"):
        assert got[aid][5] == pytest.approx(1 - 2 / 10)
    assert got["C1"][7] == 1 and got["C1"][5] == pytest.approx(1 - 1 / 10)


def test_star_5pct_estimable_but_1pct_thin():
    """Cell big enough for 5% (cell_n>=30) but too thin for 1% (<100): top person -> 5%=True, 1%=None."""
    Y = 2015
    specs = [("CAND", 9999, 5)] + [(f"B{i}", i, 5) for i in range(35)]   # cell_n=36
    got = _run_cell_sql(_pool(Y, specs), Y, ["CAND"])
    _, sf, ab, aage, stock, pct, cn, rnk = got["CAND"]
    s1, s5 = star_flags(rnk, cn, aage, gate1=GATE1, gate5=GATE5, min_academic_age=MIN_AGE, p1=0.01, p5=0.05)
    assert cn == 36 and rnk == 1 and s5 is True and s1 is None


def test_star_1pct_when_cell_ge_100():
    """Cell big enough for 1% (cell_n>=100): top person -> 1%=True."""
    Y = 2015
    specs = [("CAND", 99999, 5)] + [(f"B{i}", i, 5) for i in range(120)]  # cell_n=121
    got = _run_cell_sql(_pool(Y, specs), Y, ["CAND"])
    _, sf, ab, aage, stock, pct, cn, rnk = got["CAND"]
    s1, s5 = star_flags(rnk, cn, aage, gate1=GATE1, gate5=GATE5, min_academic_age=MIN_AGE, p1=0.01, p5=0.05)
    assert cn == 121 and rnk == 1 and s1 is True and s5 is True


def test_age_ineligible_is_false_not_none():
    """Cell is big enough but academic age 0 < min_age 2: top person -> both tiers False (evaluated, not senior
    enough), not None (cannot be estimated).
    The order of checks is pinned: the seniority False comes before the thin-cell None, so the 1% tier
    (36<100, thin) is also False."""
    Y = 2015
    specs = [("CAND", 9999, 0)] + [(f"B{i}", i, 0) for i in range(35)]   # all age 0 -> bin "0", cell_n=36
    got = _run_cell_sql(_pool(Y, specs), Y, ["CAND"])
    _, sf, ab, aage, stock, pct, cn, rnk = got["CAND"]
    s1, s5 = star_flags(rnk, cn, aage, gate1=GATE1, gate5=GATE5, min_academic_age=MIN_AGE, p1=0.01, p5=0.05)
    assert (ab, aage, cn) == ("0", 0, 36) and s5 is False
    assert s1 is False                                # the seniority gate is checked first -> not None


def test_thin_cell_is_na():
    """Cell too thin (cell_n<30) and age eligible -> both tiers None (cannot estimate, no forced call)."""
    Y = 2015
    specs = [("CAND", 9999, 5)] + [(f"B{i}", i, 5) for i in range(10)]   # cell_n=11
    got = _run_cell_sql(_pool(Y, specs), Y, ["CAND"])
    _, sf, ab, aage, stock, pct, cn, rnk = got["CAND"]
    s1, s5 = star_flags(rnk, cn, aage, gate1=GATE1, gate5=GATE5, min_academic_age=MIN_AGE, p1=0.01, p5=0.05)
    assert cn == 11 and s1 is None and s5 is None


def test_ov_subfield_override_forces_econ():
    """OV subfield override: candidate papers mislabelled '9999' are still forced into economics '2002' -> same
    cell as the 2002 background."""
    Y = 2015
    aw = [("CAND", Y - 5, 500, "9999")] + [(f"B{i}", Y - 5, i, ECON) for i in range(35)]
    got = _run_cell_sql(aw, Y, ["CAND"])              # ov default = ('CAND','2002')
    _, sf, ab, aage, stock, pct, cn, rnk = got["CAND"]
    assert sf == ECON and cn == 36                    # if OV were mistyped -> the candidate would sit alone in a (9999,..) cell, cell_n=1


def test_fpov_robust_first_pub_override():
    """FPOV first-year override: drop an old contaminating same-name paper (1960), use the robust first year 2005
    -> COALESCE takes the override."""
    Y = 2015
    aw = [("CAND", 1960, 5, ECON), ("CAND", 2005, 100, ECON), ("CAND", 2010, 100, ECON)]
    aw += [(f"B{i}", Y - 10, i, ECON) for i in range(35)]   # background age 10 -> bin "10-13"
    with_ov = _run_cell_sql(aw, Y, ["CAND"], fpov="('CAND',2005)")
    _, sf, ab, aage, stock, pct, cn, rnk = with_ov["CAND"]
    assert (aage, ab, stock) == (10, "10-13", 205)    # the override 2005 is used; stock=SUM(yr<=Y)=5+100+100
    # Control (production semantics): with no FPOV it falls back to the **pool-side robust first year** (no longer a bare MIN):
    #   1960 and 2005 are 45 apart > gap=10 -> the pool's robust year is also 2005 -> same value as the override (candidate and pool are symmetric).
    without = _run_cell_sql(aw, Y, ["CAND"])
    assert without["CAND"][3] == 10 and without["CAND"][6] == 36


# ============ Group 1b: pool-side robust first-publication year ============

def test_pool_fp_robust_drops_isolated_leading_year():
    """Regression guard: a pool member (not a candidate, no FPOV) with a lone leading old paper (1960, 45>10 apart
    from 2005) -> pool-side fp = robust = 2005 -> academic age 10 falls into the "10-13" cell, no longer
    inflated to 55 in a wrong solo cell."""
    Y = 2015
    aw = [("P_OLD", 1960, 5, ECON), ("P_OLD", 2005, 100, ECON)]
    aw += [(f"B{i}", Y - 10, i, ECON) for i in range(35)]
    got = _run_cell_sql(aw, Y, ["P_OLD"], fpov="('__none__',0)")
    _, sf, ab, aage, stock, pct, cn, rnk = got["P_OLD"]
    assert (aage, ab) == (10, "10-13")               # a bare MIN would give 55 -> fails if the robust year is removed
    assert cn == 36                                  # same cell as the background (moved to its bin after cleaning)
    assert stock == 105                              # the stock definition is unchanged: all yr<=Y are added (including the dropped year)


def test_pool_fp_robust_keeps_continuous_career():
    """Zenou anchor (opposite case): a continuous career (no gap > gap) -> the pool's robust year leaves the
    earliest year alone (1991 kept)."""
    Y = 2015
    aw = [("Z", 1991, 50, ECON), ("Z", 1998, 50, ECON), ("Z", 2005, 50, ECON),
          ("Z", 2012, 50, ECON)]
    aw += [(f"B{i}", Y - 24, i, ECON) for i in range(35)]   # background, same academic age 24
    got = _run_cell_sql(aw, Y, ["Z"])
    assert got["Z"][3] == 24                         # fp=1991 -> 2015-1991=24 (earliest year unchanged)


def test_pool_fp_robust_distinct_years_semantics():
    """Duplicate publication years do not fool the gate: the contaminated year appears in two rows (1960 x2) and is
    still a "lone leading year" (the gap is judged after DISTINCT) -> dropped as before. If the window function
    consumed duplicate rows (1960->1960 gap 0), 1960 would be wrongly kept and academic age inflated to 55;
    this test would then fail."""
    Y = 2015
    aw = [("P_DUP", 1960, 3, ECON), ("P_DUP", 1960, 2, ECON), ("P_DUP", 2005, 100, ECON)]
    aw += [(f"B{i}", Y - 10, i, ECON) for i in range(35)]
    got = _run_cell_sql(aw, Y, ["P_DUP"])
    assert got["P_DUP"][3] == 10                     # DISTINCT semantics (consistent with set() in the shared pure function)


def test_sov_native_stock_override_changes_rank_not_cell():
    """Person-level (folded) stock override: SOV is a native CTE in the production SQL; candidate stock 100->1000
    (above the whole pool) -> rank 1; cell_n unchanged (the pool does not move, only the candidate); fp/age_bin
    ignore SOV."""
    Y = 2015
    specs = [("CAND", 100, 5)] + [(f"B{i}", 200 + i, 5) for i in range(40)]
    bare = _run_cell_sql(_pool(Y, specs), Y, ["CAND"])["CAND"]
    fold = _run_cell_sql(_pool(Y, specs), Y, ["CAND"], sov="('CAND',1000)")["CAND"]
    assert bare[7] == 41 and bare[4] == 100          # bare: last place
    assert fold[4] == 1000 and fold[7] == 1          # after the override: stock=override, rank 1
    assert bare[6] == fold[6] == 41                  # cell_n unchanged
    assert bare[2] == fold[2]                        # age_bin ignores SOV


# ============ Group 2: build_star_set on a synthetic derived_root (no_arrival / panel fallback / poaching) ============

_ROSTER_SCHEMA = pa.schema([
    ("author_id", pa.string()), ("display_name", pa.string()), ("dept_key", pa.string()),
    ("year_start", pa.int64()), ("confidence", pa.string()), ("human_verified", pa.bool_()),
])


def _w(root, subpath, rows, schema=None):
    p = root / subpath
    p.parent.mkdir(parents=True, exist_ok=True)
    tbl = pa.Table.from_pylist(rows, schema=schema) if schema else pa.Table.from_pylist(rows)
    pq.write_table(tbl, str(p))


def _build_synthetic_root(tmp_path):
    """Minimal synthetic derived_root: four candidates cover four paths:
      M_ROSTER: the roster has an arrival year (2016, hand-verified) -> roster path.
      U_PANEL : the roster lacks the year (unsw) -> the panel fallback infers it (P_U 2012/2013 at UNSW I31746571).
      M_NOARR : the roster lacks the year + the panel has no row for the department -> no_arrival.
      M_NOPOOL: the roster has an arrival year (2016) but no works at all up to t-1 -> not in the reference pool
                (all-None row).
    U_PANEL was at Stockholm (SE) before arrival -> pure foreign poach = True; M_ROSTER has no overseas
    evidence -> False.
    """
    r = tmp_path
    _w(r, ROSTER_FILES[0], [
        {"author_id": "M_ROSTER", "display_name": "MonRoster", "dept_key": "monash_econ",
         "year_start": 2016, "confidence": "high", "human_verified": True},
        {"author_id": "M_NOARR", "display_name": "MonNoArr", "dept_key": "monash_econ",
         "year_start": None, "confidence": "low", "human_verified": False},
        {"author_id": "M_NOPOOL", "display_name": "MonNoPool", "dept_key": "monash_econ",
         "year_start": 2016, "confidence": "high", "human_verified": True},
    ], schema=_ROSTER_SCHEMA)
    _w(r, ROSTER_FILES[1], [
        {"author_id": "U_PANEL", "display_name": "UnswPanel", "dept_key": "unsw_econ",
         "year_start": None, "confidence": "low", "human_verified": False},
    ], schema=_ROSTER_SCHEMA)
    _w(r, "u1_edges_full_2026-07-05/authorship_edges/part.parquet", [
        {"author_id": "M_ROSTER", "work_id": "W1"}, {"author_id": "U_PANEL", "work_id": "W2"}])
    _w(r, "u1_edges_full_2026-07-05/works/part.parquet", [
        {"work_id": "W1", "publication_year": 2010, "cited_by_count": 50, "subfield_id": ECON},
        {"work_id": "W2", "publication_year": 2008, "cited_by_count": 30, "subfield_id": ECON}])
    _w(r, "u1_edges_full_2026-07-05/institutions/part.parquet", [
        {"institution_id": "I_SU", "country_code": "SE"},
        {"institution_id": "I31746571", "country_code": "AU"},
        {"institution_id": "I56590836", "country_code": "AU"}])
    _w(r, "u2_person_map_2026-07-05/person_map/part.parquet", [
        {"author_id": "M_ROSTER", "person_id": "P_MR"},
        {"author_id": "U_PANEL", "person_id": "P_U"},
        {"author_id": "M_NOARR", "person_id": "P_MN"}])
    _w(r, "u3_panel_2026-07-06/panel/part.parquet", [
        {"person_id": "P_U", "year": 2012, "primary_affil_id": "I31746571"},
        {"person_id": "P_U", "year": 2013, "primary_affil_id": "I31746571"}])
    _w(r, "u3_panel_2026-07-06/affil_timeline/part.parquet", [
        {"person_id": "P_U", "year": 2010, "raw_affil": "Stockholm University",
         "canonical_affil_id": "I_SU"}])
    return r


def test_build_star_set_no_arrival_and_panel_fallback(tmp_path):
    """no_arrival branch + panel fallback: roster has a year -> use it; roster lacks it -> infer from the panel;
    panel has none either -> list separately as no_arrival."""
    res = build_star_set(_build_synthetic_root(tmp_path))
    stars = {s["author_id"]: s for s in res["stars"]}
    assert res["no_arrival"] == ["M_NOARR"]           # arrival cannot be inferred -> listed separately, never made up
    assert "M_NOARR" not in stars
    assert stars["M_ROSTER"]["arrival"] == 2016        # roster hand-verified arrival year
    assert stars["U_PANEL"]["arrival"] == 2012         # panel fallback: inferred as MIN(year in department)


def test_build_star_set_foreign_poach_flag(tmp_path):
    """foreign_poach branch: abroad (SE) before arrival -> True; no overseas evidence -> False."""
    res = build_star_set(_build_synthetic_root(tmp_path))
    stars = {s["author_id"]: s for s in res["stars"]}
    assert stars["U_PANEL"]["is_foreign_poach"] is True    # at Stockholm (SE) before arrival
    assert stars["M_ROSTER"]["is_foreign_poach"] is False   # no overseas row before arrival


def test_build_star_set_thin_cells_give_na_stars(tmp_path):
    """Miniature pool cell too thin -> is_star is None in both tiers (no forced call), but the candidate still comes
    out with subfield=econ + the true arrival year."""
    res = build_star_set(_build_synthetic_root(tmp_path))
    z = {s["author_id"]: s for s in res["stars"]}["U_PANEL"]
    assert z["subfield"] == ECON                        # the roster-based override puts everyone in economics
    assert z["is_star_1pct"] is None and z["is_star_5pct"] is None


def test_build_star_set_nonpool_candidate_cell_n_none(tmp_path):
    """Regression guard 2: a candidate not in the pool (has an arrival year, but no works up to t-1 -> not in the
    reference pool): percentile / both flags / age_eligible / cell_n are all None. Pinned: cell_n is **None**,
    not 0 - "no cell at all" is not "0 people in the cell"."""
    res = build_star_set(_build_synthetic_root(tmp_path))
    z = {s["author_id"]: s for s in res["stars"]}["M_NOPOOL"]
    assert z["arrival"] == 2016 and z["subfield"] == ECON
    assert z["cell_n"] is None
    assert z["percentile"] is None and z["stock"] is None
    assert z["is_star_1pct"] is None and z["is_star_5pct"] is None
    assert z["age_eligible"] is None


# ====== Group 3: accounting of dropped rows with a missing publication_year ======

_WORKS_SCHEMA = pa.schema([
    ("work_id", pa.string()), ("publication_year", pa.int64()),
    ("cited_by_count", pa.int64()), ("subfield_id", pa.string()),
])
_EDGES_SCHEMA = pa.schema([("author_id", pa.string()), ("work_id", pa.string())])


def test_build_star_set_counts_dropped_null_pub_year(tmp_path, capsys):
    """Works missing a year are still dropped (behaviour unchanged, no crash), but the number dropped is counted in
    result + one run-log line. Count definition = rows entering the join (edges x works); orphan works with a
    missing year and no edge are not counted."""
    r = _build_synthetic_root(tmp_path)
    # append one more part: W3 has no year and is cited by 2 edges (counts 2); W4 has no year and no edges (never enters the join, not counted).
    _w(r, "u1_edges_full_2026-07-05/works/part2.parquet", [
        {"work_id": "W3", "publication_year": None, "cited_by_count": 5, "subfield_id": ECON},
        {"work_id": "W4", "publication_year": None, "cited_by_count": 7, "subfield_id": ECON},
    ], schema=_WORKS_SCHEMA)
    _w(r, "u1_edges_full_2026-07-05/authorship_edges/part2.parquet", [
        {"author_id": "M_ROSTER", "work_id": "W3"},
        {"author_id": "U_PANEL", "work_id": "W3"},
    ], schema=_EDGES_SCHEMA)
    res = build_star_set(r)
    assert res["n_dropped_null_pub_year"] == 2
    # dropping behaviour is unchanged: a yearless paper never enters stock (M_ROSTER stock is still only W1's 50)
    stars = {s["author_id"]: s for s in res["stars"]}
    assert stars["M_ROSTER"]["stock"] == 50
    # one run-log line (the accounting is visible, not silent)
    assert "publication_year" in capsys.readouterr().err


def test_build_star_set_dropped_count_zero_when_clean(tmp_path):
    """No missing years in the whole database -> the count is 0 (the accounting field is always present, not written
    only when non-zero)."""
    res = build_star_set(_build_synthetic_root(tmp_path))
    assert res["n_dropped_null_pub_year"] == 0


# ====== Group 4: consuming hand-review adjudications + roster version switch ======
# 1. Part-time staff (adjunct_q3) -> removed from the candidate set (part-time does not count as on staff);
# 2. Local transfers (prior_au_employment) -> is_foreign_poach forced False (a local transfer is not a poach);
# 3. The U4 roster reader accepts the new roster version roster_v2026-07-10_starfix (6 hand-verified years are in it).

def test_build_star_set_excludes_adjudicated_candidate(tmp_path):
    """Q3 removal: candidates on the adjudication list do not enter the star call (roster rows are kept - removal happens
    only at the candidate-selection layer); who was removed is recorded in result (auditable); other candidates
    are unaffected."""
    res = build_star_set(_build_synthetic_root(tmp_path),
                         exclude_candidates={"M_ROSTER": "adjunct_q3: 测试注记"})
    stars = {s["author_id"] for s in res["stars"]}
    assert "M_ROSTER" not in stars
    assert "U_PANEL" in stars                                  # others unchanged
    assert res["excluded_candidates"] == {"M_ROSTER": "adjunct_q3: 测试注记"}


def test_build_star_set_exclude_unknown_id_raises(tmp_path):
    """fail-loud: an author_id on the removal list is not among the roster candidates at all -> ValueError (a
    mistyped id is caught)."""
    with pytest.raises(ValueError, match="A_TYPO"):
        build_star_set(_build_synthetic_root(tmp_path),
                       exclude_candidates={"A_TYPO": "x"})


def test_build_star_set_poach_override_forces_false(tmp_path):
    """poach adjudication: U_PANEL's timeline gives True (Stockholm before arrival); the hand-review adjudication overrides it to
    False (previously employed in Australia -> not a pure foreign poach); who was changed is recorded in
    result."""
    root = _build_synthetic_root(tmp_path)
    base = {s["author_id"]: s for s in build_star_set(root)["stars"]}
    assert base["U_PANEL"]["is_foreign_poach"] is True         # the timeline-based call when there is no adjudication
    res = build_star_set(root, poach_overrides={"U_PANEL": False})
    got = {s["author_id"]: s for s in res["stars"]}
    assert got["U_PANEL"]["is_foreign_poach"] is False
    assert res["poach_overridden"] == {"U_PANEL": False}


def test_build_star_set_poach_override_unknown_id_raises(tmp_path):
    """fail-loud: an author_id in the poach adjudication is not in the candidate set -> ValueError."""
    with pytest.raises(ValueError, match="A_TYPO"):
        build_star_set(_build_synthetic_root(tmp_path),
                       poach_overrides={"A_TYPO": False})


# ====== Group 5: work_pollution_discards (exact exclusion by work_id) ======
# Case A5071656006: an old paper by a namesake sits exactly max_leading_gap (10) before the true career start, so
# robust_first_pub cannot drop it -> exclude by exact work_id, which fixes both first_pub and stock contamination.

def test_build_star_set_work_pollution_excludes_from_stock_and_first_pub(tmp_path):
    """Add a 2005 same-name contaminating paper to M_ROSTER (gap to 2010 = 5 <= 10 -> robust_first_pub cannot drop
    it); excluding it by work_id -> stock loses that paper's citations + first_pub moves back from 2005 to 2010
    (academic age 10->5)."""
    r = _build_synthetic_root(tmp_path)
    _w(r, "u1_edges_full_2026-07-05/works/part_poll.parquet", [
        {"work_id": "W_POLL", "publication_year": 2005, "cited_by_count": 7,
         "subfield_id": ECON}], schema=_WORKS_SCHEMA)
    _w(r, "u1_edges_full_2026-07-05/authorship_edges/part_poll.parquet", [
        {"author_id": "M_ROSTER", "work_id": "W_POLL"}], schema=_EDGES_SCHEMA)
    # baseline (no exclusion): contamination present -> first_pub 2005 (academic age 2015-2005=10), stock includes 7 -> 57
    base = {s["author_id"]: s for s in build_star_set(r)["stars"]}
    assert base["M_ROSTER"]["academic_age"] == 10 and base["M_ROSTER"]["stock"] == 57
    # exclude that work -> first_pub 2010 (academic age 5), stock 50; recorded in result
    res = build_star_set(r, work_pollution_discards={"M_ROSTER": [{"work_id": "W_POLL"}]})
    got = {s["author_id"]: s for s in res["stars"]}
    assert got["M_ROSTER"]["academic_age"] == 5 and got["M_ROSTER"]["stock"] == 50
    assert res["work_pollution_discarded"] == {"M_ROSTER": ["W_POLL"]}


def test_build_star_set_work_pollution_only_touches_named_author(tmp_path):
    """The exclusion applies only to the named (author, work): another author citing the same work_id is unaffected
    (exact scope)."""
    r = _build_synthetic_root(tmp_path)
    _w(r, "u1_edges_full_2026-07-05/works/part_poll.parquet", [
        {"work_id": "W_SHARED", "publication_year": 2005, "cited_by_count": 7,
         "subfield_id": ECON}], schema=_WORKS_SCHEMA)
    _w(r, "u1_edges_full_2026-07-05/authorship_edges/part_poll.parquet", [
        {"author_id": "M_ROSTER", "work_id": "W_SHARED"},
        {"author_id": "U_PANEL", "work_id": "W_SHARED"}], schema=_EDGES_SCHEMA)
    res = build_star_set(r, work_pollution_discards={"M_ROSTER": [{"work_id": "W_SHARED"}]})
    got = {s["author_id"]: s for s in res["stars"]}
    assert got["M_ROSTER"]["stock"] == 50          # the M_ROSTER side drops 7
    # U_PANEL still holds W_SHARED's 7 (before arrival 2011: W2 2008=30 + W_SHARED 2005=7 = 37)
    assert got["U_PANEL"]["stock"] == 37


def test_build_star_set_work_pollution_unknown_pair_raises(tmp_path):
    """fail-loud: an excluded (author, work) matches 0 rows on disk -> ValueError (a mistyped id / invalid discard is
    not silent)."""
    with pytest.raises(ValueError, match="W_TYPO|work_pollution"):
        build_star_set(_build_synthetic_root(tmp_path),
                       work_pollution_discards={"M_ROSTER": [{"work_id": "W_TYPO"}]})


# ====== Group 6: stock folded to the person level (production; stock_fold_diag promoted) ======
# Rules: clusters flagged suspected_overmerge are not folded; a candidate not in person_map gets NULL plus a diagnostic report entry
# (no silent failures: null_stock_reason in {"truncation_empty", "not_in_person_map"}).

def _add_sibling_cluster(r):
    """Give M_ROSTER a sibling fragment id S_MR (same cluster P_MR): S_MR has 50 citations in 2012 (counted, <=t-1=2015),
    999 citations in 2020 (after t-1, never counted)."""
    _w(r, "u2_person_map_2026-07-05/person_map/part_sib.parquet", [
        {"author_id": "S_MR", "person_id": "P_MR"}])
    _w(r, "u1_edges_full_2026-07-05/authorship_edges/part_sib.parquet", [
        {"author_id": "S_MR", "work_id": "W_S1"}, {"author_id": "S_MR", "work_id": "W_S2"}],
       schema=_EDGES_SCHEMA)
    _w(r, "u1_edges_full_2026-07-05/works/part_sib.parquet", [
        {"work_id": "W_S1", "publication_year": 2012, "cited_by_count": 50, "subfield_id": ECON},
        {"work_id": "W_S2", "publication_year": 2020, "cited_by_count": 999, "subfield_id": ECON},
    ], schema=_WORKS_SCHEMA)


def test_build_star_set_folds_sibling_stock(tmp_path):
    """Regression guard: candidate stock = sum over all sibling ids in the folded person cluster (<=t-1 truncation as
    in production). M_ROSTER (W1=50) + sibling S_MR's 50 in 2012 -> 100 after folding; S_MR's 999 in 2020 is not
    counted."""
    r = _build_synthetic_root(tmp_path)
    _add_sibling_cluster(r)
    res = build_star_set(r)
    stars = {s["author_id"]: s for s in res["stars"]}
    assert stars["M_ROSTER"]["stock"] == 100          # 50 (W1) + 50 (W_S1); the 999 is outside the truncation
    rep = {x["author_id"]: x for x in res["stock_fold_report"]}
    assert rep["M_ROSTER"]["fold_status"] == "folded"
    assert rep["M_ROSTER"]["n_siblings"] == 2
    assert rep["M_ROSTER"]["null_stock_reason"] is None


def test_build_star_set_overmerge_cluster_not_folded(tmp_path):
    """Rule: clusters flagged suspected_overmerge are not folded (they absorb other people's citations) -> stock stays
    at the bare id's 50; reported separately for hand review."""
    r = _build_synthetic_root(tmp_path)
    _add_sibling_cluster(r)
    res = build_star_set(r, overmerge_person_ids={"P_MR"})
    stars = {s["author_id"]: s for s in res["stars"]}
    assert stars["M_ROSTER"]["stock"] == 50           # not folded: the sibling's 50 is not merged in
    rep = {x["author_id"]: x for x in res["stock_fold_report"]}
    assert rep["M_ROSTER"]["fold_status"] == "suspected_overmerge"


def test_build_star_set_not_in_person_map_null_stock_with_reason(tmp_path):
    """Rule: a candidate not in person_map (one that bypassed U2 disambiguation, the 10/211 kind) cannot be folded ->
    stock is **honestly NULL** (a bare id's holdings no longer pose as person-level stock); the diagnostic report
    has reason=not_in_person_map."""
    r = _build_synthetic_root(tmp_path)
    # M_NOMAP: has a roster year and works, but is not in person_map.
    _w(r, ROSTER_FILES[0], [
        {"author_id": "M_ROSTER", "display_name": "MonRoster", "dept_key": "monash_econ",
         "year_start": 2016, "confidence": "high", "human_verified": True},
        {"author_id": "M_NOMAP", "display_name": "NoMap", "dept_key": "monash_econ",
         "year_start": 2016, "confidence": "high", "human_verified": True},
    ], schema=_ROSTER_SCHEMA)
    _w(r, "u1_edges_full_2026-07-05/authorship_edges/part_nomap.parquet",
       [{"author_id": "M_NOMAP", "work_id": "W_NM"}], schema=_EDGES_SCHEMA)
    _w(r, "u1_edges_full_2026-07-05/works/part_nomap.parquet", [
        {"work_id": "W_NM", "publication_year": 2010, "cited_by_count": 77,
         "subfield_id": ECON}], schema=_WORKS_SCHEMA)
    res = build_star_set(r)
    stars = {s["author_id"]: s for s in res["stars"]}
    z = stars["M_NOMAP"]
    assert z["stock"] is None and z["cell_n"] is None and z["percentile"] is None
    assert z["is_star_1pct"] is None and z["is_star_5pct"] is None
    rep = {x["author_id"]: x for x in res["stock_fold_report"]}
    assert rep["M_NOMAP"]["fold_status"] == "not_in_person_map"
    assert rep["M_NOMAP"]["null_stock_reason"] == "not_in_person_map"
    assert stars["M_ROSTER"]["stock"] == 50           # people in the map are unaffected


def test_build_star_set_truncation_empty_reason_and_would_enter(tmp_path):
    """No silent failures: in the map but emptied by the <=t-1 truncation -> reason=truncation_empty;
    sibling ids have holdings <=t-1 -> would_enter_pool=True goes to hand review (a cell is never forced; stock
    stays NULL)."""
    r = _build_synthetic_root(tmp_path)
    # M_NOPOOL was originally not in person_map -> add it to the map first (singleton), making it "in the map but emptied".
    _w(r, "u2_person_map_2026-07-05/person_map/part_np.parquet",
       [{"author_id": "M_NOPOOL", "person_id": "P_NP"}, {"author_id": "S_NP", "person_id": "P_NP"}])
    # sibling S_NP has only one paper <=t-1 -> the fold side has holdings (would_enter_pool signal).
    _w(r, "u1_edges_full_2026-07-05/authorship_edges/part_np.parquet",
       [{"author_id": "S_NP", "work_id": "W_NP"}], schema=_EDGES_SCHEMA)
    _w(r, "u1_edges_full_2026-07-05/works/part_np.parquet", [
        {"work_id": "W_NP", "publication_year": 2010, "cited_by_count": 9,
         "subfield_id": ECON}], schema=_WORKS_SCHEMA)
    res = build_star_set(r)
    z = {s["author_id"]: s for s in res["stars"]}["M_NOPOOL"]
    assert z["stock"] is None and z["cell_n"] is None   # the bare side has no cell -> a cell is never forced
    rep = {x["author_id"]: x for x in res["stock_fold_report"]}
    assert rep["M_NOPOOL"]["null_stock_reason"] == "truncation_empty"
    assert rep["M_NOPOOL"]["would_enter_pool"] is True
    # Control: in a clean root (separate subdirectory, so the parts appended above do not contaminate it) M_NOPOOL is not in the map and has no
    # works at all -> reason=not_in_person_map
    res2 = build_star_set(_build_synthetic_root(tmp_path / "clean"))
    rep2 = {x["author_id"]: x for x in res2["stock_fold_report"]}
    assert rep2["M_NOPOOL"]["null_stock_reason"] == "not_in_person_map"
    assert rep2["M_NOPOOL"]["would_enter_pool"] is False


def test_build_star_set_fold_report_covers_all_candidates(tmp_path):
    """Audit completeness: stock_fold_report always has one row for every candidate entering the star call
    (including normal in-pool ones, null_stock_reason=None); no_arrival candidates are not in it (they never
    entered the star call)."""
    res = build_star_set(_build_synthetic_root(tmp_path))
    rep_ids = {x["author_id"] for x in res["stock_fold_report"]}
    star_ids = {s["author_id"] for s in res["stars"]}
    assert rep_ids == star_ids
    assert "M_NOARR" not in rep_ids                    # no_arrival is listed separately, not in the report


def test_roster_read_side_points_at_starfix_version():
    """All U4 roster readers accept the corrected roster version (single source of truth run_u4.ROSTER_FILES;
    real_inputs imports from the same place, preventing path drift between two copies)."""
    from m7a_star.real_inputs import _ROSTER_FILES
    from run_u4 import ROSTER_FILES, U4_INPUTS
    assert all("roster_v2026-07-10_starfix" in f for f in ROSTER_FILES)
    assert U4_INPUTS["roster_monash"] == ROSTER_FILES[0]
    assert U4_INPUTS["roster_unsw"] == ROSTER_FILES[1]
    assert tuple(_ROSTER_FILES) == tuple(ROSTER_FILES)
