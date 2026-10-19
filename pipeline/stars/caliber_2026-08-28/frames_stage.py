#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""caliber_2026-08-28/frames_stage.py — the caliber STAGING layer for the frames rebuild (Task 3).

Repo-authored library (no ported byte is edited, no frozen artifact touched). It gives
`run_cal_frames.py` four things:

1. **The shadow legacy tree.** The ported frame builders resolve their inputs through
   `pipeline.lib.paths.legacy_thesis()`, which honours `$SAR_LEGACY_THESIS` (the T8 run_fwci
   arrangement). This module builds a shadow of exactly the files each builder resolves — hard
   links to the frozen legacy files where the caliber changes nothing, the cal2026-08-28 artifacts
   (T1 event tables, T2 supplement/exclusions) and derived companions where it does — and records
   every entry (path, sha256, origin) in a staging manifest.

2. **The econ surgery.** The econ chain's two un-ported rungs (prodlib stage 1 and the
   machine-generated `00_build_frame_econ920.py`) have no new events under the caliber — economics
   changes by A5044432173's event REMOVAL only — so their cal inputs are the frozen outputs with the rows
   of event `A5044432173:2006` removed, byte-preserving every other line. Register ruling R-T3-1;
   the removal is per-event by construction and the downstream row-level accounting is the proof.

3. **The prodlib staging.** `multidisc_prod_2026-07-24/code/{build_frame,prodlib,mpimports}.py`
   hold no absolute path except mpimports' units root; they are staged verbatim (hard link,
   sha-asserted against the pins below) and driven by a cal config whose only jobs are to point
   the inputs at the shadow/cal files and the run_dir at the mirror. The units mpimports pulls are
   pre-imported from THIS repository's ported copies, origin-asserted (the run_frames arrangement).

4. **The row-level accounting.** Machine-checked comparisons of every produced frame against its
   frozen counterpart, with every row in/out/changed attributed to a NAMED cause; T2's pinned
   expectations are evaluated verbatim and any deviation is REPORTED, never absorbed.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import pathlib
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))

from pipeline.lib.paths import legacy_thesis, require_readable  # noqa: E402

CAL_DIR = REPO / "data" / "cal2026-08-28"
FRAMES_OUT = CAL_DIR / "frames"

A5044432173_ID = "A5044432173"
A5044432173_EVENT = "A5044432173:2006"
#: the five new stars (author-signed 2026-08-28), field -> ids
FIVE = {"chemistry": ("A5027778630", "A5091826237", "A5062352558"),
        "math_stats": ("A5017222669", "A5090916445")}
FIVE_ALL = FIVE["chemistry"] + FIVE["math_stats"]
FIVE_NAMES = {"A5027778630": "A5027778630", "A5091826237": "A5091826237",
              "A5062352558": "A5062352558", "A5017222669": "A5017222669",
              "A5090916445": "A5090916445"}
#: the five's NEW event ids in the gold event-id shape (star:school)
NEW_EVENTS = {"chemistry": ("A5027778630:anu", "A5091826237:anu", "A5062352558:melbourne"),
              "math_stats": ("A5017222669:uq", "A5090916445:unsw")}

#: verbatim-staged legacy code, sha-pinned. Anything else at these paths is NOT the audited code.
PINNED_LEGACY_CODE = {
    "multidisc_prod_2026-07-24/code/build_frame.py":
        "d458b6392817f8c4360264abc335987359ad5e2eaa63912a259b11df420df522",
    "multidisc_prod_2026-07-24/code/prodlib.py":
        "f3a3ae2f83412a74e5e40d61e649674da37f39d4194e046ce6174e36b1580155",
    "multidisc_prod_2026-07-24/code/mpimports.py":
        "7830d4be24c03d4ea6afa9b90d01bd37bbb5318fa137746bb60b249dd04ffcb6",
    "multidisc_2026-07-24/code/roster_lib.py":
        "774f1bcc4c87c4da6adf18d690a37f0008923a29ae43a9a096d17c0b413b1230",
}

