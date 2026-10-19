#!/usr/bin/env python3
"""R1 F14 (S6, chemistry / mathematics): take the "not this person" works out of the topic dose of the M
chemistry / mathematics union frame, and add the split-id works back into the stars' vectors. A post-step
of pipeline/aws/r1/chemmath_m.py (the `post_union` hook: after union-gold, before p1-gold); the October
builders are not edited, and B0 never calls it.

    apply(union_frame_csv, out_csv, *, rule_inputs, excludes, addbacks, t1_by_event[, mode]) -> report

Two vector rules, because the union frame carries two kinds of rows and each was written by its own
builder (10-01 report review point 4: chem/maths cannot reuse the econ function):
  * network / both rows (the prodlib frame, byte-preserved by the union builder) -> the PRODLIB rule,
    multidisc_prod_2026-07-24/code/prodlib.py build_subgraph (:240-351) + attach_topic_dose (:466-503):
    identity person ids; the person's snapshot edges (DISTINCT work, author, year; year not NULL) plus
    the supplement pairs the snapshot lacks (any author of a supplement record; year = the works-domain
    year); works_domain = the snapshot works rows (subfield) plus supplement-only works with a NULL
    subfield; vector = count of rows with year <= t1 per m4_dose.topic_vec.canonical_subfield_id(sf);
    the stored text is the float32 value (prodlib.f32) written by csv.writer.
  * dept_only rows (the union builder's own rows) -> the UNION rule,
    pipeline/frames/multidisc_gold_2026-08-10/code/10_build_union_frame_gold.py:184-253 and 413-427:
    person_map_multidisc_seeds alias fold (an unmapped id is its own alias); DISTINCT (pid, year,
    subfield, work) over the u1 edges x works; the event stars' supplement rows (seed_author in the
    field's star set, first (pid, work) kept, works already in the edges dropped, subfield and a missing
    year from the u1 works row); vector over rows with year and subfield present, year <= t1, key
    canon_sf = str(sf).rsplit('/', 1)[-1]; a person with no source rows has no dose (NA); the stored
    text is pandas' float64 text (repr).
Cosine: identity.dose.topic_cos, this repository's ported unit (prodlib and the union builder both call it).

Calls (decision 5, 2026-10-12: works that are not the person's are dropped; F8 calls_lib dose_excludes.csv): a
pair (author_id, work_id) filed under ANY id of a person (the person_map fold; identity when unmapped)
removes that work from the person's source rows, under both rules. Add-backs (v2 h7, the 241 split-id
works, plus the M merges; F8 adds.csv, (main id, work)): a work enters a STAR's vector when the star's
person holds the pair, the work is not already among the star's source rows (never double counted) and is
not excluded; its year is the earliest non-NULL u1 edge year of the work, else the works-row year, and its
subfield the works-row subfield (a work with no works row is unresolved and not added).

Delta mode (v2 h6, via v3 §6): a relation (pid, event) is AFFECTED iff, with the year the vector uses and
t1 = arrival - 1, the star or the incumbent has an excluded work with year <= t1, or the star has an
add-back that would enter with year <= t1. For every affected relation:
  CONTROL  the no-change recompute, formatted in that row type's own text, must equal the stored
           dose_topic text of every row of the relation; otherwise DoseChemmathStop CONTROL_MISMATCH
           naming the (pid, event) pairs, and nothing is written (the 10-01 outside rebuild saw 21 maths
           relations off by up to 0.0011: a STOP there is correct, not noise);
  REWRITE  only the dose_topic cell of the relation's rows, in the row type's own text format; every
           other byte of the file is unchanged (verified on the written file before it is moved in place).
Accounting: rows_in == rows_out; rows changed by cause {dose_exclusion, dose_addback, both} sum to the
changed rows; relations affected / changed, max |delta|, n_to_zero.
Switch off (mode 'off', or no excludes and no add-backs): out_csv is a byte copy of the input.
"""
from __future__ import annotations

import collections
import dataclasses
import hashlib
import importlib
import json
import math
import os
import pathlib
import struct
import sys

REPO = pathlib.Path(__file__).resolve().parents[3]

