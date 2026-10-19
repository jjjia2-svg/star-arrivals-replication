# -*- coding: utf-8 -*-
"""step1 — U4 shipment of the 52-event version: star_set v3 (197+36) + events v3 (52 rows) +
colleague-pool roster (11 schools, Adelaide replaced by the gap-filled merged version, star-set members removed) + paper_contrib.

Produces u4_star_set_52ev_2026-07-21/ (a brand-new directory):
  star_set/          the existing 197 rows carried over unchanged + 36 new star rows
  events/            the existing 16 event rows carried over byte for byte + 36 new events (build_event_at_authoritative_year)
  paper_contrib/     colleague pool = rosters of 11 schools (9 schools registry_v5 [Adelaide replaced by the gap-filled merged version] +
                     the two anchor schools roster_v4_proj8) with the star-set members themselves removed
  _roster_pool/      the 11-school roster after star removal (authoritative colleague-pool file of this run, also used by U6)
  _reports/          provenance + star-removal accounting + evidence chain of the new events
How to run (original layout): cd multiplex_pipeline && PYTHONHASHSEED=0 python3 <working scripts>/final52_2026-07-21/step1_freeze_ship_52ev.py
(in this package: python3 pipeline/drivers/run_driver.py, see pipeline/drivers/README.md)
"""
import json
import pathlib
import sys
import time

_HERE = pathlib.Path(__file__).resolve().parent
_MP = _HERE.parents[1]
sys.path[:0] = [str(_HERE)] + [str(_MP / p) for p in (
    "units/u0_foundation/src", "units/u1_fetch/src", "units/u2_resolve/src",
    "units/u3_panel/src", "units/u4_output_star/src")]

import pyarrow as pa                                       # noqa: E402
import pyarrow.parquet as pq                                # noqa: E402

from common80 import (ADELAIDE_GAP_EVENT_IDS, ADELAIDE_MERGED, DEPT_INST_11,  # noqa: E402
                      EDGES_SUB, EXISTING_16EV_IDS, NINE_SCHOOLS, PM_DIR,
                      PM_SUB, PROVENANCE_NOTE, REGISTRY_V5, ROSTER_V4_PROJ8,
                      OVERRIDE_A5068400819_ID, SSD, TIMELINE_SUB, U4_16EV, U4_OUT,
                      load_new_stars_35, new_star_rows_34)
from m7a_star.arrival_departure import build_per_work_timeline  # noqa: E402
from m7a_star.events_pipeline import build_event_at_authoritative_year  # noqa: E402
from m7a_star.pollution_guard import clean_au_attributions  # noqa: E402
from m7a_star.real_inputs import load_star_evidence, load_star_modal_flags  # noqa: E402
from m7a_star.write_events import write_events             # noqa: E402
from run_u4 import (freeze_star_set, resolve_provenance,   # noqa: E402
                    ship_paper_contrib)

t0 = time.time()
REPORTS = U4_OUT / "_reports"


def build_star_set_v3():
    frozen = pq.read_table(str(U4_16EV / "star_set" / "star_set.parquet")).to_pylist()
    hdr = json.loads((U4_16EV / "star_set" / "manifest_header.json").read_text("utf-8"))
    assert len(frozen) == 197, f"16-event star-set row count drifted: {len(frozen)}"
    new_rows = new_star_rows_34()
    new_ids = {r["author_id"] for r in new_rows}
    dup = new_ids & {s["author_id"] for s in frozen}
    # Top-10% version: the only collision allowed = A5068400819 (frozen is_star=False, overridden with the new star row so that the person becomes a star).
    # Any other collision still HALTs (prevents accidentally overwriting a star that is already correctly on the list).
    if dup - {OVERRIDE_A5068400819_ID}:
        raise SystemExit(f"HALT: new star ids collide with the existing 197 (other than A5068400819) {sorted(dup-{OVERRIDE_A5068400819_ID})}")
    # Override: remove from frozen the author_id overridden by the new star row (A5068400819) and use the new star row (is_star=True).
    frozen_kept = [s for s in frozen if s["author_id"] not in new_ids]
    stars = frozen_kept + new_rows
    result = {"stars": stars,
              "n_dropped_null_pub_year": hdr["n_dropped_null_pub_year"]}
    fres = freeze_star_set(result, U4_OUT / "star_set", derived_root=SSD,
                           edges_sub=EDGES_SUB)
    print(f"star_set v3 frozen ✓ {fres['n_candidates']} rows ({len(frozen_kept)}+{len(new_rows)}, "
          f"overrides frozen={sorted(dup)}, A5063040920 excluded / A5072079903 deduplicated) "
          f"hash={fres['stars_set_hash'][:16]}.. ({time.time()-t0:.0f}s)")
    return stars, fres