#: the modules mpimports pulls by name — pre-imported from THIS repo's units, origin-asserted
PRODLIB_UNIT_MODULES = (
    "identity.dose", "identity.cohort", "identity.first_pub", "identity.output_rule",
    "m5_output.fwci_raw", "m5_output.fwci_baseline_build", "m5_output.paper_contrib",
    "m4_dose.candidate_pairs", "m4_dose.degree2_closure", "m4_dose.topic_vec", "m4_dose.cutoff",
    "m7b_assemble.assemble", "m7b_assemble.incumbent_roster", "common._redlines")
PRODLIB_UNIT_SRC = ("u0_foundation", "u1_fetch", "u4_output_star", "u5_dose", "u6_assemble")


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def real_v2() -> pathlib.Path:
    """The REAL legacy v2_output, read from config — deliberately NOT legacy_thesis(), which a
    caliber run points at the shadow. The shadow is built FROM here; nothing ever writes here."""
    from analysis.lib.paths import load_paths                       # noqa: PLC0415
    return pathlib.Path(load_paths()["legacy_v2_output"])


class Shadow:
    """A shadow of the legacy thesis tree under `root`: hard links for frozen inputs, real files
    for cal/derived ones, every entry recorded (rel, origin, sha256)."""

    def __init__(self, root: pathlib.Path):
        self.root = root
        self.entries: list[dict] = []
        root.mkdir(parents=True, exist_ok=True)

    def path(self, rel: str) -> pathlib.Path:
        return self.root / rel

    def link_frozen(self, rel: str, src: pathlib.Path) -> None:
        dest = self.root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            dest.unlink()
        want = sha(src)
        try:
            os.link(src, dest)
        except OSError:
            dest.write_bytes(src.read_bytes())
        got = sha(dest)
        assert got == want, f"shadow link corrupted: {rel} {want} != {got}"
        self.entries.append({"rel": rel, "origin": f"frozen:{src}", "sha256": got})

    def write(self, rel: str, data: bytes, origin: str) -> None:
        dest = self.root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        # 2026-09-23 (econ920 review finding): `dest` may already be a HARD LINK that
        # `link_frozen` made of a legacy file — FROZEN_LINKS is linked first and a derived table
        # for the same rel written afterwards (the supplement / patch concatenations). Writing
        # through the link truncates the shared inode, i.e. the read-only legacy tree itself
        # (econ_fnfix_2026-08-15/data/edges_supplement_fnfix.jsonl took six appended copies of
        # the 126-row supplement, econ_final_2026-08-13/patch/works_by_author.jsonl one 190-row
        # patch; both restored from their pinned bytes). Unlink first: the shadow gets its own
        # inode and the linked source is never touched. tests/test_shadow_write_through.py.
        if dest.is_symlink() or dest.exists():
            dest.unlink()
        dest.write_bytes(data)
        self.entries.append({"rel": rel, "origin": origin, "sha256": sha(dest)})

    def install(self, rel: str, produced: pathlib.Path, origin: str) -> None:
        """A cal stage's output, placed where the NEXT stage resolves it."""
        self.link_frozen(rel, produced)          # hard link + sha assert
        self.entries[-1]["origin"] = origin

    def manifest(self) -> list[dict]:
        return list(self.entries)


# ---------------------------------------------------------------------------------------------
# econ surgery (register ruling R-T3-1)
# ---------------------------------------------------------------------------------------------

