"""U0.5 Monash vertical-slice driver - parse -> align(live) -> Table B -> write to the SSD + sidecar.

Two sides:
  - build_roster_rows(parsed, aligner) - pure assembly (testable offline, the aligner can be an injected stub):
      run the aligner on every parsed person -> verdict -> to_table_b_row -> row; accumulate summary statistics along
      the way. One row per person, nothing dropped silently; needs_human goes into the needs_author list (never
      filled by guess).
  - main() - real live run: read the real archive -> parse -> query OpenAlex for every person (align.search_author,
      mailto + throttling + 429 backoff) -> write the SSD parquet (write_table_b, deterministic) + summary.json
      sidecar + the Yves Zenou note.

Output location (SSD, not in git):
  <SAR_DERIVED_ROOT>/u0p5_roster/dept_roster_panel_monash.parquet
  + summary_monash.json in the same directory (statistics + needs_author + zenou note, reproduction credential).

Hard rules: author_id bare; needs_human is never filled by guess; year is not taken as the arrival; polite rate limiting.
"""
from __future__ import annotations

import json
import os
import pathlib
from typing import Callable, Optional

from roster.align import search_author, UNSW_INST_ID
from roster.golden import ZENOU_AUTHOR_ID, ZENOU_NAME, zenou_slice_note
from roster.parse import parse_roster_lines, parse_unsw_lines
from roster.table_b import to_table_b_row, write_table_b, UNSW_DEPT_KEY

# SSD output location (architecture standard: data on the SSD, not in git).
# --- M3 port: repo path resolution (the legacy code hard-coded a local machine path) - config/paths.yaml ---
import pathlib as _sar_pl, sys as _sar_sys
_sar_repo = next(p for p in _sar_pl.Path(__file__).resolve().parents if p.name == "units").parents[1]
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
SSD_DERIVED_DIR = _sar_lazyout(_sar_derived_root() / "u0p5_roster")
TABLE_B_PARQUET = SSD_DERIVED_DIR / "dept_roster_panel_monash.parquet"
SUMMARY_JSON = SSD_DERIVED_DIR / "summary_monash.json"

# UNSW slice output location (same directory, different file name).
TABLE_B_PARQUET_UNSW = SSD_DERIVED_DIR / "dept_roster_panel_unsw.parquet"
SUMMARY_JSON_UNSW = SSD_DERIVED_DIR / "summary_unsw.json"

# Table A ECON_DEPT_REGISTRY output location (the source of econ_dept_ids, feeds U1 run_full pass_a_seed_authors).
TABLE_A_PARQUET = SSD_DERIVED_DIR / "econ_dept_registry.parquet"

# Historical roster byline line (steps 0-2): U1 full input (read-only) + output location + frozen location of the phrase config.
U1_FULL_DIR = _sar_derived_root() / "u1_edges_full_2026-07-05"
BYLINE_OUT_DIR = SSD_DERIVED_DIR / "byline_2026-07-05"
_UNITS_DIR = next(p for p in pathlib.Path(__file__).resolve().parents if p.name == "units")
PHRASE_CONFIG_DIR = _UNITS_DIR.parent / "config" / "econ_dept_phrases"  # curated config inside the code repository

# Default real archive fixture (also the only input evidence of this unit).
DEFAULT_RAW = (
    pathlib.Path(__file__).resolve().parents[2] / "tests" / "fixtures"
    / "monash_econ_pure_raw_2026-06-29.txt"
)
DEFAULT_RAW_UNSW = (
    pathlib.Path(__file__).resolve().parents[2] / "tests" / "fixtures"
    / "unsw_econ_our-people_raw_2026-06-29.txt"
)


def _star_frag_in_list(star_frags, *, star_id: str = ZENOU_AUTHOR_ID) -> str:
    """Star-anchor fragment list -> quoted + sorted fragment string for the SQL `IN (...)` clause; asserted non-empty before joining.

    Empty star_frags = the golden-standard star (Yves Zenou) is not in person_map (exactly the missed-person scenario to fear)
    -> HALT with the star_id stated clearly, instead of building `author_id IN ()` and letting duckdb raise an opaque
    ParserException.
    """
    if not star_frags:
        raise RuntimeError(
            f"Star anchor missing: gold-standard star {star_id} is not in person_map (star_frags empty) — "
            f"person_map dropped the gold-standard star; refusing to build an empty `author_id IN ()` clause."
            f" Confirm {star_id} is in person_map or fix the upstream disambiguation, then run step 7."
        )
    return ",".join(f"'{f}'" for f in sorted(star_frags))


