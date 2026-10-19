#!/usr/bin/env python3
"""R1 F8: the work-level call sets of B0 (October) and M (instance stage `calls`; the functions import anywhere).

A call is one (author id, work id) pair. Each call set has
  drops          pairs the ranking removes from aw_raw (not this person's work),
  adds           pairs the ranking adds (the 2026-08-13 split-id adds and the works merged ids bring),
  rank_adds      {main id: alias ids} - the id merges the ranking applied,
  dose_excludes  pairs that leave the topic dose.
B0 = October: drops = run_caliber.historical_calls() | october_calls(), adds = the 08-13 split-id adds, and
dose_excludes = {} (October removed no call from the dose; 10-01 report section B).
M = the cleaned works the RK6b ranking used (decision 5, 2026-10-12: works that are not the person's are dropped):
the J1a rank_requests output in6/ (one request list for the ranking and the dose, never recomputed for use)
expanded on aw_raw by rk6b_rank.pass_b_cleaning, the same function RK6b ran. dose_excludes(M) = drops minus
the rows of dose_keep_r1.csv (own book reviews whose citations OpenAlex conflated: the works are the person's,
so they stay in the dose and stay out of the rank) minus every add pair. Both identification choices (the
book-review carve-out; RK4 min_year cuts count as not this person) are the recommended defaults of the
decision sheet (not shipped), not yet signed separately.

Stage `calls` (J1a, after rank_tables): writes drops.csv, dose_excludes.csv, adds.csv (person_id, work_id,
source), rank_adds.json, summary.json (counts and ids only), RESULT.txt. STOPs (exit 1, RESULT.txt STOP):
B0 != the recovered RK1 drops/adds; in6 requests != the paper-check fold of the same inputs; a merge link
half applied; an alias with no works in aw_raw; an add whose work is not in aw_raw; a dose_keep row that is
not one of the person's exclusions; a min_year cut with a non-namesake reason; an adjudication pair on the
wrong side; a paper-checked count other than --expect-paper-checked.
Runs only on an R1 instance ($SAR_HOST), from the copy $WORK/calls_lib.py.
"""
from __future__ import annotations

import argparse
import collections
import csv
import dataclasses
import importlib
import json
import os
import pathlib
import re
import shutil
import sys

AWS_HOSTS = ("ec2-r1-test", "ec2-r1")
AID = re.compile(r"A\d{6,}")
WID = re.compile(r"W\d+")
KEEP_COLS = ["person_id", "work_id", "why", "source"]
OUT_COLS = ["person_id", "work_id", "source"]
#: source tags of a pair (drops.csv / dose_excludes.csv / adds.csv)
S_B0, S_REQ, S_MINY = "october_b0", "request_exclude", "min_year"
S_SPLIT, S_MERGE = "split_id_2026-08-13", "id_merge"
#: a min_year cut must strip a namesake's earlier works; reason fields read from an RK4 request
REASON_KEYS = ("reason", "why", "note", "basis", "status_reason")
NAMESAKE = re.compile(r"namesake|homonym|same[- ]name|同名|another person|other person|different person|wrong person|"
                      r"someone else|not (?:him|her|his|hers|the same|this person)|conflat|merged profile", re.I)


def _rq():
    return importlib.import_module("rk6_requests")


def _rb():
    return importlib.import_module("rk6b_rank")


def stop(msg: str) -> None:
    raise SystemExit("STOP " + msg)


@dataclasses.dataclass(frozen=True)
class CallSet:
    name: str
    drops: frozenset
    adds: frozenset
    rank_adds: dict
    dose_excludes: frozenset
    drop_src: dict = dataclasses.field(default_factory=dict)
    add_src: dict = dataclasses.field(default_factory=dict)
    dose_kept: frozenset = frozenset()
    aliases_without_works: frozenset = frozenset()
    adds_without_work: frozenset = frozenset()


