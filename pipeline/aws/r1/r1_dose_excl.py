#!/usr/bin/env python3
"""R1 F13 (S6, economics): take each star's and colleague's "not this person" works out of the topic
dose of the M economics pre-y frame. Repo-authored library; October's clone and econ920_lib stay as
they are.

Where it runs: the R1 econ wrapper calls `apply_dose_exclusions()` after `union_rows_proof` (which
must see the UNFIXED frame) and before `chain_from_union`; the freeze then takes the fixed pre-y and
`dose_rows_proof()` closes the step as an in-run gate. B0 never calls it (S6 mode 'off').

The vector rule is the clone's (pipeline/frames/cal2026-10/econ920/00_build_frame_econ920_cal.py
§2, mirrored line by line in `load_dose_sources`):
  * U2 person-map alias folding: bare id -> canonical person -> every author alias; every alias edge
    of a work counts (edge multiplicity kept);
  * u1_full_11school_2026-07-16 authorship edges x works subfield, cut at the EDGE-table
    publication_year <= T-1 (T = the arrival year in event_id);
  * sources: the person's edges when there are any, otherwise SUP11 + SUP_FNFIX rows (subfield
    from PATCH_B, else the u1 works row) together with the PATCH_A API rows (the clone concatenates
    both fallbacks);
  * identity.dose.topic_cos over subfield counts (empty vector -> 0.0).
A call (author_id, work_id) filed under ANY of a person's ids removes every source row of that work
from that person (edges, supplement and API rows alike). Add-backs (main_author_id, work_id) enter a
person only when the work is absent from the person's sources; year and subfield come from the u1
edge (else the works row) of that work.

Delta mode (the only signed mode): on every row of an affected relation,
    new = clip(stored + (fixed - current), 0, 1)
written as repr(float(new)), and only when the value changes; stored NA stays NA; a relation with
one side without any source rows is left alone (affected_uncomputable). Δcalls = fixed - current
and Δrule = current - stored (the July gap, never applied) are reported separately. Before anything
is written, the recomputed current dose must equal the stored dose within 1e-12 on every dept_only
and prodlib-event relation (rows the clone itself wrote): otherwise DoseRuleMismatch (STOP).

Input paths come from the union config the clone ran with (SUP11, SUP_FNFIX, PATCH_A, PATCH_B,
NEW_EVENTS). The three SSD tables resolve, like the clone, under pipeline.lib.paths.derived_root();
a config may name them explicitly with the keys PMAP / U1E / U1W (a parquet file, a directory or a
list of either) — all three or none.
"""
from __future__ import annotations

import csv
import glob
import hashlib
import importlib
import json
import math
import os
import pathlib
import re
import sys
from typing import Callable, Iterable

import pandas as pd

REPO = pathlib.Path(__file__).resolve().parents[3]

MODES = ("off", "delta")
SELF_CHECK_TOL = 1e-12
OA = "https://openalex.org/"
UNION_KEYS = ("SUP11", "SUP_FNFIX", "PATCH_A", "PATCH_B", "NEW_EVENTS")
TABLE_KEYS = ("PMAP", "U1E", "U1W")
FRAME_KEY_COLS = ("incumbent_person_id", "event_id", "dose_topic", "channel")
NA_CELLS = ("", "NA", "nan", "NaN", "None")
_SAFE_ID = re.compile(r"[A-Za-z0-9_]+")
_WORK = re.compile(r"W[0-9]+")
_AUTHOR = re.compile(r"A[0-9A-Za-z]+")

strip = lambda x: x.replace("P_", "", 1)          # noqa: E731  (the clone's own)
canon_sf = lambda s: str(s).rsplit("/", 1)[-1]   # noqa: E731  (the clone's own)


class DoseRuleMismatch(RuntimeError):
    """The recomputed current dose differs from the stored dose on a row the clone wrote itself."""

    def __init__(self, msg: str, mismatches: list[dict]):
        super().__init__(msg)
        self.mismatches = mismatches


# ---------------------------------------------------------------------------------------------
# ids
# ---------------------------------------------------------------------------------------------

def _strip_oa(x) -> str:
    s = str(x).strip()
    return s[len(OA):] if s.startswith(OA) else s


def norm_work(w) -> str:
    """'https://openalex.org/W123' or 'W123' -> 'W123'; anything else raises."""
    s = _strip_oa(w)
    if not _WORK.fullmatch(s):
        raise ValueError(f"not an OpenAlex work id: {w!r}")
    return s


