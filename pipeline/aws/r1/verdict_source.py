#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R1 F16+N1: the one verdict source every event writer reads (events_r1, stage.py, econ920_m, D7).

    import verdict_source as vs                  # consumers put pipeline/aws/r1 on sys.path; never copy this
    src = vs.load(RANK_TABLES_DIR)               # the stage output of restake_r1.py (kind.json: B0 | M)
    lines, lines_p05, dropped = vs.filter_october_rows(field, text_0828, vs.read_corrections(CORR), src)

* B0 - caliber_2026-10/write_events.py's semantics, byte for byte: economics keep = event_keep of
  restake_econ11_aug_2026-10.csv (17 rows; a star with no row keeps its event), economics p05 =
  after_pass_p05 and event_keep of restake_econ11_aug_all_2026-10.csv; chemistry and mathematics = the
  run-2 verdicts (verdicts_2026-10.csv: event_cal2026_10, event_p05), except AUTHOR_KEEP. new_events: none.
* M - the signed rank tables (restake_econ_r1.csv, verdicts_chemmath_r1.csv): verdicts from the signed
  lists (KEEP/ACCEPT keep, DROP drops), p05 from the tables and never for a dropped star. Every event star
  must have a row of its field: VerdictMissing otherwise. No AUTHOR_KEEP, no default keep.

row() is the rank that admitted the star (aage, after_pct, after_cell_n, arrival, school, rank_pass,
event_id_old). Existing October economics events keep their frozen star_set academic age in the frame
(ruling, author pending): the consumer uses row()['aage'] for new events and reports the differences.
No ranking happens here; this module reads only the rank-tables directory it is given.
"""
from __future__ import annotations

import csv
import io
import json
import pathlib

SCHEMA = "sar.r1.rank_tables.v1"
FIELDS = ("econ", "chemistry", "math_stats")
ID_COL = {"econ": 1, "chemistry": 2, "math_stats": 2}
B0_ECON_KEEP = "restake_econ11_aug_2026-10.csv"
B0_ECON_P05 = "restake_econ11_aug_all_2026-10.csv"
B0_CHEMMATH = "verdicts_2026-10.csv"
M_ECON = "restake_econ_r1.csv"
M_CHEMMATH = "verdicts_chemmath_r1.csv"
VERDICTS = {"KEEP": True, "ACCEPT": True, "DROP": False}
# caliber_2026-10/write_events.py, verbatim (a test holds the two equal); applied in B0 only
AUTHOR_KEEP = {"A5083769806": "kept by author ruling 2026-08-13"}


class VerdictMissing(LookupError):
    """M: an event star has no row of its field in the signed rank tables (STOP)."""

    def __init__(self, field: str, author_id: str, where: str):
        self.field, self.author_id = field, author_id
        super().__init__(f"VERDICT_MISSING {field} {author_id}: no row in {where}")


def _read(p: pathlib.Path) -> list[dict]:
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _int(v):
    return None if v in (None, "") else int(v)


def _float(v):
    return None if v in (None, "") else float(v)


def _field(field: str) -> str:
    if field not in FIELDS:
        raise ValueError(f"unknown field {field!r} (one of {FIELDS})")
    return field


def read_corrections(path) -> dict[str, str]:
    """star_id_corrections_2026-10.csv -> {old_id: new_id}, as write_events.main() reads it."""
    return {r["old_id"]: r["new_id"] for r in _read(pathlib.Path(path))}


def _by_id(rows: list[dict], key, where: str) -> dict:
    out = {}
    for r in rows:
        k = key(r)
        if k in out:
            raise ValueError(f"{where}: two rows for {k}")
        out[k] = r
    return out


class Source:
    """The verdicts of one rank-tables directory. Build it with load()."""

    def __init__(self, kind: str, d: pathlib.Path):
        self.kind, self.dir = kind, d
        self.kept_by_author_ruling: list[dict] = []
        if kind == "B0":
            # write_events.main(): the 17-row keep file, the aug_all p05 file, run-2 verdicts keyed by id only
            self._econ17 = {r["author_id"]: r for r in _read(d / B0_ECON_KEEP)}
            self._econ_all = {r["author_id"]: r for r in _read(d / B0_ECON_P05)}
            self._cm = {r["author_id"]: r for r in _read(d / B0_CHEMMATH) if r["field"] != "econ"}
        else:
            econ = _read(d / M_ECON)
            cm = _read(d / M_CHEMMATH)
            for r in cm:
                if r["field"] not in ("chemistry", "math_stats"):
                    raise ValueError(f"{M_CHEMMATH}: {r['author_id']} has field {r['field']!r}")
            self._m = {"econ": _by_id(econ, lambda r: r["author_id"], M_ECON)}
            both = _by_id(cm, lambda r: (r["field"], r["author_id"]), M_CHEMMATH)
            for f in ("chemistry", "math_stats"):
                self._m[f] = {a: r for (g, a), r in both.items() if g == f}
            for f, rows in self._m.items():
                for a, r in rows.items():
                    self._check_m_row(f, a, r)

    @staticmethod
    def _keep_col(field: str) -> str:
        return "event_keep" if field == "econ" else "event_cal2026_10"

    @staticmethod
    def _p05_col(field: str) -> str:
        return "after_pass_p05" if field == "econ" else "event_p05"

    def _check_m_row(self, field: str, a: str, r: dict) -> None:
        """The table must say what the signed list says: KEEP/ACCEPT keep, DROP does not; REJECT is never written;
        an ACCEPT star has no October event."""
        v = r.get("verdict", "")
        if v not in VERDICTS:
            raise ValueError(f"{field} {a}: verdict {v!r} is not one of {sorted(VERDICTS)} (REJECT rows are not written)")
        if (r[self._keep_col(field)] == "True") != VERDICTS[v]:
            raise ValueError(f"{field} {a}: {self._keep_col(field)}={r[self._keep_col(field)]!r} disagrees with verdict {v}")
        if v == "ACCEPT" and r.get("event_id_old"):
            raise ValueError(f"{field} {a}: ACCEPT row names an October event {r['event_id_old']!r}")

    def _m_row(self, field: str, a: str) -> dict:
        r = self._m[field].get(a)
        if r is None:
            raise VerdictMissing(field, a, M_ECON if field == "econ" else M_CHEMMATH)
        return r

    def keep(self, field: str, author_id: str) -> bool:
        field, a = _field(field), author_id
        if self.kind == "M":
            return self._m_row(field, a)[self._keep_col(field)] == "True"
        if field == "econ":
            return self._econ17[a]["event_keep"] == "True" if a in self._econ17 else True
        v = self._cm.get(a)
        if v is None:
            return True
        if v["event_cal2026_10"] == "True":
            return True
        if a in AUTHOR_KEEP:
            rec = {"star": a, "why": AUTHOR_KEEP[a], "machine_pct": v["after_pct"]}
            if rec not in self.kept_by_author_ruling:
                self.kept_by_author_ruling.append(rec)
            return True
        return False

    def p05(self, field: str, author_id: str) -> bool:
        field, a = _field(field), author_id
        if self.kind == "M":
            r = self._m_row(field, a)
            return r[self._p05_col(field)] == "True" and r[self._keep_col(field)] == "True"
        if field == "econ":
            r = self._econ_all.get(a)
            return bool(r) and r["after_pass_p05"] == "True" and r["event_keep"] == "True"
        v = self._cm.get(a)
        return bool(v) and v["event_p05"] == "True"

    def row(self, field: str, author_id: str) -> dict:
        """The admitting rank's row. B0 economics: the restake_econ11_aug row (its aage is the one
        econ920's rekeyed_star_set checks), else the aug_all row; B0 chemistry/maths: the run-2 verdict."""
        field, a = _field(field), author_id
        if self.kind == "M":
            r = self._m_row(field, a)
        elif field == "econ":
            r = self._econ17.get(a) or self._econ_all.get(a)
            if r is None:
                raise VerdictMissing(field, a, f"{B0_ECON_KEEP} / {B0_ECON_P05}")
        else:
            r = self._cm.get(a)
            if r is None or r["field"] != field:
                raise VerdictMissing(field, a, B0_CHEMMATH)
        return {"aage": _int(r["aage"]), "after_pct": _float(r["after_pct"]),
                "after_cell_n": _int(r["after_cell_n"]), "arrival_true": int(r["arrival_true"]),
                "school": r["school"], "rank_pass": r.get("rank_pass") or None,
                "event_id_old": r.get("event_id_old") or None}

    def new_events(self, field: str) -> list[dict]:
        """M: the ACCEPT stars (signed add list), in table order - stars with no 08-28 event. B0: none."""
        field = _field(field)
        if self.kind == "B0":
            return []
        return [{"author_id": a, "field": field, "name": "", **self.row(field, a)}
                for a, r in self._m[field].items() if r["verdict"] == "ACCEPT"]


