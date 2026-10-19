# -*- coding: utf-8 -*-
"""econ roster, every member manually verified — evidence audit + batch split (reads upstream only, writes only econ_roster_verify_2026-08-09/)"""
import json, os, unicodedata, collections
import pandas as pd

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
SSD = str(_sar_rd(_sar_ssd_root()) / "derived/u0p5_roster")
PROD = str(_sar_rd(_sar_legacy_thesis()) / "v2_output/explore_within_dept_2026-07-20/data/roster_clean_11school.parquet")
OUT = str(_sar_staged(_sar_legacy_thesis() / "v2_output/econ_roster_verify_2026-08-09"))

NINE = ["adelaide", "anu", "deakin", "macquarie", "melbourne", "sydney", "uq", "uts", "uwa"]
TWO = ["monash", "unsw"]


def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace("-", " ").replace(".", " ").replace("'", "")
    return " ".join(s.split())


prod = pd.read_parquet(PROD)
print("prod rows", len(prod), "unique author_id", prod.author_id.nunique())

ups = []
for s in NINE:
    d = pd.read_parquet(f"{SSD}/registry_v5_2026-07-20/dept_roster_panel_{s}.parquet")
    d["up_file"] = f"registry_v5_2026-07-20/dept_roster_panel_{s}.parquet"
    ups.append(d)
for s in TWO:
    d = pd.read_parquet(f"{SSD}/roster_v4_2026-07-16/dept_roster_panel_{s}.parquet")
    d["up_file"] = f"roster_v4_2026-07-16/dept_roster_panel_{s}.parquet"
    ups.append(d[["dept_key", "author_id", "display_name", "year_start", "year_end",
                  "evidence", "confidence", "human_verified", "up_file"]])
up = pd.concat(ups, ignore_index=True)
up["evi_head"] = up.evidence.fillna("").str.split("|").str[0].str.split(";").str[0].str[:40]


def hv_kind(ev):
    ev = ev or ""
    if "|hv:" in ev:
        return "2026-07-12 系边界裁决(作者只判'算不算经济系', 未核 author_id)"
    if "hv_web:" in ev:
        return "hv_web 逐人网页核验(在编/访客/学生判定, UQ 批 2026-07-11)"
    if "human_verified_web:" in ev:
        return "human_verified_web 逐人 CV/ORCID/Wayback 核验"
    return "hv 标记无注释来源(monash/unsw 老名册遗留标记, 上游自己都记了'hv来源存疑')"


up["hv_kind"] = up.evidence.map(hv_kind)
print("upstream rows", len(up))

amap = json.load(open(f"{SSD}/registry_v5_2026-07-20/_assigned_map.json"))
# key = dept_key|display_name (exact, as written by step0_registry_v5.py)
amap_norm = {}
for k, v in amap.items():
    dept, name = k.split("|", 1)
    amap_norm.setdefault((dept, norm(name)), v)

SRC_LABEL = {
    "high": "v5_auto_high(机器名字匹配高置信候选,未经人眼)",
}


def id_source_for(row):
    dk, nm, up_file = row["dept_key"], row["display_name"], row["up_file"]
    if up_file.startswith("roster_v4"):
        return "roster_v4_chain(monash/unsw 老名册链: 官方名册/中心名册/署名年 + T3换号修号)"
    hit = amap_norm.get((dk, norm(nm)))
    if hit:
        src, status = hit.get("src"), hit.get("status")
        if src == "high":
            return "v5_auto_high(机器名字匹配高置信候选,无人眼复核)"
        if src.endswith("cand"):
            return f"v5_fallback_cand:{src}(该核验片报告截断→回落机器候选,无人眼复核)"
        return f"v5_chunk_verdict:{src}(agent核验片定案配号)"
    # not in assigned map -> id pre-existed in registry_v3 (uq pilot) or propagated by same-name
    return "v3_preexisting/propagated(registry_v3 既有配号或同系同名顺延,多为 UQ raw_affil_year)"


up["id_source"] = up.apply(id_source_for, axis=1)