def norm_author(a) -> str:
    """'https://openalex.org/A1', 'P_A1' or 'A1' -> 'A1'; anything else raises."""
    s = _strip_oa(a)
    if s.startswith("P_"):
        s = s[2:]
    if not _AUTHOR.fullmatch(s):
        raise ValueError(f"not an OpenAlex author id: {a!r}")
    return s


def _source_work(w) -> str:
    """Tolerant form for source rows (never raises): the bare 'W…' id when it has one."""
    return _strip_oa(w) if w is not None and not (isinstance(w, float) and math.isnan(w)) else ""


def _norm_pairs(pairs, what: str) -> frozenset[tuple[str, str]]:
    if pairs is None:
        return frozenset()
    out = set()
    for p in pairs:
        if not isinstance(p, tuple) or len(p) != 2:
            raise ValueError(f"{what}: expected (author_id, work_id) pairs, got {p!r}")
        out.add((norm_author(p[0]), norm_work(p[1])))
    return frozenset(out)


def _norm_excludes(pairs) -> tuple[frozenset[tuple[str, str]], frozenset[tuple[str, str]]]:
    """(usable, non_openalex): a judged work with no OpenAlex id (the October calls keep one by its
    title) cannot be any frame work, so it is set aside and counted, never applied or refused."""
    usable, other = set(), set()
    for p in pairs or ():
        if not isinstance(p, tuple) or len(p) != 2:
            raise ValueError(f"excludes: expected (author_id, work_id) pairs, got {p!r}")
        a = norm_author(p[0])
        try:
            usable.add((a, norm_work(p[1])))
        except ValueError:
            other.add((a, str(p[1])))
    return frozenset(usable), frozenset(other)


# ---------------------------------------------------------------------------------------------
# the clone's dose sources
# ---------------------------------------------------------------------------------------------

def topic_cos_fn() -> Callable:
    """identity.dose.topic_cos from THIS repository's ported unit, origin-asserted
    (econ920_lib.preimport_dose's rule)."""
    src = REPO / "pipeline" / "units" / "u0_foundation" / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    mod = importlib.import_module("identity.dose")
    origin = pathlib.Path(mod.__file__).resolve()
    if not origin.is_relative_to(REPO / "pipeline" / "units"):
        raise ImportError(f"identity.dose resolves outside the repository's units: {origin}")
    return mod.topic_cos


def _parquets(v, key: str) -> list[str]:
    items = [v] if isinstance(v, (str, os.PathLike)) else list(v)
    out: list[str] = []
    for x in items:
        p = pathlib.Path(x)
        out += sorted(glob.glob(f"{p}/**/*.parquet", recursive=True)) if p.is_dir() else [str(p)]
    if not out:
        raise FileNotFoundError(f"{key}: no parquet file under {v!r}")
    missing = [x for x in out if not pathlib.Path(x).is_file()]
    if missing:
        raise FileNotFoundError(f"{key}: missing {missing[:3]}")
    return out


def resolve_tables(union_cfg: dict) -> dict[str, list[str]]:
    """PMAP / U1E / U1W: from the config when it names all three, else the clone's globs under
    derived_root()."""
    given = [k for k in TABLE_KEYS if union_cfg.get(k)]
    if given and len(given) != len(TABLE_KEYS):
        raise KeyError(f"union config names {given} but not all of {TABLE_KEYS}")
    if given:
        return {k: _parquets(union_cfg[k], k) for k in TABLE_KEYS}
    if str(REPO) not in sys.path:
        sys.path.append(str(REPO))
    from pipeline.lib.paths import derived_root, require_readable          # noqa: PLC0415
    ssd = str(require_readable(derived_root()))
    t = {"PMAP": glob.glob(f"{ssd}/u2_person_map_11school_2026-07-16/person_map/**/*.parquet", recursive=True),
         "U1E": glob.glob(f"{ssd}/u1_full_11school_2026-07-16/authorship_edges/**/*.parquet", recursive=True),
         "U1W": glob.glob(f"{ssd}/u1_full_11school_2026-07-16/works/**/*.parquet", recursive=True)}
    for k, v in t.items():
        if not v:
            raise FileNotFoundError(f"{k}: the clone's glob under {ssd} matched nothing")
    return t