MODES = ("off", "delta")
OA = "https://openalex.org/"
RULE_OF_CHANNEL = {"network": "prodlib", "both": "prodlib", "dept_only": "union"}
CAUSES = ("dose_exclusion", "dose_addback", "both")
NEED_COLS = ("incumbent_person_id", "year", "star_person_id", "event_id", "post", "dose_topic", "channel")
STOP_CODES = ("BAD_FRAME", "UNKNOWN_CHANNEL", "STAR_MISMATCH", "NO_T1", "T1_MISMATCH", "CONTROL_MISMATCH",
              "ACCOUNTING")
IDS_IN_ERROR = 50

canon_sf = lambda s: str(s).rsplit("/", 1)[-1]   # noqa: E731  (10_build_union_frame_gold.py:124, the union rule)


class DoseChemmathStop(RuntimeError):
    """A STOP of the dose post-step. .code in STOP_CODES; .ids = sorted (pid, event) pairs or ids."""

    def __init__(self, code: str, ids=(), detail: str = ""):
        assert code in STOP_CODES, code
        self.code = code
        self.ids = sorted(ids)
        super().__init__(f"STOP {code}: {detail} {self.ids[:IDS_IN_ERROR]}")


@dataclasses.dataclass(frozen=True)
class RuleInputs:
    """What both builders read for the dose (chemmath_m passes the run's own paths): the u1 edges / works
    parquet globs (the 11-school table under N2), the shadow's edges_supplement_fnfix.jsonl (None = no
    supplement), person_map_multidisc_seeds.parquet (None = identity everywhere) and the field's event
    stars (the union builder's star_set_l: every event star of the field's table, not only those with
    rows in the frame)."""
    edges_glob: str
    works_glob: str
    supplement_jsonl: str | None
    person_map: str | None
    union_stars: frozenset


# ---------------------------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------------------------

def sha(p) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def norm_id(x) -> str:
    """'https://openalex.org/W1' / 'P_A1' / 'A1' -> 'W1' / 'A1' (the form calls and frames are compared in)."""
    s = str(x).strip()
    if s.startswith(OA):
        s = s[len(OA):]
    if s.startswith("P_"):
        s = s[2:]
    return s


def _pairs(pairs, what: str) -> frozenset:
    out = set()
    for p in pairs or ():
        if not isinstance(p, tuple) or len(p) != 2:
            raise ValueError(f"{what}: expected (author_id, work_id) pairs, got {p!r}")
        a, w = norm_id(p[0]), norm_id(p[1])
        if not (a.startswith("A") and w.startswith("W")):
            raise ValueError(f"{what}: not an (A…, W…) pair: {p!r}")
        out.add((a, w))
    return frozenset(out)


def _split_excludes(pairs) -> tuple[frozenset, frozenset]:
    """(usable, non_openalex): a judged work with no OpenAlex id (the historical calls keep one by its
    title) cannot be any frame work, so it is set aside and counted, never applied or refused."""
    usable, other = set(), set()
    for p in pairs or ():
        if not isinstance(p, tuple) or len(p) != 2:
            raise ValueError(f"excludes: expected (author_id, work_id) pairs, got {p!r}")
        a, w = norm_id(p[0]), norm_id(p[1])
        if not a.startswith("A"):
            raise ValueError(f"excludes: not an (A…, W…) pair: {p!r}")
        (usable if w.startswith("W") else other).add((a, w))
    return frozenset(usable), frozenset(other)


def f32_text(x) -> str:
    """prodlib.f32 (struct float32 round trip) as csv.writer writes it (str of a Python float)."""
    return repr(struct.unpack("f", struct.pack("f", float(x)))[0])


def f64_text(x) -> str:
    """The union builder's pandas float64 text (shortest repr); NA -> empty."""
    return "" if x is None else repr(float(x))


def units():
    """(topic_cos, canonical_subfield_id) from THIS repository's ported units, origin-asserted (the
    frames_stage.preimport_prodlib_units rule)."""
    for u in ("u0_foundation", "u5_dose"):
        p = str(REPO / "pipeline" / "units" / u / "src")
        if p not in sys.path:
            sys.path.insert(0, p)
    dose = importlib.import_module("identity.dose")
    tv = importlib.import_module("m4_dose.topic_vec")
    for m in (dose, tv):
        f = pathlib.Path(m.__file__).resolve()
        if not f.is_relative_to(REPO / "pipeline" / "units"):
            raise ImportError(f"{m.__name__} resolves outside this repository's units: {f}")
    return dose.topic_cos, tv.canonical_subfield_id


