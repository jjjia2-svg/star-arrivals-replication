# DIFF.md — the econ clones against their pinned originals

Generated 2026-09-22 by `difflib.unified_diff` over the pinned files (sha256 from
`tests/pipeline_ported.sha256`, asserted at generation). Line numbers are 1-based in each file.
Every hunk is either the header comment (a `#` block right after the shebang — no code) or
field/path wiring: the `--field` choice list, the economics person map (U2 11-school map instead
of the multidisc seeds map) and the signed-star table read for the ex-star exclusion. No
computation line changed; every other economics input reaches the clones at the gold layout's
fnfix names through the shadow legacy tree (`econ_gold_stage.STAGED`).

## `10_build_union_frame_gold_econ.py` vs `pipeline/frames/multidisc_gold_2026-08-10/code/10_build_union_frame_gold.py`

pinned original sha256 `55592a516dc385091f4791e336104a0bdf5776a87521b472f7ab60b920ad51e1`

lines: original 697, clone 712; changed lines (excluding the header block): 9

```diff
--- pipeline/frames/multidisc_gold_2026-08-10/code/10_build_union_frame_gold.py
+++ pipeline/frames/cal2026-10/econ_gold/10_build_union_frame_gold_econ.py
@@ -1,3 +1,13 @@
 #!/usr/bin/env python3
+# cal2026-10 econ_gold clone of pipeline/frames/multidisc_gold_2026-08-10/code/10_build_union_frame_gold.py
+# (verbatim pin 55592a516dc385091f4791e336104a0bdf5776a87521b472f7ab60b920ad51e1).
+# Repo-authored, 2026-09-22. The ONLY changes are field/path wiring so the same machine accepts
+# economics: `--field econ` is admitted, the person map for economics is the U2 11-school map
+# (the multidisc seeds map holds no economics author), and the signed-star set read for the
+# ex-star exclusion is the field's own signed table. Every computation line is byte-identical to
+# the pinned original; the exact hunks are listed in DIFF.md next to this file. Economics inputs
+# are staged by run_econ_gold.py at the gold layout's fnfix names inside a private shadow of the
+# legacy tree (the 2026-08-28 caliber staging mechanism, frames_stage.py), so no other path line
+# had to move. Assumptions of the economics run are written in run_econ_gold.py's docstring.
 """10_build_frame_multidisc.py — 化学/数学 系暴露产出帧（照经济 v9 口径移植）
 
@@ -69,5 +79,5 @@
 
 ap = argparse.ArgumentParser()
-ap.add_argument("--field", required=True, choices=["chemistry", "math_stats"])
+ap.add_argument("--field", required=True, choices=["chemistry", "math_stats", "econ"])
 ap.add_argument("--roster-clean", default="none", choices=["none", "r1r2r3", "r1v2"])
 args = ap.parse_args()
@@ -92,4 +102,9 @@
 OUT_DIR = _sar_staged(f"{_sar_legacy_thesis()}/v2_output/multidisc_gold_2026-08-10/data/{VAR}/union_frame_{FIELD}")
 os.makedirs(OUT_DIR, exist_ok=True)
+if FIELD == "econ":   # cal2026-10 econ_gold wiring (see header): U2 person map; econ's own signed-star table
+    PMAP = str(_sar_derived_root() / "u2_person_map_11school_2026-07-16/person_map/data.parquet")
+    SIGNED_FIELDS = ("econ",)
+else:
+    SIGNED_FIELDS = ("chemistry", "math_stats")
 
 sys.path.insert(0, f"{ROOT}/multiplex_pipeline/units/u0_foundation/src")
@@ -483,5 +498,5 @@
 # ============ 6. 产出（SSD works.fwci 直取；块A）============
 signed_star_all = set()
-for f_ in ("chemistry", "math_stats"):
+for f_ in SIGNED_FIELDS:
     p_ = f"{BASE}/../data/events_{f_}_gold_2026-08-10.csv"
     signed_star_all |= set(pd.read_csv(p_).author_id)
```

## `20_rebuild_y_gold_econ.py` vs `pipeline/frames/multidisc_gold_2026-08-10/code/20_rebuild_y_gold.py`

pinned original sha256 `c7d02ab760ec426a59706b6b3a7479300ca536b57314bb8b6db420f0d746898e`

lines: original 414, clone 429; changed lines (excluding the header block): 9