def _sql_list(paths: list[str]) -> str:
    return "[" + ", ".join("'" + p.replace("'", "''") + "'" for p in paths) + "]"


def _sql_values(ids: Iterable[str]) -> str:
    vals = sorted(set(ids))
    for v in vals:
        if not _SAFE_ID.fullmatch(v):
            raise ValueError(f"unsafe id for a VALUES list: {v!r}")
    return ",".join(f"('{v}')" for v in vals)


def _counted(yr, sf, t1: int) -> bool:
    """The clone's row filter `g.yr.notna() & (g.yr <= t1) & g.sf.notna()`, one row."""
    return bool(pd.notna(yr) and yr <= t1 and pd.notna(sf))


class DoseSources:
    """Per-person source rows (work id normalised, year, subfield) under the clone's precedence."""

    def __init__(self, rows: dict[str, list[tuple[str, object, object]]], ids: dict[str, frozenset[str]],
                 origin: dict[str, str], work_meta: dict[str, tuple[object, object]], report: dict):
        self.rows, self.ids, self.origin, self.work_meta, self.report = rows, ids, origin, work_meta, report
        self.present = {p: frozenset(w for w, _, _ in r) for p, r in rows.items()}
        self._cos = topic_cos_fn()

    def ids_of(self, pid: str) -> frozenset[str]:
        return self.ids.get(pid, frozenset()) | {pid}

    def fixed_rows(self, pid: str, drop: frozenset[str], add: tuple = ()) -> list | None:
        r = self.rows.get(pid)
        if r is None:
            return None
        return [x for x in r if x[0] not in drop] + list(add)

    @staticmethod
    def vector_of(rows: list | None, t1: int) -> dict | None:
        """The clone's topic_vec on a row list (None = no source rows at all)."""
        if rows is None:
            return None
        v: dict[str, float] = {}
        for _w, yr, sf in rows:
            if _counted(yr, sf, t1):
                k = canon_sf(sf)
                v[k] = v.get(k, 0.0) + 1.0
        return v

    def cos(self, a: dict | None, b: dict | None) -> float | None:
        if a is None or b is None:
            return None
        return self._cos(a, b)