def drop_event_lines(src: pathlib.Path, event: str, col: int) -> tuple[bytes, int, int]:
    """`src` minus every data line whose `col`-th CSV field equals `event`, header and every other
    line byte-preserved (line endings included). Returns (bytes, kept, removed)."""
    raw = src.read_bytes()
    out, removed, kept = [], 0, 0
    lines = raw.split(b"\n")
    trailing_empty = lines and lines[-1] == b""
    if trailing_empty:
        lines = lines[:-1]
    for i, ln in enumerate(lines):
        if i == 0:
            out.append(ln)
            continue
        cells = next(csv.reader([ln.decode("utf-8").rstrip("\r")]))
        if len(cells) > col and cells[col] == event:
            removed += 1
            continue
        kept += 1
        out.append(ln)
    blob = b"\n".join(out) + (b"\n" if trailing_empty else b"")
    return blob, kept, removed


def surgery_new_events_econ(v2: pathlib.Path) -> tuple[bytes, int]:
    """The frozen 38-row `new_events_econ.csv` minus A5044432173's line, others byte-preserved."""
    src = v2 / "econ_fnfix_2026-08-15/data/new_events_econ.csv"
    raw = src.read_bytes()
    lines = raw.split(b"\n")
    hdr = next(csv.reader([lines[0].decode("utf-8").rstrip("\r")]))
    aid_col = hdr.index("author_id")
    out, removed = [], 0
    for i, ln in enumerate(lines):
        if i and ln:
            cells = next(csv.reader([ln.decode("utf-8").rstrip("\r")]))
            if cells[aid_col] == A5044432173_ID:
                removed += 1
                continue
        out.append(ln)
    assert removed == 1, f"expected exactly one A5044432173 row in new_events_econ.csv, found {removed}"
    return b"\n".join(out), removed


def surgery_build_report(v2: pathlib.Path) -> tuple[bytes, dict]:
    """The frozen prodlib build_report with the export counts moved for A5044432173's event removal.
    ONLY the consumed keys move; the delta is returned for the staging manifest."""
    src = v2 / "econ_fnfix_2026-08-15/runs/econ_fnfix/build_report.json"
    rep = json.loads(src.read_text(encoding="utf-8"))
    frame_csv = v2 / "econ_fnfix_2026-08-15/runs/econ_fnfix/data/analysis_frame_p01_52ev_topicdose_2026-07-21.csv"
    _, kept, removed = drop_event_lines(frame_csv, A5044432173_EVENT, 3)
    before = {"n_events_in_frame": rep["export"]["n_events_in_frame"],
              "n_rows": rep["export"]["n_rows"]}
    assert removed > 0, "A5044432173's event has no rows in the prodlib network frame — surgery is wrong"
    rep["export"]["n_events_in_frame"] = before["n_events_in_frame"] - 1
    rep["export"]["n_rows"] = before["n_rows"] - removed
    delta = {"before": before, "after": dict(rep["export"], **{}), "rows_removed": removed}
    delta["after"] = {k: rep["export"][k] for k in ("n_events_in_frame", "n_rows")}
    return json.dumps(rep, ensure_ascii=False, indent=1).encode("utf-8"), delta


# ---------------------------------------------------------------------------------------------
# 70_prep-shaped companions for the cal event tables (the products T2 did not remake)
# ---------------------------------------------------------------------------------------------

def cal_fnfixbase(v2: pathlib.Path, field: str) -> bytes:
    """frozen events_{field}_fnfixbase + the new events' (event_id, arrival_year) rows —
    the exact construction of `70_prep_fnfix_inputs.py:42-45`, with the cal admissions as NEW."""
    src = v2 / f"multidisc_gold_2026-08-10/data/events_{field}_fnfixbase_2026-08-10.csv"
    base = list(csv.DictReader(io.StringIO(src.read_bytes().decode("utf-8"))))
    add = _cal_new_rows(field)
    base += [{"event_id": f"{r['author_id']}:{r['school']}", "arrival_year": r["arrival_corrected"]}
             for r in add]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["event_id", "arrival_year"])
    w.writeheader()
    w.writerows(base)
    blob = buf.getvalue().encode("utf-8")
    assert blob.startswith(src.read_bytes()), (
        f"cal fnfixbase({field}) does not byte-preserve the frozen table as a prefix")
    return blob