def _q(p) -> str:
    return str(p).replace("'", "''")


def _register(con, name: str, cols: dict, ints=()) -> None:
    """A small id table: every column VARCHAR, except the `ints` columns (BIGINT), typed even when empty."""
    import pyarrow as pa                                                 # noqa: PLC0415
    con.register(f"_{name}_arrow", pa.table({k: pa.array(list(v), pa.int64() if k in ints else pa.string())
                                             for k, v in cols.items()}))
    con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM _{name}_arrow")
    con.unregister(f"_{name}_arrow")


# ---------------------------------------------------------------------------------------------
# the frame
# ---------------------------------------------------------------------------------------------

def read_frame(path) -> dict:
    """The union frame as raw lines. Cells are split on ',' only: every cell of this frame is an id, a
    number, a boolean or empty, and a quote is a STOP (BAD_FRAME) rather than a re-quoted rewrite. The
    07-24 CRLF leftover ('…\\r,network') stays inside its cell, so a rewritten line keeps every other byte."""
    raw = pathlib.Path(path).read_bytes()
    trailing = raw.endswith(b"\n")
    parts = raw.split(b"\n")
    if trailing:
        parts = parts[:-1]
    if not parts:
        raise DoseChemmathStop("BAD_FRAME", detail=f"{path} is empty")
    header = parts[0].decode("utf-8").split(",")
    missing = [c for c in NEED_COLS if c not in header]
    if missing:
        raise DoseChemmathStop("BAD_FRAME", detail=f"{path} lacks columns {missing}")
    rows = []
    for i, ln in enumerate(parts[1:], 1):
        s = ln.decode("utf-8")
        if '"' in s:
            raise DoseChemmathStop("BAD_FRAME", detail=f"{path} line {i + 1} holds a quote")
        c = s.split(",")
        if len(c) != len(header):
            raise DoseChemmathStop("BAD_FRAME", detail=f"{path} line {i + 1}: {len(c)} cells, header {len(header)}")
        rows.append(c)
    return {"header": header, "col": {c: header.index(c) for c in NEED_COLS}, "lines": parts[1:],
            "rows": rows, "trailing": trailing, "header_line": parts[0]}


def relations_of(fr: dict) -> dict:
    """(pid, event) -> {'channel', 'rule', 'star', 'rows': [row index]}; one channel and one star per
    relation, one star per event."""
    col = fr["col"]
    rel: dict = {}
    star_of_event: dict = {}
    for i, c in enumerate(fr["rows"]):
        pid, ev, star = c[col["incumbent_person_id"]], c[col["event_id"]], c[col["star_person_id"]]
        ch = c[col["channel"]].rstrip("\r")
        if ch not in RULE_OF_CHANNEL:
            raise DoseChemmathStop("UNKNOWN_CHANNEL", [(pid, ev)], f"channel {ch!r}")
        if star_of_event.setdefault(ev, star) != star:
            raise DoseChemmathStop("STAR_MISMATCH", [ev], "two star ids for one event")
        r = rel.setdefault((pid, ev), {"channel": ch, "rule": RULE_OF_CHANNEL[ch], "star": star, "rows": []})
        if r["channel"] != ch:
            raise DoseChemmathStop("BAD_FRAME", [(pid, ev)], "one relation, two channels")
        r["rows"].append(i)
    return rel


def frame_t1(fr: dict) -> dict:
    """event -> min(year | post true) - 1, the frame's own arrival (post is written True / true)."""
    col = fr["col"]
    arr: dict = {}
    for c in fr["rows"]:
        if c[col["post"]].strip().lower() in ("true", "1"):
            y = int(float(c[col["year"]]))
            ev = c[col["event_id"]]
            arr[ev] = min(arr.get(ev, y), y)
    return {e: a - 1 for e, a in arr.items()}


# ---------------------------------------------------------------------------------------------
# source rows
# ---------------------------------------------------------------------------------------------

