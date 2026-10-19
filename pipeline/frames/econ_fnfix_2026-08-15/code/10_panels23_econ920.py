#!/usr/bin/env python3
"""10_build_panels23.py — Panel 2 (first tie to the star) + Panel 3 (ties among colleagues), unified-population version (2026-07-31)

Population = the 6,842 (person x star) relations of Panel 1 v9: incumbents of the department ∪ people reachable in the co-authorship network, one panel.

Panel 2 becoming_unified: one row = person x star x year
  y = the first year the two co-write (decided at work level: earliest year of a shared work); out of the sample once co-written;
  relations already co-written before arrival (being) do not enter the risk set (same as the old rule, counted as is).
  Window tau in [-6, +10] (keeps the design of opening a separate clock per star, as fixed in twoworlds).

Panel 3 pairs_unified: one row = two people in the same event x year
  pair = all pairs of the event's exposed population (canonical de-duplicated); y = the first year the two co-write; exit as above;
  y_any removes papers signed by this event's star / y_raw does not (keeps the twoworlds dual result).

Work domain for deciding co-writing (consistent with the 7-23/7-24 supplements):
  u1_full_11school edge table (person_map alias-folded) ∪ supplement133 ∪ stars11 ∪ API-supplemented works.
Self-check gates: zero exit violations / no self-pairs (canonical) / row-count identity / being-count reconciliation.
"""
import glob, json, os, sys
from collections import defaultdict

import duckdb
import pandas as pd

# --- M3 port: repo path resolution (legacy hard-coded the author's machine) — config/paths.yaml ---
import pathlib as _sar_pl, sys as _sar_sys
_sar_repo = next(p for p in _sar_pl.Path(__file__).resolve().parents if p.name == "frames").parents[1]
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
ROOT = str(_sar_rd(_sar_legacy_thesis()))
BASE = os.path.dirname(os.path.abspath(__file__))
SSD = str(_sar_rd(_sar_derived_root()))
PMAP = glob.glob(f"{SSD}/u2_person_map_11school_2026-07-16/person_map/**/*.parquet", recursive=True)
U1E = glob.glob(f"{SSD}/u1_full_11school_2026-07-16/authorship_edges/**/*.parquet", recursive=True)
SUP133 = f"{ROOT}/v2_output/netbase_supplement_2026-07-23/edges_supplement_133.jsonl"
SUP11 = f"{ROOT}/v2_output/netbase_supplement_2026-07-23/edges_supplement_stars11.jsonl"
PATCH_A = str(_sar_legacy_thesis() / "v2_output/econ_final_2026-08-13/patch/works_by_author.jsonl")   # extension package (108+4 people); a silent skip when exists() fails is a trap — the path has been verified to exist
REL = str(_sar_legacy_thesis() / "v2_output/econ_fnfix_2026-08-15/data/relationships.csv")
PRE, POST = 6, 10

con = duckdb.connect(); con.execute("PRAGMA threads=8")
report = {}

# ---------- 1. population: Panel 1 relations -> canonical ----------
rel = pd.read_csv(REL)
rel["star"] = rel.event_id.str.split(":").str[0]
rel["arrival"] = rel.event_id.str.split(":").str[1].astype(int)
bares = sorted(set(rel.pid) | set(rel.star))
con.execute("CREATE TEMP TABLE cb AS SELECT * FROM (VALUES %s) t(bare)"
            % ",".join(f"('{p}')" for p in bares))
cn = con.execute(f"""SELECT n.bare, m.person_id FROM cb n
    JOIN read_parquet({PMAP!r}) m ON m.author_id = n.bare""").df()
canon = dict(zip(cn.bare, cn.person_id))
canon_of = lambda x: canon.get(x, f"P_{x}")
alias = con.execute(f"""
    WITH c AS (SELECT n.bare, m.person_id FROM cb n
               JOIN read_parquet({PMAP!r}) m ON m.author_id = n.bare)
    SELECT c.bare, m2.author_id FROM c
    JOIN read_parquet({PMAP!r}) m2 USING (person_id)""").df()
alias = pd.concat([alias, pd.DataFrame({"bare": [b for b in bares if b not in set(alias.bare)],
                                        "author_id": [b for b in bares if b not in set(alias.bare)]})])
con.register("al", alias)

# ---------- 2. each person's work set (work_id, year): union of four sources ----------
own = con.execute(f"""
    SELECT a.bare pid, e.work_id, min(e.publication_year) yr
    FROM read_parquet({U1E!r}) e JOIN al a ON e.author_id = a.author_id
    WHERE e.publication_year IS NOT NULL GROUP BY 1,2""").df()
works_of = defaultdict(dict)
for r in own.itertuples():
    works_of[r.pid][r.work_id] = int(r.yr)
def _add(pid, wid, yr):
    if yr is None: return
    d = works_of[pid]
    if wid not in d or yr < d[wid]: d[wid] = int(yr)
