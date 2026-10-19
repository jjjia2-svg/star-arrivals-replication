# -*- coding: utf-8 -*-
"""caliber_2026-08-28/restake_equiv.py — the equivalent of `72_restake_fnfix_stars.py`, built in the
caliber layer because the ported `72` cannot accept an injected first_pub without editing ported
code (which M3's verbatim rule forbids). Repo-authored.

Fidelity contract, stated so it can fail:

* Every query and every formula below that is not the override branch is copied from
  `pipeline/stars/multidisc_gold_2026-08-10/code/72_restake_fnfix_stars.py` — the aw_raw build
  (:51-55), the per-Y `_POOL_SQL` ranking (:64), the econ forced-subfield re-rank (:72-78), the
  4-dp rounding (:87, finding F2 kept), and the `pass_p10` WITHOUT the age gate (:91, finding F1
  kept — D-A lives in `caliber.gate_age`, applied downstream, never smuggled in here).
* The override branch is the ONE addition: a candidate with a dossier-anchored first_pub is written
  with `aage = (Y − anchor)` and, when that moves his milojevic bin, re-ranked in the anchored bin
  by the SAME `+1` convention the ported `72` already uses for a candidate ranked in a cell that
  does not natively contain him (the ECON_SF path, `72_…py:72-78`).
* Equivalence is PROVED, not asserted: `run_caliber.py` runs this machine on the frozen 67-row
  inputs with no overrides and requires the produced rows to be byte-identical to the frozen
  `fnfix_restake_2026-08-15.csv` rows for the proof candidates.

The ranking machine (`_POOL_SQL`, `screening_lib`) is imported from THIS repository's ported copy,
the same way `run_stars.py` pre-imports it, and the origin of both modules is asserted.
"""
from __future__ import annotations

import csv
import os
import pathlib
import sys
from collections import defaultdict

REPO = pathlib.Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))

SCREENING = REPO / "pipeline" / "stars" / "multidisc_2026-07-24" / "code" / "star_screening"

ECON_SF = "2002"                    # 72_…py:36 — economics' forced subfield

RESTAKE_HEADER = ["author_id", "name", "field", "school", "arrival_true", "before_stock",
                  "before_cell", "before_pct", "before_pass", "after_stock", "after_cell",
                  "after_cell_n", "after_pct", "after_pass", "note", "aage"]


def _screening_modules():
    """The repo's ported ranking machine, origin-asserted (same rule as run_stars.py)."""
    if str(SCREENING) not in sys.path:
        sys.path.insert(0, str(SCREENING))
    import screening_lib as L                       # noqa: PLC0415
    from run_screening import _POOL_SQL             # noqa: PLC0415
    import run_screening                            # noqa: PLC0415
    for mod in (L, run_screening):
        origin = pathlib.Path(getattr(mod, "__file__", "")).resolve()
        if origin.parent != SCREENING:
            raise RuntimeError(f"{mod.__name__} resolved to {origin}, not the repo's ported copy")
    return L, _POOL_SQL


def connect(duck_tmp: pathlib.Path):
    """A DuckDB session with 72's exact pragmas (:46-49) and the cbin function."""
    import duckdb                                   # noqa: PLC0415
    L, _ = _screening_modules()
    con = duckdb.connect()
    con.execute("PRAGMA threads=6")
    con.execute("PRAGMA memory_limit='12GB'")
    duck_tmp.mkdir(parents=True, exist_ok=True)
    con.execute(f"PRAGMA temp_directory='{duck_tmp}'")
    con.create_function("cbin", lambda a: L.cohort_bin(int(a)), ["INTEGER"], "VARCHAR")
    return con


def load_aw_raw(con) -> int:
    """72_…py:51-55 verbatim: the SSD authorship-edges × works join."""
    from pipeline.lib.paths import derived_root, require_readable      # noqa: PLC0415
    ssd = pathlib.Path(str(require_readable(derived_root() / "u1_edges_full_2026-07-05")))
    ep = ssd.as_posix()
    con.execute(f"""CREATE TEMP TABLE aw_raw AS
    SELECT e.author_id aid, e.work_id wid, w.publication_year yr, w.cited_by_count c, w.subfield_id sf
    FROM read_parquet('{ep}/authorship_edges/**/*.parquet') e
    JOIN read_parquet('{ep}/works/**/*.parquet') w ON e.work_id = w.work_id
    WHERE w.publication_year IS NOT NULL""")
    return con.execute("SELECT count(*) FROM aw_raw").fetchone()[0]