# ---- join production rows to upstream ----
up["ys_i"] = up.year_start
up["ye_i"] = up.year_end
key4 = up.dropna(subset=["author_id", "ys_i", "ye_i"]).copy()
key4["ys_i"] = key4.ys_i.astype(int)
key4["ye_i"] = key4.ye_i.astype(int)

m = prod.merge(
    key4[["dept_key", "author_id", "ys_i", "ye_i", "display_name", "evidence", "evi_head",
          "hv_kind", "confidence", "human_verified", "id_source", "up_file"]],
    left_on=["dept_key", "author_id", "year_start", "year_end"],
    right_on=["dept_key", "author_id", "ys_i", "ye_i"], how="left")
print("prod rows after 4-key join:", len(m), " unmatched:", m.display_name.isna().sum())

# fallback: (dept_key, author_id) only
miss = m.display_name.isna()
if miss.any():
    fb = (key4.sort_values(["dept_key", "author_id"])
          .groupby(["dept_key", "author_id"], as_index=False).first())
    f = m.loc[miss, ["dept_key", "author_id"]].merge(
        fb[["dept_key", "author_id", "display_name", "evidence", "evi_head", "hv_kind",
            "confidence", "human_verified", "id_source", "up_file"]],
        on=["dept_key", "author_id"], how="left")
    for c in ["display_name", "evidence", "evi_head", "hv_kind", "confidence",
              "human_verified", "id_source", "up_file"]:
        m.loc[miss, c] = f[c].values
    print("after fallback join, still unmatched:", m.display_name.isna().sum())

m["human_verified"] = m["human_verified"].fillna(False).astype(bool)

# ---- collapse to person level (994) ----
rows = []
for aid, g in m.groupby("author_id"):
    # primary school = most person-years in production roster
    g = g.copy()
    g["span"] = g.year_end - g.year_start + 1
    sch_span = g.groupby("school")["span"].sum().sort_values(ascending=False)
    primary = sorted(sch_span[sch_span == sch_span.max()].index)[0]
    names = [x for x in g.display_name.dropna().unique().tolist()]
    hv = bool(g.human_verified.any())
    evid = sorted(set(g.evi_head.dropna().tolist()))
    conf = sorted(set(g.confidence.dropna().tolist()))
    idsrc = sorted(set(g.id_source.dropna().tolist()))
    spells = "; ".join(f"{r.school} {r.year_start}-{r.year_end}"
                       for r in g.sort_values(["school", "year_start"]).itertuples())
    multi = g.school.nunique() > 1

    reason_bits = []
    if hv:
        hv_rows = g[g.human_verified]
        hv_evi = sorted(set(hv_rows.evi_head.dropna().tolist()))
        hv_kinds = sorted(set(hv_rows.hv_kind.dropna().tolist()))
        auto_id = any(("v5_auto_high" in s) or ("fallback_cand" in s) or
                      ("preexisting" in s) for s in hv_rows.id_source.dropna())
        reason_bits.append("上游 human_verified=True; 人核类型=" + " / ".join(hv_kinds) +
                           "; 证据=" + ",".join(hv_evi))
        if auto_id:
            reason_bits.append("注意: author_id 仍是机器配号, 配号本身未经人核")
    else:
        reason_bits.append("上游 human_verified=False — 从未人核")
        if any("v5_auto_high" in s for s in idsrc):
            reason_bits.append("author_id=机器名字匹配高置信候选, 无人眼确认")
        if any("fallback_cand" in s for s in idsrc):
            reason_bits.append("author_id=核验片报告截断后回落机器候选, 风险最高")
        if any("chunk_verdict" in s for s in idsrc):
            reason_bits.append("author_id 经 agent 核验片定案, 但作者本人未过目")
        if any("roster_v4_chain" in s for s in idsrc):
            reason_bits.append("monash/unsw 老名册链, 该行未标 hv")
        if any("preexisting" in s for s in idsrc):
            reason_bits.append("author_id 为 registry_v3 既有/同名顺延, 来源为 OpenAlex 署名机构串")
    if multi:
        reason_bits.append(f"跨校多段: {spells}")
    if not names:
        reason_bits.append("上游查不到 display_name(join 未命中)")

    rows.append(dict(
        school=primary,
        author_id=aid,
        display_name=names[0] if names else "",
        year_start=int(g.year_start.min()),
        year_end=int(g.year_end.max()),
        evidence_upstream="|".join(evid) if evid else "查不到",
        confidence_upstream="|".join(conf) if conf else "查不到",
        human_verified_upstream=hv,
        id_source="|".join(idsrc) if idsrc else "查不到",
        needs_verification="否" if hv else "是",
        reason=" ; ".join(reason_bits),
    ))