def alias_map(con, person_map, persons) -> tuple[dict, int]:
    """bare id -> every author id of its person_map person (itself included); an unmapped id (a new
    chemistry / mathematics person the seeds map does not hold) is its own only alias. Returns
    (map, n_unmapped). person_map None = identity for everyone."""
    persons = sorted(set(persons))
    out = {p: {p} for p in persons}
    if person_map is None or not persons:
        return out, (len(persons) if person_map is None else 0)
    _register(con, "dc_needp", {"bare": persons})
    pm = _q(person_map)
    rows = con.execute(f"""
        WITH canon AS (SELECT n.bare, m.person_id FROM dc_needp n JOIN read_parquet('{pm}') m ON m.author_id = n.bare)
        SELECT c.bare, m2.author_id FROM canon c JOIN read_parquet('{pm}') m2 ON m2.person_id = c.person_id""").fetchall()
    mapped = set()
    for bare, a in rows:
        mapped.add(bare)
        out[bare].add(a)
    return out, len(persons) - len(mapped)


def _sup_rows(path) -> list[dict]:
    if not path:
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]                          # prodlib reads every line


def prodlib_rows(con, ri: RuleInputs, persons) -> dict:
    """pid -> [(work_id, year, subfield)] under the prodlib rule (identity ids); subfield None for a
    supplement-only work or a work without a works row (such rows never enter the vector, as prodlib's
    inner join drops them)."""
    persons = sorted(set(persons))
    out: dict = {p: [] for p in persons}
    if not persons:
        return out
    _register(con, "dc_pp", {"id": persons})
    sup = []
    keep = set(persons)
    for r in _sup_rows(ri.supplement_jsonl):
        for a in r["authors"]:
            if a in keep:
                sup.append((r["work_id"], a, r["publication_year"]))
    _register(con, "dc_sup_raw", {"work_id": [x[0] for x in sup], "author_id": [x[1] for x in sup],
                                  "jsonl_year": [x[2] for x in sup]}, ints=("jsonl_year",))
    eg, wg = _q(ri.edges_glob), _q(ri.works_glob)
    con.execute("""CREATE OR REPLACE TABLE dc_sup AS
        SELECT work_id, author_id, min(jsonl_year) AS jsonl_year FROM dc_sup_raw GROUP BY 1, 2""")
    con.execute(f"""CREATE OR REPLACE TABLE dc_snap AS
        SELECT DISTINCT e.work_id, e.author_id, e.publication_year
        FROM read_parquet('{eg}', hive_partitioning=0) e JOIN dc_pp p ON e.author_id = p.id
        WHERE e.publication_year IS NOT NULL""")
    con.execute("""CREATE OR REPLACE TABLE dc_needw AS
        SELECT work_id FROM dc_snap UNION SELECT work_id FROM dc_sup""")
    con.execute(f"""CREATE OR REPLACE TABLE dc_wd AS
        SELECT w.work_id, w.publication_year, w.subfield_id
        FROM read_parquet('{wg}', hive_partitioning=0) w JOIN dc_needw n ON w.work_id = n.work_id""")
    con.execute("""INSERT INTO dc_wd
        SELECT p.work_id, min(p.jsonl_year), NULL FROM dc_sup p LEFT JOIN dc_wd w ON p.work_id = w.work_id
        WHERE w.work_id IS NULL GROUP BY p.work_id""")
    con.execute("""CREATE OR REPLACE TABLE dc_supnew AS
        SELECT p.work_id, p.author_id, wd.publication_year
        FROM dc_sup p JOIN dc_wd wd ON p.work_id = wd.work_id
        LEFT JOIN dc_snap sn ON p.work_id = sn.work_id AND p.author_id = sn.author_id
        WHERE sn.work_id IS NULL AND wd.publication_year IS NOT NULL""")
    rows = con.execute("""
        WITH merged AS (SELECT * FROM dc_snap UNION ALL SELECT DISTINCT * FROM dc_supnew)
        SELECT m.author_id, m.work_id, m.publication_year, w.subfield_id
        FROM merged m LEFT JOIN dc_wd w ON m.work_id = w.work_id""").fetchall()
    for a, w, y, sf in rows:
        out[a].append((w, y, sf))
    return out