def cal_shortlist(v2: pathlib.Path) -> bytes:
    """frozen shortlist_fnfix + the five (70_prep lines 49-52, with the cal admissions as NEW)."""
    src = v2 / "multidisc_gold_2026-08-10/data/shortlist_fnfix.csv"
    rows = list(csv.DictReader(io.StringIO(src.read_bytes().decode("utf-8"))))
    for field in ("chemistry", "math_stats"):
        rows += [{"author_id": r["author_id"], "field": r["field"], "school": r["school"],
                  "arrival_year": r["arrival_corrected"]} for r in _cal_new_rows(field)]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["author_id", "field", "school", "arrival_year"])
    w.writeheader()
    w.writerows(rows)
    blob = buf.getvalue().encode("utf-8")
    assert blob.startswith(src.read_bytes()), "cal shortlist does not byte-preserve the frozen one"
    return blob


def _cal_new_rows(field: str) -> list[dict]:
    """The cal event table's rows BEYOND the frozen fnfix prefix — T1 froze the tables as frozen
    bytes + appended admissions, so the tail rows ARE the admissions, asserted by id."""
    cal = list(csv.DictReader(open(CAL_DIR / f"events_{field}_cal.csv", encoding="utf-8")))
    frozen_n = {"chemistry": 35, "math_stats": 31}[field]
    tail = cal[frozen_n:]
    assert tuple(r["author_id"] for r in tail) == tuple(
        e.split(":")[0] for e in NEW_EVENTS[field]), (field, [r["author_id"] for r in tail])
    return tail


# ---------------------------------------------------------------------------------------------
# shadow assembly
# ---------------------------------------------------------------------------------------------

#: frozen inputs the builders resolve through legacy_thesis() that the caliber does not change
FROZEN_LINKS = (
    "econ_fnfix_2026-08-15/data/edges_supplement_fnfix.jsonl",
    "r_p10_80ev_2026-07-22/data/analysis_frame_p01_52ev_topicdose_2026-07-21.csv",
    "event_ledger_2026-07-27/event_ledger_79_2026-07-27.csv",
    "econ_final_2026-08-13/patch/works_by_author.jsonl",
    "fwci_fullsnapshot_rebuild_2026-08-09/data/econ_units_2026-08-09.parquet",
    "fwci_fullsnapshot_rebuild_2026-08-09/data/fwci_expected_fullsnapshot_2026-08-09.parquet",
    "netbase_supplement_2026-07-23/edges_supplement_133.jsonl",
    "netbase_supplement_2026-07-23/edges_supplement_stars11.jsonl",
    "multidisc_2026-07-24/code/roster_lib.py",
    "multidisc_gold_2026-08-10/data/events_chemistry_gold_2026-08-10.csv",
    "multidisc_gold_2026-08-10/data/events_math_stats_gold_2026-08-10.csv",
    "multidisc_gold_2026-08-10/data/fnfix/roster_gold_chemistry.parquet",
    "multidisc_gold_2026-08-10/data/fnfix/roster_gold_math_stats.parquet",
    "multidisc_v2_2026-08-04/data/person_map_multidisc_seeds.parquet",
    "fwci_baseline_fullsnapshot_2026-08-09/data/fwci_baseline_pop_full.parquet",
)

#: `runs/econ_fnfix/…` — the frozen prodlib frame the ledger stage compares its NEW rows against
ECON_RUN_FRAME = "econ_fnfix_2026-08-15/runs/econ_fnfix/data/analysis_frame_p01_52ev_topicdose_2026-07-21.csv"