bare_set = set(bares)
SUP_FNFIX = str(_sar_legacy_thesis() / "v2_output/econ_fnfix_2026-08-15/data/edges_supplement_fnfix.jsonl")
for f in (SUP133, SUP11, SUP_FNFIX):
    for l in open(f):
        d = json.loads(l)
        yr = d.get("publication_year")
        for a in set(d.get("authors") or []) | {d.get("seed_author")}:
            if a in bare_set: _add(a, d["work_id"], yr)
if os.path.exists(PATCH_A):
    for l in open(PATCH_A):
        d = json.loads(l)
        if d["author_id"] in bare_set:
            _add(d["author_id"], d["work_id"], d.get("publication_year"))
        for a in d.get("author_ids") or []:
            if a in bare_set: _add(a, d["work_id"], d.get("publication_year"))
report["works_persons"] = len(works_of)

def first_shared(pa, pb):
    wa, wb = works_of.get(pa), works_of.get(pb)
    if not wa or not wb: return None
    shared = wa.keys() & wb.keys()
    if not shared: return None
    return min(max(wa[w], wb[w]) for w in shared)   # for the one work both persons are on, take that work's year

# star-signed work set (used by Panel 3 for star removal): per event star
star_works = {s: set(works_of.get(s, {})) for s in set(rel.star)}

# ---------- 3. Panel 2: person x star x year ----------
rows2, being2, self2 = [], 0, 0
for r in rel.itertuples():
    if canon_of(r.pid) == canon_of(r.star): self2 += 1; continue
    ft = first_shared(r.pid, r.star)
    if ft is not None and ft < r.arrival - PRE: being2 += 1; continue
    end_tau = POST
    if ft is not None and ft <= r.arrival + POST:
        end_tau = ft - r.arrival
    for tau in range(-PRE, end_tau + 1):
        y = 1 if (ft is not None and r.arrival + tau == ft) else 0
        rows2.append((r.pid, r.star, r.event_id, r.channel, r.arrival + tau, tau,
                      int(tau >= 0), y))
p2 = pd.DataFrame(rows2, columns=["pid", "star", "event_id", "channel", "year",
                                  "tau", "post", "y"])
report["panel2"] = {"rows": len(p2), "relationships": int(p2.groupby(['pid','event_id']).ngroups),
                    "first_ties": int(p2.y.sum()), "being_excluded": being2,
                    "self_excluded": self2}
# exit-violation self-check
v = p2[p2.y == 1].groupby(["pid", "event_id"]).year.min().rename("ty").reset_index()
chk = p2.merge(v, on=["pid", "event_id"], how="inner")
assert (chk[chk.year > chk.ty].shape[0]) == 0, "panel 2: rows remain after the first tie"
p2.to_csv(str(_sar_staged(_sar_legacy_thesis() / "v2_output/econ_fnfix_2026-08-15/data/becoming_unified.csv")), index=False)

# ---------- 4. Panel 3: pairs within an event x year ----------
rows3, being3 = [], 0
for evid, g in rel.groupby("event_id"):
    star = evid.split(":")[0]; arr = int(evid.split(":")[1])
    members = sorted({(canon_of(p), p) for p in g.pid})   # canonical de-duplication, take the lexicographically smallest bare as representative
    seen_c, mem = set(), []
    for c, b in members:
        if c in seen_c or c == canon_of(star): continue
        seen_c.add(c); mem.append(b)
    sw = star_works.get(star, set())
    for i in range(len(mem)):
        for j in range(i + 1, len(mem)):
            a, b = mem[i], mem[j]
            ft = first_shared(a, b)
            if ft is not None and ft < arr - PRE: being3 += 1; continue
            # star-removed first-tie year: remove from the shared works those signed by this event's star
            wa, wb = works_of.get(a, {}), works_of.get(b, {})
            shared = [w for w in wa.keys() & wb.keys()]
            ft_ex = min((max(wa[w], wb[w]) for w in shared if w not in sw), default=None)
            end_tau = POST
            stop = min([x for x in (ft, ft_ex) if x is not None], default=None)
            if stop is not None and stop <= arr + POST:
                end_tau = stop - arr
            for tau in range(-PRE, end_tau + 1):
                yy = arr + tau
                rows3.append((a, b, evid, yy, tau, int(tau >= 0),
                              1 if (ft_ex is not None and yy == ft_ex) else 0,
                              1 if (ft is not None and yy == ft) else 0))
p3 = pd.DataFrame(rows3, columns=["i_id", "j_id", "event_id", "year", "tau", "post",
                                  "y_any", "y_raw"])
report["panel3"] = {"rows": len(p3),
                    "pairs": int(p3.groupby(['i_id','j_id','event_id']).ngroups),
                    "events": int(p3.event_id.nunique()),
                    "first_ties_ex_star": int(p3.y_any.sum()),
                    "first_ties_raw": int(p3.y_raw.sum()),
                    "being_excluded": being3}
p3.to_csv(str(_sar_staged(_sar_legacy_thesis() / "v2_output/econ_fnfix_2026-08-15/data/pairs_unified.csv")), index=False)
json.dump(report, open(str(_sar_staged(_sar_legacy_thesis() / "v2_output/econ_fnfix_2026-08-15/data/panels23_report.json")), "w"), indent=1, default=str)
print(json.dumps(report, indent=1, default=str))