# --- B0 ---------------------------------------------------------------------------------------------------
def b0(rc=None) -> CallSet:
    """October's own call builders, nothing else: the restake inputs of run_caliber (R phase)."""
    if rc is None:
        rc = importlib.import_module("run_caliber")
    hist_drops, hist_adds, _ = rc.historical_calls()
    oct_drops, _ = rc.october_calls()
    drops = frozenset(set(hist_drops) | set(oct_drops))
    adds = frozenset(hist_adds)
    return CallSet("B0", drops, adds, {}, frozenset(), {p: frozenset({S_B0}) for p in drops},
                   {p: frozenset({S_SPLIT}) for p in adds})


def _diff_ids(a, b) -> str:
    d = sorted(set(a) ^ set(b))
    return f"{len(d)} pairs, e.g. " + " ".join(f"{x} {y}" for x, y in d[:5])


def b0_control(cs: CallSet, rk1_drops, rk1_adds) -> None:
    """B0 must equal the inputs of the 10-02 RK1 run that reproduced all 187 October percentiles (as sets)."""
    if set(cs.drops) != set(rk1_drops):
        stop(f"B0 drops differ from RK1 drops.csv: {_diff_ids(cs.drops, rk1_drops)}")
    if set(cs.adds) != set(rk1_adds):
        stop(f"B0 adds differ from RK1 adds.csv: {_diff_ids(cs.adds, rk1_adds)}")


