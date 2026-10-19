# Intermediate artifacts — producer, hash, and where each one is

The frames are in `data/frames/`, sha256-pinned in `data/MANIFEST.sha256`, and
`tests/test_pipeline_rebuild.py` proves 19 of the 21 rebuild exactly. This file is about everything
*between* the OpenAlex snapshot and those frames: the tables the builders read and write on the way.
Some ship, most do not, and a replication package that does not say which is which is not honest.

**Availability, and it is the only column that matters:**

| tag | meaning |
|---|---|
| **repo** | in this repository, sha256-pinned in `data/MANIFEST.sha256`. Nothing else needed. |
| **rebuildable** | a stage in `pipeline/run_all.sh` regenerates it and the rebuild is checked. Its INPUTS are the other rows of this table, which for most of them are **legacy** or **SSD** — so "rebuildable" is a property of the code, not a promise that you can run it. |
| **legacy** | on the author's read-only thesis tree only. Not in this package. |
| **SSD** | on the 4 TB data disk only (`ssd_root` in `config/paths.yaml`). Not in this package, and too big to be. |
| **gone** | does not exist anywhere. Every one of these has an entry in `pipeline/NOT_REPRODUCIBLE.md`. |

sha256 is given as its first 16 hex characters; the full value is in `data/MANIFEST.sha256` for
anything tagged **repo**, and is reproducible with `shasum -a 256` for the rest.

---

## 1. Snapshot and the U1/U2/U3 base — **SSD**

| artifact | producer | size | availability |
|---|---|---|---|
| OpenAlex snapshot 2026-06-26 (2,446 works shards) | `aws s3 sync s3://openalex/data/jsonl` | ~694 GiB | **SSD** — manifest sha256 prefix `da78e4b9b706d48d` |
| `derived/u1_edges_full_2026-07-05/` (works, authorship edges, refs, FWCI pop) | U1, on EC2 (`pipeline/aws/launch_u1_fetch.sh`) | 24 GB | **SSD** |
| `derived/u1_full_11school_2026-07-16/` | U1, on EC2 | 15 GB | **SSD**, no writer on disk → register #13 |
| `derived/u2_person_map_11school_2026-07-16/` | U2, on EC2 | 11 MB | **SSD**, no writer on disk → register #13 |
| `derived/u3_panel_11school_2026-07-16/` | U3 (`run_u3_rebuild_f123_2026-07-06.py`) | 610 MB | **SSD**, no writer on disk → register #13 |
| `derived/u0p5_roster/` (department rosters) | U0.5 | 189 MB | **SSD** |
| `derived/u5u6_final_2026-07-18_work/roster_v4_proj8/` | — | small | **SSD**, **gone** producer → register #11 |
| `…/adelaide_backfill_2007_2021_2026-07-20/…_MERGED_209plus_gapfill.parquet` | a hand-run Wayback-CDX crawl | small | **SSD**, **gone** producer → register #12 |

Nothing in this section is rebuildable from the package: the first row is 694 GiB of third-party
data and the rest is 17 hours on a rented machine. This is where the package's reproducibility
claim starts from a hash rather than from a rerun.

## 2. FWCI — the denominator

| artifact | producer | sha256 | size | availability |
|---|---|---|---|---|
| `fwci_baseline_pop_full.parquet` (543,037 cells) | `01_scan_full_snapshot.py` (`fwci scan`, 37 min) | `03ce4144a1ba4237` | 4,143,092 | **repo** `data/fwci/` |
| `scan_manifest.json` | same run | — | 789 | **repo** — 510,372,821 records, 2,446 shards, 0 bad lines |
| `scan_full_2026-08-09.log` | same run | — | 32,618 | **repo** — the cost gate's numbers are read from it |
| `fwci_expected_fullsnapshot_2026-08-09.parquet` (130,061 cells) | `01_build_expected_full.py` (`fwci build`, 0.9 s) | `1fc323a37dc78f22` | 633,092 | **repo** + **rebuildable**, byte-identical |
| `fwci_expected_oldpop_2026-08-09.parquet` (43,175 cells) | same | — | 416,619 | **repo** + **rebuildable** |
| `derived/u1_edges_full_2026-07-05/fwci_baseline_pop/` (pre-rebuild denominator) | U1 | — | 514 MB | **SSD** — the one input `fwci build` still needs off-package |
| `econ_units_2026-08-09.parquet` (160,437 rows) | `03_econ_anchor_test.py`, not ported | `3950cec3ed2c2b82` | 2,062,404 | **repo** `data/fwci/`, producer not run → register #6 |
| `g_step1_expected.json`, `gate_a_reconcile.json`, `gate_b_cell_recount.json`, `g_c_old_vs_new.json` | the scan and rebuild runs | — | small | **repo** `data/fwci/` |

