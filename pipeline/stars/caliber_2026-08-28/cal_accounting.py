#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
[post-freeze note] The frozen-side anchors below name the PRE-freeze canon
(e.g. p1_frame_econ_new38). After the freeze promoted new37 into data/frames, this accounting
phase re-runs faithfully only against `git checkout pre-cal-freeze` artifacts.
caliber_2026-08-28/cal_accounting.py — the row-level accounting for the T3 frames rebuild.

Every produced frame is compared against its frozen counterpart and every row in/out/changed is
attributed to a NAMED cause; a row no cause claims is UNACCOUNTED and stops the discipline. T2's
pinned expectations are evaluated verbatim through the caller's `pin_eval` — a deviation is
recorded as a DEVIATION, never absorbed into a widened expectation.

The named causes (each verified, not asserted):
  A5044432173_event econ rows of event A5044432173:2006 (D-A removal; T1)
  five_member       chem/math rows whose person/member is one of the five new stars — their
                    NETWORK-channel membership leaves via stars_excluded (prodlib pool), their
                    dose/works enrich via the T2 supplement, so any row keyed on them may move
  new_event         rows of the five new events (no frozen counterpart; internal consistency
                    checks apply instead)
  h1_fwci_ulp       fwci_frac / fwci_frac_ex_star last-bit noise, <= 8 ULP — the M3-documented
                    H1 characterisation of the gold y-rebuild (unordered parallel accumulation)
  ex_star_ripple    ex_star-family columns moved for a person who shares a work with one of the
                    five (the five entered the outcome-exclusion star set) — membership in the
                    five's coauthor set is checked per row
  coauthor_ripple   first-connection (y) moved for persons appearing in the five's supplement
                    works (the works_of pool gained those works) — membership checked per row