def build_pool_rosters(stars):
    """Colleague-pool roster = 9 schools v5 (Adelaide replaced by the gap-filled merged version) + the two anchor schools' proj8, with star-set members removed."""
    pm = pq.read_table(str(SSD / PM_DIR / "data.parquet"),
                       columns=["author_id", "person_id"]).to_pylist()
    pid_by_author = {r["author_id"]: r["person_id"] for r in pm}
    flagged = [s for s in stars if s.get("is_star_1pct") or s.get("is_star_5pct")]
    star_pids = {pid_by_author[s["author_id"]] for s in flagged
                 if s["author_id"] in pid_by_author}
    star_frags = {r["author_id"] for r in pm if r["person_id"] in star_pids}

    pool_dir = U4_OUT / "_roster_pool"
    pool_dir.mkdir(parents=True, exist_ok=True)
    files, tally = [], {}
    srcs = [(s, ADELAIDE_MERGED if s == "adelaide" else
            REGISTRY_V5 / f"dept_roster_panel_{s}.parquet") for s in NINE_SCHOOLS]
    srcs += [(a, ROSTER_V4_PROJ8 / f"dept_roster_panel_{a}.parquet")
             for a in ("monash", "unsw")]
    dropped_detail = []
    for school, src in srcs:
        rows = pq.read_table(str(src)).to_pylist()
        kept = [r for r in rows if r["author_id"] not in star_frags]
        dropped = [r for r in rows if r["author_id"] in star_frags]
        dropped_detail += [{"school": school, "display_name": r["display_name"],
                            "author_id": r["author_id"]} for r in dropped]
        tally[school] = {"rows_in": len(rows), "kept": len(kept),
                         "dropped_star_rows": len(dropped),
                         "source": str(src)}
        out = pool_dir / f"dept_roster_panel_{school}.parquet"
        cols = ["dept_key", "author_id", "display_name", "year_start", "year_end",
                "evidence", "confidence", "human_verified"]
        arrays = {}
        src_t = pq.read_table(str(src))
        for cn in cols:
            typ = src_t.schema.field(cn).type
            if pa.types.is_null(typ):
                typ = pa.string()
            arrays[cn] = pa.array([r[cn] for r in kept], type=typ)
        pq.write_table(pa.table(arrays), str(out))
        files.append(out)
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "pool_star_exclusion.json").write_text(json.dumps({
        "rule": ("同事池 = 各事件校名册 (Adelaide 换 2007-2021 补洞合并版), 剔除星集成员本人 "
                 f"(star_set v3 1%∨5% 旗 {len(flagged)} 星 → person {len(star_pids)} → 碎片 "
                 f"{len(star_frags)}); 口径选择 = 主笔裁定, 已知会"),
        "tally": tally, "n_dropped_rows": len(dropped_detail),
        "dropped_rows": dropped_detail,
    }, ensure_ascii=False, indent=1, sort_keys=True), "utf-8")
    print(f"colleague-pool roster ✓ 11 schools (Adelaide = gap-filled merged version), star rows dropped {len(dropped_detail)} "
          f"({time.time()-t0:.0f}s)")
    return files, tally


