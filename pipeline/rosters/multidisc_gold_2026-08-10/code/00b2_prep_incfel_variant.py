# Add a third tier, incfel = include ∪ the "academic" members of ambiguous (fellow-type titles + a title printed only as Dr),
# dropping the clearly non-academic ones in ambiguous (administrative/laboratory/teaching assistant/Honours/Visitor/honorific without a degree/Research staff/Officer).
# Reason: the economics population already includes research fellows (and adds fellows from ARC grant records) — this is the tier that is "identical to economics".
import re, csv, json, os
import duckdb, pandas as pd
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
ROOT=str(_sar_staged(_sar_legacy_thesis()))
G=f"{ROOT}/v2_output/multidisc_gold_2026-08-10"
VER=f"{ROOT}/v2_output/multidisc_roster_econ_grade_2026-08-09/verify/chemmath_roster_verified_all.csv"
GOLD=f"{ROOT}/v2_output/multidisc_roster_econ_grade_2026-08-09/roster_clean_chemmath_verified.parquet"
COLLECT=f"{ROOT}/v2_output/multidisc_roster_econ_grade_2026-08-09/collect"

KEEP = re.compile(r"\bfellow", re.I)              # Research/Senior/ARC DECRA/Future/Professorial/Principal Fellow
KEEP_BARE = re.compile(r"^(dr\.?|prof\.?|professor|a/?prof\.?)$", re.I)
DROP = re.compile(r"administrat|laborator|lab assistant|teaching assistant|honours|visitor|visiting|"
                  r"technician|technical|workshop|secretar|reception|^m(r|s|rs|iss)\.?$|"
                  r"research staff|research officer|student|casual", re.I)

def academic(title):
    parts=[p.strip() for p in re.split(r"[;|]", str(title or "")) if p.strip()]
    if not parts: return False, "无职称"
    if any(KEEP.search(p) for p in parts): return True, "fellow系"
    if any(DROP.search(p) for p in parts): return False, "非学术"
    if any(KEEP_BARE.match(p) for p in parts): return True, "仅Dr/Prof"
    return False, "其他"

con=duckdb.connect()
# The 41 events: take the title from the full manually verified table
rows=list(csv.DictReader(open(VER)))
tcol = "titles" if "titles" in rows[0] else ("title" if "title" in rows[0] else None)
amb_keep=set(); stats={}
for r in rows:
    if r.get("rank_tag")!="ambiguous": continue
    ok,why=academic(r.get(tcol) if tcol else "")
    stats[why]=stats.get(why,0)+1
    if ok and r.get("author_id"): amb_keep.add((r.get("dept_key"), r["author_id"]))
print("verdicts on the ambiguous rows of 41 events:", stats, "→ kept", len(amb_keep), "(department, person) pairs")

base=con.execute(f"""SELECT dept_key, school, author_id, CAST(year_start AS BIGINT) year_start,
  CAST(year_end AS BIGINT) year_end, field, rank_tag FROM read_parquet('{GOLD}')
  WHERE author_id IS NOT NULL AND author_id <> ''""").df()
mask = base.rank_tag.eq("include") | base.apply(
    lambda r: r.rank_tag=="ambiguous" and (r.dept_key, r.author_id) in amb_keep, axis=1)
sub = base[mask]

# The two new events: use the title from the collect CSV directly
extra=[]
NEW={"A5109260299:monash":("monash_chem","monash","chemistry"),
     "A5100398634:sydney":("sydney_chem","sydney","chemistry")}
newstat={}
for ev,(dk,sch,fld) in NEW.items():
    for r in csv.DictReader(open(f"{COLLECT}/{ev}/openalex_match_{ev}.csv")):
        aid=(r.get("author_id") or "").strip()
        if not aid: continue
        if r["rank_tag"]=="include": ok=True
        elif r["rank_tag"]=="ambiguous":
            ok,why=academic(r.get("title")); newstat[why]=newstat.get(why,0)+1
        else: ok=False
        if ok:
            y=int(str(r["snapshot_ts"])[:4])
            extra.append({"dept_key":dk,"school":sch,"author_id":aid,"year_start":y,"year_end":y,"field":fld})
print("verdicts on the ambiguous rows of the 2 new events:", newstat, "→ total kept", len(extra), "rows")

os.makedirs(f"{G}/data/incfel", exist_ok=True)
allrows=pd.concat([sub[["dept_key","school","author_id","year_start","year_end","field"]],
                   pd.DataFrame(extra)], ignore_index=True)
con.register("allr", allrows)
for field in ("chemistry","math_stats"):
    p=f"{G}/data/incfel/roster_gold_{field}.parquet"
    con.execute(f"""COPY (SELECT dept_key, school, author_id, min(year_start) year_start,
      max(year_end) year_end FROM allr WHERE field='{field}'
      GROUP BY dept_key, school, author_id ORDER BY author_id) TO '{p}' (FORMAT PARQUET)""")
    n,ppl=con.execute(f"SELECT count(*), count(DISTINCT author_id) FROM read_parquet('{p}')").fetchone()
    print(f"[incfel] {field}: {n} spells / {ppl} people")
# config
for field in ("chemistry","math_stats"):
    cfg=json.load(open(f"{G}/config/inc_{field}.json"))
    cfg["label"]=cfg["label"].replace("人群档=inc：include（讲师级以上全职，对齐签字闸门）",
        "人群档=incfel：include ∪ ambiguous 中的学术型（fellow 系列 + 仅印 Dr/Prof），剔行政/实验室/教学助理/Honours/Visitor/Research staff·Officer —— 对齐经济（经济人群含 research fellow）")
    cfg["roster_variant"]="incfel"
    cfg["roster"]["path"]=f"{G}/data/incfel/roster_gold_{field}.parquet"
    cfg["run_dir"]=f"{G}/runs/incfel/{field}"
    json.dump(cfg, open(f"{G}/config/incfel_{field}.json","w"), ensure_ascii=False, indent=2)
print("configs written")
