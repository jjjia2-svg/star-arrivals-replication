#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Merge 22 human-verified batches -> gold roster + rejected list + stats."""
import pandas as pd, glob, os, re, json, unicodedata

# --- M3 port: repo path resolution (legacy hard-coded the author's machine) — config/paths.yaml ---
import pathlib as _sar_pl, sys as _sar_sys
_sar_repo = next(p for p in _sar_pl.Path(__file__).resolve().parents if p.name == "rosters").parents[1]
if str(_sar_repo) not in _sar_sys.path:
    _sar_sys.path.append(str(_sar_repo))
from pipeline.lib.paths import (derived_root as _sar_derived_root,  # noqa: E402,F401
                                snapshot_root as _sar_snapshot_root,
                                ssd_root as _sar_ssd_root,
                                legacy_thesis as _sar_legacy_thesis,
                                require_readable as _sar_rd,
                                require_writable as _sar_rw,
                                output_target as _sar_out,
                                deferred_output_target as _sar_lazyout,
                                staged_run_dir as _sar_staged)
BASE = str(_sar_staged(_sar_legacy_thesis() / "v2_output/econ_roster_verify_2026-08-09"))
OUT_ALL = f"{BASE}/econ_roster_verified_all.csv"
OUT_PQ  = f"{BASE}/roster_clean_11school_verified.parquet"
OUT_REJ = f"{BASE}/rejected_persons.csv"

# ---------- 1. load ----------
fs = sorted(glob.glob(f"{BASE}/verified/batch_*_verified.csv"),
            key=lambda p: int(re.search(r'batch_(\d+)_', p).group(1)))
frames = []
for f in fs:
    d = pd.read_csv(f, dtype=str, keep_default_na=False)
    d["src_batch"] = int(re.search(r'batch_(\d+)_', f).group(1))
    frames.append(d)
V = pd.concat(frames, ignore_index=True)
V["verdict"] = V["verdict"].str.strip().str.lower()

# ---------- 2. dedup (same person+school): keep strongest evidence ----------
ET_RANK = {  # higher = stronger
    "orcid_employment": 100, "orcid": 95,
    "wayback_dept_roster": 90, "wayback_roster": 90, "wayback_stafflist": 90,
    "official_roster": 90, "dept_roster": 88, "centre_roster": 85,
    "wayback_staff_page": 84, "wayback_staff_profile": 84, "wayback_dept_page": 82,
    "cv": 80, "personal_cv": 80, "self_cv": 80,
    "dept_website_current": 75, "dept_staff_page": 75, "university_portal": 72,
    "repec": 60, "crossref": 55, "openalex": 20, "openalex_author": 15,
}
def ev_rank(et):
    et = (et or "").lower()
    best = 30
    for k, v in ET_RANK.items():
        if k in et:
            best = max(best, v)
    return best
VERDICT_RANK = {"confirmed": 3, "rejected": 2, "uncertain": 1}
V["_ev"] = V["evidence_type"].map(ev_rank)
V["_vr"] = V["verdict"].map(VERDICT_RANK).fillna(0)
V = (V.sort_values(["_vr", "_ev"], ascending=False)
       .drop_duplicates(["school", "author_id"], keep="first")
       .sort_values(["src_batch"]).reset_index(drop=True))

# ---------- 3. year_correction parser ----------
DASH = dict.fromkeys(map(ord, "–—－"), "-")
BLOCK = ["存疑", "未查到", "未见硬", "无直接证据", "未证实", "未被独立证实",
         "unknown", "疑为", "无法", "待核", "未证", "几乎肯定错"]
