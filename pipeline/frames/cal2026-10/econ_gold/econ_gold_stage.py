#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cal2026-10/econ_gold/econ_gold_stage.py — staging, shape adapters and row-level accounting for
running ECONOMICS through the chemistry/mathematics gold chain (the three `_econ` clones beside
this file). Repo-authored library, 2026-09-22; edits no ported file and no frozen artifact.

What the gold chain expects and what economics has (the two id conventions, measured 2026-09-22):

  gold layout (chem/math)                         economics (frozen frames, 2026-08-28 caliber)
  incumbent_person_id  bare  `A5…`                `P_A5…`  (network rows: the U2 person id, which is
                                                  always `P_` + one member author id — measured
                                                  487,688/487,688; roster rows: `P_` + author_id)
  star_person_id       bare                       `P_` + star author id
  event_id             `star:school`              `star:arrival_year`
  signed ledger        field,school,author_id,    event_id,star_id,school,arrival_year,… (the
                       display_name,arrival_      cal event table, `data/raw_verified/
                       corrected,evidence_grade,  events_econ_cal2026-08-28.csv` shape)
                       evidence_url,signature
  base ledger          event_id,arrival_year      (none)
  person map           multidisc seeds parquet    U2 11-school map (`person_map/data.parquet`)

The three clones keep every computation line of the pinned originals, so the shapes are converted
OUTSIDE them, here, and converted back after: `adapt_network_frame` (P_ stripped on both id
columns, event ids relabelled star:year -> star:school through the event table — a bijection
because no economics star has two events, asserted) and `restore_p1` / `restore_p2` (the exact
inverse, plus the legacy row order for the dept-only block). Both directions preserve every other
cell byte for byte, so the accounting below compares the chain's output with the frozen frames
cell by cell rather than through any tolerance.

The network POOL (D2/D4 of the 2026-09-22 rules: the network route's population is the verified
roster) is applied to the network frame before staging: a network row is kept when its incumbent
id is `P_<author_id>` of a roster author OR the U2 person id of a roster author — the identity
rule of `analysis/robustness/verified_pool/build_verified_pool.py` (its `ver_p`), so on the 920
roster the persons dropped must be exactly that build's 162 excluded persons (checked by the
driver, a positive control of the filter).

Shadow: economics inputs are staged at the gold layout's fnfix names inside a private shadow of
the legacy tree (`$SAR_LEGACY_THESIS`, the frames_stage.py mechanism of the 2026-08-28 caliber),
every entry recorded with its origin and sha256, so the clones' path lines did not have to move.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import pathlib
import sys

import duckdb

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[3]
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))
CAL0828 = REPO / "pipeline" / "stars" / "caliber_2026-08-28"
if str(CAL0828) not in sys.path:
    sys.path.insert(0, str(CAL0828))
import frames_stage as fs  # noqa: E402  (Shadow, sha, real_v2, ulps, read_frame_rows, keyed accounting)

#: the gold layout's fnfix names at which the economics inputs are staged (relative to v2_output)
GOLD = "multidisc_gold_2026-08-10"
STAGED = {
    "network_frame": f"{GOLD}/runs/fnfix/econ/data/analysis_frame_p01_52ev_topicdose_2026-07-21.csv",
    "roster": f"{GOLD}/data/fnfix/roster_gold_econ.parquet",
    "ledger": f"{GOLD}/data/events_econ_fnfix_2026-08-10.csv",
    "ledger_base": f"{GOLD}/data/events_econ_fnfixbase_2026-08-10.csv",
    "ledger_signed_loop": f"{GOLD}/data/events_econ_gold_2026-08-10.csv",
    "stars_excluded": f"{GOLD}/data/stars_excluded_fnfix.parquet",
    "supplement": f"{GOLD}/data/edges_supplement_fnfix.jsonl",
}
#: frozen legacy files the clones resolve through legacy_thesis() and the caliber does not change
FROZEN_LINKS = (
    "multidisc_2026-07-24/code/roster_lib.py",
    "fwci_fullsnapshot_rebuild_2026-08-09/data/fwci_expected_fullsnapshot_2026-08-09.parquet",
)
ROSTERLIB_REL = "multidisc_2026-07-24/code/roster_lib.py"