def load_dose_sources(union_cfg: dict, persons: Iterable[str], *,
                      addback_works: Iterable[str] = ()) -> DoseSources:
    """The clone's §2 for `persons` (bare ids): alias folding, edges x works, the supplement and API
    fallbacks with its precedence. `addback_works` (normalised 'W…' ids) get (year, subfield) from
    the u1 edge (else the works row) for the add-back switch."""
    import duckdb                                                         # noqa: PLC0415
    missing = [k for k in UNION_KEYS if k not in union_cfg]
    if missing:
        raise KeyError(f"union config lacks {missing}")
    need_persons = sorted(set(persons))
    if not need_persons:
        raise ValueError("load_dose_sources: no persons")
    T = resolve_tables(union_cfg)
    PMAP, U1E, U1W = _sql_list(T["PMAP"]), _sql_list(T["U1E"]), _sql_list(T["U1W"])
    con = duckdb.connect()
    con.execute("PRAGMA threads=8")
    con.execute("CREATE TEMP TABLE needp AS SELECT * FROM (VALUES %s) t(bare)" % _sql_values(need_persons))
    alias = con.execute(f"""
        WITH canon AS (
            SELECT n.bare, m.person_id
            FROM needp n JOIN read_parquet({PMAP}) m ON m.author_id = n.bare)
        SELECT c.bare AS person_id, m2.author_id
        FROM canon c JOIN read_parquet({PMAP}) m2 ON m2.person_id = c.person_id""").df()
    mapped = set(alias.person_id)
    alias = pd.concat([alias, pd.DataFrame({"person_id": [p for p in need_persons if p not in mapped],
                                            "author_id": [p for p in need_persons if p not in mapped]})],
                      ignore_index=True)
    con.register("alias_df", alias)
    pedges = con.execute(f"""
        SELECT a.person_id pid, e.publication_year yr, w.subfield_id sf, e.work_id
        FROM read_parquet({U1E}) e
        JOIN alias_df a ON e.author_id = a.author_id
        JOIN read_parquet({U1W}) w ON e.work_id = w.work_id
        WHERE e.publication_year IS NOT NULL""").df()
    # supplements: seed_author rows; meta from PATCH_B, then the u1 works row (the clone's order)
    PATCH_A, PATCH_B = union_cfg["PATCH_A"], union_cfg["PATCH_B"]
    pa = pd.DataFrame([json.loads(l) for l in open(PATCH_A) if l.strip()]) if os.path.exists(PATCH_A) else pd.DataFrame()
    meta_b = {}
    if os.path.exists(PATCH_B):
        for l in open(PATCH_B):
            if l.strip():
                d = json.loads(l)
                meta_b[d["work_id"]] = d
    sup_rows = []
    for l in (list(open(union_cfg["SUP11"])) + list(open(union_cfg["SUP_FNFIX"]))):
        if not l.strip():
            continue
        d = json.loads(l)
        m = meta_b.get(d["work_id"], {})
        sup_rows.append({"pid": d["seed_author"], "work_id": d["work_id"],
                         "yr": d.get("publication_year") or m.get("publication_year"),
                         "sf": m.get("subfield_id")})
    sup_df = pd.DataFrame(sup_rows) if sup_rows else pd.DataFrame(columns=["pid", "work_id", "yr", "sf"])
    need_sf = sup_df[sup_df.sf.isna()].work_id.unique().tolist()
    if need_sf:
        con.execute("CREATE TEMP TABLE nsf AS SELECT * FROM (VALUES %s) t(w)"
                    % ",".join("('" + str(w).replace("'", "''") + "')" for w in need_sf))
        u1sf = con.execute(f"""SELECT w.work_id, w.subfield_id, w.publication_year
            FROM read_parquet({U1W}) w JOIN nsf ON w.work_id = nsf.w""").df()
        m2 = dict(zip(u1sf.work_id, u1sf.subfield_id)); y2 = dict(zip(u1sf.work_id, u1sf.publication_year))
        sup_df["sf"] = sup_df.apply(lambda r: r.sf if pd.notna(r.sf) else m2.get(r.work_id), axis=1)
        sup_df["yr"] = sup_df.apply(lambda r: r.yr if pd.notna(r.yr) else y2.get(r.work_id), axis=1)
    if len(pa):
        pa_d = pa.rename(columns={"author_id": "pid", "publication_year": "yr",
                                  "subfield_id": "sf"})[["pid", "work_id", "yr", "sf"]]
    else:
        pa_d = pd.DataFrame(columns=["pid", "work_id", "yr", "sf"])
    pids_in_pedges = set(pedges.pid)
    cols = ["pid", "yr", "sf", "work_id"]
    sup_only = sup_df[~sup_df.pid.isin(pids_in_pedges)][cols]
    pa_only = pa_d[~pa_d.pid.isin(pids_in_pedges)][cols]
    dose_src = pd.concat([pedges[cols], sup_only, pa_only], ignore_index=True)
    want = set(need_persons)
    rows: dict[str, list] = {}
    for p, g in dose_src.groupby("pid"):
        if p in want:
            rows[p] = [(_source_work(w), yr, sf) for w, yr, sf in zip(g.work_id, g.yr, g.sf)]
    origin = {p: ("pedges" if p in pids_in_pedges else "sup_api") for p in rows}
    ids: dict[str, set] = {}
    for p, a in zip(alias.person_id, alias.author_id):
        try:
            ids.setdefault(p, set()).add(norm_author(a))
        except ValueError:
            ids.setdefault(p, set()).add(str(a))
    # add-back metadata: year from the u1 edge (earliest non-null), else the works row; subfield from works
    work_meta: dict[str, tuple[object, object]] = {}
    aw = sorted({norm_work(w) for w in addback_works})
    if aw:
        forms = aw + [OA + w for w in aw]
        lst = ",".join("'" + f.replace("'", "''") + "'" for f in forms)
        ey = {_source_work(w): y for w, y in con.execute(
            f"SELECT work_id, min(publication_year) FROM read_parquet({U1E}) "
            f"WHERE work_id IN ({lst}) AND publication_year IS NOT NULL GROUP BY 1").fetchall()}
        wr = {}
        for w, sf, y in con.execute(f"SELECT work_id, subfield_id, publication_year FROM read_parquet({U1W}) "
                                    f"WHERE work_id IN ({lst})").fetchall():
            wr.setdefault(_source_work(w), (sf, y))
        for w in aw:
            sf, wy = wr.get(w, (None, None))
            yr = ey.get(w, wy)
            if w in ey or w in wr:
                work_meta[w] = (yr, sf)
    con.close()
    rep = {"persons": len(need_persons), "with_sources": len(rows),
           "origin": {k: v for k, v in (("pedges", sum(o == "pedges" for o in origin.values())),
                                         ("sup_api", sum(o == "sup_api" for o in origin.values()))) if v},
           "rows": int(sum(len(r) for r in rows.values())),
           "alias": {"author_rows": len(alias), "mapped_persons": len(mapped),
                     "multi_alias_persons": int((alias.groupby("person_id").size() > 1).sum())},
           "tables": {k: len(v) for k, v in T.items()},
           "inputs": {k: str(union_cfg[k]) for k in UNION_KEYS}}
    return DoseSources(rows, {p: frozenset(s) for p, s in ids.items()}, origin, work_meta, rep)