# hand overrides after eyeballing every auto-applied row (school|author_id -> (s,e) or None=noted)
# reason for each is recorded in OVERRIDE_WHY
OVERRIDE = {
 "monash|A5033837815": (2007, 2014),   # start-year-only correction; parser had consumed year_end
 "sydney|A5100758183": (2010, 2019),   # start-year-only correction; roster-attested start year used
 "uq|A5074458129":     (2014, 2019),   # start-year-only correction; evidence year used
 "uq|A5111390546":     (2003, 2008),   # approximate range in the correction; bounds taken
 "macquarie|A5047158807": (2020, 2022),# start year only; end unchanged
 "melbourne|A5068641067": (2015, 2024),# start year corrected; end unchanged
 "melbourne|A5006379257": (2013, 2025),# two spells; one-row schema takes the envelope
 "melbourne|A5069962916": (2002, 2025),# two spells; one-row schema takes the envelope
 "uwa|A5069435530":    None,           # correction rests on OpenAlex affiliation years only; left as noted
}
def norm(s):
    s = unicodedata.normalize("NFKC", str(s or "")).strip()
    return s.translate(DASH).lstrip("~≈")

def parse_correction(txt, ys, ye):
    """return (new_start, new_end, tier) tier in {'none','applied','noted'}"""
    t = norm(txt)
    if t == "" or t.startswith("无"):
        return ys, ye, "none"
    if any(b in t.lower() for b in BLOCK):
        return ys, ye, "noted"
    RNG = r'(\d{4})\s*-\s*(\d{4})'
    # A. full range anchored at head
    m = re.match(r'^[\s<>=≤]*' + RNG, t)
    if m:
        return int(m.group(1)), int(m.group(2)), "applied"
    # B. explicit assignment phrase + full range
    m = re.search(r'(?:应为|实际|真实年段|改为|段\s*=|正确年段)[^0-9]{0,8}' + RNG, t)
    if m:
        return int(m.group(1)), int(m.group(2)), "applied"
    # C. start-only correction (no range following)
    m = re.match(r'^(?:入职|起始年?|起点|起于|到任)[约为是应该可提前至\s<>=≤]{0,6}(\d{4})(?!\s*-\s*\d{4})', t)
    if m:
        return int(m.group(1)), ye, "applied"
    # D. end-only correction
    m = re.match(r'^(?:结束年?|year_?end|可延到)[^0-9]{0,14}(\d{4})(?!\s*-\s*\d{4})', t)
    if m:
        return ys, int(m.group(1)), "applied"
    # E. generic: exactly one range in the string, appearing early
    rngs = list(re.finditer(r'(?<!\d)' + RNG + r'(?!\d)', t))
    if len(rngs) == 1 and rngs[0].start() <= 40:
        return int(rngs[0].group(1)), int(rngs[0].group(2)), "applied"
    return ys, ye, "noted"

V["year_start"] = V["year_start"].astype(int)
V["year_end"]   = V["year_end"].astype(int)
def _row_parse(r):
    key = r["school"] + "|" + r["author_id"]
    if key in OVERRIDE:
        ov = OVERRIDE[key]
        if ov is None:
            return (r["year_start"], r["year_end"], "noted")
        return (ov[0], ov[1], "applied")
    return parse_correction(r["year_correction"], r["year_start"], r["year_end"])
res = V.apply(_row_parse, axis=1, result_type="expand")
V["year_start_final"], V["year_end_final"], V["yc_tier"] = res[0], res[1], res[2]
# sanity: never allow start>end
bad = V["year_start_final"] > V["year_end_final"]
V.loc[bad, ["year_start_final", "year_end_final"]] = V.loc[bad, ["year_start", "year_end"]].values
V.loc[bad, "yc_tier"] = "noted"
V["year_changed"] = (V["year_start_final"] != V["year_start"]) | (V["year_end_final"] != V["year_end"])

# ---------- 4. upstream audit (994 baseline) ----------
A = pd.read_csv(f"{BASE}/audit/econ_roster_evidence_audit.csv", dtype=str, keep_default_na=False)
A.columns = [c.strip().lstrip("﻿") for c in A.columns]
A["year_start"] = A["year_start"].astype(int); A["year_end"] = A["year_end"].astype(int)
prior = A[A["human_verified_upstream"].str.lower() == "true"].copy()