def _stats(con, cands, label, L, pool_sql, overrides=None):
    """72_…py stats() (:59-94), plus the override branch (after-pass only; see module docstring)."""
    overrides = overrides or {}
    by_Y = defaultdict(list)
    for c in cands:
        by_Y[int(c["arrival_true"]) - 1].append(c)
    out = {}
    for i, Y in enumerate(sorted(by_Y), 1):
        con.execute(pool_sql.format(Y=Y, GAP=L.ROBUST_FIRST_PUB_MAX_GAP))
        ids = ",".join(f"'{c['author_id']}'" for c in by_Y[Y])
        got = {r[0]: r for r in con.execute(
            f"SELECT aid, stock, subfield, age_bin, aage, rnk, cell_n FROM poolY WHERE aid IN ({ids})").fetchall()}
        need = [c["author_id"] for c in by_Y[Y] if c["field"] == "econ" and c["author_id"] in got
                and str(got[c["author_id"]][2]).rsplit("/", 1)[-1] != ECON_SF]
        if need:
            idn = ",".join(f"'{a}'" for a in need)
            for r in con.execute(f"""
                WITH me AS (SELECT aid, stock, age_bin, aage FROM poolY WHERE aid IN ({idn})),
                cell AS (SELECT age_bin, stock FROM poolY WHERE subfield='{ECON_SF}')
                SELECT me.aid, me.stock, '{ECON_SF}', me.age_bin, me.aage,
                       1 + (SELECT count(*) FROM cell c WHERE c.age_bin=me.age_bin AND c.stock>me.stock) rnk,
                       (SELECT count(*) FROM cell c WHERE c.age_bin=me.age_bin) + 1 cell_n
                FROM me""").fetchall():
                got[r[0]] = r
        for c in by_Y[Y]:
            r = got.get(c["author_id"])
            if not r:
                out[c["author_id"]] = {"stock": None, "cell": None, "aage": None, "rnk": None,
                                       "cell_n": None, "pct": None, "estimable": False,
                                       "pass_p10": False, "note": "not_in_pool"}
                continue
            _, stock, sub, ab, aage, rnk, cn = r
            note = ""
            if c["author_id"] in overrides:
                if c["field"] == "econ":
                    raise NotImplementedError(
                        "first_pub override for an econ candidate would interact with the ECON_SF "
                        "re-rank branch; no signed ruling needs it — refusing rather than guessing")
                fp_o = int(overrides[c["author_id"]])
                aage_o = Y - fp_o
                ab_o = L.cohort_bin(aage_o)
                if ab_o != str(ab):
                    # the 72 ECON_SF "+1" convention, in the dossier-anchored bin
                    rnk, cn = con.execute(f"""
                        SELECT 1 + (SELECT count(*) FROM poolY p WHERE p.subfield = me.subfield
                                    AND p.age_bin = '{ab_o}' AND p.stock > me.stock),
                               (SELECT count(*) FROM poolY p WHERE p.subfield = me.subfield
                                    AND p.age_bin = '{ab_o}') + 1
                        FROM poolY me WHERE me.aid = '{c["author_id"]}'""").fetchone()
                    note = f"first_pub_override={fp_o};rebinned {ab}->{ab_o} (+1 convention, 72 econ path)"
                    ab = ab_o
                elif int(aage) != aage_o:
                    note = f"first_pub_override={fp_o};aage {aage}->{aage_o} (same bin)"
                aage = aage_o
            pct = round(1 - rnk / cn, 4)
            out[c["author_id"]] = {"stock": int(stock), "cell": f"{str(sub).rsplit('/',1)[-1]}|{ab}",
                                   "aage": int(aage), "rnk": int(rnk), "cell_n": int(cn), "pct": pct,
                                   "estimable": cn >= L.CELL_MIN_N["floor"],
                                   "pass_p10": (pct >= 1 - L.P10) and cn >= L.CELL_MIN_N["floor"],
                                   "note": note}
        print(f"  [{label}] Y={Y} ({i}/{len(by_Y)}) done", flush=True)
    return out


def restake(con, cands, drop_pairs, out_csv: pathlib.Path, overrides=None) -> list[list]:
    """72_…py:97-116: before on aw_raw, after on aw_raw minus the drops; identical CSV shape.

    `con` must already hold aw_raw (load_aw_raw). Overrides apply to the AFTER pass only — the
    first_pub correction is part of the same per-paper identity cleanup the drops belong to."""
    L, pool_sql = _screening_modules()
    con.execute("CREATE OR REPLACE TEMP TABLE aw AS SELECT aid, yr, c, sf FROM aw_raw")
    before = _stats(con, cands, "before", L, pool_sql)
    con.execute("CREATE OR REPLACE TEMP TABLE dropt(aid VARCHAR, wid VARCHAR)")
    if drop_pairs:
        con.executemany("INSERT INTO dropt VALUES (?,?)", sorted(drop_pairs))
    con.execute("""CREATE OR REPLACE TEMP TABLE aw AS
        SELECT aid, yr, c, sf FROM aw_raw r WHERE NOT EXISTS (SELECT 1 FROM dropt d WHERE d.aid=r.aid AND d.wid=r.wid)""")
    after = (_stats(con, cands, "after", L, pool_sql, overrides=overrides)
             if drop_pairs or overrides else before)
    rows = []
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(RESTAKE_HEADER)
        for c in cands:
            b, a = before[c["author_id"]], after[c["author_id"]]
            row = [c["author_id"], c["name"], c["field"], c["school"], c["arrival_true"],
                   b["stock"], b["cell"], b["pct"], b["pass_p10"], a["stock"], a["cell"],
                   a["cell_n"], a["pct"], a["pass_p10"], a["note"] or b["note"], a["aage"]]
            w.writerow(row)
            rows.append(row)
            print(f"  {c['author_id']} {c['name'][:26]:26s} {c['field'][:4]} arr={c['arrival_true']} "
                  f"before {b['stock']} pct {b['pct']} -> after {a['stock']} pct {a['pct']} "
                  f"pass={a['pass_p10']} {a['note']}", flush=True)
    return rows


def csv_lines_by_author(path: pathlib.Path) -> dict[str, str]:
    """Raw (byte-faithful) data lines of a restake-shaped CSV, keyed by author_id.

    Read as BYTES, not text: `read_text()` runs universal-newline translation, which silently
    strips the `\\r` of the gold CSVs' `\\r\\n` endings and turns a byte comparison into a
    newline-normalised one. Split on `\\n`; every line keeps its trailing `\\r`."""
    text = path.read_bytes().decode("utf-8")
    lines = [ln for ln in text.split("\n") if ln]
    return {ln.split(",", 1)[0]: ln for ln in lines[1:]}