FRAME_COLS = ["incumbent_person_id", "year", "star_person_id", "event_id", "treated",
              "post", "dose_coupling_baseline", "dose_topic", "dose_low_confidence",
              "age_gap", "fwci_frac", "pub_count", "fwci_frac_ex_star",
              "pub_count_ex_star", "fwci_mean", "fwci_mean_ex_star"]
P2_COLS = ["pid", "star", "event_id", "channel", "year", "tau", "post", "y"]


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ---------------------------------------------------------------------------------------------
# events
# ---------------------------------------------------------------------------------------------

class EventMap:
    """The economics event table and the star:year <-> star:school bijection."""

    def __init__(self, events_csv: pathlib.Path):
        rows = list(csv.DictReader(open(events_csv, encoding="utf-8")))
        need = {"event_id", "star_id", "school", "arrival_year"}
        assert need <= set(rows[0]), (events_csv, sorted(set(rows[0])))
        self.rows = rows
        self.by_star = {}
        for r in rows:
            assert r["event_id"] == f"{r['star_id']}:{int(r['arrival_year'])}", r["event_id"]
            assert r["star_id"] not in self.by_star, (
                f"star {r['star_id']} has two events — star:school is not a bijection of star:year")
            self.by_star[r["star_id"]] = (r["school"], int(r["arrival_year"]))
        self.econ_ids = {f"{s}:{y}" for s, (_, y) in self.by_star.items()}
        self.gold_ids = {f"{s}:{sch}" for s, (sch, _) in self.by_star.items()}
        assert len(self.gold_ids) == len(self.econ_ids) == len(rows)

    def to_gold(self, econ_event_id: str) -> str:
        star, year = econ_event_id.rsplit(":", 1)
        sch, y = self.by_star[star]
        assert int(year) == y, (econ_event_id, y)
        return f"{star}:{sch}"

    def to_econ(self, gold_event_id: str) -> str:
        star, sch = gold_event_id.rsplit(":", 1)
        s2, y = self.by_star[star]
        assert s2 == sch, (gold_event_id, s2)
        return f"{star}:{y}"

    def gold_ledger(self) -> bytes:
        """The signed-table shape the gold builders read (`events_{field}_fnfix_2026-08-10.csv`)."""
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=["field", "school", "author_id", "display_name",
                                            "arrival_corrected", "evidence_grade", "evidence_url",
                                            "signature"])
        w.writeheader()
        for r in self.rows:
            w.writerow({"field": "econ", "school": r["school"], "author_id": r["star_id"],
                        "display_name": "", "arrival_corrected": int(r["arrival_year"]),
                        "evidence_grade": r.get("arrival_evidence", ""),
                        "evidence_url": r.get("evidence_source", ""),
                        "signature": r.get("arrival_source", "")})
        return buf.getvalue().encode("utf-8")

    def gold_base(self) -> bytes:
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=["event_id", "arrival_year"])
        w.writeheader()
        for r in self.rows:
            w.writerow({"event_id": f"{r['star_id']}:{r['school']}",
                        "arrival_year": int(r["arrival_year"])})
        return buf.getvalue().encode("utf-8")

    def stars(self) -> list[str]:
        return sorted(self.by_star)


# ---------------------------------------------------------------------------------------------
# pool
# ---------------------------------------------------------------------------------------------

def pool_ids(roster_parquet: pathlib.Path, pmap_parquet: pathlib.Path) -> tuple[set[str], dict]:
    """Frame ids that count as roster persons: `P_<author_id>` for every roster author, plus the U2
    person id of every roster author found in the map (build_verified_pool.py `ver_p`)."""
    con = duckdb.connect()
    rows = con.execute(f"""
        SELECT DISTINCT 'P_' || v.author_id FROM read_parquet('{roster_parquet}') v
        UNION
        SELECT DISTINCT m.person_id FROM read_parquet('{roster_parquet}') v
        JOIN read_parquet('{pmap_parquet}') m USING (author_id)""").fetchall()
    n_auth, n_mapped = con.execute(f"""
        SELECT count(DISTINCT v.author_id), count(DISTINCT m.author_id)
        FROM read_parquet('{roster_parquet}') v
        LEFT JOIN read_parquet('{pmap_parquet}') m USING (author_id)""").fetchone()
    con.close()
    ids = {r[0] for r in rows}
    return ids, {"roster_authors": n_auth, "roster_authors_in_person_map": n_mapped,
                 "pool_frame_ids": len(ids)}


