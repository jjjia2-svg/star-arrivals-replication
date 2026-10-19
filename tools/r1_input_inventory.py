#!/usr/bin/env python3
"""R1 F27: every input the P4 jobs read, where it is, and how it reaches an instance (Mac side).

  r1_input_inventory.py scan --out config/r1/input_inventory.tsv   # code scan + S3 listing + Mac stat
  r1_input_inventory.py sync JOB                                    # the job's data_sync pairs (JSON)

Reads repo text, `aws s3 ls` prefix listings and directory existence on the Mac; never a data file.
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]


@dataclasses.dataclass(frozen=True)
class Root:
    s3: str
    local: str


ROOTS = {
    "legacy_v2_output": Root("r1/legacy/legacy_v2_output/", "/data/legacy/thesis/v2_output/"),
    "legacy_thesis": Root("r1/legacy/legacy_thesis/", "/data/legacy/thesis/"),
    "legacy_multiplex": Root("r1/legacy/legacy_multiplex/", "/data/legacy/thesis/multiplex_pipeline/"),
    "derived": Root("r1/derived/", "/data/openalex_pipeline/derived/"),
    "snapshot": Root("r1/snapshot/", "/data/openalex_pipeline/snapshot/"),
    "ref": Root("r1/ref/october/", "/data/ref/october/"),
}
LEGACY = ("legacy_v2_output", "legacy_thesis", "legacy_multiplex")
NAME = r"([A-Za-z0-9_][A-Za-z0-9_.-]*)"          # a leading '_' too (multiplex_pipeline/_handoff_...)
PATTERNS = (
    ("legacy_v2_output", re.compile(r"(?<![A-Za-z0-9_])v2_output/" + NAME)),
    ("legacy_v2_output", re.compile(r"""["']v2_output["']\s*/\s*["']""" + NAME + "[\"']")),
    ("legacy_v2_output", re.compile(r"\$\{LEGACY_V2\}/" + NAME)),
    ("legacy_multiplex", re.compile(r"multiplex_pipeline/" + NAME)),
    ("legacy_thesis", re.compile(r"(?<![A-Za-z0-9_])(thesis_report)/")),
    ("derived", re.compile(r"(?<![A-Za-z0-9_])derived/" + NAME)),
    ("derived", re.compile(r"\$\{DERIVED\}/" + NAME)),
    ("derived", re.compile(r"\{SSD\}/" + NAME)),            # f"{SSD}/<table>": SSD is the derived root in econ920
    ("derived", re.compile(r"""derived_root\(\)\s*/\s*["']""" + NAME + "[\"']")),
    ("snapshot", re.compile(r"(?<![A-Za-z0-9_])snapshot/([a-z_]+)/")),
    ("output", re.compile(r"(?<![A-Za-z0-9_/])output/" + NAME)),
)
#: + the Figure 1 extractor J1a runs (W2-ORIGINS): its snapshot authors/institutions and u1/U2 reads become rows
SCAN = ("pipeline", "analysis", "tests", "tools/check_paper.py", "tools/star_origins_extract_2026-10.py")
#: the launchers, and the R1 tests whose toy strings name folders on purpose
SKIP = ("pipeline/aws/", "tests/test_r1_", "tests/r1_fakes.py", "tests/test_f0_test_safety.py")
SUFFIXES = (".py", ".R", ".sh", ".json", ".yaml", ".yml")
_OCT = ("pipeline/frames/", "pipeline/stars/", "pipeline/rosters/", "pipeline/fwci/",
        "analysis/estimation/", "analysis/robustness/p3_afar_cuts/", "analysis/robustness/sensitivity/")
#: job -> the code it runs (path prefixes); a row is needed by a job when a referencing file is in scope
JOB_SCOPES = {"j0": _OCT, "j1a": _OCT + ("tools/star_origins_extract_2026-10.py",),
              # j1b's robustness drivers rebuild frames through pipeline/frames and the 08-28 caliber layer (review P3b)
              "j1b": ("analysis/robustness/", "analysis/estimation/", "pipeline/frames/", "pipeline/stars/caliber_2026-08-28/"),
              "final": ("analysis/paper/", "tools/check_paper.py"), "test_big": ("tests/", "pipeline/units/")}
