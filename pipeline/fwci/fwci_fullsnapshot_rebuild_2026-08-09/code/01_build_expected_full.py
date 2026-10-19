#!/usr/bin/env python3
"""01_build_expected_full.py — full-snapshot denominator -> expected table (denominator rule correction)

The FWCI denominator uses the full-snapshot field benchmark instead of the seed-subset pop.
This script folds the newly scanned cell table (fwci_baseline_pop_full.parquet: 543,037 cells /
375.5 million papers / 2.877 billion citations; G-A and G-B pass) into an expected table under the
fixed rules below, directly replacing the output of `01_build_selffwci_baseline.py`.

Fixed rules (read from common/_redlines.py):
  - included_types = [article, review] (whitelist, same list for numerator and denominator, B-SYM)
  - expected_method = mean -> expected = citation_sum / work_count
  - missing_fill = NA (missing cell / missing subfield / expected=0 -> NA on the numerator side, never filled with 0)
  - denominator_leave_star = false (the denominator contains all stars)
  - paratext_symmetric_drop = TRUE <- ★can be applied on the denominator side for the first time
      The new table carries paratext_count / paratext_citation_sum (the is_paratext=True subset of
      the same cell), so expected = (citation_sum − paratext_citation_sum) / (work_count − paratext_count).
      On the numerator side fwci_raw.py already does `if work.get("is_paratext"): return NA`, so the two sides are symmetric.

Output (written to the new directory only):
  data/fwci_expected_fullsnapshot_2026-08-09.parquet — same 4-column schema as the old expected table
  data/g_step1_expected.json — table-build verification record
"""
import json
import os
import sys

import duckdb

# --- M3 port: repo path resolution (legacy hard-coded the author's machine) — config/paths.yaml ---
import pathlib as _sar_pl, sys as _sar_sys
_sar_repo = next(p for p in _sar_pl.Path(__file__).resolve().parents if p.name == "fwci").parents[1]
if str(_sar_repo) not in _sar_sys.path:
    _sar_sys.path.append(str(_sar_repo))
from pipeline.lib.paths import (derived_root as _sar_derived_root,  # noqa: E402,F401
                                snapshot_root as _sar_snapshot_root,
                                ssd_root as _sar_ssd_root,
                                legacy_thesis as _sar_legacy_thesis,
                                require_readable as _sar_rd,
                                require_writable as _sar_rw,
                                output_target as _sar_out,
                                deferred_output_target as _sar_lazyout)

ROOT = str(_sar_rd(_sar_legacy_thesis()))
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEWPOP = f"{ROOT}/v2_output/fwci_baseline_fullsnapshot_2026-08-09/data/fwci_baseline_pop_full.parquet"
OLDPOP = str(_sar_rd(_sar_derived_root()) / "u1_edges_full_2026-07-05/fwci_baseline_pop/**/*.parquet")
OUT = f"{BASE}/data/fwci_expected_fullsnapshot_2026-08-09.parquet"
OUT_OLD = f"{BASE}/data/fwci_expected_oldpop_2026-08-09.parquet"   # old-rule expected (for the G-C comparison)
OUT_JSON = f"{BASE}/data/g_step1_expected.json"

sys.path.insert(0, f"{ROOT}/multiplex_pipeline/units/u0_foundation/src")
from common._redlines import RED, require  # noqa: E402

INCLUDED = tuple(require("fwci", "included_types"))
assert require("fwci", "expected_method") == "mean"
assert RED["fwci"]["paratext_symmetric_drop"] is True
assert RED["fwci"]["missing_fill"] == "NA"

con = duckdb.connect()
con.execute("SET memory_limit='8GB'")
con.execute("PRAGMA threads=8")

rep = {"date": "2026-08-09", "included_types": list(INCLUDED),
       "expected_method": "mean", "paratext_symmetric_drop": True,
       "source_new_pop": NEWPOP, "source_old_pop": OLDPOP}

# ---------------- 1. New denominator -> expected (with the paratext symmetric drop) ----------------
con.execute(f"""
    CREATE TABLE newpop AS
    SELECT subfield_id, year, work_type, work_count, citation_sum,
           paratext_count, paratext_citation_sum
    FROM read_parquet('{NEWPOP}')
    WHERE work_type IN {INCLUDED}""")

# Hard check 1: paratext must be a true subset of the main count (the scanner merge already checked; checked again independently here)
bad = con.execute("SELECT count(*) FROM newpop WHERE paratext_count > work_count "
                  "OR paratext_citation_sum > citation_sum").fetchone()[0]
assert bad == 0, f"HALT: {bad} cells have a paratext count above the main count"
# Hard check 2: subfield must not be all None (C-4 snapshot-fallback guard, copied verbatim from fwci_baseline_build.py)
assert con.execute("SELECT count(*) FROM newpop WHERE subfield_id IS NULL").fetchone()[0] == 0