def build_shadow(root: pathlib.Path) -> tuple[Shadow, dict]:
    """The full input shadow (before any cal stage runs). Returns (shadow, econ surgery record)."""
    v2 = real_v2()
    require_readable(v2, "the real legacy v2_output")
    sh = Shadow(root / "v2_output")
    for rel in FROZEN_LINKS:
        sh.link_frozen(rel, v2 / rel)
    assert sha(sh.path(PINNED_LEGACY_CODE_ROSTERLIB)) == \
        PINNED_LEGACY_CODE["multidisc_2026-07-24/code/roster_lib.py"], (
        "roster_lib.py in the legacy tree no longer matches its pin")

    surgery: dict = {}
    # --- econ: A5044432173's event removed from the un-ported rungs' frozen outputs -----------------
    blob, n_removed = surgery_new_events_econ(v2)
    sh.write("econ_fnfix_2026-08-15/data/new_events_econ.csv", blob,
             "surgery:new_events_econ minus A5044432173 (R-T3-1)")
    surgery["new_events_rows_removed"] = n_removed

    frame_blob, kept, removed = drop_event_lines(v2 / ECON_RUN_FRAME, A5044432173_EVENT, 3)
    sh.write(ECON_RUN_FRAME, frame_blob, "surgery:prodlib network frame minus A5044432173's event rows")
    surgery["prodlib_frame_rows_removed"] = removed

    rep_blob, delta = surgery_build_report(v2)
    sh.write("econ_fnfix_2026-08-15/runs/econ_fnfix/build_report.json", rep_blob,
             f"surgery:prodlib build_report export counts {delta['before']} -> {delta['after']}")
    surgery["build_report_delta"] = delta

    rel_blob, kept, removed = drop_event_lines(
        v2 / "econ_fnfix_2026-08-15/data/relationships.csv", A5044432173_EVENT, _rel_event_col(v2))
    sh.write("econ_fnfix_2026-08-15/data/relationships.csv", rel_blob,
             "surgery:relationships minus A5044432173's event rows")
    surgery["relationships_rows_removed"] = removed

    fi = v2 / "econ_fnfix_2026-08-15/data/analysis_frame_dept_p01_econ920_2026-08-13.csv"
    fi_blob, kept, removed = drop_event_lines(fi, A5044432173_EVENT, 3)
    sh.write("econ_fnfix_2026-08-15/data/analysis_frame_dept_p01_econ920_2026-08-13.csv", fi_blob,
             "surgery:pre-y econ frame minus A5044432173's event rows")
    surgery["pre_y_frame_rows_removed"] = removed

    # --- chem/math: the cal event tables + supplements + exclusions at the fnfix names ------
    gold = "multidisc_gold_2026-08-10/data"
    for field in ("chemistry", "math_stats"):
        sh.write(f"{gold}/events_{field}_fnfix_2026-08-10.csv",
                 (CAL_DIR / f"events_{field}_cal.csv").read_bytes(),
                 f"cal:events_{field}_cal.csv (T1)")
        sh.write(f"{gold}/events_{field}_fnfixbase_2026-08-10.csv", cal_fnfixbase(v2, field),
                 "derived:frozen fnfixbase + cal admissions (70_prep rule)")
    sh.write(f"{gold}/shortlist_fnfix.csv", cal_shortlist(v2),
             "derived:frozen shortlist_fnfix + the five (70_prep rule)")
    sh.write(f"{gold}/stars_excluded_fnfix.parquet",
             (CAL_DIR / "stars_excluded_cal2026-08-28.parquet").read_bytes(),
             "cal:stars_excluded_cal2026-08-28.parquet (T2, fnfix 1832 + the five = 1837)")
    sh.write(f"{gold}/edges_supplement_fnfix.jsonl",
             (CAL_DIR / "edges_supplement_cal2026-08-28.jsonl").read_bytes(),
             "cal:edges_supplement_cal2026-08-28.jsonl (T2, fnfix 13,564 lines + 2,005)")
    return sh, surgery


PINNED_LEGACY_CODE_ROSTERLIB = "multidisc_2026-07-24/code/roster_lib.py"