# ---------------------------------------------------------------------------------------------
# the frame
# ---------------------------------------------------------------------------------------------

def _split(raw: bytes) -> tuple[bytes, list[bytes], bool]:
    """(header, data lines, trailing newline?) — raw bytes, '\\r' kept (inpost_filter.read_lines)."""
    trailing = raw.endswith(b"\n")
    parts = raw.split(b"\n")
    if trailing:
        parts = parts[:-1]
    return parts[0], parts[1:], trailing


def _cells(line: bytes) -> list[str]:
    return next(csv.reader([line.decode("utf-8").rstrip("\r")]))


def _sha(p: pathlib.Path) -> str:
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def _is_na(cell: str) -> bool:
    return cell.strip() in NA_CELLS


def _event(ev: str) -> tuple[str, int]:
    star, t = ev.split(":")[0], ev.split(":")[1]
    return star, int(t)


def _col_index(hdr: list[str]) -> dict[str, int]:
    miss = [c for c in FRAME_KEY_COLS if c not in hdr]
    if miss:
        raise ValueError(f"the pre-y frame lacks {miss}")
    return {c: hdr.index(c) for c in FRAME_KEY_COLS}


def prodlib_events(path) -> set[str]:
    """The clone's _NEW_EV: f'{author_id}:{int(arrival)}' over the provenance table."""
    with open(path, newline="") as f:
        return {f"{r['author_id']}:{int(r['arrival'])}" for r in csv.DictReader(f)}


def _rewrite_cell(line: bytes, i: int, value: str, width: int) -> bytes:
    cr = line.endswith(b"\r")
    body = line[:-1] if cr else line
    if b'"' in body:
        raise ValueError(f"quoted cell on a line to rewrite: {line[:120]!r}")
    parts = body.split(b",")
    if len(parts) != width:
        raise ValueError(f"line has {len(parts)} cells, header {width}: {line[:120]!r}")
    parts[i] = value.encode("ascii")
    return b",".join(parts) + (b"\r" if cr else b"")


# ---------------------------------------------------------------------------------------------
# the step
# ---------------------------------------------------------------------------------------------

def affected_relations(relations: Iterable[tuple[str, str]], sources: DoseSources,
                       excludes_of: Callable[[str], frozenset], addrows_of: Callable[[str], tuple]) -> dict:
    """{(incumbent cell, event_id): {'colleague': bool, 'star': bool}} for every relation whose
    colleague or star vector at T-1 changes: a counted source row (edge year <= T-1, subfield
    present) of an excluded work, or a counted add-back row."""
    out = {}
    for pid_cell, ev in relations:
        star, t = _event(ev)
        sides = {}
        for side, p in (("colleague", strip(pid_cell)), ("star", star)):
            r = sources.rows.get(p)
            drop = excludes_of(p)
            lost = r is not None and any(w in drop and _counted(y, s, t - 1) for w, y, s in r)
            gained = r is not None and any(_counted(y, s, t - 1) for _w, y, s in addrows_of(p))
            sides[side] = bool(lost or gained)
        if sides["colleague"] or sides["star"]:
            out[(pid_cell, ev)] = sides
    return out


