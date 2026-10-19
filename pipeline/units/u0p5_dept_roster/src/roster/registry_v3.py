"""11-school registry v3 assembly - the rosters of the 8 new schools + UQ are finalized according to the boundary
adjudications.

In plain words: the draft Table B of each of the 8 new schools is turned into the official roster by applying the 4
types of boundary adjudications (removals delete rows, fail loudly; boundary acceptances get hv=True + an evidence
note), and together with the 3 frozen rosters (Monash STARFIX / UNSW / UQ) +
Table A (department boundaries of the 11 schools) they are integrated into the new directory registry_v3_2026-07-12/.

Hard rules (following the uq_finalize / table_a / table_b precedent):
  - **New directory, never overwrite production/frozen old files** (carry_frozen first verifies by sha that the
    source is the expected one; the write is idempotent).
  - Removals fail loudly name by name (0 hits -> ValueError; a misspelled name never silently deletes the wrong person).
  - Year columns untouched (the verified year span goes into the evidence note; years are changed uniformly later in
    the final per-person check).
  - author_id is never filled by guess (draft all None, to be folded to person_id by U2; the disambiguation queue is in
    each school's checklist and is not a panel change).
  - Yves Zenou golden standard guarded (after carry the Monash roster must contain Yves Zenou@A5017376589@monash_econ).
  - Schema guarded row by row + deterministic write (same content, byte-level sha equal).

No discretionary identification decisions: every inclusion/exclusion comes from the boundary adjudications.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import shutil
import unicodedata
from typing import Mapping, Sequence

from common.schema import DEPT_ROSTER_PANEL, assert_matches_schema
from roster.table_a import build_table_a_rows_all, write_table_a
from roster.table_b import write_table_b

# ─── Constants ────────────────────────────────────────────────────────────────────
REGISTRY_V3_DIR = "registry_v3_2026-07-12"
BATCH_DATE = "2026-07-12"
RULING_DOC = ("design_notes/"
              "2026-07-12_discipline_boundary_ruling.md")   # an internal record, not shipped

# Frozen files = v3 authority, carried byte for byte (Monash = the STARFIX version with star arrival corrections, not the pre-starfix centres).
FROZEN_PANELS: dict[str, dict] = {
    "monash_econ": {
        "dir": "roster_v2026-07-11_centres_starfix",
        "file": "dept_roster_panel_monash.parquet",
        "sha256": "9277b449a595fca3bdfc7070639f98f34e3ab809a02168adf4d45662ea40ab53",
    },
    "unsw_econ": {
        "dir": "roster_v2026-07-11_centres_starfix",
        "file": "dept_roster_panel_unsw.parquet",
        "sha256": "bcfef0aaad7aa8c8feac175287d1f100c56f77b0cfae5b87c3cc436dabc327a3",
    },
    "uq_econ": {
        "dir": "roster_v2026-07-11_uq",
        "file": "dept_roster_panel_uq.parquet",
        "sha256": "64a4a20de1965d85909e24c7e6a7c60f352f510e7f6c1ef9c9e379e1fbd789c6",
    },
}
TABLE_A_SHA = "c8d508a0ee1bc02172769e972a91b317482ba0a78563593dcfc8cbca3109527f"
TABLE_A_FILE = "econ_dept_registry_11schools.parquet"

# Yves Zenou golden-standard anchor (hard requirement; = golden.ZENOU_AUTHOR_ID / MONASH).
ZENOU_AUTHOR_ID = "A5017376589"
ZENOU_NAME = "Yves Zenou"
ZENOU_DEPT = "monash_econ"

# 8 new schools: dept_key -> (expansion directory, draft file, output panel file).
EXPANSION_SCHOOLS: dict[str, dict] = {
    "melbourne_econ": {"dir": "expansion_melbourne_2026-07-11",
                       "draft": "melbourne_table_b_draft.parquet",
                       "panel": "dept_roster_panel_melbourne.parquet", "adj": "melbourne"},
    "sydney_econ": {"dir": "expansion_sydney_2026-07-11",
                    "draft": "sydney_table_b_draft.parquet",
                    "panel": "dept_roster_panel_sydney.parquet", "adj": "sydney"},
    "anu_econ": {"dir": "expansion_anu_2026-07-11",
                 "draft": "anu_table_b_draft.parquet",
                 "panel": "dept_roster_panel_anu.parquet", "adj": "anu"},
    "uwa_econ": {"dir": "expansion_uwa_2026-07-11",
                 "draft": "uwa_table_b_draft.parquet",
                 "panel": "dept_roster_panel_uwa.parquet", "adj": "uwa"},
    "adelaide_econ": {"dir": "expansion_adelaide_2026-07-11",
                      "draft": "adelaide_table_b_draft.parquet",
                      "panel": "dept_roster_panel_adelaide.parquet", "adj": "adelaide"},
    "deakin_econ": {"dir": "expansion_deakin_2026-07-11",
                    "draft": "deakin_table_b_draft.parquet",
                    "panel": "dept_roster_panel_deakin.parquet", "adj": "deakin"},
    "uts_econ": {"dir": "expansion_uts_2026-07-11",
                 "draft": "uts_table_b_draft.parquet",
                 "panel": "dept_roster_panel_uts.parquet", "adj": "uts"},
    "macquarie_econ": {"dir": "expansion_macquarie_2026-07-11",
                       "draft": "macquarie_table_b_draft.parquet",
                       "panel": "dept_roster_panel_macquarie.parquet", "adj": "macquarie"},
}

# Historical gaps that Wayback could not capture for each school, to be filled by the full U1 byline / a few precise
# Chrome passes (marked gap_pending, not blocking finalization - the schema has no gap column, so they are recorded in
# the school-level metadata sidecar).
GAP_PENDING: dict[str, list[str]] = {
    "uwa_econ": ["2001-2025 (机器可达 Wayback 仅 1997-2000 econs 子站; 2001-25 全靠 Chrome/byline)"],
    "anu_econ": ["2004-2010 (Wayback 缺)"],
    "sydney_econ": ["2000", "2002", "2009-2012", "2020-2025 (list.php 停/JS 壳)"],
    "adelaide_econ": ["Chrome 缺口 60 处 (老系职级不明 16 + 中心组任职线 + distinctive-name 真号复搜)"],
    "uts_econ": ["2018-2024 (profiles.uts JS 期, 静态档到顶)"],
    "deakin_econ": ["2000-2002 (无直接快照, 推断)"],
    "macquarie_econ": ["2 处小快照缺口 (断档 2007-2011 / 2009-2011)"],
    "melbourne_econ": ["少量 (Wayback 覆盖好, byline 补零星)"],
}


# ─── Pure functions: normalization + matching ────────────────────────────────────────────────────
def _norm(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFKD", s or "")
                if not unicodedata.combining(c))
    s = s.replace("’", "'").replace("‐", "-")
    return re.sub(r"[\s\.]+", " ", s).strip().lower()


def _match_rows(rows: Sequence[dict], name: str) -> list[int]:
    key = _norm(name)
    return [i for i, r in enumerate(rows) if _norm(r["display_name"]) == key]


# ─── Pure function: apply the boundary adjudications (removal + stamp hv on boundary acceptance) ───────────────────────────────
def apply_adjudication(draft_rows: Sequence[dict], adj: Mapping, *,
                       batch_date: str = BATCH_DATE,
                       ruling_doc: str = RULING_DOC) -> dict:
    """Draft rows + boundary adjudications -> finalized rows (pure function, original rows unchanged) + report.

    adj keys:
      - removals: [{name, why}]      rows to delete (each needs >= 1 hit, 0 hits -> ValueError).
      - verified: [{name, reason}]   boundary acceptances get hv=True + confidence=high +
                                     evidence appended '|hv:{date}<boundary-accept tag>;{reason}|src:{doc}'
                                     (the tag is a fixed Chinese label, "boundary adjudication: accept").
                                     (Year columns untouched.)
    The row indices hit by removals and acceptances must be disjoint (one person cannot be both removed and accepted
    -> RuntimeError).
    """
    rows = [dict(r) for r in draft_rows]

    removed_people, removed_rows, removed_idx = [], 0, set()
    for rm in adj.get("removals", []):
        hits = _match_rows(rows, rm["name"])
        if not hits:
            raise ValueError(f"apply_adjudication/removal: {rm['name']!r} matched 0 rows in the draft "
                             "— misspelled name / no longer on the roster, fail-loud")
        removed_idx.update(hits)
        removed_people.append({"name": rm["name"], "n_rows": len(hits),
                               "why": rm.get("why", "")})
        removed_rows += len(hits)

    verified_people, verified_idx = [], set()
    for vf in adj.get("verified", []):
        hits = _match_rows(rows, vf["name"])
        if not hits:
            raise ValueError(f"apply_adjudication/verified: {vf['name']!r} matched 0 rows "
                             "— misspelled name / already deleted, fail-loud")
        verified_idx.update(hits)
        verified_people.append({"name": vf["name"], "n_rows": len(hits),
                                "reason": vf.get("reason", "")})

    clash = removed_idx & verified_idx
    if clash:
        raise RuntimeError(f"apply_adjudication: the same row is both removed and verified (idx={sorted(clash)[:3]}) "
                           "— the removals and verified lists contradict each other; stop")

    # Stamp hv (rows to be removed are deleted later, not stamped)
    for vf in adj.get("verified", []):
        for i in _match_rows(rows, vf["name"]):
            rows[i]["human_verified"] = True
            rows[i]["confidence"] = "high"
            rows[i]["evidence"] = (f"{rows[i]['evidence']}|hv:{batch_date}边界裁决_收"
                                   f";{vf.get('reason', '')}|src:{ruling_doc}")

    # Delete rows (pop in reverse order)
    for i in sorted(removed_idx, reverse=True):
        rows.pop(i)

    # Guard: schema row by row
    for r in rows:
        assert_matches_schema(r.keys(), DEPT_ROSTER_PANEL, label="registry_v3_row")

    report = {
        "n_draft_rows": len(draft_rows),
        "n_final_rows": len(rows),
        "n_removed_rows": removed_rows,
        "n_removed_people": len(removed_people),
        "n_verified_people": len(verified_people),
        "n_hv_true_rows": sum(1 for r in rows if r["human_verified"]),
        "n_unique_people": len({_norm(r["display_name"]) for r in rows}),
        "removed": removed_people,
        "verified": verified_people,
    }
    return {"rows": rows, "report": report}


# ─── Write helper: byte-level carry of frozen files (sha guard) ───────────────────────────────────
def _sha256(p) -> str:
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def carry_frozen(src, dst, expected_sha: str) -> str:
    """Copy the frozen panel to dst byte for byte; before writing verify src sha == expected (mismatch -> fail, guards
    against touching the wrong file), after writing verify dst sha == expected (confirms byte-level equality). Returns the sha."""
    src, dst = pathlib.Path(src), pathlib.Path(dst)
    got = _sha256(src)
    if got != expected_sha:
        raise RuntimeError(f"carry_frozen: source {src} sha={got[:16]} ≠ expected "
                           f"{expected_sha[:16]} — wrong frozen file; stop")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    out = _sha256(dst)
    if out != expected_sha:
        raise RuntimeError(f"carry_frozen: sha of {dst} changed after writing ({out[:16]}) — fail-loud")
    return out


def assert_zenou_in_panel(panel_path) -> dict:
    """Golden-standard guard: the Monash roster must contain Yves Zenou@A5017376589@monash_econ (hard requirement). Returns a summary of that row."""
    import pandas as pd
    df = pd.read_parquet(panel_path)
    z = df[df["display_name"] == ZENOU_NAME]
    if len(z) != 1:
        raise RuntimeError(f"assert_zenou_in_panel: in {panel_path}, Yves Zenou appears {len(z)} times, must be exactly 1")
    r = z.iloc[0]
    if r["author_id"] != ZENOU_AUTHOR_ID or r["dept_key"] != ZENOU_DEPT:
        raise RuntimeError(f"assert_zenou_in_panel: Zenou id/dept drifted "
                           f"(id={r['author_id']} dept={r['dept_key']}) — gold standard broken; stop")
    return {"author_id": r["author_id"], "dept_key": r["dept_key"],
            "year_start": (None if r["year_start"] is None else int(r["year_start"]))}


# ─── Assembler (ship) ───────────────────────────────────────────────────────────
def assemble_registry_v3(ssd_roster_dir, adjudications: Mapping, *,
                         out_dir_name: str = REGISTRY_V3_DIR) -> dict:
    """Integrate the 11 schools -> new registry_v3 directory. Never overwrite production/frozen old files.

    Steps:
      1. Create the new directory (exists and non-empty -> fail, prevents overwriting).
      2. Table A: rebuild with code build_table_a_rows_all(), write, assert sha == frozen (deterministic regression).
      3. Carry the 3 frozen rosters (Monash STARFIX/UNSW/UQ) byte for byte (sha guard).
      4. 8 new schools: read the draft -> apply_adjudication(that school's adjudications) -> write_table_b (deterministic write).
      5. Yves Zenou golden-standard guard (assert on the carried Monash roster read back).
      6. Write roster_versions.json (v3) + summary sidecar + the frozen adjudications JSON.
    """
    import pandas as pd

    ssd = pathlib.Path(ssd_roster_dir)
    out = ssd / out_dir_name
    if out.exists() and any(out.iterdir()):
        raise RuntimeError(f"assemble_registry_v3: output directory {out} already exists and is non-empty — never overwrite, "
                           "use another directory or check by hand")
    out.mkdir(parents=True, exist_ok=True)

    report: dict = {"out_dir": str(out), "schools": {}, "frozen": {}, "guards": {}}

    # 2. Table A (rebuilt by code + sha guard)
    ta_path = out / TABLE_A_FILE
    write_table_a(build_table_a_rows_all(), ta_path)
    ta_sha = _sha256(ta_path)
    if ta_sha != TABLE_A_SHA:
        raise RuntimeError(f"assemble_registry_v3: Table A sha={ta_sha[:16]} != frozen "
                           f"{TABLE_A_SHA[:16]} — department boundary drifted, fail-loud")
    report["table_a"] = {"file": str(ta_path), "sha256": ta_sha, "rows": 11}

    # 3. Carry the frozen rosters
    for dept_key, meta in FROZEN_PANELS.items():
        src = ssd / meta["dir"] / meta["file"]
        dst = out / meta["file"]
        sha = carry_frozen(src, dst, meta["sha256"])
        n = len(pd.read_parquet(dst))
        report["frozen"][dept_key] = {"file": meta["file"], "sha256": sha, "rows": n,
                                      "carried_from": str(src)}

    # 4. Finalize the 8 new schools
    versions: dict = {}
    for dept_key, meta in EXPANSION_SCHOOLS.items():
        draft = pd.read_parquet(ssd / meta["dir"] / meta["draft"])
        draft_rows = draft.to_dict("records")
        # pandas/pyarrow read back numpy/NA; normalize to native python (as table_b writing requires):
        #   year_start/year_end -> int|None; author_id -> str|None; evidence/confidence -> str;
        #   human_verified -> bool.
        for r in draft_rows:
            for k in ("year_start", "year_end"):
                r[k] = None if pd.isna(r[k]) else int(r[k])
            r["author_id"] = None if pd.isna(r["author_id"]) else str(r["author_id"])
            r["evidence"] = str(r["evidence"])
            r["confidence"] = str(r["confidence"])
            r["display_name"] = str(r["display_name"])
            r["dept_key"] = str(r["dept_key"])
            r["human_verified"] = bool(r["human_verified"])
        res = apply_adjudication(draft_rows, adjudications[meta["adj"]])
        panel = out / meta["panel"]
        write_table_b(res["rows"], panel)
        report["schools"][dept_key] = {
            "file": meta["panel"], "sha256": _sha256(panel), **res["report"],
            "gap_pending": GAP_PENDING.get(dept_key, []),
        }

    # 5. Yves Zenou golden-standard guard
    report["guards"]["zenou"] = assert_zenou_in_panel(out / FROZEN_PANELS["monash_econ"]["file"])
    report["guards"]["frozen_sha_preserved"] = True

    # 6. roster_versions.json v3 + summary + adjudications JSON
    versions = {
        "authorized_by": "2026-07-12 人工批全部 4 类边界裁决 (8 新校+UQ 名册转正 → 11 校 registry v3)",
        "date": BATCH_DATE,
        "ruling_doc": RULING_DOC,
        "note": ("registry v3 = 表A(11校系边界,代码重建 sha 守) + 3 冻结册(Monash STARFIX/"
                 "UNSW/UQ 字节级 carry) + 8 新校(draft 按边界裁决 finalize)。生产 econ_dept_"
                 "registry.parquet(2 行) + 冻结件原目录一字不动 — 本目录只新建。"),
        "table_a": {"file": TABLE_A_FILE, "sha256": ta_sha, "rows": 11},
        "roster_versions": {},
    }
    for dept_key, meta in FROZEN_PANELS.items():
        versions["roster_versions"][dept_key] = {
            "file": meta["file"], "sha256": report["frozen"][dept_key]["sha256"],
            "status": "frozen_carried", "rows": report["frozen"][dept_key]["rows"]}
    for dept_key, meta in EXPANSION_SCHOOLS.items():
        s = report["schools"][dept_key]
        versions["roster_versions"][dept_key] = {
            "file": meta["panel"], "sha256": s["sha256"], "status": "finalized_v3",
            "rows": s["n_final_rows"], "unique_people": s["n_unique_people"],
            "n_removed_people": s["n_removed_people"], "n_hv_true_rows": s["n_hv_true_rows"],
            "gap_pending": GAP_PENDING.get(dept_key, [])}
    (out / "roster_versions.json").write_text(
        json.dumps(versions, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    (out / "registry_v3_adjudications_2026-07-12.json").write_text(
        json.dumps(dict(adjudications), ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "summary_registry_v3_2026-07-12.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")

    report["roster_versions_file"] = str(out / "roster_versions.json")
    return report