# ---------- 5. merged full evidence table ----------
V["dept_key"] = V["school"] + "_econ"
ALL_COLS = ["dept_key","school","author_id","display_name","year_start","year_end",
            "year_start_final","year_end_final","year_changed","yc_tier","verdict",
            "evidence_url","evidence_type","evidence_year","year_correction","id_issue",
            "notes","src_batch"]
V[ALL_COLS].to_csv(OUT_ALL, index=False)

# ---------- 6. rejected ----------
REJ = V[V["verdict"] == "rejected"].copy()
REJ[["dept_key","school","author_id","display_name","year_start","year_end",
     "evidence_url","evidence_type","evidence_year","id_issue","notes","src_batch"]] \
    .rename(columns={"year_start":"year_start_old","year_end":"year_end_old"}) \
    .to_csv(OUT_REJ, index=False)

# ---------- 7. gold roster parquet ----------
keep = V[V["verdict"] != "rejected"].copy()
gold = pd.DataFrame({
    "dept_key": keep["dept_key"],
    "school":   keep["school"],
    "author_id":keep["author_id"],
    "year_start": keep["year_start_final"].astype("int64"),
    "year_end":   keep["year_end_final"].astype("int64"),
    "evidence":   keep["evidence_type"].replace("", "unspecified"),
    "confidence": keep["verdict"].map({"confirmed":"high","uncertain":"low"}),
    "human_verified": keep["verdict"].eq("confirmed"),
    "evidence_url": keep["evidence_url"],
    "year_start_orig": keep["year_start"].astype("int64"),
    "year_end_orig":   keep["year_end"].astype("int64"),
    "year_corrected":  keep["year_changed"],
    "id_issue":   keep["id_issue"],
    "year_note":  keep.apply(lambda r: r["year_correction"] if r["yc_tier"] == "noted" else "", axis=1),
    "verify_source": "batch_human_核 2026-08-09",
})
# prior-verified upstream people (not re-cored in this round)
rej_keys = set(zip(REJ["school"], REJ["author_id"]))
done_keys = set(zip(V["school"], V["author_id"]))
pri = prior[~prior.apply(lambda r: (r["school"], r["author_id"]) in done_keys, axis=1)].copy()
gold_prior = pd.DataFrame({
    "dept_key": pri["school"] + "_econ",
    "school": pri["school"], "author_id": pri["author_id"],
    "year_start": pri["year_start"].astype("int64"),
    "year_end": pri["year_end"].astype("int64"),
    "evidence": pri["evidence_upstream"].replace("", "unspecified"),
    "confidence": pri["confidence_upstream"].replace("", "medium"),
    "human_verified": True,
    "evidence_url": "",
    "year_start_orig": pri["year_start"].astype("int64"),
    "year_end_orig": pri["year_end"].astype("int64"),
    "year_corrected": False,
    "id_issue": "",
    "year_note": "",
    "verify_source": "upstream_prior_人核(未在本轮重核)",
})
GOLD = pd.concat([gold, gold_prior], ignore_index=True).sort_values(["dept_key","author_id"]).reset_index(drop=True)
# normalise confidence: compound upstream strings -> weakest level (conservative)
ORD = {"low": 0, "medium": 1, "high": 2}
def conf_norm(s):
    parts = [p.strip().lower() for p in str(s).split("|") if p.strip().lower() in ORD]
    if not parts:
        return "medium"
    return min(parts, key=lambda p: ORD[p])
GOLD["confidence"] = GOLD["confidence"].map(conf_norm)
GOLD["id_issue"] = GOLD["id_issue"].fillna("").astype(str).str.strip()
GOLD.loc[GOLD["id_issue"].str.startswith("无"), "id_issue"] = ""
# same-person-split-across-two-author_ids, flagged by the human-core batches
DUP_PERSON = {"A5110361967": "same person as A5110739859",
              "A5110739859": "same person as A5110361967 (primary id; suggest dropping this row)",
              "A5047755944": "same person as A5120916839",
              "A5120916839": "same person as A5047755944 (primary id; suggest merging)"}