def apply_dose_exclusions(pre_y, out, *, union_cfg: dict, excludes: frozenset,
                          addbacks: frozenset = frozenset(), mode: str | None = None) -> dict:
    """S6 economics post-step. mode 'off' returns {'path': pre_y, 'written': False} and touches
    nothing; 'delta' writes `out` (sha-identical to `pre_y` when there is nothing to remove or add)
    and returns the accounting report; any other mode raises ValueError. DoseRuleMismatch (raised
    before anything is written) = the reimplemented rule does not reproduce the clone's dose."""
    if mode not in MODES:
        raise ValueError(f"S6 dose mode {mode!r} is not signed; one of {MODES}")
    pre_y = pathlib.Path(pre_y)
    if mode == "off":
        return {"mode": "off", "path": str(pre_y), "written": False}
    out = pathlib.Path(out)
    if out.resolve() == pre_y.resolve():
        raise ValueError("apply_dose_exclusions never rewrites the pre-y frame in place")
    excl, excl_other = _norm_excludes(excludes)
    adds = _norm_pairs(addbacks, "addbacks")
    raw = pre_y.read_bytes()
    rep: dict = {"mode": "delta", "input": str(pre_y), "input_sha256": hashlib.sha256(raw).hexdigest(),
                 "calls": {"pairs": len(excl) + len(excl_other), "ids": len({a for a, _ in excl | excl_other}),
                           "non_openalex_pairs": len(excl_other)},
                 "addback_pairs": len(adds)}
    if not excl and not adds:
        _write(out, raw)
        rep.update({"path": str(out), "written": True, "output_sha256": _sha(out), "affected": [],
                    "note": "no exclusions and no add-backs: byte copy"})
        return rep

    header, lines, trailing = _split(raw)
    hdr = _cells(header)
    ci = _col_index(hdr)
    rel_lines: dict[tuple[str, str], list[int]] = {}
    rel_channels: dict[tuple[str, str], set] = {}
    cells_cache: list[list[str]] = []
    for i, ln in enumerate(lines):
        c = _cells(ln)
        cells_cache.append(c)
        k = (c[ci["incumbent_person_id"]], c[ci["event_id"]])
        rel_lines.setdefault(k, []).append(i)
        rel_channels.setdefault(k, set()).add(c[ci["channel"]])
    persons = {strip(p) for p, _ in rel_lines} | {_event(e)[0] for _, e in rel_lines}
    prodlib = prodlib_events(union_cfg["NEW_EVENTS"])
    src = load_dose_sources(union_cfg, persons, addback_works={w for _, w in adds})
    rep["sources"] = src.report

    # calls / add-backs per person (a call under any of the person's ids)
    excl_by_author: dict[str, set] = {}
    for a, w in excl:
        excl_by_author.setdefault(a, set()).add(w)
    add_by_author: dict[str, set] = {}
    for a, w in adds:
        add_by_author.setdefault(a, set()).add(w)
    _e: dict[str, frozenset] = {}

    def excludes_of(p: str) -> frozenset:
        if p not in _e:
            _e[p] = frozenset().union(*(excl_by_author.get(a, ()) for a in src.ids_of(p)))
        return _e[p]

    ab = {"entered": 0, "already_present": 0, "excluded": 0, "unresolved": 0, "person_without_sources": 0}
    _a: dict[str, tuple] = {}

    def addrows_of(p: str) -> tuple:
        if p not in _a:
            got = []
            for w in sorted(frozenset().union(*(add_by_author.get(a, ()) for a in src.ids_of(p)))):
                if w in excludes_of(p):
                    ab["excluded"] += 1
                elif p not in src.rows:
                    ab["person_without_sources"] += 1
                elif w in src.present[p]:
                    ab["already_present"] += 1
                elif w not in src.work_meta:
                    ab["unresolved"] += 1
                else:
                    yr, sf = src.work_meta[w]
                    got.append((w, yr, sf))
                    ab["entered"] += 1
            _a[p] = tuple(got)
        return _a[p]

    for p in sorted(persons):
        addrows_of(p)
    rep["addbacks"] = ab
    frame_ids = {a for p in persons for a in src.ids_of(p)}
    rep["calls"].update({
        "pairs_of_frame_persons": sum(a in frame_ids for a, _ in excl),
        "pairs_in_frame_sources": sum(1 for p in persons for w in excludes_of(p) if w in src.present.get(p, ())),
    })

    vcache: dict[tuple, dict | None] = {}

    def vec(p: str, t1: int, fixed: bool) -> dict | None:
        k = (p, t1, fixed)
        if k not in vcache:
            rows = src.fixed_rows(p, excludes_of(p), addrows_of(p)) if fixed else src.rows.get(p)
            vcache[k] = DoseSources.vector_of(rows, t1)
        return vcache[k]

    # ---- self-check: the clone's own rows (dept_only, prodlib events) ---------------------------
    sc = {"relations": 0, "rows": 0, "missing_side": 0, "stored_na_rows": 0, "mismatches": 0, "max_abs_diff": 0.0}
    bad: list[dict] = []
    di = ci["dose_topic"]
    for k, idx in rel_lines.items():
        pid_cell, ev = k
        if not ("dept_only" in rel_channels[k] or ev in prodlib):
            continue
        star, t = _event(ev)
        cur = src.cos(vec(strip(pid_cell), t - 1, False), vec(star, t - 1, False))
        sc["relations"] += 1
        if cur is None:
            sc["missing_side"] += 1
            continue
        for i in idx:
            s = cells_cache[i][di]
            if _is_na(s):
                sc["stored_na_rows"] += 1
                continue
            sc["rows"] += 1
            d = abs(cur - float(s))
            sc["max_abs_diff"] = max(sc["max_abs_diff"], d)
            if d > SELF_CHECK_TOL:
                sc["mismatches"] += 1
                if len(bad) < 50:
                    bad.append({"incumbent_person_id": pid_cell, "event_id": ev, "line": i + 2,
                                "channel": cells_cache[i][ci["channel"]], "stored": s, "current": repr(cur)})
    rep["self_check"] = sc
    if bad:
        raise DoseRuleMismatch(
            f"the reimplemented dose rule differs from the clone's on {sc['mismatches']} row(s) of dept_only/"
            f"prodlib relations (max {sc['max_abs_diff']:.3g} > {SELF_CHECK_TOL}); STOP, nothing written", bad)

    # ---- the affected relations, delta mode -----------------------------------------------------
    aff = affected_relations(rel_lines.keys(), src, excludes_of, addrows_of)
    R = {"total": len(rel_lines), "affected": len(aff), "affected_uncomputable": 0, "affected_stored_na": 0,
         "delta_nonzero": 0, "changed": 0, "delta_abs_gt_0.01": 0, "delta_abs_gt_0.05": 0,
         "stored_positive_to_zero": 0, "current_positive_to_fixed_zero": 0,
         "events_affected": len({e for _, e in aff}), "events_delta_nonzero": 0, "events_changed": 0}
    sides = {"delta_nonzero": {"colleague_only": 0, "star_only": 0, "both": 0},
             "changed": {"colleague_only": 0, "star_only": 0, "both": 0}}
    dcalls, drule = [], []
    rule_rows = {"rows": 0, "nonzero_gt_1e-12": 0, "max_abs": 0.0}
    left = 0
    new_lines = list(lines)
    rows_changed = 0
    ev_nz, ev_ch = set(), set()
    width = len(hdr)
    for k, sd in aff.items():
        pid_cell, ev = k
        pid = strip(pid_cell)
        star, t = _event(ev)
        cur = src.cos(vec(pid, t - 1, False), vec(star, t - 1, False))
        fix = src.cos(vec(pid, t - 1, True), vec(star, t - 1, True))
        if cur is None or fix is None:
            R["affected_uncomputable"] += 1
            continue
        for p, on in ((pid, sd["colleague"]), (star, sd["star"])):
            if on:
                drop = excludes_of(p)
                left += sum(1 for w, y, s in src.fixed_rows(p, drop, addrows_of(p)) if w in drop and _counted(y, s, t - 1))
        delta = fix - cur
        side = "both" if sd["colleague"] and sd["star"] else ("colleague_only" if sd["colleague"] else "star_only")
        dcalls.append((abs(delta), pid_cell, ev, cur, fix))
        if delta != 0.0:
            R["delta_nonzero"] += 1
            sides["delta_nonzero"][side] += 1
            ev_nz.add(ev)
        R["delta_abs_gt_0.01"] += abs(delta) > 0.01
        R["delta_abs_gt_0.05"] += abs(delta) > 0.05
        R["current_positive_to_fixed_zero"] += cur > 0.0 and fix == 0.0
        changed = to_zero = had_na = False
        rmax = 0.0
        for i in rel_lines[k]:
            s = cells_cache[i][di]
            if _is_na(s):
                had_na = True
                continue
            st = float(s)
            rule = cur - st
            rule_rows["rows"] += 1
            rule_rows["nonzero_gt_1e-12"] += abs(rule) > 1e-12
            rmax = max(rmax, abs(rule))
            new = min(1.0, max(0.0, st + delta))
            if new != st:
                new_lines[i] = _rewrite_cell(lines[i], di, repr(float(new)), width)
                rows_changed += 1
                changed = True
                to_zero |= (st > 0.0 and new == 0.0)
        rule_rows["max_abs"] = max(rule_rows["max_abs"], rmax)
        drule.append((rmax, pid_cell, ev))
        R["affected_stored_na"] += had_na
        R["stored_positive_to_zero"] += to_zero
        if changed:
            R["changed"] += 1
            sides["changed"][side] += 1
            ev_ch.add(ev)
    R["events_delta_nonzero"], R["events_changed"] = len(ev_nz), len(ev_ch)
    R = {k: int(v) for k, v in R.items()}
    dcalls.sort(key=lambda x: (-x[0], x[1], x[2]))
    drule.sort(key=lambda x: (-x[0], x[1], x[2]))
    rep["relations"] = R
    rep["sides"] = sides
    rep["rows_changed"] = rows_changed
    rep["delta_calls"] = {"what": "fixed - current (applied)", "n": len(dcalls),
                          "n_nonzero": int(sum(1 for d in dcalls if d[0] != 0.0)),
                          "max_abs": dcalls[0][0] if dcalls else 0.0,
                          "largest": [{"incumbent_person_id": p, "event_id": e, "current": c, "fixed": f}
                                      for _d, p, e, c, f in dcalls[:12]]}
    rep["delta_rule"] = {"what": "current - stored (the July gap, NOT applied)", **rule_rows,
                         "largest": [{"incumbent_person_id": p, "event_id": e, "max_abs": d} for d, p, e in drule[:12]]}
    rep["excluded_left_in_fixed"] = int(left)
    rep["affected"] = sorted([p, e] for p, e in aff)

    body = b"\n".join([header] + new_lines) + (b"\n" if trailing else b"")
    if rows_changed == 0:
        assert body == raw, "no cell changed, yet the rebuilt bytes differ from the input"
    _write(out, body)
    rep.update({"path": str(out), "written": True, "output_sha256": _sha(out)})
    return rep