`fwci build` reads the full-snapshot population through the legacy tree in the ported source; since
Task 8 the launcher serves it from the **repo** copy above and checks its hash against
`data/MANIFEST.sha256` first, so only the 514 MB **SSD** row is off-package.

## 3. Rosters — who counts as a colleague

| artifact | producer | sha256 | size | availability |
|---|---|---|---|---|
| `roster_clean_chemmath_verified.parquet` (1,550) | `merge_chemmath_verified_v2.py` (`rosters merge`) | `2e5c357bf51e421d` | 81,894 | **legacy** + **rebuildable**, byte-identical; the private COPY at `data/raw_verified/roster_chemmath_verified.parquet` was byte-identical. The **public** copy has person-identifying columns removed: sha256 `<<SHA256: data/raw_verified/roster_chemmath_verified.parquet>>` |
| `roster_clean_11school_verified.parquet` (920) | `merge_roster.py` (`rosters econ-merge`, RECOVERED) | `cbcf11ef3427b262` | 43,809 | **legacy** + **rebuildable**, byte-identical to the private original; frozen in **repo** `data/raw_verified/roster_econ_verified.parquet` with person-identifying columns removed, sha256 `<<SHA256: data/raw_verified/roster_econ_verified.parquet>>` |
| `econ_roster_evidence_audit.csv` (994) | `build_audit.py` (`rosters econ-audit`, RECOVERED) | — | — | **legacy** + **rebuildable** |
| `data/inc/`, `data/incamb/roster_gold_*.parquet` | `00b_prep_roster_variants.py` (`rosters variants`) | — | 4.7–8.3 KB each | **legacy** + **rebuildable** |
| `data/incfel/roster_gold_*.parquet` | `00b2_prep_incfel_variant.py` (`rosters incfel`, RECOVERED) | — | small | **repo** `data/raw_verified/incfel/` + **rebuildable** |
| `data/final/roster_gold_{chemistry,math_stats}.parquet` | `00c_prep_final_population.py` (`rosters final`) | `778608dd3850169f`, `5089ee89efaae1ef` | 7,528 / 7,905 | **repo** `data/raw_verified/` + **rebuildable** |
| `data/fnfix/roster_gold_*.parquet` | `70_prep_fnfix_inputs.py` — a `shutil.copyfile` of `data/final` | identical to the row above | | **repo**; the copy is asserted, not re-made |
| `rejected_persons.csv` 13th column (`reject_cause`) | `add_reject_cause.py` (`rosters econ-merge`, RECOVERED) | `0c5dd47cd8e3bfe1` | 64,148 | **legacy** + **rebuildable**, byte-identical → register #3 |

## 4. Stars and events

| artifact | producer | sha256 | size | availability |
|---|---|---|---|---|
| `new_stars_COMBINED_p10_2026-07-22.csv` (65 rows) | a deleted temporary directory | — | — | **gone** → register #7 |
| `fnfix_candidates_restake.csv` (67) | four chained heredocs (`stars candidates`, RECOVERED) | `a1c6b34c7528108e` | 9,170 | **legacy** + **rebuildable**, byte-identical |
| `poach_fn_recheck_econ_U4flagged9_2026-08-16.csv` (9) | rung 4 of the same chain | — | — | **legacy** + **rebuildable**, byte-identical |
| `fnfix_restake_2026-08-15.csv` (67) | `72_restake_fnfix_stars.py` (`stars restake`, needs SSD) | `f11031eac506cb9d` | 7,527 | **legacy** + **rebuildable**, byte-identical |
| `poach_fn_suspects_{econ,chemistry,math_stats}.csv` | `60_poach_gate_false_negatives.py` (`stars suspects`, needs SSD) | `d7fb7719f9eb580f` (econ) | 20,025 | **legacy** + **rebuildable**; econ and math byte-identical, chemistry content-equal only (legacy `string_agg` is unordered) |
| `poach_fn_prescreen_v2_2026-08-15.csv` | `61_poach_fn_prescreen_v2.py` — **live OpenAlex API** | `5f2c11919e123050` | 73,576 | **legacy**; never re-run (a fresh call returns different data) |
| `fnfix_new_events.csv` (24) + `_wide_extra.csv` (1) | `00_select_new_events_chemmath.py` (RECOVERED) | `1959c6a193bb7fb1`, `f7e651d71743a6d4` | 3,900 / 244 | **legacy** + **rebuildable**, byte-identical |
| `new_events_econ.csv` (38) | `00_select_new_events_econ.py` (RECOVERED) | `36d7645197b3676d` | 5,713 | **legacy** + **rebuildable**; frozen in **repo** as `data/raw_verified/events_econ_new38.csv` (public copy without `name` and `evidence_url`, sha256 `<<SHA256: data/raw_verified/events_econ_new38.csv>>`) |
| `u4_aug/events/data.parquet`, `u4_aug/star_set/star_set.parquet` (38 / 277) | `00_make_u4_aug.py` (`stars u4aug`) | `a935af717c94fb3b`, `b8a73d89e1416353` | 4,334 / 16,101 | **legacy** + **rebuildable**, content-equal |
| the 192-person verification rounds, the 385 + 3,874 per-paper identity calls | humans | — | — | **legacy** evidence only → register #2, #8 |