def _rel_event_col(v2: pathlib.Path) -> int:
    hdr = open(v2 / "econ_fnfix_2026-08-15/data/relationships.csv", newline="",
               encoding="utf-8").readline().strip().split(",")
    return hdr.index("event_id")


# ---------------------------------------------------------------------------------------------
# prodlib staging
# ---------------------------------------------------------------------------------------------

def preimport_prodlib_units() -> list[str]:
    """Bind every module mpimports pulls to THIS repository's ported units, origin-asserted."""
    import importlib                                                  # noqa: PLC0415
    for u in PRODLIB_UNIT_SRC:
        p = REPO / "pipeline" / "units" / u / "src"
        assert p.is_dir(), p
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    used = []
    for m in PRODLIB_UNIT_MODULES:
        mod = importlib.import_module(m)
        f = pathlib.Path(getattr(mod, "__file__", "") or "").resolve()
        assert f.is_relative_to(REPO / "pipeline" / "units"), (
            f"{m} resolved to {f}, not to this repository's ported units — prodlib would compute "
            f"with the LEGACY code")
        used.append(f"{m} <- {f.relative_to(REPO)}")
    return used


def stage_prodlib(mirror: pathlib.Path) -> dict[str, str]:
    """Hard-link the prodlib trio into `mirror/code`, byte-asserted against the pins."""
    v2 = real_v2()
    code = mirror / "code"
    code.mkdir(parents=True, exist_ok=True)
    shas = {}
    for name in ("build_frame.py", "prodlib.py", "mpimports.py"):
        rel = f"multidisc_prod_2026-07-24/code/{name}"
        src = v2 / rel
        dest = code / name
        if dest.exists():
            dest.unlink()
        os.link(src, dest)
        got = sha(dest)
        assert got == PINNED_LEGACY_CODE[rel], (
            f"{rel} no longer matches its pin: {got} — the staged code is not the audited code")
        shas[name] = got
    return shas


def prodlib_config(field: str, shadow_root: pathlib.Path, run_dir: pathlib.Path,
                   cal: bool) -> dict:
    """The frozen fnfix config with (cal=True) inputs repointed at the shadow, or (cal=False,
    the control) only run_dir moved. SSD globs stay on the real data disk either way."""
    v2 = real_v2()
    cfg = json.loads((v2 / f"multidisc_gold_2026-08-10/config/fnfix_{field}.json")
                     .read_text(encoding="utf-8"))
    cfg["run_dir"] = str(run_dir)
    if cal:
        gold = shadow_root / "v2_output" / "multidisc_gold_2026-08-10" / "data"
        cfg["label"] += "；cal2026-08-28 staged (T3)"
        cfg["events"]["signed_csv"] = str(gold / f"events_{field}_fnfix_2026-08-10.csv")
        cfg["events"]["shortlist_csv"] = str(gold / "shortlist_fnfix.csv")
        cfg["supplement_jsonl"] = str(gold / "edges_supplement_fnfix.jsonl")
        cfg["roster"]["path"] = str(gold / "fnfix" / f"roster_gold_{field}.parquet")
        cfg["roster"]["exclude_authors_parquet"] = str(gold / "stars_excluded_fnfix.parquet")
        cfg["outcome_exclusion_stars"]["path"] = str(gold / "stars_excluded_fnfix.parquet")
    return cfg


# ---------------------------------------------------------------------------------------------
# row-level accounting
# ---------------------------------------------------------------------------------------------

def ulps(x: float, y: float) -> int:
    a, b = (struct.unpack("<q", struct.pack("<d", v))[0] for v in (x, y))
    return abs(a - b)