# ---------------------------------------------------------------------------------------------
# adapters: economics shape -> gold shape (before the chain)
# ---------------------------------------------------------------------------------------------

def adapt_network_frame(src: pathlib.Path, ev: EventMap, pool: set[str] | None) -> tuple[bytes, dict]:
    """The economics network frame in the gold builders' shape.

    Per data line: event not in the event table -> dropped (reported per event); incumbent not in
    `pool` (when given) -> dropped (reported per person); otherwise `P_` stripped from the two id
    columns (asserted present) and event_id relabelled star:year -> star:school. Every other cell
    is preserved byte for byte; lines are re-joined with "\\n" (the source carries no CR)."""
    raw = src.read_bytes()
    assert b"\r" not in raw, "network frame carries CR — the byte-preserving adapter assumes LF only"
    lines = raw.decode("utf-8").split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    hdr = next(csv.reader([lines[0]]))
    assert hdr == FRAME_COLS, hdr
    out = [",".join(FRAME_COLS)]
    dropped_events: dict[str, int] = {}
    dropped_pool: dict[str, int] = {}
    kept_persons, kept = set(), 0
    for ln in lines[1:]:
        cells = next(csv.reader([ln]))
        assert len(cells) == len(FRAME_COLS), cells[:4]
        pid, star, evid = cells[0], cells[2], cells[3]
        if evid not in ev.econ_ids:
            dropped_events[evid] = dropped_events.get(evid, 0) + 1
            continue
        if pool is not None and pid not in pool:
            dropped_pool[pid] = dropped_pool.get(pid, 0) + 1
            continue
        assert pid.startswith("P_") and star.startswith("P_"), (pid, star)
        cells[0], cells[2], cells[3] = pid[2:], star[2:], ev.to_gold(evid)
        # re-serialise only what changed: the other cells are the original strings. The original
        # line must carry no quoting at all (a quoted cell would be re-emitted bare, silently
        # changing bytes); the round-trip below then proves the re-join parses to the same cells.
        assert '"' not in ln, ln[:120]
        new = ",".join(cells)
        assert next(csv.reader([new])) == cells, new[:120]
        out.append(new)
        kept += 1
        kept_persons.add(pid)
    stats = {"rows_in": len(lines) - 1, "rows_kept": kept,
             "rows_dropped_event_not_in_table": sum(dropped_events.values()),
             "events_dropped": dropped_events,
             "rows_dropped_not_in_pool": sum(dropped_pool.values()),
             "persons_dropped_not_in_pool": sorted(dropped_pool),
             "persons_kept": len(kept_persons)}
    return ("\n".join(out) + "\n").encode("utf-8"), stats


def stars_excluded_parquet(star_ids: list[str], out: pathlib.Path) -> None:
    con = duckdb.connect()
    con.execute("CREATE TABLE t(author_id VARCHAR)")
    con.executemany("INSERT INTO t VALUES (?)", [(s,) for s in sorted(set(star_ids))])
    con.execute(f"COPY (SELECT author_id FROM t ORDER BY author_id) TO '{out}' (FORMAT PARQUET)")
    con.close()


def supplement_jsonl(parts: list[pathlib.Path], patch_jsonl: pathlib.Path | None) -> tuple[bytes, dict]:
    """One supplement file in the `netbase_supplement` schema the gold builders read
    ({work_id, publication_year, type, seed_author, authors}): the given supplement files
    concatenated line for line, plus — when given — the API works-by-author patch
    (`econ_final_2026-08-13/patch/works_by_author.jsonl`, schema {author_id, work_id,
    publication_year, fwci, cited_by_count, subfield_id, n_authors, author_ids}) re-shaped as
    seed_author=author_id / authors=author_ids / type=null. The legacy economics P2 builder
    (`10_panels23_econ920.py`) read exactly these four sources."""
    out, stats = [], {}
    for p in parts:
        n = 0
        for ln in open(p, encoding="utf-8"):
            if not ln.strip():
                continue
            d = json.loads(ln)
            assert {"work_id", "seed_author"} <= set(d), (p, d)
            out.append(ln.rstrip("\n"))
            n += 1
        stats[p.name] = n
    if patch_jsonl is not None:
        n = 0
        for ln in open(patch_jsonl, encoding="utf-8"):
            d = json.loads(ln)
            out.append(json.dumps({"work_id": d["work_id"], "publication_year": d.get("publication_year"),
                                   "type": None, "seed_author": d["author_id"],
                                   "authors": list(d.get("author_ids") or [])}, ensure_ascii=False))
            n += 1
        stats[patch_jsonl.name + " (reshaped)"] = n
    return ("\n".join(out) + "\n").encode("utf-8"), stats