GOLD["dup_person_flag"] = GOLD["author_id"].map(DUP_PERSON).fillna("")
GOLD.to_parquet(OUT_PQ, index=False)

# ---------- 8. stats ----------
def pct(a,b): return round(100*a/b,1) if b else 0.0
by = V.groupby("school")["verdict"].value_counts().unstack(fill_value=0)
for c in ["confirmed","rejected","uncertain"]:
    if c not in by: by[c]=0
by["n_cored"]=by[["confirmed","rejected","uncertain"]].sum(axis=1)
by["acc%"]=by.apply(lambda r: pct(r["confirmed"],r["n_cored"]),axis=1)
by["rej%"]=by.apply(lambda r: pct(r["rejected"],r["n_cored"]),axis=1)
base = A.groupby("school").size().rename("old_total")
newn = GOLD.groupby("school").size().rename("new_total")
by = by.join(base).join(newn)
by["delta"] = by["new_total"]-by["old_total"]
by = by[["n_cored","confirmed","rejected","uncertain","acc%","rej%","old_total","new_total","delta"]]
by = by.sort_values("n_cored", ascending=False)

yc = V[V["year_changed"] & (V["verdict"] != "rejected")].copy()
yc["d_start"]=(yc["year_start_final"]-yc["year_start"]).abs()
yc["d_end"]=(yc["year_end_final"]-yc["year_end"]).abs()
yc["d_max"]=yc[["d_start","d_end"]].max(axis=1)
idi = V[(V["id_issue"].str.strip()!="") & (~V["id_issue"].str.strip().str.startswith("无"))]

stats = {
 "n_cored": int(len(V)),
 "confirmed": int((V.verdict=="confirmed").sum()),
 "rejected": int((V.verdict=="rejected").sum()),
 "uncertain": int((V.verdict=="uncertain").sum()),
 "acc_pct": pct((V.verdict=="confirmed").sum(), len(V)),
 "rej_pct": pct((V.verdict=="rejected").sum(), len(V)),
 "unc_pct": pct((V.verdict=="uncertain").sum(), len(V)),
 "yc_nonempty": int(((V.year_correction.str.strip()!="") & (~V.year_correction.str.strip().str.startswith("无"))).sum()),
 "yc_applied_all": int(V.year_changed.sum()),
 "yc_applied": int(len(yc)),
 "yc_noted_only": int((V.yc_tier=="noted").sum()),
 "yc_noted_only_keep": int(((V.yc_tier=="noted") & (V.verdict!="rejected")).sum()),
 "yc_mean_abs_shift": round(float(yc["d_max"].mean()),1) if len(yc) else 0,
 "yc_median_abs_shift": float(yc["d_max"].median()) if len(yc) else 0,
 "yc_max_abs_shift": int(yc["d_max"].max()) if len(yc) else 0,
 "yc_ge5": int((yc["d_max"]>=5).sum()) if len(yc) else 0,
 "id_issue_n": int(len(idi)),
 "old_total": int(len(A)),
 "new_total": int(len(GOLD)),
 "gold_human_verified": int(GOLD.human_verified.sum()),
 "gold_low_conf": int((GOLD.confidence=="low").sum()),
}
print(json.dumps(stats, ensure_ascii=False, indent=1))
print()
print(by.to_string())
print()
print("=== YEAR CORRECTIONS APPLIED (top by shift) ===")
print(yc.sort_values("d_max",ascending=False)[["school","display_name","year_start","year_end",
      "year_start_final","year_end_final","d_max","year_correction"]].head(60).to_string())
by.to_csv("/private/tmp/removed-session-directory/by_school.csv")
yc.to_csv("/private/tmp/removed-session-directory/yc_applied.csv", index=False)
V[V.yc_tier=="noted"].to_csv("/private/tmp/removed-session-directory/yc_noted.csv", index=False)
json.dump(stats, open("/private/tmp/removed-session-directory/stats.json","w"), ensure_ascii=False, indent=1)