def strict_removal_walk(frozen: pathlib.Path, new: pathlib.Path,
                        is_removed) -> dict:
    """The STRONGEST accounting shape: `new` must be `frozen` with the `is_removed` lines deleted,
    order preserved, every kept line byte-identical. Streams both files; any other difference is
    an unaccounted row and fails the walk. `is_removed(cells) -> bool` sees the parsed line."""
    removed, kept, mismatch = 0, 0, None
    with open(frozen, "rb") as ff, open(new, "rb") as fn:
        h1, h2 = ff.readline(), fn.readline()
        if h1 != h2:
            return {"closed": False, "reason": f"header differs: {h1[:80]!r} vs {h2[:80]!r}"}
        nline = fn.readline()
        for fline in ff:
            cells = next(csv.reader([fline.decode("utf-8").rstrip("\r\n")]))
            if is_removed(cells):
                removed += 1
                continue
            if fline != nline:
                mismatch = {"frozen": fline[:160].decode("utf-8", "replace"),
                            "new": nline[:160].decode("utf-8", "replace"), "after_kept": kept}
                break
            kept += 1
            nline = fn.readline()
        else:
            if nline:                                      # new file has EXTRA lines
                mismatch = {"frozen": "<EOF>", "new": nline[:160].decode("utf-8", "replace"),
                            "after_kept": kept}
    out = {"closed": mismatch is None, "rows_removed": removed, "rows_kept": kept}
    if mismatch:
        out["reason"] = "unaccounted line"
        out["sample"] = mismatch
    return out


def read_frame_rows(p: pathlib.Path) -> tuple[list[str], list[list[str]]]:
    """Read a frame CSV the way `20_rebuild_y_gold.py` reads its own inputs: split on \\n and
    STRIP every \\r — the union frame's network rows carry the 07-24 CRLF legacy embedded
    mid-line, which the plain csv module would mis-parse as a row break."""
    lines = [ln.replace("\r", "") for ln in p.read_bytes().decode("utf-8").split("\n") if ln]
    hdr = next(csv.reader([lines[0]]))
    return hdr, [next(csv.reader([ln])) for ln in lines[1:]]


def keyed_csv_accounting(frozen: pathlib.Path, new: pathlib.Path, key_cols: tuple[str, ...],
                         float_cols: tuple[str, ...] = ()) -> dict:
    """Keyed comparison for frames where rows may be added, removed AND modified. Returns per-key
    classification: identical / modified (with the set of differing columns, float diffs measured
    in ULPs) / removed / added. Keys must be unique per file (asserted)."""
    def load(p):
        hdr, parsed = read_frame_rows(p)
        rows = {}
        for cells in parsed:
            row = dict(zip(hdr, cells))
            assert len(cells) == len(hdr), (p.name, cells[:4], len(cells), len(hdr))
            k = tuple(row[c] for c in key_cols)
            assert k not in rows, f"duplicate key {k} in {p.name}"
            rows[k] = row
        return rows
    a, b = load(frozen), load(new)
    removed = sorted(set(a) - set(b))
    added = sorted(set(b) - set(a))
    identical, modified = 0, []
    for k in a.keys() & b.keys():
        ra, rb = a[k], b[k]
        diff_cols = [c for c in ra if ra[c] != rb.get(c)]
        if not diff_cols:
            identical += 1
            continue
        entry = {"key": k, "cols": diff_cols}
        fdiff = {}
        for c in diff_cols:
            if c in float_cols and ra[c] and rb[c]:
                try:
                    fdiff[c] = ulps(float(ra[c]), float(rb[c]))
                except ValueError:
                    fdiff[c] = None
        if fdiff:
            entry["ulps"] = fdiff
        entry["frozen"] = {c: ra[c] for c in diff_cols}
        entry["new"] = {c: rb.get(c) for c in diff_cols}
        modified.append(entry)
    return {"identical": identical, "modified": modified, "removed": removed, "added": added,
            "rows_frozen": len(a), "rows_new": len(b)}


def t2_expectations() -> list[dict]:
    return list(csv.DictReader(open(CAL_DIR / "colleague_rows_expected_2026-08-28.csv",
                                    encoding="utf-8")))