aud = pd.DataFrame(rows)
aud = aud.sort_values(["school", "display_name", "author_id"]).reset_index(drop=True)
os.makedirs(f"{OUT}/audit", exist_ok=True)
aud.to_csv(f"{OUT}/audit/econ_roster_evidence_audit.csv", index=False, encoding="utf-8-sig")
print("\naudit rows", len(aud))
print(aud.needs_verification.value_counts().to_string())
print()
print(aud.groupby("school").agg(total=("author_id", "size"),
                                verified=("human_verified_upstream", "sum")).to_string())
print()
print(aud.id_source.str.split("|").str[0].str.split("(").str[0].value_counts().to_string())
print()
print("no display_name:", (aud.display_name == "").sum())
print("evidence not found:", (aud.evidence_upstream == "查不到").sum())

# ---- batches ----
need = aud[aud.needs_verification == "是"].copy()
need = need.sort_values(["school", "display_name", "author_id"]).reset_index(drop=True)
MINB, MAXB = 35, 40
# Walk the school-sorted list once. Cut at 40, or early (>=35) at a school
# boundary so batches stay school-clustered wherever the arithmetic allows.
idx, cuts, cur = list(need.index), [], []
schools = need.school.tolist()
for i, ridx in enumerate(idx):
    if cur and len(cur) >= MINB and schools[i] != schools[i - 1]:
        cuts.append(cur); cur = []
    elif len(cur) == MAXB:
        cuts.append(cur); cur = []
    cur.append(ridx)
if cur:
    cuts.append(cur)
# tail shorter than MINB: pull people back from earlier batches that have slack
while len(cuts) > 1 and len(cuts[-1]) < MINB:
    donor = None
    for j in range(len(cuts) - 2, -1, -1):
        if len(cuts[j]) > MINB:
            donor = j; break
    if donor is None:
        break
    cuts[donor + 1].insert(0, cuts[donor].pop())
    if donor + 1 != len(cuts) - 1:      # ripple the shift down to the tail
        for j in range(donor + 1, len(cuts) - 1):
            cuts[j + 1].insert(0, cuts[j].pop())
final = [need.loc[c].copy() for c in cuts]

os.makedirs(f"{OUT}/batches", exist_ok=True)
files = []
for i, b in enumerate(final, 1):
    p = f"{OUT}/batches/batch_{i:02d}.csv"
    b.to_csv(p, index=False, encoding="utf-8-sig")
    files.append(p)
    print(f"batch_{i:02d}  n={len(b):3d}  schools={dict(b.school.value_counts())}")

assert sum(len(b) for b in final) == len(need), "batch total mismatch"
print("\ntotal batched", sum(len(b) for b in final), "of", len(need))

summary = dict(
    total=int(len(aud)),
    already_verified=int((aud.needs_verification == "否").sum()),
    needs_verification=int(len(need)),
    n_batches=len(files),
    batch_files=files,
    by_school={k: dict(total=int(v["total"]), already_verified=int(v["verified"]),
                       needs_verification=int(v["total"] - v["verified"]))
               for k, v in aud.groupby("school").agg(
                   total=("author_id", "size"),
                   verified=("human_verified_upstream", "sum")).iterrows()},
)
json.dump(summary, open(f"{OUT}/audit/_summary.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(summary["by_school"], ensure_ascii=False))