def union_rows(con, ri: RuleInputs, persons, aliases: dict) -> dict:
    """pid -> DataFrame(pid, yr, sf, work_id) under the union rule, built with the builder's own pandas
    steps (dtype behaviour included); a person with no source row is absent (its dose is NA)."""
    import pandas as pd                                                  # noqa: PLC0415
    persons = sorted(set(persons))
    if not persons:
        return {}
    alias = pd.DataFrame([(p, a) for p in persons for a in sorted(aliases.get(p, {p}))],
                         columns=["person_id", "author_id"])
    con.register("alias_df", alias)
    eg, wg = _q(ri.edges_glob), _q(ri.works_glob)
    pedges = con.execute(f"""
        SELECT DISTINCT a.person_id pid, e.publication_year yr, w.subfield_id sf, e.work_id
        FROM read_parquet('{eg}', hive_partitioning=0) e
        JOIN alias_df a ON e.author_id = a.author_id
        JOIN read_parquet('{wg}', hive_partitioning=0) w ON e.work_id = w.work_id
        WHERE e.publication_year IS NOT NULL""").df()
    con.unregister("alias_df")
    sup_rows = []
    want = set(ri.union_stars) & set(persons)
    for d in _sup_rows(ri.supplement_jsonl):
        if d["seed_author"] in want:
            sup_rows.append({"pid": d["seed_author"], "work_id": d["work_id"],
                             "yr": d.get("publication_year"), "sf": None})
    sup_df = pd.DataFrame(sup_rows, columns=["pid", "work_id", "yr", "sf"])
    if len(sup_df):
        sup_df = sup_df.drop_duplicates(["pid", "work_id"])
        have = pedges.groupby("pid").work_id.apply(set).to_dict()
        sup_df = sup_df[[w not in have.get(p, ()) for p, w in zip(sup_df.pid, sup_df.work_id)]].copy()
        need_sf = sup_df.work_id.unique().tolist()
        if need_sf:
            _register(con, "dc_nsf", {"w": need_sf})
            u1sf = con.execute(f"""SELECT w.work_id, w.subfield_id, w.publication_year
                FROM read_parquet('{wg}', hive_partitioning=0) w JOIN dc_nsf ON w.work_id = dc_nsf.w""").df()
            m2 = dict(zip(u1sf.work_id, u1sf.subfield_id))
            y2 = dict(zip(u1sf.work_id, u1sf.publication_year))
            sup_df["sf"] = [m2.get(w) for w in sup_df.work_id]
            sup_df["yr"] = [y if pd.notna(y) else y2.get(w) for y, w in zip(sup_df.yr, sup_df.work_id)]
    src = pd.concat([pedges[["pid", "yr", "sf", "work_id"]], sup_df[["pid", "yr", "sf", "work_id"]]],
                    ignore_index=True)
    return {p: g for p, g in src.groupby("pid")}


def addback_meta(con, ri: RuleInputs, works) -> dict:
    """work -> (year, subfield_raw, subfield_union) for add-back works: year = earliest non-NULL u1 edge
    year, else the works-row year; subfield = the works row's (subfield_union taken through pandas, the
    union rule's own path for extra star works). A work with no works row is absent (unresolved)."""
    works = sorted(set(works))
    if not works:
        return {}
    forms = sorted({w for w in works} | {OA + w for w in works})
    _register(con, "dc_addw", {"w": forms})
    eg, wg = _q(ri.edges_glob), _q(ri.works_glob)
    ey = {norm_id(w): y for w, y in con.execute(f"""
        SELECT e.work_id, min(e.publication_year) FROM read_parquet('{eg}', hive_partitioning=0) e
        JOIN dc_addw a ON e.work_id = a.w WHERE e.publication_year IS NOT NULL GROUP BY 1""").fetchall()}
    q = f"""SELECT w.work_id, w.subfield_id, w.publication_year
        FROM read_parquet('{wg}', hive_partitioning=0) w JOIN dc_addw a ON w.work_id = a.w ORDER BY 1"""
    wdf = con.execute(q).df()
    sf_union = {}
    for w, sf in zip(wdf.work_id, wdf.subfield_id):
        sf_union.setdefault(norm_id(w), sf)                              # one works row per work (the first)
    out = {}
    for w, sf, y in con.execute(q).fetchall():
        k = norm_id(w)
        if k in out:
            continue
        year = ey.get(k, y)
        out[k] = (None if year is None else int(year), sf, sf_union[k], w)
    return out


# ---------------------------------------------------------------------------------------------
# vectors
# ---------------------------------------------------------------------------------------------

