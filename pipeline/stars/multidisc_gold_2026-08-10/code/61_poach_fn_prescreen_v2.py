#!/usr/bin/env python3
"""61_poach_fn_prescreen_v2.py — machine pre-screen v2 of the false-negative pool (independent of OpenAlex affiliation years, robust to backfill)
Signal = a three-way classification of the person's own raw affiliation on each pre-arrival work: AU-only / joint (AU+overseas) / overseas-only.
  backfill victim (type A5086383420): mostly overseas-only, AU-only≈0 (AU appears only as "joint")
  genuine new arrival from overseas (Yves Zenou type): mostly overseas-only, AU-only few or late
  long-term local (type A5103238089): AU-only many and early, overseas-only≈0
Rule: CHECK = overseas-only>=3 and (AU-only <= 0.5×overseas-only or earliest AU-only year >= arrival-3); everything else is dropped.
Gold cases: A5086383420=CHECK, Yves Zenou=CHECK (if not in the event table), A5103238089=drop.
"""
import json, os, time, urllib.request, urllib.error, csv
K=[l for l in open(os.path.expanduser("~/.zshrc")) if "OPENALEX_API_KEY" in l][0].split("=",1)[1].strip().strip('"\'')
BASE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def get(u,t=5):
    for i in range(t):
        try:
            with urllib.request.urlopen(u,timeout=90) as r: return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429,500,503): time.sleep(4*(i+1)); continue
            raise
        except Exception: time.sleep(2*(i+1))
    return None
AU=("australia","monash","melbourne","sydney","new south wales","queensland","adelaide","western australia","deakin","macquarie","technology sydney","canberra","griffith","tasmania","curtin","rmit","newcastle","wollongong","la trobe","flinders","murdoch","james cook","southern cross","charles darwin","csiro","unsw","anu ")
CACHE=f"{BASE}/data/_poach_profile_cache.json"
cache=json.load(open(CACHE)) if os.path.exists(CACHE) else {}
def profile(aid, arr):
    key=f"{aid}:{arr}"
    if key in cache: return cache[key]
    cur="*"; n_au=n_mx=n_ov=n_none=0; yrs=[]
    while True:
        d=get(f"https://api.openalex.org/works?filter=author.id:{aid},publication_year:<{arr}&per-page=200&cursor={cur}&api_key={K}&select=id,publication_year,authorships")
        if not d: break
        for w in d["results"]:
            mine=[a for a in w.get("authorships",[]) if ((a.get("author") or {}).get("id") or "").endswith(aid)]
            raw=[s.lower() for a in mine for s in (a.get("raw_affiliation_strings") or [])]
            if not raw: n_none+=1; continue
            has_au=any(any(h in s for h in AU) for s in raw); has_ov=any(not any(h in s for h in AU) for s in raw)
            if has_au and has_ov: n_mx+=1
            elif has_au: n_au+=1; yrs.append(w.get("publication_year"))
            else: n_ov+=1
        cur=d["meta"].get("next_cursor")
        if not cur: break
        time.sleep(0.15)
    p={"au_only":n_au,"mixed":n_mx,"ov_only":n_ov,"none":n_none,"au_only_first":min([y for y in yrs if y],default=None)}
    cache[key]=p; return p
def rule(p, arr):
    if p["ov_only"]<3: return "drop_no_overseas_signal"
    if p["au_only"] <= 0.5*p["ov_only"]: return "CHECK"
    if p["au_only_first"] and p["au_only_first"]>=arr-3: return "CHECK"
    return "drop_local_long"
out=[]
for field in ("econ","chemistry","math_stats"):
    rows=list(csv.DictReader(open(f"{BASE}/data/poach_fn_suspects_{field}.csv")))
    for i,r in enumerate(rows):
        p=profile(r["author_id"], int(r["arrival_roster"]))
        out.append({**r, **p, "prescreen":rule(p,int(r["arrival_roster"]))})
        if i%20==0:
            json.dump(cache,open(CACHE,"w")); print(f"  {field} {i}/{len(rows)}",end="\r",flush=True)
json.dump(cache,open(CACHE,"w"))
with open(f"{BASE}/data/poach_fn_prescreen_v2_2026-08-15.csv","w",newline="") as f:
    w=csv.DictWriter(f,fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
from collections import Counter
print()
for field in ("econ","chemistry","math_stats"):
    print(field, dict(Counter(o["prescreen"] for o in out if o["field"]==field)))
b=[o for o in out if o["author_id"]=="A5086383420"]
print("gold-standard case A5086383420:", b[0]["prescreen"] if b else "not in pool")