"""
from __future__ import annotations

import csv
import json
import pathlib
import sys

import duckdb

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import caliber                                                        # noqa: E402
import frames_stage as fs                                             # noqa: E402

A5044432173_ID, A5044432173_EVENT = fs.A5044432173_ID, fs.A5044432173_EVENT
FIVE, NEW_EVENTS = fs.FIVE, fs.NEW_EVENTS

EXSTAR_COLS = ("fwci_frac_ex_star", "pub_count_ex_star", "fwci_mean_ex_star")
FWCI_COLS = ("fwci_frac", "fwci_frac_ex_star", "fwci_mean", "fwci_mean_ex_star")
#: every column the five's SUPPLEMENT can legitimately move for one of their coauthors: the
#: works pool gains the five's full-API works, so outcomes, dose vectors and the robust
#: first-pub year (hence age_gap) may all recompute. Verified per row by coauthor membership.
ENRICH_COLS = frozenset({"dose_topic", "age_gap", "fwci_frac", "pub_count",
                         "fwci_frac_ex_star", "pub_count_ex_star",
                         "fwci_mean", "fwci_mean_ex_star"})


#: legacy intermediates' sha256 prefixes, from pipeline/MANIFEST_intermediates.md — the frozen-side
#: anchor for comparisons whose frozen operand is not in data/frames (M3's anchor-the-subject rule)
INTERMEDIATE_PINS = {
    "econ_fnfix_2026-08-15/data/pairs_unified.csv": "d107b5843bc49dcf",
    "multidisc_gold_2026-08-10/data/fnfix/panels23_math_stats_gold/pairs_none.parquet":
        "16c9198a7b3c786d",
}

#: the ONE frozen operand the byte pin cannot bless: the whole `panels23_chemistry_gold/`
#: directory was rewritten on 2026-08-26 17:20 by the M3-registered legacy write incident
#: (the author's build log of 2026-08-26, private; the author has not asked for a restore), so
#: the on-disk copy is the SAME builder's rerun, not the original bytes
#: (`pipeline/MANIFEST_intermediates.md` still pins the original, ae10bfb2…, 1,180,495 B; the
#: incident copy is 1,240,640 B — H1's licensed parquet nondeterminism). This anchor was CAUGHT by
#: the byte pin, not assumed: the fallback is a DERIVED-CONTENT anchor, asserted in
#: `anchor_chem_pairs_by_content` — the incident copy's slim projection must content-equal the
#: manifest-pinned `data/frames/p3_slim_ev_chemistry.parquet`, which was built from the ORIGINAL.
#: Scope stated honestly: that proves the (i,j,event,year,y_any,post) multiset; y_raw and tau are
#: outside the projection and carry no estimation cell.
INCIDENT_REL = "multidisc_gold_2026-08-10/data/fnfix/panels23_chemistry_gold/pairs_none.parquet"
INCIDENT_SHA16 = "3e63121882b9492c"          # the incident copy, pinned so even IT cannot drift


def anchor_chem_pairs_by_content(REPO: pathlib.Path, v2: pathlib.Path,
                                 scratch: pathlib.Path) -> dict:
    got = fs.sha(v2 / INCIDENT_REL)
    assert got.startswith(INCIDENT_SHA16), (
        f"{INCIDENT_REL}: sha256 {got[:16]} is neither the original (ae10bfb2…) nor the "
        f"registered 2026-08-26 incident copy ({INCIDENT_SHA16}) — a THIRD state; stop and look")
    sys.path.insert(0, str(REPO / "pipeline" / "frames"))
    import make_slim as ms                                            # noqa: PLC0415
    scratch.mkdir(parents=True, exist_ok=True)
    out = scratch / "anchor_slim_ev_chemistry.parquet"
    ms.make_slim("chemistry", v2 / INCIDENT_REL, out)
    sys.path.insert(0, str(REPO / "tools"))
    import content_equal as ce                                        # noqa: PLC0415
    r = ce.content_equal(out, REPO / "data" / "frames" / "p3_slim_ev_chemistry.parquet")
    assert r.equal, (
        f"the incident copy of {INCIDENT_REL} is NOT content-equal (slim projection) to the "
        f"manifest-pinned p3_slim_ev_chemistry.parquet built from the original:\n{r.detail}")
    return {"incident_copy_sha16": got[:16],
            "anchor": "slim projection content-equal to data/frames/p3_slim_ev_chemistry.parquet",
            "scope": "(pair,event,year,y_any,post) multiset; y_raw/tau outside the projection"}


def anchor_frames_manifest(repo: pathlib.Path, frozen: pathlib.Path) -> None:
    """The frozen operand of a comparison must BE the manifest-pinned shipped artifact."""
    manifest = (repo / "data" / "MANIFEST.sha256").read_text(encoding="utf-8")
    line = f"{fs.sha(frozen)}  data/frames/{frozen.name}"
    assert line in manifest, (
        f"{frozen.name} does not match its line in data/MANIFEST.sha256 — the frozen operand of "
        f"this accounting is not the shipped artifact")


def anchor_intermediate(v2: pathlib.Path, rel: str) -> None:
    got = fs.sha(v2 / rel)
    assert got.startswith(INTERMEDIATE_PINS[rel]), (
        f"{rel}: sha256 {got[:16]} does not match pipeline/MANIFEST_intermediates.md's "
        f"{INTERMEDIATE_PINS[rel]} — the frozen operand moved")


def _count_lines(path: pathlib.Path, pred) -> int:
    """Count data rows matching `pred`, reading with the \\r-stripping recipe the gold consumers
    use (the union frame's network rows carry the 07-24 CRLF legacy mid-line)."""
    _, rows = fs.read_frame_rows(path)
    return sum(1 for cells in rows if pred(cells))


def five_supplement_authors() -> tuple[set[str], set[str]]:
    """(coauthors-of-five, persons-in-five-supplement-works) from the T2 supplement — the
    verification sets for the ex_star and first-connection ripples."""
    coa = set()
    for ln in open(fs.CAL_DIR / "edges_supplement_cal2026-08-28.jsonl", encoding="utf-8"):
        d = json.loads(ln)
        if d.get("seed_author") in fs.FIVE_ALL:
            coa.update(d.get("authors") or [])
            coa.add(d["seed_author"])
    return coa, set(coa)


def classify(acc: dict, *, five: tuple[str, ...], new_events: tuple[str, ...],
             pid_ix: int, event_ix: int, coauthors: set[str],
             allow_h1: bool = True, name: str = "") -> dict:
    """Attribute a keyed accounting's removed/added/modified keys to the named causes."""
    out = {"name": name, "rows_frozen": acc["rows_frozen"], "rows_new": acc["rows_new"],
           "identical": acc["identical"]}
    rem_five, rem_other = 0, []
    for k in acc["removed"]:
        if k[pid_ix] in five:
            rem_five += 1
        else:
            rem_other.append(k)
    add_new, add_five, add_other = 0, 0, []
    for k in acc["added"]:
        if k[event_ix] in new_events:
            add_new += 1
        elif k[pid_ix] in five:
            add_five += 1
        else:
            add_other.append(k)
    mod = {"five_member": 0, "h1_fwci_ulp": 0, "ex_star_ripple": 0,
           "supplement_enrichment_ripple": 0, "coauthor_ripple": 0}
    mod_other = []
    for e in acc["modified"]:
        k, cols = e["key"], set(e["cols"])
        pid = k[pid_ix].removeprefix("P_")
        if k[pid_ix] in five or pid in five:
            mod["five_member"] += 1
        elif allow_h1 and cols <= {"fwci_frac", "fwci_frac_ex_star"} and e.get("ulps") and \
                all(u is not None and u <= 8 for u in e["ulps"].values()):
            mod["h1_fwci_ulp"] += 1
        elif cols <= set(EXSTAR_COLS) | {"fwci_frac", "fwci_frac_ex_star"} and pid in coauthors:
            mod["ex_star_ripple"] += 1
        elif cols <= ENRICH_COLS and pid in coauthors:
            mod["supplement_enrichment_ripple"] += 1
        elif cols <= {"y", "tau", "post", "y_any", "y_raw"} and pid in coauthors:
            mod["coauthor_ripple"] += 1
        else:
            mod_other.append(e)
    out["removed"] = {"five_member": rem_five, "n_unaccounted": len(rem_other),
                      "unaccounted_sample": rem_other[:12]}
    out["added"] = {"new_event": add_new, "five_dept": add_five,
                    "n_unaccounted": len(add_other), "unaccounted_sample": add_other[:12]}
    out["modified"] = dict(mod, n_unaccounted=len(mod_other), unaccounted_sample=mod_other[:6])
    out["closed"] = not (rem_other or add_other or mod_other)
    return out


# ---------------------------------------------------------------------------------------------

def run_accounting(REPO: pathlib.Path, v2: pathlib.Path, root: pathlib.Path,
                   shadow_root: pathlib.Path, stages: dict, pin_eval, stop, log) -> dict:
    A: dict = {}
    frames = REPO / "data" / "frames"
    rd = {k: v["run_dir"] for k, v in stages.items() if "run_dir" in v}
    coauthors, _ = five_supplement_authors()
    A["five_coauthor_set_size"] = len(coauthors)

    # --- frozen-side anchors, BEFORE any comparison (the M3 anchor-the-subject rule) ----------
    for name in ("p1_events_ledger_econ.csv", "p1_frame_econ.csv", "p1_frame_econ_old79.csv",
                 "p1_frame_econ_new38.csv", "p2_becoming_econ.csv", "p1_frame_chemistry.csv",
                 "p1_frame_math_stats.csv", "p2_becoming_chemistry.csv",
                 "p2_becoming_math_stats.csv", "p3_afar_counts.csv"):
        anchor_frames_manifest(REPO, frames / name)
    for rel in INTERMEDIATE_PINS:
        anchor_intermediate(v2, rel)
    A["incident_anchor_chem_pairs"] = anchor_chem_pairs_by_content(REPO, v2,
                                                                  root / "anchor_slim_chem")
    A["frozen_side_anchors"] = ("data/MANIFEST.sha256 x10 + MANIFEST_intermediates x2 verified; "
                                "chemistry pairs_none = the registered 2026-08-26 incident copy, "
                                "anchored by derived content (see incident_anchor_chem_pairs)")

    # ================================ ECON (must close EXACTLY) ================================
    log("accounting: econ")
    E: dict = {}

    w = fs.strict_removal_walk(frames / "p1_events_ledger_econ.csv",
                               rd["ledger"] / "data/event_ledger_fnfix.csv",
                               lambda c: c[1] == A5044432173_ID)
    E["ledger"] = w
    if not (w["closed"] and w["rows_removed"] == 1):
        stop(f"econ ledger accounting did not close: {w}")

    cal_p1 = rd["p1_econ"] / "data/analysis_frame_econ920_unified_fullsnap_2026-08-13.csv"
    w = fs.strict_removal_walk(frames / "p1_frame_econ.csv", cal_p1,
                               lambda c: c[3] == A5044432173_EVENT)
    E["p1_frame"] = w
    pin_eval("econ.p1_star_side_removed", 1012, w.get("rows_removed"))
    if not w["closed"]:
        stop(f"econ P1 accounting did not close: {w}")
    kept_colleague = _count_lines(cal_p1, lambda c: c[0] == f"P_{A5044432173_ID}")
    pin_eval("econ.p1_colleague_side_persists", 88, kept_colleague)
    E["p1_A5044432173_colleague_rows_kept"] = kept_colleague

    old79 = rd["split"] / "data/analysis_frame_econ_fnfix_old79.csv"
    E["old79_byte_equal_to_frozen"] = fs.sha(old79) == fs.sha(frames / "p1_frame_econ_old79.csv")
    if not E["old79_byte_equal_to_frozen"]:
        stop("econ old79 split is not byte-identical to the frozen p1_frame_econ_old79.csv — "
             "A5044432173 is a new38 event, so the old79 side must not move at all")
    w = fs.strict_removal_walk(frames / "p1_frame_econ_new38.csv",
                               rd["split"] / "data/analysis_frame_econ_fnfix_new38.csv",
                               lambda c: c[3] == A5044432173_EVENT)
    E["new37_vs_frozen_new38"] = w
    if not (w["closed"] and w["rows_removed"] == 1012):
        stop(f"econ new37 accounting did not close: {w}")

    cal_p2 = rd["p2_econ"] / "data/becoming_unified.csv"
    w = fs.strict_removal_walk(frames / "p2_becoming_econ.csv", cal_p2,
                               lambda c: c[2] == A5044432173_EVENT)
    E["p2_becoming"] = w
    pin_eval("econ.p2_star_side_removed", 1547, w.get("rows_removed"))
    if not w["closed"]:
        stop(f"econ P2 accounting did not close: {w}")
    kept = _count_lines(cal_p2, lambda c: c[0] == A5044432173_ID)
    pin_eval("econ.p2_colleague_side_persists", 136, kept)

    cal_pairs = rd["p2_econ"] / "data/pairs_unified.csv"
    legacy_pairs = v2 / "econ_fnfix_2026-08-15/data/pairs_unified.csv"
    w = fs.strict_removal_walk(legacy_pairs, cal_pairs, lambda c: c[2] == A5044432173_EVENT)
    E["pairs_unified"] = w
    pin_eval("econ.pairs_event_side_removed", 70028, w.get("rows_removed"))
    if not w["closed"]:
        stop(f"econ pairs accounting did not close: {w}")
    kept = _count_lines(cal_pairs, lambda c: A5044432173_ID in (c[0], c[1]))
    pin_eval("econ.pairs_member_side_persists", 17545, kept)
    A["econ"] = E

    # ============================ CHEM / MATH (channel-resolved) ===============================
    con = duckdb.connect()
    for field in ("chemistry", "math_stats"):
        log(f"accounting: {field}")
        F: dict = {}
        five, new_ev = FIVE[field], NEW_EVENTS[field]

        # ---- prodlib network frame vs frozen runs/fnfix ---------------------------------------
        frozen_pl = v2 / GOLD_REL / "runs/fnfix" / field / "data" / \
            "analysis_frame_p01_52ev_topicdose_2026-07-21.csv"
        cal_pl = root / f"cal_prodlib_{field}" / "runs" / field / "data" / \
            "analysis_frame_p01_52ev_topicdose_2026-07-21.csv"
        acc = fs.keyed_csv_accounting(frozen_pl, cal_pl,
                                      ("incumbent_person_id", "event_id", "year"),
                                      float_cols=FWCI_COLS + ("dose_topic",))
        F["prodlib_frame"] = classify(acc, five=five, new_events=new_ev, pid_ix=0, event_ix=1,
                                      coauthors=coauthors, allow_h1=False,
                                      name=f"prodlib network frame {field}")
        if not F["prodlib_frame"]["closed"]:
            stop(f"{field} prodlib-frame accounting did not close: "
                 f"{json.dumps(F['prodlib_frame'], default=str)[:1200]}")

        # ---- union frame vs frozen ------------------------------------------------------------
        frozen_u = v2 / GOLD_REL / "data/fnfix" / f"union_frame_{field}" / \
            f"analysis_frame_{field}_2026-08-10.csv"
        cal_u = rd[f"union_{field}"] / f"data/fnfix/union_frame_{field}" / \
            f"analysis_frame_{field}_2026-08-10.csv"
        acc = fs.keyed_csv_accounting(frozen_u, cal_u,
                                      ("incumbent_person_id", "event_id", "year"),
                                      float_cols=FWCI_COLS + ("dose_topic",))
        F["union_frame"] = classify(acc, five=five, new_events=new_ev, pid_ix=0, event_ix=1,
                                    coauthors=coauthors, name=f"union frame {field}")
        if not F["union_frame"]["closed"]:
            stop(f"{field} union-frame accounting did not close: "
                 f"{json.dumps(F['union_frame'], default=str)[:1200]}")

        # ---- relationships: the rel-level pin -------------------------------------------------
        frozen_rel = v2 / GOLD_REL / "data/fnfix" / f"union_frame_{field}" / "relationships.csv"
        cal_rel = rd[f"union_{field}"] / f"data/fnfix/union_frame_{field}" / "relationships.csv"
        rel_before = {aid: _count_lines(frozen_rel, lambda c, a=aid: c[0] == a) for aid in five}
        rel_after = {aid: _count_lines(cal_rel, lambda c, a=aid: c[0] == a) for aid in five}
        F["relationships_five"] = {a: {"frozen": rel_before[a], "cal": rel_after[a]}
                                   for a in five}

        # ---- P1 frame vs frozen data/frames ---------------------------------------------------
        cal_p1g = rd[f"p1_{field}"] / f"data/fnfix/analysis_frame_{field}_new_gold_2026-08-10.csv"
        acc = fs.keyed_csv_accounting(frames / f"p1_frame_{field}.csv", cal_p1g,
                                      ("incumbent_person_id", "event_id", "year"),
                                      float_cols=FWCI_COLS)
        F["p1_frame"] = classify(acc, five=five, new_events=new_ev, pid_ix=0, event_ix=1,
                                 coauthors=coauthors, name=f"p1_frame_{field}")
        if not F["p1_frame"]["closed"]:
            stop(f"{field} P1 accounting did not close: "
                 f"{json.dumps(F['p1_frame'], default=str)[:1200]}")

        # ---- P2 becoming vs frozen ------------------------------------------------------------
        cal_p2g = rd[f"p2_{field}"] / f"data/fnfix/panels23_{field}_gold/becoming_none.csv"
        acc = fs.keyed_csv_accounting(frames / f"p2_becoming_{field}.csv", cal_p2g,
                                      ("pid", "event_id", "year"))
        F["p2_becoming"] = classify(acc, five=five, new_events=new_ev, pid_ix=0, event_ix=1,
                                    coauthors=coauthors, allow_h1=False,
                                    name=f"p2_becoming_{field}")
        if not F["p2_becoming"]["closed"]:
            stop(f"{field} P2 accounting did not close: "
                 f"{json.dumps(F['p2_becoming'], default=str)[:1200]}")

        # ---- pair layer vs the frozen legacy pairs_none ---------------------------------------
        frozen_pn = v2 / GOLD_REL / "data/fnfix" / f"panels23_{field}_gold" / "pairs_none.parquet"
        cal_pn = rd[f"p2_{field}"] / f"data/fnfix/panels23_{field}_gold/pairs_none.parquet"
        F["pairs"] = pairs_accounting(con, frozen_pn, cal_pn, five, new_ev, coauthors)
        if not F["pairs"]["closed"]:
            stop(f"{field} pair-layer accounting did not close: "
                 f"{json.dumps(F['pairs'], default=str)[:1200]}")

        # ---- T2 pins, evaluated verbatim ------------------------------------------------------
        exp = {(r["author_id"], r["layer"]): r for r in fs.t2_expectations()}
        for aid in five:
            nm = fs.FIVE_NAMES[aid].split()[-1]
            pin_eval(f"{field}.{nm}.rel_removed", int(exp[(aid, "rel_fnfix")]["rows"]),
                     rel_before[aid] - rel_after[aid],
                     note=f"frozen {rel_before[aid]} -> cal {rel_after[aid]} (dept-channel rows "
                          f"persist under the machinery's stars_excluded rule)")
            p1_before = _count_lines(frames / f"p1_frame_{field}.csv",
                                     lambda c, a=aid: c[0] == a)
            p1_after = _count_lines(cal_p1g, lambda c, a=aid: c[0] == a)
            pin_eval(f"{field}.{nm}.p1_rows_removed", int(exp[(aid, "p1_frame")]["rows"]),
                     p1_before - p1_after,
                     note=f"frozen {p1_before} -> cal {p1_after}")
            p2_before = _count_lines(frames / f"p2_becoming_{field}.csv",
                                     lambda c, a=aid: c[0] == a)
            p2_after = _count_lines(cal_p2g, lambda c, a=aid: c[0] == a)
            pin_eval(f"{field}.{nm}.p2_rows_removed", int(exp[(aid, "p2_becoming")]["rows"]),
                     p2_before - p2_after,
                     note=f"frozen {p2_before} -> cal {p2_after}")
            pr = con.execute(f"""SELECT
                (SELECT count(*) FROM read_parquet('{frozen_pn}') WHERE i_id='{aid}' OR j_id='{aid}'),
                (SELECT count(*) FROM read_parquet('{cal_pn}') WHERE i_id='{aid}' OR j_id='{aid}')
                """).fetchone()
            pin_eval(f"{field}.{nm}.pair_rows_removed", int(exp[(aid, "pairs_legacy")]["rows"]),
                     pr[0] - pr[1], note=f"frozen {pr[0]} -> cal {pr[1]}")

        # ---- slims: internal consistency against the cal pair table ---------------------------
        F["slim"] = slim_consistency(con, stages[f"slim_{field}"], cal_pn, field, stop)
        # ---- new events: internal consistency -------------------------------------------------
        F["new_events"] = new_event_consistency(con, field, cal_u, cal_p2g, cal_pn,
                                                shadow_root, stop)
        A[field] = F

    # econ slims against the cal pairs_unified
    A["econ"]["slim"] = slim_consistency(
        con, stages["slim_econ"], rd["p2_econ"] / "data/pairs_unified.csv", "econ", stop)

    # ================================ A_far counts =============================================
    log("accounting: A_far counts")
    A["afar_counts"] = afar_counts_accounting(frames / "p3_afar_counts.csv",
                                              rd["afar"] / "data/lb_counts.csv", pin_eval)
    return A


GOLD_REL = "multidisc_gold_2026-08-10"


def pairs_accounting(con, frozen_pn: pathlib.Path, cal_pn: pathlib.Path,
                     five: tuple[str, ...], new_ev: tuple[str, ...],
                     coauthors: set[str]) -> dict:
    """Pair-level accounting on the (i_id, j_id, event_id) universe plus a row-level check on
    surviving pairs."""
    fv = ",".join(f"'{a}'" for a in five)
    ne = ",".join(f"'{e}'" for e in new_ev)
    co = ",".join(f"'{a}'" for a in sorted(coauthors)) or "''"
    q = f"""
    WITH fp AS (SELECT DISTINCT i_id, j_id, event_id FROM read_parquet('{frozen_pn}')),
         np AS (SELECT DISTINCT i_id, j_id, event_id FROM read_parquet('{cal_pn}')),
         rem AS (SELECT * FROM fp EXCEPT SELECT * FROM np),
         add_ AS (SELECT * FROM np EXCEPT SELECT * FROM fp)
    SELECT
      (SELECT count(*) FROM fp), (SELECT count(*) FROM np),
      (SELECT count(*) FROM rem),
      (SELECT count(*) FROM rem WHERE i_id IN ({fv}) OR j_id IN ({fv})),
      (SELECT count(*) FROM add_),
      (SELECT count(*) FROM add_ WHERE event_id IN ({ne})),
      (SELECT count(*) FROM add_ WHERE event_id NOT IN ({ne})
              AND (i_id IN ({fv}) OR j_id IN ({fv})))
    """
    fp, np_, rem, rem_five, add, add_new, add_five = con.execute(q).fetchone()
    out = {"pairs_frozen": fp, "pairs_cal": np_,
           "pairs_removed": rem, "pairs_removed_five_member": rem_five,
           "pairs_added": add, "pairs_added_new_event": add_new,
           "pairs_added_five_dept": add_five,
           "pairs_removed_unaccounted": rem - rem_five,
           "pairs_added_unaccounted": add - add_new - add_five}
    # row-level: surviving pairs whose year-rows changed (first-connection ripples)
    q2 = f"""
    WITH fp AS (SELECT * FROM read_parquet('{frozen_pn}')),
         np AS (SELECT * FROM read_parquet('{cal_pn}')),
         common AS (SELECT i_id, j_id, event_id FROM
                    (SELECT DISTINCT i_id, j_id, event_id FROM fp)
                    INTERSECT (SELECT DISTINCT i_id, j_id, event_id FROM np)),
         d1 AS (SELECT f.* FROM fp f JOIN common USING (i_id, j_id, event_id)
                EXCEPT ALL SELECT n.* FROM np n JOIN common USING (i_id, j_id, event_id)),
         chg AS (SELECT DISTINCT i_id, j_id, event_id FROM d1)
    SELECT (SELECT count(*) FROM chg),
           (SELECT count(*) FROM chg WHERE i_id IN ({fv}) OR j_id IN ({fv})),
           (SELECT count(*) FROM chg WHERE i_id NOT IN ({fv}) AND j_id NOT IN ({fv})
                   AND i_id IN ({co}) AND j_id IN ({co}))
    """
    chg, chg_five, chg_coa = con.execute(q2).fetchone()
    out["pairs_rows_changed"] = chg
    out["pairs_rows_changed_five_member"] = chg_five
    out["pairs_rows_changed_coauthor_ripple"] = chg_coa
    out["pairs_rows_changed_unaccounted"] = chg - chg_five - chg_coa
    out["closed"] = (out["pairs_removed_unaccounted"] == 0
                     and out["pairs_added_unaccounted"] == 0
                     and out["pairs_rows_changed_unaccounted"] == 0)
    return out


def slim_consistency(con, slim: dict, pairs: pathlib.Path, field: str, stop) -> dict:
    """The slim has no frozen counterpart under the caliber (its grp ids re-rank); the acceptance
    is internal: a faithful 1:1 projection of the CAL pair table — stated explicitly."""
    rd_ = "read_csv_auto" if str(pairs).endswith(".csv") else "read_parquet"
    n_rows, n_pairs, n_ev, s_y = con.execute(
        f"""SELECT count(*), count(DISTINCT i_id || '|' || j_id || '|' || event_id),
                   count(DISTINCT event_id), sum(y_any) FROM {rd_}('{pairs}')""").fetchone()
    ev = slim["stats"]
    out = {"pairs_table": {"rows": n_rows, "pairs": n_pairs, "events": n_ev, "ties": int(s_y)},
           "slim": {k: ev[k] for k in ("rows", "pairs", "ties", "events")},
           "note": "no frozen counterpart (grp/ev re-rank under the caliber); acceptance = "
                   "faithful projection of the CAL pair table"}
    out["consistent"] = (ev["rows"] == n_rows and ev["pairs"] == n_pairs
                         and ev["events"] == n_ev and ev["ties"] == int(s_y))
    if not out["consistent"]:
        stop(f"{field} slim is not a faithful projection of the cal pair table: {out}")
    return out


def new_event_consistency(con, field: str, cal_union: pathlib.Path, cal_p2: pathlib.Path,
                          cal_pairs: pathlib.Path, shadow_root: pathlib.Path, stop) -> dict:
    """The new events have NO frozen counterpart — the acceptance is internal consistency,
    stated explicitly: population > 0, 11 rows per person-event in P1, 17 in P2, dose present,
    exposure inside roster spells, no duplicate pair-years, arrival inside the uniform window."""
    out: dict = {}
    roster = shadow_root / "v2_output" / GOLD_REL / "data/fnfix" / f"roster_gold_{field}.parquet"
    events = {r["author_id"]: r for r in csv.DictReader(
        open(fs.CAL_DIR / f"events_{field}_cal.csv", encoding="utf-8"))}
    u_hdr, u_rows = fs.read_frame_rows(cal_union)
    u_ix = {c: i for i, c in enumerate(u_hdr)}
    p2_hdr, p2_rows = fs.read_frame_rows(cal_p2)
    p2_ix = {c: i for i, c in enumerate(p2_hdr)}
    for ev in NEW_EVENTS[field]:
        star, school = ev.split(":")
        arrival = int(events[star]["arrival_corrected"])
        e: dict = {"arrival": arrival, "in_window": caliber.in_window(arrival)}
        mine = [c for c in u_rows if c[u_ix["event_id"]] == ev]
        e["p1_rows"] = len(mine)
        e["p1_persons"] = len({c[u_ix["incumbent_person_id"]] for c in mine})
        e["p1_rows_with_dose"] = sum(1 for c in mine if c[u_ix["dose_topic"]] not in ("", None))
        e["p1_rows_per_person_is_11"] = (e["p1_persons"] > 0
                                         and e["p1_rows"] == 11 * e["p1_persons"])
        mine2 = [c for c in p2_rows if c[p2_ix["event_id"]] == ev]
        e["p2_rows"] = len(mine2)
        e["p2_persons"] = len({c[p2_ix["pid"]] for c in mine2})
        # the becoming panel's real structure: per person a CONTIGUOUS tau run from -6, at most
        # 17 rows, exiting at the first tie (y=1 only on the last row) — "exit once co-authored"
        per: dict = {}
        for c in mine2:
            per.setdefault(c[p2_ix["pid"]], []).append((int(c[p2_ix["tau"]]),
                                                        int(c[p2_ix["y"]])))
        bad_shape = []
        for pid, rows_ in per.items():
            rows_.sort()
            taus = [t for t, _ in rows_]
            ys = [y for _, y in rows_]
            if not (taus[0] == -6 and taus[-1] <= 10 and len(taus) == taus[-1] - taus[0] + 1
                    and sum(ys) <= 1 and (sum(ys) == 0 or ys[-1] == 1)):
                bad_shape.append(pid)
        e["p2_persons_with_malformed_run"] = len(bad_shape)
        e["p2_shape_ok"] = (e["p2_persons"] > 0 and not bad_shape
                            and e["p2_rows"] <= 17 * e["p2_persons"])
        dup, npair = con.execute(f"""SELECT count(*) - count(DISTINCT i_id || '|' || j_id || '|' || year),
                                            count(DISTINCT i_id || '|' || j_id)
                                     FROM read_parquet('{cal_pairs}')
                                     WHERE event_id = '{ev}'""").fetchone()
        e["pair_year_duplicates"], e["pairs"] = dup, npair
        # exposure: every dept member's roster spell covers the arrival (the builder's own JOIN
        # guarantees it; re-verified here against the roster parquet)
        dept_members = sorted({c[u_ix["incumbent_person_id"]] for c in mine
                               if c[u_ix["channel"]] == "dept_only"})
        bad = 0
        if dept_members:
            vals = ",".join(f"('{p}')" for p in dept_members)
            bad = con.execute(f"""
                WITH mem(pid) AS (SELECT * FROM (VALUES {vals}))
                SELECT count(*) FROM mem WHERE NOT EXISTS (
                    SELECT 1 FROM read_parquet('{roster}') r
                    WHERE r.author_id = mem.pid AND r.school = '{school}'
                      AND {arrival} BETWEEN r.year_start AND r.year_end)""").fetchone()[0]
        e["dept_members_outside_roster_spell"] = bad
        ok = (e["in_window"] and e["p1_rows_per_person_is_11"] and e["p2_shape_ok"]
              and e["pair_year_duplicates"] == 0 and bad == 0)
        e["ok"] = ok
        if not ok:
            stop(f"{field} new event {ev} fails internal consistency: {e}")
        out[ev] = e
    return out


def afar_counts_accounting(frozen: pathlib.Path, cal: pathlib.Path, pin_eval) -> dict:
    fz = {(r["field"], r["cell"]): r for r in csv.DictReader(open(frozen, encoding="utf-8-sig"))}
    cl = {(r["field"], r["cell"]): r for r in csv.DictReader(open(cal, encoding="utf-8-sig"))}
    out = {}
    for k in sorted(fz):
        f, c = fz[k], cl.get(k)
        out["|".join(k)] = {
            "cut": {"frozen": f["cut"], "cal": c["cut"] if c else None},
            "pairs": {"frozen": f["pairs"], "cal": c["pairs"] if c else None},
            "events": {"frozen": f["events"], "cal": c["events"] if c else None}}
    econ_afar = cl.get(("econ", "A_far"))
    if econ_afar and fz[("econ", "A_far")]["cut"] == econ_afar["cut"]:
        # the F1 consequence holds only if the (recomputed) topic cut did not move
        pin_eval("econ.afar_events_86", 86, int(econ_afar["events"]),
                 note="F1 consequence (A5044432173's event out of A_far)")
        pin_eval("econ.afar_pairs_23830", 23830, int(econ_afar["pairs"]),
                 note="F1 consequence")
    else:
        out["econ_afar_cut_moved"] = {
            "frozen": fz[("econ", "A_far")]["cut"],
            "cal": econ_afar["cut"] if econ_afar else None,
            "note": "the dose median is recomputed at build time (H5); with the cut moved the F1 "
                    "86/23,830 arithmetic no longer applies verbatim — reported, not absorbed"}
    return out