# ---------------------------------------------------------------------------------------------
# adapters: gold shape -> economics shape (after the chain)
# ---------------------------------------------------------------------------------------------

def restore_p1(gold_csv: pathlib.Path, ev: EventMap, n_network_rows: int) -> bytes:
    """The y-rebuilt union frame back in the economics shape: `P_` restored on both id columns,
    event ids star:school -> star:year, the `channel` column kept. The first `n_network_rows` data
    lines (the network block, written verbatim by the union builder) keep their order; the
    dept-only block that follows is re-ordered to the legacy order — sorted by (pid, econ event_id)
    then year — because the union builder sorts it by the GOLD event id, which orders differently
    within a person. Every other cell is byte-preserved."""
    hdr, rows = fs.read_frame_rows(gold_csv)
    assert hdr == FRAME_COLS + ["channel"], hdr
    fixed = []
    for cells in rows:
        cells = list(cells)
        cells[0] = "P_" + cells[0]
        cells[2] = "P_" + cells[2]
        cells[3] = ev.to_econ(cells[3])
        fixed.append(cells)
    head, tail = fixed[:n_network_rows], fixed[n_network_rows:]
    assert all(c[-1] in ("network", "both") for c in head), "network block is not the frame's head"
    assert all(c[-1] == "dept_only" for c in tail), "dept-only block is not the frame's tail"
    tail.sort(key=lambda c: (c[0], c[3], int(float(c[1]))))
    buf = io.StringIO()
    buf.write(",".join(hdr) + "\n")
    for cells in head + tail:
        buf.write(",".join(cells) + "\n")
    return buf.getvalue().encode("utf-8")


def restore_p2(becoming_csv: pathlib.Path, ev: EventMap) -> bytes:
    """The becoming panel back in the economics shape: event ids star:school -> star:year, rows in
    the legacy order (pid, event_id, year). pid/star are bare in both conventions."""
    hdr, rows = fs.read_frame_rows(becoming_csv)
    assert hdr == P2_COLS, hdr
    fixed = []
    for cells in rows:
        cells = list(cells)
        cells[2] = ev.to_econ(cells[2])
        fixed.append(cells)
    fixed.sort(key=lambda c: (c[0], c[2], int(c[4])))
    buf = io.StringIO()
    buf.write(",".join(hdr) + "\n")
    for cells in fixed:
        buf.write(",".join(cells) + "\n")
    return buf.getvalue().encode("utf-8")


# ---------------------------------------------------------------------------------------------
# accounting
# ---------------------------------------------------------------------------------------------

P1_BUCKETS = {
    "y": ("fwci_frac", "fwci_mean"),
    "y_ex_star": ("fwci_frac_ex_star", "fwci_mean_ex_star", "pub_count_ex_star"),
    "dose": ("dose_topic",),
    "age_gap": ("age_gap",),
    "pub_count": ("pub_count",),
    "channel": ("channel",),
}
P1_FLOATS = ("dose_topic", "age_gap", "fwci_frac", "fwci_frac_ex_star", "fwci_mean",
             "fwci_mean_ex_star", "pub_count", "pub_count_ex_star")


def _bucket(cols: list[str]) -> str:
    names = []
    for name, members in P1_BUCKETS.items():
        if any(c in members for c in cols):
            names.append(name)
    rest = [c for c in cols if not any(c in m for m in P1_BUCKETS.values())]
    if rest:
        names.append("other(" + ",".join(rest) + ")")
    return "+".join(names)