#: finalb0 is the final job's October twin (W2-FINALJOB): same code, same inputs
JOB_SCOPES["finalb0"] = JOB_SCOPES["final"]
_D = "/data/openalex_pipeline/derived/"
_V2 = ("r1/legacy/legacy_v2_output/", "/data/legacy/thesis/v2_output/")
#: the four stable R1 rank references (REF4): rk6b-06 and the exact upstream runs it pulled (rec-01, merge-04,
#: rk6a-04; data/cal2026-10r1/aws/runs/rk6b-06/launch_record.json, not shipped). rk6b-06 replaced rk6b-05
#: after the 3e paper checks; a rank re-run on these copies reproduces it, which J1a's rank_gate checks.
REF4 = (("r1/recovered/rec-01/", "/data/ref/r1/rec/"), ("r1/runs/merge-04/out/files/", "/data/ref/r1/merge/"),
        ("r1/runs/rk6a-04/out/files/", "/data/ref/r1/rk6a/"), ("r1/runs/rk6b-06/out/files/", "/data/ref/r1/rk6b/"))


def _sub(table, *subs):
    return tuple((f"{table}/{s}/", f"{_D}{table}/{s}/") for s in subs)


#: sync pairs a job always gets. Jobs whose code the scanner cannot see (the R1 kit's own instance scripts
#: under pipeline/aws/, SKIPped) list their pairs here, so EVERY job spec's data_sync is `sync <job>`
#: (R1 wave 1 integration: tests/test_r1_stages.py checks all of config/r1/jobs/).
JOB_EXTRA = {"final": (("r1/ref/october/", "/data/ref/october/"),),
             "fielddiag": _sub("u1_edges_full_2026-07-05", "authorship_edges", "works")
                          + _sub("u1_full_11school_2026-07-16", "authorship_edges", "works"),
             "rk6a": _sub("u1_edges_full_2026-07-05", "authorship_edges", "works", "work_text")
                     + _sub("u1_full_11school_2026-07-16", "authorship_edges", "works", "work_text"),
             "rk6b": _sub("u1_edges_full_2026-07-05", "authorship_edges", "works")
                     + _sub("u1_full_11school_2026-07-16", "authorship_edges", "works"),
             "rostermatch": (("r1/snapshot/authors/", "/data/snapshot/authors/"),),
             # V3-REC: the 10-02 bodies glob three legacy v2_output folders; the pins know only the root pair
             "recder": (_V2,),
             # merge-04 / rankdiff take their inputs as --pull dests (required_dests), not as data_sync
             "merge": (), "rankdiff": (),
             # J0-MEAS.3e: three 11-school sub-tables + the U2 person map; and, as rk6a, the 07-05 sub-tables:
             # dossier_pack calls restake_equiv.connect, whose run_screening import needs u1_edges_full_2026-07-05
             # (dossier-01 failed at start without it)
             "dossier": _sub("u1_full_11school_2026-07-16", "authorship_edges", "works", "work_text")
                        + (("u2_person_map_11school_2026-07-16/", f"{_D}u2_person_map_11school_2026-07-16/"),)
                        + _sub("u1_edges_full_2026-07-05", "authorship_edges", "works", "work_text"),
             # V3-RANK: REF4 + the two whole u1 tables
             "rankrepro": REF4 + (("u1_edges_full_2026-07-05/", f"{_D}u1_edges_full_2026-07-05/"),
                                  ("u1_full_11school_2026-07-16/", f"{_D}u1_full_11school_2026-07-16/")),
             # batch B4: the Figure 1 full-scan control reads the uploaded snapshot authors/institutions; the F11
             # econ920_null proof (tests/test_r1_econ920_m_real.py -> econ920_m.run_october_plan -> October's c1a
             # control and the 08-15 econ config's panel_glob) reads the U3 panel, which the scan cannot see (the
             # test is a tests/test_r1_ file and its driver sits under pipeline/aws/; t-big-03 failed on setup)
             "test_big": (("r1/snapshot/authors/", "/data/openalex_pipeline/snapshot/authors/"),
                          ("r1/snapshot/institutions/", "/data/openalex_pipeline/snapshot/institutions/"),
                          ("u3_panel_11school_2026-07-16/", f"{_D}u3_panel_11school_2026-07-16/")),
             # W2-INT: J1a's rank rows read the REF4 copies (W1-RANK / W2-TJ1A; rk6b-06 since W3-MPIN) and
             # its star_origins_extract row the snapshot authors/institutions (W2-ORIGINS; the scan finds them too)
             "j1a": REF4 + (("r1/snapshot/authors/", "/data/openalex_pipeline/snapshot/authors/"),
                            ("r1/snapshot/institutions/", "/data/openalex_pipeline/snapshot/institutions/"))}