def _write(out: pathlib.Path, data: bytes) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, out)


def dose_rows_proof(before, after, affected: Iterable[tuple[str, str]]) -> dict:
    """In-run gate: `after` equals `before` byte for byte except, on rows of the `affected`
    relations ((incumbent cell, event_id)), the dose_topic cell, which must hold repr(float(x)) with
    0 <= x <= 1. Same header, same line count, same trailing newline."""
    before, after = pathlib.Path(before), pathlib.Path(after)
    hb, lb, tb = _split(before.read_bytes())
    ha, la, ta = _split(after.read_bytes())
    aff = {(str(p), str(e)) for p, e in affected}
    bad: list[dict] = []
    if hb != ha:
        bad.append({"what": "header differs"})
    if tb != ta:
        bad.append({"what": "trailing newline differs"})
    if len(lb) != len(la):
        bad.append({"what": "line count differs", "before": len(lb), "after": len(la)})
    names = _cells(hb)
    ci = _col_index(names)
    di = ci["dose_topic"]
    identical = rewritten = 0
    rels = set()
    for n, (b, a) in enumerate(zip(lb, la)):
        if b == a:
            identical += 1
            continue
        cb, ca = _cells(b), _cells(a)
        key = (cb[ci["incumbent_person_id"]], cb[ci["event_id"]])
        rb, ra = b.rstrip(b"\r").split(b","), a.rstrip(b"\r").split(b",")
        diff = [j for j in range(max(len(rb), len(ra))) if j >= len(rb) or j >= len(ra) or rb[j] != ra[j]]
        ok = (diff == [di] and key in aff and len(cb) == len(ca) and b.endswith(b"\r") == a.endswith(b"\r"))
        if ok:
            try:
                x = float(ca[di])
                ok = repr(x) == ca[di] and 0.0 <= x <= 1.0
            except ValueError:
                ok = False
        if ok:
            rewritten += 1
            rels.add(key)
        elif len(bad) < 20:
            bad.append({"what": "unexpected difference", "line": n + 2, "key": list(key),
                        "cells": [names[j] if j < len(names) else j for j in diff]})
        else:
            bad.append({"what": "unexpected difference"})
    return {"closed": not bad, "lines": len(lb), "identical": identical, "rewritten_rows": rewritten,
            "rewritten_relations": len(rels), "n_bad": len(bad), "bad": bad[:20],
            "before_sha256": _sha(before), "after_sha256": _sha(after)}