def _num(s):
    try:
        return float(s) if s not in ("", None) else None
    except ValueError:
        return None


def _value_diff_summary(entries: list[dict], col: str) -> dict:
    """NA-status changes, numeric diff count, max |diff|, max relative diff, share within 1e-6."""
    na_to_val = val_to_na = 0
    diffs, rels = [], []
    for e in entries:
        if col not in e["cols"]:
            continue
        a, b = _num(e["frozen"][col]), _num(e["new"][col])
        if a is None and b is not None:
            na_to_val += 1
        elif a is not None and b is None:
            val_to_na += 1
        elif a is not None and b is not None:
            d = abs(a - b)
            diffs.append(d)
            rels.append(d / max(abs(a), 1e-12))
    return {"rows_touched": sum(1 for e in entries if col in e["cols"]),
            "na_to_value": na_to_val, "value_to_na": val_to_na, "numeric_diffs": len(diffs),
            "max_abs_diff": max(diffs) if diffs else None,
            "max_rel_diff": max(rels) if rels else None,
            "numeric_within_rel_1e-6": sum(1 for r in rels if r <= 1e-6)}


def account_p1(new_csv: pathlib.Path, ref_csv: pathlib.Path) -> dict:
    """Keyed (person, event, year) comparison of the chain's P1 frame with the frozen one."""
    acc = fs.keyed_csv_accounting(ref_csv, new_csv, ("incumbent_person_id", "event_id", "year"),
                                  P1_FLOATS)
    hdr_r, rows_r = fs.read_frame_rows(ref_csv)
    hdr_n, rows_n = fs.read_frame_rows(new_csv)
    ch_r = {tuple(c[i] for i in (0, 3)): c[-1] for c in rows_r}
    ch_n = {tuple(c[i] for i in (0, 3)): c[-1] for c in rows_n}
    # row order, judged on the keys both frames carry (removed/added rows excluded): a plain
    # list comparison is False as soon as one row is missing, which says nothing about order
    keys_n = [(c[0], c[3], c[1]) for c in rows_n]
    common_n = set(keys_n) & {(c[0], c[3], c[1]) for c in rows_r}
    order_identical = ([k for k in keys_n if k in common_n]
                       == [k for k in ((c[0], c[3], c[1]) for c in rows_r) if k in common_n])
    buckets: dict[str, int] = {}
    by_channel: dict[str, dict] = {}
    for e in acc["modified"]:
        b = _bucket(e["cols"])
        buckets[b] = buckets.get(b, 0) + 1
        ch = ch_r.get((e["key"][0], e["key"][1]), "?")
        by_channel.setdefault(ch, {})[b] = by_channel.setdefault(ch, {}).get(b, 0) + 1
    rels_removed = sorted({(k[0], k[1]) for k in acc["removed"]})
    rels_added = sorted({(k[0], k[1]) for k in acc["added"]})
    persons_removed = sorted({k[0] for k in acc["removed"]} - {c[0] for c in rows_n})
    persons_added = sorted({k[0] for k in acc["added"]} - {c[0] for c in rows_r})
    ident_keys = set(ch_r) & set(ch_n)
    channel_changed = sorted(k for k in ident_keys if ch_r[k] != ch_n[k])
    out = {
        "rows_frozen": acc["rows_frozen"], "rows_new": acc["rows_new"],
        "identical": acc["identical"], "modified": len(acc["modified"]),
        "removed_rows": len(acc["removed"]), "added_rows": len(acc["added"]),
        "row_order_identical_on_common_keys": order_identical,
        "modified_by_bucket": dict(sorted(buckets.items(), key=lambda kv: -kv[1])),
        "modified_by_channel_and_bucket": by_channel,
        "value_diffs": {c: _value_diff_summary(acc["modified"], c) for c in P1_FLOATS},
        "relationships_removed": {"n": len(rels_removed),
                                  "by_channel": _count_by(rels_removed, ch_r),
                                  "sample": rels_removed[:20]},
        "relationships_added": {"n": len(rels_added), "by_channel": _count_by(rels_added, ch_n),
                                "sample": rels_added[:20]},
        "persons_removed": {"n": len(persons_removed), "sample": persons_removed[:20]},
        "persons_added": {"n": len(persons_added), "sample": persons_added[:20]},
        "relationship_channel_changed": {"n": len(channel_changed),
                                         "sample": [(k, ch_r[k], ch_n[k]) for k in channel_changed[:20]]},
        "channels_frozen": _count_by(sorted(ch_r), ch_r), "channels_new": _count_by(sorted(ch_n), ch_n),
        "modified_examples": acc["modified"][:12],
    }
    return out