JOB_EXTRA["finalb0"] = JOB_EXTRA["final"]
#: signed P2/P3 inputs, tracked in git (not shipped in the public copy)
SIGNED_INPUTS = ("data/cal2026-10r1/inputs/p2_decisions.json", "data/cal2026-10r1/inputs/add_list_r1.json",
                 "data/cal2026-10r1/inputs/flips_r1.json", "data/cal2026-10r1/inputs/p2_discipline",
                 "data/cal2026-10r1/inputs/paper_checks", "data/cal2026-10r1/inputs/p3_roster",
                 # W1-EVENTS (F10 + N16-S14): the redates and the add-list gate events_r1 reads (not shipped)
                 "data/cal2026-10r1/inputs/add_list_r1_summary.json", "data/cal2026-10r1/inputs/person_overrides.csv",
                 "data/cal2026-10r1/inputs/fixes_1001.csv", "data/cal2026-10r1/inputs/arrival_checks")
#: (root, name) -> why a scanner hit is not an input (filled after reviewing the first TSV; > 30 chars each)
_U1E = "a sub-table of derived/u1_edges_full_2026-07-05 (SSD names that table in the gold frame builders); synced with it"
_ROS = "a sub-folder of derived/u0p5_roster (SSD names that folder in build_audit.py); synced with it"
IGNORE: dict[tuple[str, str], str] = {
    ("derived", "authorship_edges"): _U1E, ("derived", "works"): _U1E, ("derived", "works_affil"): _U1E,
    ("derived", "fwci_baseline_pop"): _U1E,
    ("derived", "registry_v5_2026-07-20"): _ROS, ("derived", "roster_v4_2026-07-16"): _ROS,
    ("derived", "u1_edges"): "the ported units' generic default output root (--out-root); the real U1 tables are "
                             "u1_edges_full_2026-07-05 and u1_full_11school_2026-07-16",
    ("derived", "u2_person_map"): "a toy path '/X/derived/u2_person_map...' inside tests/test_ledger_new_2026_10.py",
    ("derived", "u2_resolve"): "an output folder the ported U2 unit writes (--out-dir); no P4 job reads it",
    ("derived", "u3_panel"): "an output folder the ported U3 unit writes (--out-dir); no P4 job reads it",
}
FIELDS = ("root", "name", "availability", "s3_prefix", "instance_path", "needed_by", "used_by")


@dataclasses.dataclass(frozen=True)
class Ref:
    root: str
    name: str
    file: str


@dataclasses.dataclass(frozen=True)
class Row:
    root: str
    name: str
    availability: str
    s3_prefix: str
    instance_path: str
    needed_by: str
    used_by: str


def _files(repo):
    repo = pathlib.Path(repo)
    for top in SCAN:
        base = repo / top
        paths = [base] if base.is_file() else (sorted(base.rglob("*")) if base.is_dir() else [])
        for path in paths:
            if not path.is_file() or "__pycache__" in path.parts or path.suffix not in SUFFIXES:
                continue
            rel = path.relative_to(repo).as_posix()
            if rel.startswith(SKIP):
                continue
            yield rel, path


def scan(repo) -> list:
    refs = set()
    for rel, path in _files(repo):
        text = path.read_text(encoding="utf-8", errors="replace")
        for root, pat in PATTERNS:
            for m in pat.finditer(text):
                name = m.group(1).rstrip(".")
                if name and (root, name) not in IGNORE:
                    refs.add(Ref(root, name, rel))
    return sorted(refs, key=lambda r: (r.root, r.name, r.file))


def _needed_by(files) -> str:
    return ",".join(j for j, scope in JOB_SCOPES.items() if any(f.startswith(scope) for f in files))


