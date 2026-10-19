#!/usr/bin/env python3
"""75_prefetch_star_works.py A5xxx [A5yyy ...] — prefetch the full works cache for new candidate stars (same format as 40_star_merge_screen.star_works)"""
import json, os, re, sys, time, urllib.request
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = f"{BASE}/data/_star_works_cache"; os.makedirs(CACHE, exist_ok=True)
KEY = ""
for line in open(os.path.expanduser("~/.zshrc"), errors="ignore"):
    m = re.search(r'OPENALEX_API_KEY=["\']?([^"\'\s]+)', line)
    if m: KEY = m.group(1); break
if not KEY: sys.exit("FATAL: no OPENALEX_API_KEY")
def get(url, tries=6):
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=90) as r: return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 503): time.sleep(5*(i+1)); continue
            raise
        except Exception: time.sleep(3*(i+1))
    raise RuntimeError(url)
for aid in sys.argv[1:]:
    p = f"{CACHE}/{aid}.json"
    if os.path.exists(p): print("cached", aid); continue
    rows, cur = [], "*"
    while True:
        d = get(f"https://api.openalex.org/works?filter=author.id:{aid}&per-page=200&cursor={cur}&api_key={KEY}&select=id,doi,publication_year,type,authorships")
        for w in d["results"]:
            rows.append({"work_id": w["id"].rsplit("/",1)[-1],
                "doi": (w.get("doi") or "").lower().replace("https://doi.org/",""),
                "year": w.get("publication_year"),
                "authors": [a["author"]["id"].rsplit("/",1)[-1] for a in w.get("authorships",[]) if (a.get("author") or {}).get("id")],
                "insts": sorted({i for a in w.get("authorships",[]) if ((a.get("author") or {}).get("id") or "").rsplit("/",1)[-1]==aid for i in (a.get("raw_affiliation_strings") or [])})})
        cur = d["meta"].get("next_cursor")
        if not cur: break
        time.sleep(0.25)
    json.dump(rows, open(p,"w")); print("fetched", aid, len(rows))