def build_events_v3(stars, stars_set_hash):
    frozen_ev = pq.read_table(str(U4_16EV / "events" / "data.parquet")).to_pylist()
    anchors = [e for e in frozen_ev if e["event_id"] in set(EXISTING_16EV_IDS)]
    assert len(anchors) == 16, f"existing 16-event rows extracted: {len(anchors)} != 16"

    new35 = load_new_stars_35()
    ids35 = [s["author_id"] for s in new35]
    by_id = {s["author_id"]: s for s in new35}
    ev = load_star_evidence(SSD, ids35, person_map_sub=PM_DIR,
                            timeline_sub=TIMELINE_SUB, edges_sub=EDGES_SUB)
    modal = load_star_modal_flags(
        SSD, {aid: (by_id[aid]["arrival"], by_id[aid]["dept"]) for aid in ids35},
        dept_inst_map=DEPT_INST_11, person_map_sub=PM_DIR,
        timeline_sub=TIMELINE_SUB)
    new_events, prov_rows, n_dropped = [], [], 0
    for aid in sorted(ids35):
        s = by_id[aid]
        cleaned = clean_au_attributions(ev["evidence_by_star"].get(aid, []))
        n_dropped += cleaned["n_dropped"]
        timeline = build_per_work_timeline(cleaned["kept"])
        built = build_event_at_authoritative_year(
            star_person_id=aid, dept_id=DEPT_INST_11[s["dept"]],
            timeline=timeline,
            truth_evidence={"official_roster": int(s["arrival"])},
            modal_inst_year=bool(modal.get(aid, False)),
            arrival_year=int(s["arrival"]))
        evrow = built["event"]
        assert evrow["event_id"] == f"{aid}:{s['arrival']}"
        new_events.append(evrow)
        prov_rows.append({
            "event_id": evrow["event_id"], "name": s["name"], "dept": s["dept"],
            "arrival_verified": s["arrival"], "evidence_grade": s["grade"],
            "discipline_flag": s["discipline_flag"], "decision": s["decision"],
            "modal_inst_year": evrow["modal_inst_year"],
            "departed_year": evrow["departed_year"],
            "prior_main_inst": built["prior_main_inst"],
            "n_polluted_dropped": cleaned["n_dropped"],
            "adelaide_gap_event": evrow["event_id"] in ADELAIDE_GAP_EVENT_IDS,
        })

    rows51 = anchors + new_events
    pv = resolve_provenance(SSD, edges_sub=EDGES_SUB)
    res = write_events([dict(r) for r in rows51], U4_OUT / "events",
                       ship_star_ids={r["star_person_id"] for r in rows51},
                       stars_set_hash=stars_set_hash,
                       source_snapshot_merkle=pv["source_snapshot_merkle"],
                       config_sha=pv["config_sha"],
                       n_polluted_dropped=n_dropped)
    (REPORTS / "events_v3_provenance.json").write_text(json.dumps({
        "note": PROVENANCE_NOTE,
        "provenance_tag": "author_task_2026-07-21",
        "existing_16ev_unchanged": EXISTING_16EV_IDS,
        "excluded_A5063040920_flag_for_author": True,
        "new_events": prov_rows,
    }, ensure_ascii=False, indent=1, sort_keys=True), "utf-8")
    print(f"events v3 ✓ {res['n_events']} rows (target 52, actual 51: A5063040920 excluded pending manual review) "
          f"({time.time()-t0:.0f}s)")
    return res


def main():
    if U4_OUT.exists() and any(U4_OUT.iterdir()):
        raise SystemExit(f"HALT: {U4_OUT} already exists and is not empty — only a new directory may be created")
    U4_OUT.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)

    stars, fres = build_star_set_v3()
    pool_files, pool_tally = build_pool_rosters(stars)
    ev_res = build_events_v3(stars, fres["stars_set_hash"])

    rel_pool = [str(p.relative_to(SSD)) for p in pool_files]
    pc = ship_paper_contrib(SSD, U4_OUT, star_rows=stars, edges_sub=EDGES_SUB,
                            person_map_sub=PM_SUB, roster_files=rel_pool)
    print(f"paper_contrib ✓ {pc['n_rows']} rows; star persons {pc['n_star_persons']}; "
          f"unmapped star authors {pc['n_unmapped_star_authors']} ({time.time()-t0:.0f}s)")

    report = {
        "date": "2026-07-21",
        "mode": "FREEZE_SHIP_52EV_TARGET_ACTUAL_51 (作者任务: 跑完前5%扩军版全链; "
                "目标52事件, 实跑排除A5063040920[识别门槛冲突, 待人工复核]=51)",
        "star_set": {"n": len(stars), "n_new_rows": 34,
                     "stars_set_hash": fres["stars_set_hash"]},
        "events": {"n": ev_res["n_events"], "existing": 16, "new": 35,
                  "target_was_52": True, "excluded_A5063040920_conflict": "A5063040920"},
        "paper_contrib": {"n_rows": pc["n_rows"],
                          "n_unmapped_star_authors": pc["n_unmapped_star_authors"]},
        "pool_tally": pool_tally,
        "elapsed_s": round(time.time() - t0, 1),
    }
    (REPORTS / "freeze_ship_52ev_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1, sort_keys=True), "utf-8")
    print("STEP1_DONE →", U4_OUT)


if __name__ == "__main__":
    main()