def load(rank_tables_dir) -> Source:
    d = pathlib.Path(rank_tables_dir)
    meta = json.loads((d / "kind.json").read_text(encoding="utf-8"))
    if meta.get("schema") != SCHEMA:
        raise ValueError(f"{d / 'kind.json'}: schema {meta.get('schema')!r}, want {SCHEMA}")
    if meta.get("kind") not in ("B0", "M"):
        raise ValueError(f"{d / 'kind.json'}: kind {meta.get('kind')!r} is not B0 or M")
    return Source(meta["kind"], d)


def filter_october_rows(field: str, src_text: str, corr: dict, source: Source):
    """caliber_2026-10/write_events.py write()'s loop, lifted verbatim: the 2026-08-28 rows with the star-id
    corrections applied, filtered by source.keep, and the p05 subset by source.p05.
    Returns (lines, lines_p05, dropped); both line lists start with the header, and a file is
    "\\n".join(lines) + "\\n"."""
    id_col = ID_COL[_field(field)]
    key_fn = (lambda f: f[0]) if field == "econ" else (lambda f: f"{f[2]}:{f[1]}")
    lines = [ln for ln in src_text.split("\n") if ln]
    hdr, body = lines[0], lines[1:]
    out, out05, dropped = [hdr], [hdr], []
    for ln in body:
        f = next(csv.reader([ln]))
        old = f[id_col]
        new = corr.get(old, old)
        if new != old:
            f[id_col] = new
            if field == "econ":
                f[0] = f[0].replace(old, new)
            buf = io.StringIO(); csv.writer(buf, lineterminator="").writerow(f); ln = buf.getvalue()  # noqa: E702
        if not source.keep(field, new):
            dropped.append({"field": field, "event": key_fn(f), "star": new})
            continue
        out.append(ln)
        if source.p05(field, new):
            out05.append(ln)
    return out, out05, dropped