```diff
--- pipeline/frames/multidisc_gold_2026-08-10/code/20_rebuild_y_gold.py
+++ pipeline/frames/cal2026-10/econ_gold/20_rebuild_y_gold_econ.py
@@ -1,3 +1,13 @@
 #!/usr/bin/env python3
+# cal2026-10 econ_gold clone of pipeline/frames/multidisc_gold_2026-08-10/code/20_rebuild_y_gold.py
+# (verbatim pin c7d02ab760ec426a59706b6b3a7479300ca536b57314bb8b6db420f0d746898e).
+# Repo-authored, 2026-09-22. The ONLY changes are field/path wiring so the same machine accepts
+# economics: `--field econ` is admitted, the person map for economics is the U2 11-school map
+# (the multidisc seeds map holds no economics author), and the signed-star set read for the
+# ex-star exclusion is the field's own signed table. Every computation line is byte-identical to
+# the pinned original; the exact hunks are listed in DIFF.md next to this file. Economics inputs
+# are staged by run_econ_gold.py at the gold layout's fnfix names inside a private shadow of the
+# legacy tree (the 2026-08-28 caliber staging mechanism, frames_stage.py), so no other path line
+# had to move. Assumptions of the economics run are written in run_econ_gold.py's docstring.
 """05_rebuild_multidisc_y.py — 化学/数学帧换分母重算 y（2026-08-09）
 
@@ -67,7 +77,12 @@
 
 ap = argparse.ArgumentParser()
-ap.add_argument("--field", required=True, choices=["chemistry", "math_stats"])
+ap.add_argument("--field", required=True, choices=["chemistry", "math_stats", "econ"])
 args = ap.parse_args()
 FIELD = args.field
+if FIELD == "econ":   # cal2026-10 econ_gold wiring (see header): U2 person map; econ's own signed-star table
+    PMAP = str(_sar_derived_root() / "u2_person_map_11school_2026-07-16/person_map/data.parquet")
+    SIGNED_FIELDS = ("econ",)
+else:
+    SIGNED_FIELDS = ("chemistry", "math_stats")
 VAR = os.environ.get("GOLDVAR", "inc")
 FRAME_DIR = f"{_sar_legacy_thesis()}/v2_output/multidisc_gold_2026-08-10/data/{VAR}/union_frame_{FIELD}"
@@ -134,5 +149,5 @@
 
 signed_star_all = set()
-for f_ in ("chemistry", "math_stats"):
+for f_ in SIGNED_FIELDS:
     signed_star_all |= set(pd.read_csv(f"{_sar_legacy_thesis()}/v2_output/multidisc_gold_2026-08-10/data/events_{f_}_gold_2026-08-10.csv").author_id)
 excl_authors = {t[0] for t in con.execute(
```

## `30_build_panels23_gold_econ.py` vs `pipeline/frames/multidisc_gold_2026-08-10/code/30_build_panels23_gold.py`

pinned original sha256 `453b0f7da4d878b51d37ff5fe6a22003e7e16168a5319ef5549a750a90c381c9`

lines: original 375, clone 389; changed lines (excluding the header block): 6

```diff
--- pipeline/frames/multidisc_gold_2026-08-10/code/30_build_panels23_gold.py
+++ pipeline/frames/cal2026-10/econ_gold/30_build_panels23_gold_econ.py
@@ -1,3 +1,13 @@
 #!/usr/bin/env python3
+# cal2026-10 econ_gold clone of pipeline/frames/multidisc_gold_2026-08-10/code/30_build_panels23_gold.py
+# (verbatim pin 453b0f7da4d878b51d37ff5fe6a22003e7e16168a5319ef5549a750a90c381c9).
+# Repo-authored, 2026-09-22. The ONLY changes are field/path wiring so the same machine accepts
+# economics: `--field econ` is admitted, the person map for economics is the U2 11-school map
+# (the multidisc seeds map holds no economics author), and the signed-star set read for the
+# ex-star exclusion is the field's own signed table. Every computation line is byte-identical to
+# the pinned original; the exact hunks are listed in DIFF.md next to this file. Economics inputs
+# are staged by run_econ_gold.py at the gold layout's fnfix names inside a private shadow of the
+# legacy tree (the 2026-08-28 caliber staging mechanism, frames_stage.py), so no other path line
+# had to move. Assumptions of the economics run are written in run_econ_gold.py's docstring.
 """20_build_panels23_multidisc.py — 化学/数统 面板二（连星首连）+ 面板三（同事对互连）
 
@@ -62,9 +72,11 @@
 
 ap = argparse.ArgumentParser()
-ap.add_argument("--field", required=True, choices=["chemistry", "math_stats"])
+ap.add_argument("--field", required=True, choices=["chemistry", "math_stats", "econ"])
 ap.add_argument("--roster-clean", default="none", choices=["none", "r1r2r3", "r1v2"])
 ap.add_argument("--panel3", default="auto", choices=["auto", "full", "slim", "none"])
 args = ap.parse_args()
 FIELD, CLEAN = args.field, args.roster_clean
+if FIELD == "econ":   # cal2026-10 econ_gold wiring (see header): U2 person map (set after PMAP below)
+    _ECON_PMAP = str(_sar_derived_root() / "u2_person_map_11school_2026-07-16/person_map/data.parquet")
 SUF = "" if CLEAN == "none" else f"_{CLEAN}"     # 读对应清洗档的 relationships 表
 P3MODE = args.panel3 if args.panel3 != "auto" else ("slim" if FIELD == "chemistry" else "full")
@@ -77,4 +89,6 @@
 LEDGER_BASE = f"{_sar_legacy_thesis()}/v2_output/multidisc_gold_2026-08-10/data/events_{FIELD}_{_LSUF[1]}_2026-08-10.csv"
 PMAP = f"{ROOT}/v2_output/multidisc_v2_2026-08-04/data/person_map_multidisc_seeds.parquet"
+if FIELD == "econ":
+    PMAP = _ECON_PMAP   # cal2026-10 econ_gold wiring
 U1E = f"{SSD}/authorship_edges/**/*.parquet"
 SUP = f"{_sar_legacy_thesis()}/v2_output/multidisc_gold_2026-08-10/data/edges_supplement_{VAR}.jsonl" if os.path.exists(f"{_sar_legacy_thesis()}/v2_output/multidisc_gold_2026-08-10/data/edges_supplement_{VAR}.jsonl") else f"{_sar_legacy_thesis()}/v2_output/multidisc_gold_2026-08-10/data/edges_supplement_gold.jsonl"   # 变体自带补数边则用之（fnfix 2026-08-15）
```