def build_roster_rows(
    parsed: list[dict],
    *,
    aligner: Callable[..., dict],
    api_key: Optional[str] = None,
) -> tuple[list[dict], dict]:
    """parsed records -> (list of Table B rows, summary statistics). The aligner is injected (real = search_author, test = stub).

    One row per person (nothing dropped); for each person aligner(name) -> verdict -> to_table_b_row.
    summary accumulates: parsed_count / author_id_matched / needs_human_count / needs_author[]
                / adjunct_count / emeritus_count / zenou_matched / zenou_id.
    """
    rows: list[dict] = []
    needs_author: list[str] = []
    matched = 0
    zenou_id = None

    for rec in parsed:
        verdict = aligner(rec["display_name"], api_key=api_key)
        row = to_table_b_row(rec, verdict)
        rows.append(row)
        if verdict.get("needs_human") or row["author_id"] is None:
            needs_author.append(rec["display_name"])
        else:
            matched += 1
        if rec["display_name"] == ZENOU_NAME:
            zenou_id = row["author_id"]

    summary = {
        "dept_key": "monash_econ",
        "parsed_count": len(parsed),
        "author_id_matched": matched,
        "needs_human_count": len(needs_author),
        "needs_author": needs_author,
        "adjunct_count": sum(1 for r in parsed if r["is_adjunct"]),
        "emeritus_count": sum(1 for r in parsed if r["is_emeritus"]),
        "center_impact_labs_count": sum(1 for r in parsed if r["center"] == "Impact Labs"),
        "zenou_matched": zenou_id == ZENOU_AUTHOR_ID,
        "zenou_id": zenou_id,
        "zenou_note": zenou_slice_note(),
    }
    return rows, summary


def build_unsw_roster_rows(
    parsed: list[dict],
    *,
    aligner: Callable[..., dict],
    api_key: Optional[str] = None,
) -> tuple[list[dict], dict]:
    """UNSW parsed records -> (list of Table B rows, summary statistics). The aligner is injected (real = search_author, test = stub).

    Same skeleton as Monash build_roster_rows, differences: dept_key=unsw_econ; the flag counts are
    visiting/emeritus/postdoc (Monash: adjunct/emeritus/Impact Labs); no Yves Zenou note
    (Yves Zenou is the Monash golden standard, not in the UNSW slice).

    One row per person, nothing dropped silently; needs_human goes into needs_author; year passes through (always None for UNSW).
    """
    rows: list[dict] = []
    needs_author: list[str] = []
    matched = 0

    for rec in parsed:
        verdict = aligner(rec["display_name"], api_key=api_key)
        row = to_table_b_row(rec, verdict, dept_key=UNSW_DEPT_KEY)
        rows.append(row)
        if verdict.get("needs_human") or row["author_id"] is None:
            needs_author.append(rec["display_name"])
        else:
            matched += 1

    summary = {
        "dept_key": UNSW_DEPT_KEY,
        "parsed_count": len(parsed),
        "author_id_matched": matched,
        "needs_human_count": len(needs_author),
        "needs_author": needs_author,
        "visiting_count": sum(1 for r in parsed if r.get("is_visiting")),
        "emeritus_count": sum(1 for r in parsed if r.get("is_emeritus")),
        "postdoc_count": sum(1 for r in parsed if r.get("is_postdoc")),
    }
    return rows, summary