## 5. Frames — the inputs the builders read

| artifact | producer | sha256 | size | availability |
|---|---|---|---|---|
| **`pairs_unified.csv`** | `10_panels23_econ920.py` (`frames p2-econ`, needs SSD) | **`d107b5843bc49dcf`** | 662,663,276 | **legacy** + **rebuildable, BYTE-IDENTICAL** — the one large intermediate this package can regenerate and prove |
| `becoming_unified.csv` | same stage | `d131dca4dae56ac5` | 11,080,719 | **legacy** + **rebuildable**; frozen in **repo** as `data/frames/p2_becoming_econ.csv` |
| `panels23_chemistry_gold/pairs_none.parquet` | `30_build_panels23_gold.py` (`frames p2-gold`, needs SSD) | `ae10bfb2ec945ae6` | 1,180,495 | **legacy** + **rebuildable** |
| `panels23_math_stats_gold/pairs_none.parquet` | same | `16c9198a7b3c786d` | 325,860 | **legacy** + **rebuildable** |
| `analysis_frame_econ920_unified_fullsnap_2026-08-13.csv` | `04_rebuild_y.py` (`frames p1-econ`, needs SSD) | `fd221b387e5cec1e` | 19,127,653 | **legacy** + **rebuildable**, byte-identical; frozen in **repo** as `data/frames/p1_frame_econ.csv` |
| `lb_counts.csv`, `lb_tau_profile.csv`, `lb_manifest.json` | `50_leftbehind_build.py` + `60_lb_tau.py` (`frames afar`) | `e2983c46b4706f74` (manifest) | 3,712 | **legacy** + **rebuildable**; the first two are frozen in **repo** as `data/frames/p3_afar_{counts,tau_profile}.csv` |
| `pairs_slim_cap_{econ,chemistry,math_stats}_ALL.parquet` | `90_capped_build.py` — **not ported** | `45860d7b3402b297`, `20ad3e872de86618`, `8e70862e6760f11c` | 13.4 / 6.6 / 1.9 MB | **legacy**; 3 of the speed bracket's 9 cells → register #9 |
| `pairs_slim_ev_*.parquet`, `pairs_slim_*.parquet` (the six P3 slims) | `pipeline/frames/make_slim.py` | see `data/MANIFEST.sha256` | | **repo** `data/frames/` + **rebuildable**, content-equal |

## 6. Estimates

| artifact | producer | availability |
|---|---|---|
| 19 local estimate JSONs | `analysis/run_all.sh` | **repo** `data/estimates/` + **rebuildable**, ALL_EQUAL |
| `P3_econ_fnfix`, `P3_fnfix_chemistry`, `P3evcl_econ`, `P3evcl_chemistry` | r6i.16xlarge, us-east-1 | **repo** `data/estimates/`; custody-checked, not re-run → register #16 |

---

## What this table is for

Two questions, and it should answer both without reading any code.

**"Can I rebuild this?"** — read the availability column, and read it carefully:
**rebuildable** means a stage in this package regenerates it *from inputs listed elsewhere in this
table*, which for most rows are tagged **legacy** or **SSD**. A row tagged **legacy** +
**rebuildable** is one where the legacy tree is an INPUT, not an output — the stage reads from it and
writes a copy this package can compare. So `bash pipeline/run_all.sh --with-ssd` exercises those rows
**only on a machine that has the legacy trees and the data disk**; on a machine with neither, **15 of 15**
default stages fail (measured with both roots repointed at empty directories; the 14-of-15 figure is
the legacy-only arm — `fwci/build` survives that one and dies when the disk goes too). **gone** means the artifact does not exist and
`pipeline/NOT_REPRODUCIBLE.md` says what to check instead.

**"Where does the chain actually break?"** — twice, and it is worth being exact. Section 1 is the
hard break: 694 GiB of OpenAlex and 17 hours of EC2 that no package can ship. Sections 2–5 are a
softer one: the code is here and the rebuilds are verified, but their inputs are the author's
read-only trees, so the claim for those rows is *"this code produced these bytes, checked"* and not
*"you can produce them yourself"*. The one row where the stronger claim holds all the way down is
`pairs_unified.csv` — 663 MB, regenerated **byte for byte** — and even that reads the SSD tables of
section 1.