para_cells = con.execute("SELECT count(*), coalesce(sum(paratext_count),0), "
                         "coalesce(sum(paratext_citation_sum),0) FROM newpop "
                         "WHERE paratext_count > 0").fetchone()
allpara_cells = con.execute("SELECT count(*) FROM newpop "
                            "WHERE work_count - paratext_count <= 0").fetchone()[0]
rep["paratext_symmetric_drop_effect"] = {
    "article_review_cells_with_paratext": para_cells[0],
    "paratext_works_removed_from_denominator": int(para_cells[1]),
    "paratext_citations_removed_from_denominator": int(para_cells[2]),
    "cells_emptied_by_drop": allpara_cells,
    "note": ("本快照里 is_paratext=True 的 works 其 type 也全是 'paratext'，"
             "已被 included_types 白名单挡在外面 → 对称剔在 article/review cell 上"
             "数值影响为 0（实测，非假设）。减法照做，作为口径落地凭证。"),
}

con.execute("""
    CREATE TABLE expected_new AS
    SELECT subfield_id, year, work_type,
           (citation_sum - paratext_citation_sum) * 1.0
             / (work_count - paratext_count) AS expected_citations
    FROM newpop
    WHERE work_count - paratext_count > 0
    ORDER BY subfield_id, year, work_type""")

n_new, n_zero_new = con.execute(
    "SELECT count(*), sum(CASE WHEN expected_citations = 0 THEN 1 ELSE 0 END) "
    "FROM expected_new").fetchone()
con.execute(f"COPY expected_new TO '{OUT}' (FORMAT PARQUET)")

# ---------------- 2. Old denominator -> expected (G-C comparison; formula identical to the production code) ----------------
con.execute(f"""
    CREATE TABLE expected_old AS
    SELECT subfield_id, year, work_type,
           citation_sum * 1.0 / work_count AS expected_citations,
           work_count, citation_sum
    FROM read_parquet('{OLDPOP}', hive_partitioning=0)
    WHERE work_type IN {INCLUDED}
    ORDER BY subfield_id, year, work_type""")
n_old, n_zero_old = con.execute(
    "SELECT count(*), sum(CASE WHEN expected_citations = 0 THEN 1 ELSE 0 END) "
    "FROM expected_old").fetchone()
con.execute(f"COPY (SELECT subfield_id, year, work_type, expected_citations, "
            f"work_count, citation_sum FROM expected_old) TO '{OUT_OLD}' (FORMAT PARQUET)")

# ---------------- 3. Oracle reconciliation: recompute every cell with the production build_fwci_baseline itself ----------------
# (pure production formula without the paratext drop; since the paratext drop has zero effect on article/review in this snapshot,
#   the two must be bit-identical — this also verifies that "the subtraction broke no cell")
sys.path.insert(0, f"{ROOT}/multiplex_pipeline/units/u4_output_star/src")
from m5_output.fwci_baseline_build import build_fwci_baseline  # noqa: E402

pop_rows = [dict(zip(("subfield_id", "year", "work_type", "work_count", "citation_sum"), t))
            for t in con.execute(
                f"SELECT subfield_id, year, work_type, work_count, citation_sum "
                f"FROM read_parquet('{NEWPOP}')").fetchall()]
oracle = {(r["subfield_id"], r["year"], r["work_type"]): r["expected_citations"]
          for r in build_fwci_baseline(pop_rows)}
mine = {(sf, yr, wt): exp for sf, yr, wt, exp in con.execute(
    "SELECT subfield_id, year, work_type, expected_citations FROM expected_new").fetchall()}
only_o, only_m = set(oracle) - set(mine), set(mine) - set(oracle)
mism = [(k, oracle[k], mine[k]) for k in (set(oracle) & set(mine)) if oracle[k] != mine[k]]
oracle_pass = not only_o and not only_m and not mism
rep["oracle_vs_production_build_fwci_baseline"] = {
    "oracle_cells": len(oracle), "mine_cells": len(mine),
    "only_oracle": len(only_o), "only_mine": len(only_m),
    "value_mismatch": len(mism), "mismatch_examples": [list(map(str, m)) for m in mism[:5]],
    "pass": oracle_pass}

rep["expected_new"] = {"cells": n_new, "zero_expected_cells": int(n_zero_new or 0), "out": OUT}
rep["expected_old"] = {"cells": n_old, "zero_expected_cells": int(n_zero_old or 0), "out": OUT_OLD}
rep["PASS"] = bool(oracle_pass)

json.dump(rep, open(OUT_JSON, "w"), indent=1, ensure_ascii=False)
print(json.dumps(rep, indent=1, ensure_ascii=False))
if not oracle_pass:
    raise SystemExit(2)