def vec_prodlib(rows, t1: int, canon) -> dict:
    v: dict = {}
    for _w, y, sf in rows:
        if sf is None or y is None or y > t1:
            continue
        k = canon(sf)
        v[k] = v.get(k, 0.0) + 1.0
    return v


def vec_union(g, t1: int):
    if g is None:
        return None
    s = g[(g.yr.notna()) & (g.yr <= t1) & g.sf.notna()]
    v: dict = {}
    for x in s.sf:
        k = canon_sf(x)
        v[k] = v.get(k, 0.0) + 1.0
    return v


# ---------------------------------------------------------------------------------------------
# the post-step
# ---------------------------------------------------------------------------------------------

def _copy(src, out) -> None:
    out = pathlib.Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_bytes(pathlib.Path(src).read_bytes())
    os.replace(tmp, out)


def apply(union_frame_csv, out_csv, *, rule_inputs: RuleInputs, excludes, addbacks, t1_by_event: dict,
          mode: str = "delta") -> dict:
    """See the module docstring. Returns the report (counts, codes and (pid, event) ids)."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    src, out = pathlib.Path(union_frame_csv), pathlib.Path(out_csv)
    if src.resolve() == out.resolve():
        raise ValueError("out_csv must differ from the input frame")
    (ex, ex_other), ab = _split_excludes(excludes), _pairs(addbacks, "addbacks")
    base = {"mode": mode, "input": {"sha256": sha(src)},
            "calls": {"excludes": len(ex), "non_openalex_excludes": len(ex_other), "addbacks": len(ab)}}
    if mode == "off" or (not ex and not ab):
        _copy(src, out)
        return {**base, "identity_copy": True, "output": {"sha256": sha(out)}, "rows_changed": 0}

    import duckdb                                                        # noqa: PLC0415
    topic_cos, canon = units()
    fr = read_frame(src)
    col = fr["col"]
    rel = relations_of(fr)
    t1f = frame_t1(fr)
    events = {ev for _p, ev in rel}
    no_t1 = sorted(e for e in events if e not in t1_by_event)
    if no_t1:
        raise DoseChemmathStop("NO_T1", no_t1, "events without a t1 in t1_by_event")
    bad_t1 = sorted(e for e in events if e in t1f and int(t1_by_event[e]) != t1f[e])
    if bad_t1:
        raise DoseChemmathStop("T1_MISMATCH", bad_t1, "t1 from the event table != frame min(post year) - 1")

    persons = {p for p, _e in rel} | {r["star"] for r in rel.values()}
    con = duckdb.connect()
    try:
        aliases, n_unmapped = alias_map(con, rule_inputs.person_map, persons)
        ex_of = {p: {w for (a, w) in ex if a in al} for p, al in aliases.items()}
        add_of = {p: {w for (a, w) in ab if a in al} for p, al in aliases.items()}
        stars = {r["star"] for r in rel.values()}
        cand_ex = {p for p, s in ex_of.items() if s}
        cand_add = {s for s in stars if add_of.get(s)}
        touching = {k: r for k, r in rel.items() if k[0] in cand_ex or r["star"] in cand_ex or r["star"] in cand_add}
        need = {"prodlib": set(), "union": set()}
        for (pid, _ev), r in touching.items():
            need[r["rule"]].update((pid, r["star"]))
        P = prodlib_rows(con, rule_inputs, need["prodlib"])
        U = union_rows(con, rule_inputs, need["union"], aliases)
        meta = addback_meta(con, rule_inputs, {w for s in cand_add for w in add_of[s]})
    finally:
        con.close()

    ab_count = collections.Counter()
    ab_seen: set = set()

    def adds_for(rule, star, t1, present: set) -> list:
        """add-back rows for `star` that would enter at t1 (not present, not excluded, resolved, year <= t1)."""
        rows = []
        for w in sorted(add_of.get(star, ())):
            key = (rule, star, w)
            if w in ex_of.get(star, set()):
                tag = "excluded"
            elif w in present:
                tag = "already_present"
            elif w not in meta or meta[w][0] is None:
                tag = "unresolved"
            elif meta[w][0] > t1:
                tag = "after_t1"
            else:
                tag = "entered"
                rows.append((w, meta[w]))
            if key + (t1,) not in ab_seen:
                ab_seen.add(key + (t1,))
                ab_count[tag] += 1
        return rows

    def prod_dose(pid, star, t1, fixed: bool):
        rp, rs = P.get(pid, []), P.get(star, [])
        if fixed:
            rp = [r for r in rp if norm_id(r[0]) not in ex_of.get(pid, set())]
            rs = [r for r in rs if norm_id(r[0]) not in ex_of.get(star, set())]
            rs = rs + [(m[3], m[0], m[1]) for _w, m in adds_for("prodlib", star, t1, {norm_id(r[0]) for r in P.get(star, [])})]
        return topic_cos(vec_prodlib(rp, t1, canon), vec_prodlib(rs, t1, canon))

    def union_frame_of(pid, fixed: bool, star_side: bool, t1):
        import pandas as pd                                              # noqa: PLC0415
        g = U.get(pid)
        if not fixed:
            return g
        if g is not None:
            g = g[[norm_id(w) not in ex_of.get(pid, set()) for w in g.work_id]]
        if star_side:
            present = set() if U.get(pid) is None else {norm_id(w) for w in U[pid].work_id}
            add = adds_for("union", pid, t1, present)
            if add:
                extra = pd.DataFrame({"pid": [pid] * len(add), "yr": [m[0] for _w, m in add],
                                      "sf": [m[2] for _w, m in add], "work_id": [m[3] for _w, m in add]})
                g = extra if g is None else pd.concat([g, extra], ignore_index=True)
        return g

    def union_dose(pid, star, t1, fixed: bool):
        vi = vec_union(union_frame_of(pid, fixed, False, t1), t1)
        vs = vec_union(union_frame_of(star, fixed, True, t1), t1)
        if vi is None or vs is None:
            return None
        return topic_cos(vi, vs)

    def hits(rule, pid, star, t1) -> tuple[bool, bool]:
        """(an excluded work with year <= t1 on either side, an add-back entering with year <= t1)."""
        exh = False
        for x in (pid, star):
            exw = ex_of.get(x, set())
            if not exw:
                continue
            if rule == "prodlib":
                exh |= any(y is not None and y <= t1 and norm_id(w) in exw for w, y, _sf in P.get(x, []))
            else:
                g = U.get(x)
                if g is not None:
                    s = g[(g.yr.notna()) & (g.yr <= t1)]
                    exh |= any(norm_id(w) in exw for w in s.work_id)
        addh = False
        if add_of.get(star):
            present = ({norm_id(r[0]) for r in P.get(star, [])} if rule == "prodlib" else
                       (set() if U.get(star) is None else {norm_id(w) for w in U[star].work_id}))
            addh = any(w not in ex_of.get(star, set()) and w not in present and w in meta
                       and meta[w][0] is not None and meta[w][0] <= t1 for w in add_of[star])
        return exh, addh

    affected: dict = {}
    for (pid, ev), r in sorted(touching.items()):
        exh, addh = hits(r["rule"], pid, r["star"], int(t1_by_event[ev]))
        if exh or addh:
            affected[(pid, ev)] = "both" if (exh and addh) else ("dose_exclusion" if exh else "dose_addback")

    # CONTROL, then the fixed value per affected relation
    mismatch, new_text, deltas, to_zero = [], {}, [], []
    by_rule = {"prodlib": collections.Counter(), "union": collections.Counter()}
    for (pid, ev), cause in affected.items():
        r = rel[(pid, ev)]
        t1 = int(t1_by_event[ev])
        if r["rule"] == "prodlib":
            cur, fix = prod_dose(pid, r["star"], t1, False), prod_dose(pid, r["star"], t1, True)
            ct, ft = f32_text(cur), f32_text(fix)
        else:
            cur, fix = union_dose(pid, r["star"], t1, False), union_dose(pid, r["star"], t1, True)
            ct, ft = f64_text(cur), f64_text(fix)
        stored = {fr["rows"][i][col["dose_topic"]] for i in r["rows"]}
        if stored != {ct}:
            mismatch.append((pid, ev))
            continue
        by_rule[r["rule"]]["affected"] += 1
        new_text[(pid, ev)] = ft
        if cur is not None and fix is not None:
            deltas.append(abs(float(ft) - float(ct)))
            if float(ct) > 0 and float(ft) == 0.0:
                to_zero.append((pid, ev))
    if mismatch:
        raise DoseChemmathStop("CONTROL_MISMATCH", mismatch,
                               "the no-change recompute does not reproduce the stored dose_topic text")

    # rewrite only the dose cell of changed relations
    ic = col["dose_topic"]
    changed_rows: dict = {}
    lines = list(fr["lines"])
    rows_by_cause = collections.Counter()
    changed_rel = []
    for k, ft in sorted(new_text.items()):
        r = rel[k]
        if fr["rows"][r["rows"][0]][ic] == ft:
            continue
        changed_rel.append(k)
        by_rule[r["rule"]]["changed"] += 1
        for i in r["rows"]:
            cells = list(fr["rows"][i])
            cells[ic] = ft
            lines[i] = ",".join(cells).encode("utf-8")
            changed_rows[i] = affected[k]
            rows_by_cause[affected[k]] += 1
    blob = b"\n".join([fr["header_line"]] + lines) + (b"\n" if fr["trailing"] else b"")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_bytes(blob)
    proof = rows_proof(src, tmp, set(changed_rows), ic)
    closed = (proof["closed"] and proof["rows_in"] == proof["rows_out"]
              and sum(rows_by_cause.values()) == len(changed_rows) == proof["rows_rewritten"])
    if not closed:
        tmp.unlink(missing_ok=True)
        raise DoseChemmathStop("ACCOUNTING", [], f"the rewrite did not close: {proof}")
    os.replace(tmp, out)
    return {
        **base, "identity_copy": False,
        "rule": "delta: affected iff an excluded work (either side) or an entering add-back (star) with "
                "year <= t1; CONTROL = exact stored text; only dose_topic rewritten",
        "input": {"sha256": sha(src), "rows": len(fr["rows"]), "relations": len(rel), "events": len(events)},
        "output": {"sha256": sha(out), "rows": proof["rows_out"]},
        "person_map": {"persons": len(persons), "unmapped_identity": n_unmapped},
        "calls": {"excludes": len(ex), "non_openalex_excludes": len(ex_other), "addbacks": len(ab),
                  "persons_with_excludes": len(cand_ex),
                  "stars_with_addbacks": len(cand_add)},
        "relations": {"touching": len(touching), "affected": len(affected),
                      "affected_by_cause": {c: sum(1 for v in affected.values() if v == c) for c in CAUSES},
                      "changed": len(changed_rel), "n_to_zero": len(to_zero),
                      "max_abs_delta": max(deltas) if deltas else 0.0},
        "by_rule": {k: dict(v) for k, v in by_rule.items()},
        "addbacks": {t: ab_count.get(t, 0) for t in ("entered", "already_present", "excluded", "unresolved",
                                                       "after_t1")},
        "control": {"relations_checked": len(affected), "mismatches": 0},
        "rows_in": proof["rows_in"], "rows_out": proof["rows_out"], "rows_changed": len(changed_rows),
        "rows_changed_by_cause": {c: rows_by_cause.get(c, 0) for c in CAUSES},
        "accounting_closed": True,
        "affected": sorted([p, e] for p, e in affected), "changed": sorted([p, e] for p, e in changed_rel),
        "to_zero": sorted([p, e] for p, e in to_zero),
    }


def rows_proof(before, after, rewritten: set, dose_ix: int) -> dict:
    """Line by line: equal line count and header; a line outside `rewritten` byte-identical; a rewritten
    line equal in every cell but dose_ix."""
    a = pathlib.Path(before).read_bytes().split(b"\n")
    b = pathlib.Path(after).read_bytes().split(b"\n")
    out = {"rows_in": len(a) - 1 - (a[-1] == b""), "rows_out": len(b) - 1 - (b[-1] == b""),
           "rows_rewritten": 0, "bad": []}
    if len(a) != len(b) or a[0] != b[0]:
        out["closed"] = False
        out["bad"].append("line count or header")
        return out
    for i, (x, y) in enumerate(zip(a[1:], b[1:])):
        if i in rewritten:
            cx, cy = x.split(b","), y.split(b",")
            if len(cx) != len(cy) or any(p != q for j, (p, q) in enumerate(zip(cx, cy)) if j != dose_ix):
                out["bad"].append(i)
            elif cx[dose_ix] != cy[dose_ix]:
                out["rows_rewritten"] += 1
        elif x != y:
            out["bad"].append(i)
    out["closed"] = not out["bad"]
    out["bad"] = out["bad"][:20]
    return out