# --- inputs -----------------------------------------------------------------------------------------------
def read_csv(p) -> list:
    with open(p, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def fold_requests(merged_csv, rk4_requests, paper_checks, works_dir) -> tuple:
    """rk6_requests' own fold (requests_from_merged on the paper checks), with the checks parsed once.
    Used only to prove in6 is that fold; the stage consumes in6 itself."""
    rq = _rq()
    checks = rq.load_paper_checks(paper_checks, works_dir)
    reqs, skipped = rq.requests_from_merged(read_csv(merged_csv), rq.prior_cleaning(rk4_requests), checks)
    return reqs, skipped, checks


def load_dose_keep(p) -> list:
    rows = read_csv(p)
    with open(p, encoding="utf-8", newline="") as fh:
        head = next(csv.reader(fh), [])
    if head != KEEP_COLS:
        stop(f"dose_keep header {head} is not {KEEP_COLS}")
    for r in rows:
        if not AID.fullmatch(r["person_id"]) or not WID.fullmatch(r["work_id"]) or not r["why"].strip() or not r["source"].strip():
            stop(f"dose_keep row malformed: {r['person_id']} {r['work_id']}")
    seen = collections.Counter((r["person_id"], r["work_id"]) for r in rows)
    dup = sorted(k for k, n in seen.items() if n > 1)
    if dup:
        stop(f"dose_keep row twice: {dup[0][0]} {dup[0][1]}")
    return rows


def merge_links(overrides_csv, fixes_csv, add_list_json) -> list:
    """(main, alias, source) for every signed id merge: person_overrides merge_ids, fixes_1001 merge_ids and the
    multi-id ACCEPT rows of the add list. They reach the ranking through candidates_merged all_ids; check_links
    proves they did."""
    out = []
    for r in read_csv(overrides_csv):
        if r["action"] == "merge_ids":
            out += [(r["author_id"], x, "person_overrides") for x in r["value"].split("|") if x]
    for r in read_csv(fixes_csv):
        if r["fix"] == "merge_ids":
            out += [(r["author_id"], x, "fixes_1001") for x in r["value"].split("|") if x]
    rows = json.loads(pathlib.Path(add_list_json).read_text(encoding="utf-8"))["rows"]
    for r in rows:
        ids = [x for x in str(r.get("all_ids") or "").split("|") if x]
        if r.get("verdict") == "ACCEPT" and len(ids) > 1:
            out += [(r["person_id"], x, "add_list") for x in ids if x != r["person_id"]]
    bad = [x for a, b, _ in out for x in (a, b) if not AID.fullmatch(x)]
    if bad:
        stop(f"merge link with a malformed id: {bad[0]}")
    return sorted(set(out))


def check_links(requests, links) -> list:
    """Every link is inside one request's ids, or neither id is ranked (returned, for the summary). A link with
    one id ranked and the other missing is a STOP. Requests ranked on corrected ids are exempt (the paper checks
    replaced the ids)."""
    groups = [set(q["ids"]) for q in requests if not q.get("id_corrected")]
    corrected = {i for q in requests if q.get("id_corrected") for i in (q["person"], *q["ids"])}
    unranked = set()
    for a, b, src in links:
        if a in corrected or b in corrected or any(a in g and b in g for g in groups):
            continue
        if any(a in g or b in g for g in groups):
            stop(f"merge link not in the rank requests: {a} {b} ({src})")
        unranked.add(a)
    return sorted(unranked)


def check_min_year(rk4_requests) -> dict:
    """RK4 min_year cuts count as not this person only if they strip a namesake: a cut whose
    reason says something else STOPs; a cut with no reason text is listed."""
    out = {"namesake": set(), "no_reason": set()}
    bad = []
    for r in rk4_requests:
        if not (r.get("cleaning") and r.get("min_year")):
            continue
        pid = r["ids"][0]
        text = " ".join(str(r.get(k) or "") for k in REASON_KEYS).strip()
        if not text:
            out["no_reason"].add(pid)
        elif NAMESAKE.search(text):
            out["namesake"].add(pid)
        else:
            bad.append(pid)
    if bad:
        stop("min_year cut without a namesake reason: " + " ".join(sorted(set(bad))))
    return {k: sorted(v) for k, v in out.items()}


# --- M ----------------------------------------------------------------------------------------------------
def rank_adds_from_requests(requests) -> dict:
    out = collections.defaultdict(set)
    owner = {}
    for q in requests:
        main = q["ids"][0]
        for a in q["ids"][1:]:
            if owner.setdefault(a, main) != main:
                stop(f"alias under two main ids: {a} {owner[a]} {main}")
            out[main].add(a)
    clash = sorted(set(out) & set(owner))
    if clash:
        stop(f"an id is both a main id and an alias: {clash[0]}")
    return {k: tuple(sorted(v)) for k, v in sorted(out.items())}


def expand(con, cs: CallSet) -> tuple:
    """(merged aliases with no works in aw_raw, add pairs whose work is not in aw_raw): both add nothing, in the
    ranking as here (its pass B reads aw_raw; restake_with_adds joins an add to aw_raw on its work id)."""
    aliases = sorted({a for v in cs.rank_adds.values() for a in v})
    con.execute("CREATE OR REPLACE TEMP TABLE calls_alias(aid VARCHAR)")
    if aliases:
        con.executemany("INSERT INTO calls_alias VALUES (?)", [(a,) for a in aliases])
    miss = [r[0] for r in con.execute("SELECT aid FROM calls_alias a WHERE NOT EXISTS "
                                      "(SELECT 1 FROM aw_raw r WHERE r.aid = a.aid) ORDER BY aid").fetchall()]
    no_works = miss
    con.execute("CREATE OR REPLACE TEMP TABLE calls_add(aid VARCHAR, wid VARCHAR)")
    if cs.adds:
        con.executemany("INSERT INTO calls_add VALUES (?,?)", sorted(cs.adds))
    miss = con.execute("SELECT aid, wid FROM calls_add a WHERE NOT EXISTS "
                       "(SELECT 1 FROM aw_raw r WHERE r.wid = a.wid) ORDER BY aid, wid").fetchall()
    return no_works, [tuple(r) for r in miss]


def _ids_of(requests, pid) -> set:
    out = {pid}
    for q in requests:
        if q["person"] == pid or pid in q["ids"]:
            out |= {q["person"], *q["ids"]}
    return out


def m(base: CallSet, requests, con, keep_rows=(), links=(), dose_on=True) -> CallSet:
    """M = base (B0) + the in6 requests expanded on aw_raw exactly as RK6b pass B did."""
    rb = _rb()
    check_links(requests, links)
    rank_adds = rank_adds_from_requests(requests)
    xd, xa = rb.pass_b_cleaning(con, requests, set(base.drops))
    # the min_year part alone (same function, requests stripped to their cut), for the source tags
    cuts = [{"ids": q["ids"], "min_year": q["min_year"]} for q in requests if q.get("min_year")]
    my = rb.pass_b_cleaning(con, cuts, set())[0] if cuts else set()
    req_ex = {(a, w) for q in requests for a in q["ids"] for w in q.get("exclude_wids") or []}
    drops = frozenset(set(base.drops) | xd)
    adds = frozenset(set(base.adds) | xa)
    dsrc = collections.defaultdict(set)
    for p in drops:
        if p in base.drops:
            dsrc[p] |= set(base.drop_src.get(p, {S_B0}))
        if p in req_ex:
            dsrc[p].add(S_REQ)
        if p in my:
            dsrc[p].add(S_MINY)
    asrc = collections.defaultdict(set)
    for p in adds:
        if p in base.adds:
            asrc[p] |= set(base.add_src.get(p, {S_SPLIT}))
        if p in xa:
            asrc[p].add(S_MERGE)
    kept = set()
    for r in keep_rows:
        pid, w = r["person_id"], r["work_id"]
        hits = {(a, w) for a in _ids_of(requests, pid) if (a, w) in drops}
        if not hits:
            stop(f"dose_keep row not among the person's exclusions: {pid} {w}")
        kept |= hits
    alias_of = {a: main for main, al in rank_adds.items() for a in al}
    merged_pairs = {(a, w) for a, w in drops if a in alias_of and (alias_of[a], w) in adds}
    dose = frozenset(drops - kept - adds - merged_pairs) if dose_on else frozenset()
    cs = CallSet("M", drops, adds, rank_adds, dose, {p: frozenset(v) for p, v in dsrc.items()},
                 {p: frozenset(v) for p, v in asrc.items()}, frozenset(kept) if dose_on else frozenset())
    no_works, no_work = expand(con, cs)
    return dataclasses.replace(cs, aliases_without_works=frozenset(no_works), adds_without_work=frozenset(no_work))


# --- gates ------------------------------------------------------------------------------------------------
def gate_adjudication(cs: CallSet, requests, adjudication) -> dict:
    """The 2026-10-11 adjudication (when in doubt, a pair is not kept): every 'exclude' pair leaves the dose, no 'keep' pair does."""
    n = collections.Counter()
    for w in adjudication["works"]:
        pid, wid, final = w["person_id"], w["wid"], w["final"]
        inside = any((a, wid) in cs.dose_excludes for a in _ids_of(requests, pid))
        if final == "exclude" and not inside:
            stop(f"adjudication 'exclude' not in dose_excludes: {pid} {wid}")
        if final == "keep" and inside:
            stop(f"adjudication 'keep' in dose_excludes: {pid} {wid}")
        if final not in ("exclude", "keep"):
            stop(f"adjudication final {final!r}: {pid} {wid}")
        n[final] += 1
    return dict(sorted(n.items()))


def gate_paper_checked(checks, requests, skipped, expect: int) -> int:
    if len(checks) != expect:
        stop(f"paper-checked persons {len(checks)}, expected {expect}")
    ranked = {q["person"] for q in requests} | set(skipped)
    miss = sorted(set(checks) - ranked)
    if miss:
        stop("paper-checked person neither ranked nor skipped: " + " ".join(miss))
    return len(checks)


# --- output -----------------------------------------------------------------------------------------------
def _write_pairs(p, pairs, src) -> None:
    with open(p, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(OUT_COLS)
        for a, wid in sorted(pairs):
            w.writerow([a, wid, "|".join(sorted(src.get((a, wid), ())))])


def write_outputs(cs: CallSet, out, ids=None, counts=None) -> dict:
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    _write_pairs(out / "drops.csv", cs.drops, cs.drop_src)
    _write_pairs(out / "dose_excludes.csv", cs.dose_excludes, cs.drop_src)
    _write_pairs(out / "adds.csv", cs.adds, cs.add_src)
    (out / "rank_adds.json").write_text(json.dumps({k: list(v) for k, v in sorted(cs.rank_adds.items())},
                                                   indent=1, sort_keys=True) + "\n", encoding="utf-8")
    by_src = collections.Counter(t for p in cs.drops for t in cs.drop_src.get(p, ()))
    add_src = collections.Counter(t for p in cs.adds for t in cs.add_src.get(p, ()))
    c = {"drops": len(cs.drops), "dose_excludes": len(cs.dose_excludes), "adds": len(cs.adds),
         "dose_kept": len(cs.dose_kept), "rank_add_mains": len(cs.rank_adds),
         "rank_add_aliases": sum(len(v) for v in cs.rank_adds.values()),
         "drops_by_source": dict(sorted(by_src.items())), "adds_by_source": dict(sorted(add_src.items())),
         "drop_persons": len({a for a, _ in cs.drops}), "dose_persons": len({a for a, _ in cs.dose_excludes}),
         "adds_over_drops": len(cs.adds & cs.drops), "rank_add_aliases_without_works": len(cs.aliases_without_works),
         "adds_without_work": len(cs.adds_without_work)}
    c.update(counts or {})
    i = {"rank_add_mains": sorted(cs.rank_adds), "dose_kept_persons": sorted({a for a, _ in cs.dose_kept}),
         "adds_over_drops": sorted({a for a, _ in cs.adds & cs.drops}),
         "rank_add_aliases_without_works": sorted(cs.aliases_without_works),
         "adds_without_work": [f"{a} {w}" for a, w in sorted(cs.adds_without_work)]}
    i.update({k: sorted(v) for k, v in (ids or {}).items()})
    summary = {"result": "OK", "name": cs.name, "counts": c, "ids": i}
    (out / "summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return summary


# --- stage ------------------------------------------------------------------------------------------------
def _fail(out, msg) -> None:
    out.mkdir(parents=True, exist_ok=True)
    first = msg.splitlines()[0][:160] if msg else ""
    (out / "summary.json").write_text(json.dumps({"result": "STOP", "reason": first,
                                                  "ids": sorted(set(AID.findall(msg)))}, indent=1) + "\n", encoding="utf-8")
    (out / "RESULT.txt").write_text("STOP\n", encoding="utf-8")


def run(a) -> int:
    repo = a.repo.resolve()
    sys.path[:0] = [str(repo), str(repo / "pipeline" / "aws" / "r1")]
    rb, rq = _rb(), _rq()
    rb.setup_import_paths(repo)                      # repo, caliber_2026-08-28, caliber_2026-10 (2026-10 first)
    from pipeline.lib import r1_config               # noqa: PLC0415
    cfg = r1_config.load(a.config, repo=repo)
    if not cfg.is_on("calls"):
        stop(f"switch calls is {cfg.switch('calls')!r}: B0 runs October's restake, never this stage")
    dose_on = cfg.is_on("dose_excludes")
    rq.require_recovered(a.recovered)
    rk1in = a.recovered / "rk1" / "payload" / "in"
    rk1_drops, rk1_adds = rb.read_pairs(rk1in / "drops.csv"), rb.read_pairs(rk1in / "adds.csv")
    if rb.read_pairs(a.requests / "drops.csv") != rk1_drops or rb.read_pairs(a.requests / "adds.csv") != rk1_adds:
        stop("in6 drops.csv/adds.csv are not the recovered RK1 inputs")
    base = b0()
    b0_control(base, rk1_drops, rk1_adds)
    reqs = json.loads((a.requests / "requests.json").read_text(encoding="utf-8"))
    skipped = json.loads((a.requests / "skipped.json").read_text(encoding="utf-8"))
    rk4 = json.loads((a.recovered / "rk4" / "payload" / "in" / "requests.json").read_text(encoding="utf-8"))
    fold, fold_skipped, checks = fold_requests(a.merged, rk4, a.paper_checks, a.rk6a / "review_pack" / "works")
    if fold != reqs or fold_skipped != skipped:
        theirs, mine = {q["key"]: q for q in reqs}, {q["key"]: q for q in fold}
        diff = sorted(k for k in set(theirs) | set(mine) if theirs.get(k) != mine.get(k))
        stop(f"in6 requests are not the paper-check fold of the same inputs: {len(diff)} keys, e.g. {diff[:5]}")
    miny = check_min_year(rk4)
    links = merge_links(a.overrides, a.fixes, a.add_list)
    unranked = check_links(reqs, links)
    keep = load_dose_keep(a.dose_keep)
    import duckdb                                    # noqa: PLC0415 - only on the instance and in tests
    from restake_econ11 import load_aw_raw_11        # noqa: PLC0415 - the table RK6b pass B ran on
    tmp = a.out / "duck_tmp"
    tmp.mkdir()
    con = duckdb.connect()
    try:
        con.execute("PRAGMA threads=30")
        con.execute("PRAGMA memory_limit='200GB'")
        con.execute(f"PRAGMA temp_directory='{tmp}'")
        n_raw = load_aw_raw_11(con)
        cs = m(base, reqs, con, keep_rows=keep, links=links, dose_on=dose_on)
    finally:
        con.close()
        shutil.rmtree(tmp, ignore_errors=True)
    adj = gate_adjudication(cs, reqs, json.loads(a.adjudication.read_text(encoding="utf-8"))) if dose_on else {}
    n_checked = gate_paper_checked(checks, reqs, skipped, a.expect_paper_checked)
    write_outputs(cs, a.out,
                  ids={"min_year_namesake": miny["namesake"], "min_year_no_reason": miny["no_reason"],
                       "links_unranked": unranked, "skipped": skipped},
                  counts={"aw_raw_rows": n_raw, "requests": len(reqs), "paper_checked": n_checked,
                          "adjudication": adj, "b0_drops": len(base.drops), "b0_adds": len(base.adds),
                          "links": len(links), "dose_on": int(dose_on)})
    (a.out / "RESULT.txt").write_text("OK\n", encoding="utf-8")
    print(f"calls M: drops {len(cs.drops)}, dose_excludes {len(cs.dose_excludes)}, adds {len(cs.adds)}, "
          f"rank_adds {len(cs.rank_adds)}; B0 control EQUAL")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="R1 F8 call sets (stage calls)")
    for flag in ("--config", "--repo", "--requests", "--recovered", "--merged", "--rk6a", "--paper-checks",
                 "--adjudication", "--dose-keep", "--overrides", "--fixes", "--add-list", "--out"):
        ap.add_argument(flag, required=True, type=pathlib.Path)
    ap.add_argument("--expect-paper-checked", required=True, type=int)
    a = ap.parse_args(argv)
    if os.environ.get("SAR_HOST", "").strip() not in AWS_HOSTS:
        raise SystemExit("R1 rule (design v3 §4): calls_lib.py runs only on an R1 AWS instance ($SAR_HOST)")
    a.out.mkdir(parents=True, exist_ok=True)         # the stage driver hands over an empty STAGE_OUT
    if any(a.out.iterdir()):
        raise SystemExit(f"STOP {a.out} is not empty")
    try:
        return run(a)
    except SystemExit as e:
        if not isinstance(e.code, int):
            _fail(a.out, str(e.code))
        raise
    except Exception as e:                           # noqa: BLE001 - recorded, then re-raised
        _fail(a.out, f"{type(e).__name__}: {e}")
        raise


if __name__ == "__main__":
    sys.exit(main())