def main(raw_path: Optional[pathlib.Path] = None) -> dict:
    """Real live run (Monash): read the archive -> parse -> align via real OpenAlex queries -> write the SSD parquet + summary.

    Returns the summary (also written to the summary_monash.json sidecar).
    """
    raw_path = pathlib.Path(raw_path) if raw_path else DEFAULT_RAW
    api_key = os.environ.get("OPENALEX_API_KEY")

    parsed = parse_roster_lines(raw_path.read_text(encoding="utf-8"))
    rows, summary = build_roster_rows(parsed, aligner=search_author, api_key=api_key)

    SSD_DERIVED_DIR.mkdir(parents=True, exist_ok=True)
    write_table_b(rows, TABLE_B_PARQUET)
    summary_out = dict(summary)
    summary_out["table_b_path"] = str(TABLE_B_PARQUET)
    summary_out["table_b_rows"] = len(rows)
    SUMMARY_JSON.write_text(json.dumps(summary_out, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary_out


def main_unsw(raw_path: Optional[pathlib.Path] = None) -> dict:
    """Real live run (UNSW): read the archive -> parse_unsw -> align via real OpenAlex queries restricted to UNSW -> write to the SSD.

    The institution-restricted search uses UNSW_INST_ID (I31746571); a second route, the global subfield 2002, converges on the same criterion.
    Returns the summary (also written to the summary_unsw.json sidecar).
    """
    raw_path = pathlib.Path(raw_path) if raw_path else DEFAULT_RAW_UNSW
    api_key = os.environ.get("OPENALEX_API_KEY")

    def _unsw_aligner(display_name, *, api_key=None):
        return search_author(display_name, api_key=api_key, inst_id=UNSW_INST_ID)

    parsed = parse_unsw_lines(raw_path.read_text(encoding="utf-8"))
    rows, summary = build_unsw_roster_rows(parsed, aligner=_unsw_aligner, api_key=api_key)

    SSD_DERIVED_DIR.mkdir(parents=True, exist_ok=True)
    write_table_b(rows, TABLE_B_PARQUET_UNSW)
    summary_out = dict(summary)
    summary_out["table_b_path"] = str(TABLE_B_PARQUET_UNSW)
    summary_out["table_b_rows"] = len(rows)
    summary_out["openalex_inst_id"] = UNSW_INST_ID
    # I31746571 confirmed - kept in sync with main_table_a so the two summaries do not conflict.
    summary_out["openalex_inst_id_needs_author"] = False
    SUMMARY_JSON_UNSW.write_text(json.dumps(summary_out, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary_out


def main_table_a(target: Optional[pathlib.Path] = None) -> dict:
    """Produce + write Table A ECON_DEPT_REGISTRY (coarse two-school criterion) -> deterministic parquet + summary sidecar (same directory).

    Table A = the source of econ_dept_ids: the downstream run_full driver calls build_econ_dept_ids(rows, ...) with the
    real registry_by_id to fold out the institution set that feeds pass_a_seed_authors. This entry point only
    **produces and writes** Table A; the econ_dept_ids folding is done on the run_full side (coarse criterion = the
    institution id sets of the two schools, see table_a.build_econ_dept_ids).
    By default it writes to the real SSD (TABLE_A_PARQUET); tests pass a tmp target -> the summary goes to the directory
    of the target (the real SSD is not touched).
    """
    from roster.table_a import build_table_a_rows, write_table_a

    target = pathlib.Path(target) if target else TABLE_A_PARQUET
    rows = build_table_a_rows()
    target.parent.mkdir(parents=True, exist_ok=True)
    write_table_a(rows, target)

    summary = {
        "table_a_path": str(target),
        "table_a_rows": len(rows),
        "dept_keys": [r["dept_key"] for r in rows],
        "openalex_inst_ids": {r["dept_key"]: r["openalex_inst_id"] for r in rows},
        # UNSW I31746571 confirmed by full-run evidence.
        "unsw_inst_id_needs_author": False,
        "unsw_inst_id_confirmed_by": "the roster and disambiguation sign-off record of 2026-07-05 (internal, not shipped) §1",
    }
    (target.parent / "summary_table_a.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def main_byline_steps_0_2(out_dir: Optional[pathlib.Path] = None, *, use_prefilter: bool = True) -> dict:
    """Historical roster, byline line, steps 0-2 on real data - thin assembly, every part is already test-driven (roster.byline).

    Flow: write Table A (deterministic) -> freeze the phrase config into the repo (SHA recorded) -> step 0 precondition gate
    (upstream + registry, HALT-or-go) -> step 1 department matching (byline_dept_hits + unbound sidecar)
    -> step 2 year determination (byline_year_evidence + mismatch sidecar) -> summary sidecar written to out_dir.
    Output = candidate layer (pending, promoted to the official level only after human review); never taken as the arrival year.
    """
    from roster.byline import (
        build_dept_hits,
        build_phrase_config,
        build_year_evidence,
        probe_registry,
        probe_upstream,
        write_phrase_config,
    )
    from roster.table_a import build_table_a_rows

    out = pathlib.Path(out_dir) if out_dir else BYLINE_OUT_DIR
    table_a_summary = main_table_a()

    cfgs = build_phrase_config(build_table_a_rows())
    config_shas = write_phrase_config(cfgs, PHRASE_CONFIG_DIR)

    probe_up = probe_upstream(U1_FULL_DIR / "works_affil", U1_FULL_DIR / "authorship_edges")
    probe_reg = probe_registry(TABLE_A_PARQUET, [c["dept_key"] for c in cfgs])

    step1 = build_dept_hits(U1_FULL_DIR / "works_affil", cfgs, out, use_prefilter=use_prefilter)
    step2 = build_year_evidence(out / "byline_dept_hits.parquet",
                                U1_FULL_DIR / "authorship_edges", out)

    summary = {
        "inputs": {"u1_full_dir": str(U1_FULL_DIR), "table_a": str(TABLE_A_PARQUET)},
        "table_a": table_a_summary,
        "phrase_config_dir": str(PHRASE_CONFIG_DIR),
        "phrase_config_sha256": config_shas,
        "probe_upstream": probe_up,
        "probe_registry": probe_reg,
        "step1_dept_hits": step1,
        "step2_year_evidence": step2,
        "authority_note": "候选层 pending (G2); year 是署名年绝非到任年 (红线 #3)",
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary_byline_steps_0_2.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def main_byline_steps_3_6(out_dir: Optional[pathlib.Path] = None) -> dict:
    """Historical roster steps 3-6 on real data - thin assembly (roster.byline_skeleton is already test-driven).

    Reads the hits/evidence already on disk (no rescan of the 79 million edges) + WORKS subfield + the U2 person_map +
    author names, and produces the skeleton under **both variants in parallel**: evidence_rule in {all, printed_only}
    (how to use stamps is not fixed; no default is smuggled in). The threshold is read from
    require("roster","dept_membership_min").
    """
    import duckdb
    from common._redlines import require
    from roster.byline_skeleton import (
        build_skeleton_rows,
        fill_display_names,
        write_skeleton,
        year_by_pair_from_evidence,
    )

    out = pathlib.Path(out_dir) if out_dir else BYLINE_OUT_DIR
    hits_path = out / "byline_dept_hits.parquet"
    ev_path = out / "byline_year_evidence.parquet"

    import pyarrow.parquet as _pq
    hits = _pq.read_table(str(hits_path)).to_pylist()
    ybp = year_by_pair_from_evidence(ev_path)
    membership_min = require("roster", "dept_membership_min")

    con = duckdb.connect()
    con.execute("CREATE TEMP TABLE hit_works AS SELECT DISTINCT work_id FROM read_parquet(?)",
                [str(hits_path)])
    subfield_by_work = dict(con.execute(
        f"SELECT w.work_id, w.subfield_id FROM read_parquet('{U1_FULL_DIR}/works/**/*.parquet') w "
        "JOIN hit_works h ON w.work_id = h.work_id").fetchall())
    con.execute("CREATE TEMP TABLE hit_authors AS SELECT DISTINCT author_id FROM read_parquet(?)",
                [str(hits_path)])
    pm = str(_sar_derived_root() / "u2_person_map_2026-07-05/person_map/data.parquet")
    person_of = dict(con.execute(
        f"SELECT p.author_id, p.person_id FROM read_parquet('{pm}') p "
        "JOIN hit_authors h ON p.author_id = h.author_id").fetchall())
    name_of = dict(con.execute(
        f"SELECT a.author_id, a.display_name FROM read_parquet('{U1_FULL_DIR}/authors/**/*.parquet') a "
        "JOIN hit_authors h ON a.author_id = h.author_id").fetchall())

    summaries = {}
    for rule in ("all", "printed_only"):
        skeleton, stats, summary = build_skeleton_rows(
            hits, ybp, subfield_by_work, person_of,
            evidence_rule=rule, membership_min=membership_min)
        skeleton = fill_display_names(skeleton, name_of)
        write_skeleton(skeleton, stats, out, suffix=rule)
        summary["n_named"] = sum(1 for r in skeleton if r["display_name"] is not None)
        summaries[rule] = summary

    result = {
        "inputs": {"hits": str(hits_path), "evidence": str(ev_path)},
        "membership_min_signed": membership_min,
        "rules": summaries,
        "authority_note": ("两口径并行 (盖章用法unsigned); 全员 confidence=low + "
                           "human_verified=False (Q10); year_start/year_end 是署名年区间"
                           "、绝非到任年 (红线 #3)"),
    }
    (out / "summary_byline_steps_3_6.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main_byline_step_7(out_dir: Optional[pathlib.Path] = None) -> dict:
    """Historical roster step 7 on real data - merge preview + trust-set statistics + human-review queue (roster.byline_merge is already test-driven).

    The official Table B file is never touched; each variant produces dept_roster_panel_merged_{all,printed_only}.parquet.
    Star anchor = all fragments of the Yves Zenou person (person_map) - **limited to the two-school smoke test of this batch**:
    Yves Zenou is the only confirmed star of this batch (golden-standard anchor); when scaling to the 11 schools, the star list
    produced by the star-definition procedure must be connected, otherwise the 100% human review of the other
    stars would be silently missing. First degree = co-authored with any fragment (authorship_edges, whole history,
    deliberately wide - extra human review does no harm). Stamp-only pair = n_works_printed=0 in the all-variant stats:
    those passing the threshold go to P2, those not passing go to P3 (so that no coverage is silently narrowed).
    """
    import duckdb
    import pyarrow.parquet as _pq
    from roster.byline_merge import (
        build_human_review_queue,
        merge_candidate_rows,
        reconcile_counts,
        trusted_view,
        write_merged_preview,
    )
    from roster.byline import _write_det
    from roster.golden import ZENOU_AUTHOR_ID

    out = pathlib.Path(out_dir) if out_dir else BYLINE_OUT_DIR
    official = (_pq.read_table(str(TABLE_B_PARQUET)).to_pylist()
                + _pq.read_table(str(TABLE_B_PARQUET_UNSW)).to_pylist())

    con = duckdb.connect()
    pm = str(_sar_derived_root() / "u2_person_map_2026-07-05/person_map/data.parquet")
    star_frags = [r[0] for r in con.execute(
        f"SELECT author_id FROM read_parquet('{pm}') WHERE person_id = "
        f"(SELECT person_id FROM read_parquet('{pm}') WHERE author_id = ?)",
        [ZENOU_AUTHOR_ID]).fetchall()]
    edges = f"{U1_FULL_DIR}/authorship_edges/**/*.parquet"
    # Assert the star anchor is non-empty before joining the IN clause (empty = Yves Zenou missing from person_map -> HALT clearly, instead of crashing in the SQL).
    frag_list = _star_frag_in_list(star_frags)
    first_degree = {r[0] for r in con.execute(
        f"SELECT DISTINCT e2.author_id FROM read_parquet('{edges}') e2 "
        f"WHERE e2.work_id IN (SELECT work_id FROM read_parquet('{edges}') "
        f"WHERE author_id IN ({frag_list}))").fetchall()}
    star_set = set(star_frags) | first_degree

    stats_all = _pq.read_table(str(out / "byline_skeleton_stats_all.parquet")).to_pylist()
    stamped_only = {(r["author_id"], r["dept_key"]) for r in stats_all
                    if r["qualified"] and r["n_works_printed"] == 0}
    below_ids = [r for r in stats_all
                 if (not r["qualified"]) and r["n_works_printed"] == 0]
    bt_names = dict(con.execute(
        f"SELECT a.author_id, a.display_name FROM read_parquet('{U1_FULL_DIR}/authors/**/*.parquet') a "
        f"WHERE a.author_id IN ({','.join('?' * len(below_ids)) or "''"})",
        [r["author_id"] for r in below_ids]).fetchall()) if below_ids else {}
    stamped_below = [{"author_id": r["author_id"], "dept_key": r["dept_key"],
                      "display_name": bt_names.get(r["author_id"])} for r in below_ids]

    result = {"star_anchor_note": "本批冒烟限定: 星锚=Zenou (金标准); 11 校扩量须接已签明星定义流程的星名单",
              "star_fragments": sorted(star_frags),
              "n_first_degree_coauthors": len(first_degree),
              "n_stamped_only_qualified_pairs": len(stamped_only),
              "n_stamped_only_below_threshold_pairs": len(stamped_below),
              "rules": {}}
    queue_written = False
    for rule in ("all", "printed_only"):
        skeleton = _pq.read_table(
            str(out / f"byline_roster_skeleton_{rule}.parquet")).to_pylist()
        merged = merge_candidate_rows(official, skeleton)
        target = write_merged_preview(merged, out, suffix=rule)
        tv = trusted_view(merged, star_and_first_degree=star_set)
        rc = reconcile_counts(official, skeleton)
        result["rules"][rule] = {
            "merged_rows": len(merged), "merged_file": target.name,
            "trusted_view_rows": len(tv),
            "reconcile": rc,
            "zenou_rows": sorted(r["evidence"] for r in merged
                                 if r["author_id"] == ZENOU_AUTHOR_ID),
        }
        if rule == "all" and not queue_written:
            queue = build_human_review_queue(
                merged, star_and_first_degree=star_set,
                stamped_only_pairs=stamped_only,
                stamped_below_threshold=stamped_below)
            _QUEUE_SCHEMA = {"priority": "int16", "author_id": "str", "dept_key": "str",
                             "display_name": "str", "year_start": "int16",
                             "year_end": "int16", "reason": "str"}
            # The sort key uses the integer priority rank: stars + first-degree collaborators come first, consistent with the CSV/in-memory order
            _write_det(queue, _QUEUE_SCHEMA, out / "human_review_queue.parquet",
                       ("priority", "dept_key", "author_id"))
            import csv
            with (out / "human_review_queue.csv").open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(_QUEUE_SCHEMA.keys()))
                w.writeheader()
                w.writerows(queue)
            result["human_review_queue"] = {
                "rows": len(queue),
                "star_or_first_degree": sum(1 for r in queue
                                            if r["reason"] == "star_or_first_degree"),
                "stamped_only": sum(1 for r in queue if r["reason"] == "stamped_only"),
                "stamped_only_below_threshold": sum(
                    1 for r in queue if r["reason"] == "stamped_only_below_threshold"),
                "stamped_coverage_note": ("纯盖章 94 对全数在队: 过门槛 41 (34 独立 + 7 并星优先)"
                                          " + 未过门槛 53 (P3, 无区间)"),
            }
            queue_written = True

    result["authority_note"] = ("预览版并表 — 正式表B 未动; 人工签盖章口径后转正; "
                                "信任集=official+已人核候选 (G2/Q0/Q10); 队列=必核名单非裁决")
    (out / "summary_byline_step_7.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main_finalize(backup_dir: Optional[pathlib.Path] = None) -> dict:
    """Finalization: human-review results + printed_only skeleton -> official Table B (two schools). Back up first."""
    import csv as _csv
    import pyarrow.parquet as _pq
    from roster.byline_finalize import build_final_rows, finalize_school_table_b

    out = BYLINE_OUT_DIR
    backup = pathlib.Path(backup_dir) if backup_dir else (
        SSD_DERIVED_DIR / "_backup_2026-07-06_pre_finalize")
    skeleton = _pq.read_table(str(out / "byline_roster_skeleton_printed_only.parquet")).to_pylist()
    review = list(_csv.DictReader(open(out / "human_review_results_2026-07-06.csv", encoding="utf-8")))

    result = {"signed": "S-1 printed_only + S-7 转正 (2026-07-06 台账)", "schools": {}}
    for dept_key, path in (("monash_econ", TABLE_B_PARQUET), ("unsw_econ", TABLE_B_PARQUET_UNSW)):
        # Idempotent: official rows are recognized only by evidence=official_roster (on a re-run the review rows added last time are rebuilt from this review)
        official = [r for r in _pq.read_table(str(path)).to_pylist()
                    if r["evidence"] == "official_roster"]
        rows = build_final_rows(official_rows=official, skeleton_rows=skeleton,
                                review_rows=review, dept_key=dept_key)
        info = finalize_school_table_b(rows, path, backup_dir=backup)
        added = [r for r in rows if r["evidence"] != "official_roster"]
        info["official_rows"] = len(official)
        info["added_human_verified"] = len(added)
        info["added_manual_evidence"] = sum(1 for r in added if r["evidence"] == "manual")
        result["schools"][dept_key] = info
    (out / "summary_finalize_2026-07-06.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else "monash"
    if target == "unsw":
        s = main_unsw()
        print(json.dumps(s, ensure_ascii=False, indent=2))
    elif target == "table_a":
        s = main_table_a()
        print(json.dumps(s, ensure_ascii=False, indent=2))
    elif target == "byline":
        s = main_byline_steps_0_2()
        print(json.dumps(s, ensure_ascii=False, indent=2))
    elif target == "skeleton":
        s = main_byline_steps_3_6()
        print(json.dumps(s, ensure_ascii=False, indent=2))
    elif target == "merge":
        s = main_byline_step_7()
        print(json.dumps(s, ensure_ascii=False, indent=2))
    elif target == "finalize":
        s = main_finalize()
        print(json.dumps(s, ensure_ascii=False, indent=2))
    else:
        s = main()
        print(json.dumps({k: v for k, v in s.items() if k != "zenou_note"}, ensure_ascii=False, indent=2))