def classify(refs, *, mac_roots, s3_prefixes, tracked) -> list:
    groups = {}
    for r in refs:
        groups.setdefault((r.root, r.name), []).append(r.file)
    rows = []
    for (root, name), files in sorted(groups.items()):
        files = sorted(set(files))
        used = ";".join(files[:3]) + (f";+{len(files) - 3}" if len(files) > 3 else "")
        need = _needed_by(files)
        if root == "output":
            rows.append(Row(root, name, "generated", "", "", need, used))
            continue
        prefix, local = ROOTS[root].s3 + name + "/", ROOTS[root].local + name + "/"
        if root == "derived" and prefix not in s3_prefixes and name + "/" in s3_prefixes:
            prefix = name + "/"
        if prefix in s3_prefixes:
            avail = "s3"
        elif root in LEGACY and root in mac_roots and (pathlib.Path(mac_roots[root]) / name).is_dir():
            avail = "mac"
        else:
            avail = "missing"
        rows.append(Row(root, name, avail, prefix, local, need, used))
    for p in SIGNED_INPUTS:
        ok = any(t == p or t.startswith(p.rstrip("/") + "/") for t in tracked)
        rows.append(Row("repo", p, "repo" if ok else "missing", "", "", "j1a", ""))
    return rows


def write_tsv(rows, path) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow(dataclasses.asdict(r))


def read_tsv(path) -> list:
    with open(path, encoding="utf-8", newline="") as fh:
        return [Row(**r) for r in csv.DictReader(fh, delimiter="\t")]


def sync_pairs(rows, job) -> list:
    pairs = {tuple(p) for p in JOB_EXTRA.get(job, ())}
    for r in rows:
        if job not in r.needed_by.split(",") or r.root in ("output", "repo"):
            continue
        if r.availability != "s3":
            raise ValueError(f"{r.root}/{r.name} is {r.availability}: upload it (V3-UP) or explain it in IGNORE")
        # the derived and legacy roots collapse to one pinned root pair; the snapshot never does - its root is the
        # whole OpenAlex snapshot, so each table syncs alone (W2-INT, when the Figure 1 extractor joined the scan)
        if r.root in LEGACY or (r.root != "snapshot" and r.s3_prefix.startswith(ROOTS[r.root].s3)):
            pairs.add((ROOTS[r.root].s3, ROOTS[r.root].local))
        else:
            pairs.add((r.s3_prefix, r.instance_path))
    return [list(p) for p in sorted(pairs)]


def all_sync_pairs(rows) -> list:
    out = set()
    for job in JOB_SCOPES:
        out |= {tuple(p) for p in sync_pairs(rows, job)}
    for extra in JOB_EXTRA.values():
        out |= set(extra)
    return sorted(out)


def _s3_prefixes(aws, bucket) -> set:
    bases = ["", "r1/derived/", "r1/snapshot/", "r1/ref/october/"] + [ROOTS[k].s3 for k in LEGACY]
    out = set()
    for base in bases:
        try:
            text = aws(["s3", "ls", f"s3://{bucket}/{base}"])
        except Exception:                                       # noqa: BLE001  (an absent prefix lists as empty)
            continue
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("PRE "):
                out.add(base + line[4:].strip().rstrip("/") + "/")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="R1 F27 input inventory")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("scan")
    sc.add_argument("--out", default=str(REPO / "config" / "r1" / "input_inventory.tsv"))
    sy = sub.add_parser("sync")
    sy.add_argument("job")
    sy.add_argument("--tsv", default=str(REPO / "config" / "r1" / "input_inventory.tsv"))
    a = ap.parse_args(argv)
    if a.cmd == "sync":
        print(json.dumps(sync_pairs(read_tsv(a.tsv), a.job), indent=1))
        return 0
    sys.path.insert(0, str(REPO / "pipeline" / "aws" / "r1"))
    import r1kit  # noqa: PLC0415
    from analysis.lib.paths import load_paths  # noqa: PLC0415
    env = r1kit.use_env()
    p = load_paths()
    mac = {k: p[k] for k in LEGACY if k in p}
    tracked = set(subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True).stdout.split("\n"))
    rows = classify(scan(REPO), mac_roots=mac, s3_prefixes=_s3_prefixes(r1kit.aws, env["SAR_S3_BUCKET"]), tracked=tracked)
    write_tsv(rows, a.out)
    counts = {}
    for r in rows:
        counts[r.availability] = counts.get(r.availability, 0) + 1
    for k in sorted(counts):
        print(f"{k:<10} {counts[k]}")
    for r in rows:
        if r.availability == "missing":
            print(f"MISSING  {r.root}/{r.name}  needed_by={r.needed_by}  used_by={r.used_by}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(REPO))
    sys.exit(main())