def _count_by(keys, chan: dict) -> dict:
    out: dict[str, int] = {}
    for k in keys:
        c = chan.get(k, "?")
        out[c] = out.get(c, 0) + 1
    return out


def account_p2(new_csv: pathlib.Path, ref_csv: pathlib.Path) -> dict:
    acc = fs.keyed_csv_accounting(ref_csv, new_csv, ("pid", "event_id", "year"), ())
    hdr_r, rows_r = fs.read_frame_rows(ref_csv)
    hdr_n, rows_n = fs.read_frame_rows(new_csv)
    ch_r = {(c[0], c[2]): c[3] for c in rows_r}
    ch_n = {(c[0], c[2]): c[3] for c in rows_n}
    cols: dict[str, int] = {}
    for e in acc["modified"]:
        k = "+".join(e["cols"])
        cols[k] = cols.get(k, 0) + 1
    rels_removed = sorted({(k[0], k[1]) for k in acc["removed"]} - set(ch_n))
    rels_added = sorted({(k[0], k[1]) for k in acc["added"]} - set(ch_r))
    rels_shortened = sorted({(k[0], k[1]) for k in acc["removed"]} & set(ch_n))
    rels_lengthened = sorted({(k[0], k[1]) for k in acc["added"]} & set(ch_r))
    y_r = sum(int(c[7]) for c in rows_r)
    y_n = sum(int(c[7]) for c in rows_n)
    keys_n = [(c[0], c[2], c[4]) for c in rows_n]
    common_n = set(keys_n) & {(c[0], c[2], c[4]) for c in rows_r}
    order_identical = ([k for k in keys_n if k in common_n]
                       == [k for k in ((c[0], c[2], c[4]) for c in rows_r) if k in common_n])
    return {
        "rows_frozen": acc["rows_frozen"], "rows_new": acc["rows_new"],
        "identical": acc["identical"], "modified": len(acc["modified"]),
        "removed_rows": len(acc["removed"]), "added_rows": len(acc["added"]),
        "row_order_identical_on_common_keys": order_identical,
        "modified_by_columns": cols,
        "first_ties_frozen": y_r, "first_ties_new": y_n,
        "relationships_frozen": len(ch_r), "relationships_new": len(ch_n),
        "relationships_removed": {"n": len(rels_removed), "by_channel": _count_by(rels_removed, ch_r),
                                  "sample": rels_removed[:20]},
        "relationships_added": {"n": len(rels_added), "by_channel": _count_by(rels_added, ch_n),
                                "sample": rels_added[:20]},
        "relationships_window_shortened": {"n": len(rels_shortened), "sample": rels_shortened[:20]},
        "relationships_window_lengthened": {"n": len(rels_lengthened), "sample": rels_lengthened[:20]},
        "channels_frozen": _count_by(sorted(ch_r), ch_r), "channels_new": _count_by(sorted(ch_n), ch_n),
        "modified_examples": acc["modified"][:12],
    }


def estimate_side_by_side(new_json: pathlib.Path, ref_json: pathlib.Path) -> dict:
    """The headline numbers of two result JSONs next to each other (P1: per channel; P2: one)."""
    a, b = json.load(open(new_json)), json.load(open(ref_json))
    keys = ("obs", "rels", "persons", "events", "ate", "se", "p_joint_effects", "p_joint_placebo",
            "rows", "first_ties", "rows_raw", "rows_kept")

    def pick(d):
        return {k: d.get(k) for k in keys if k in d}
    if "channels" in b:
        return {"top": {"new": pick(a), "frozen": pick(b)},
                **{c: {"new": pick(a.get("channels", {}).get(c, {})), "frozen": pick(b["channels"][c])}
                   for c in b["channels"]}}
    return {"new": pick(a), "frozen": pick(b)}
