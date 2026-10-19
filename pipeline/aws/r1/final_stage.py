#!/usr/bin/env python3
"""R1 final job driver (V3-FINAL, unit W2-FINALJOB). Runs on an R1 instance only ($SAR_HOST).

The final job (config/r1/stages/final.json, mode M) and its twin finalb0 (config/r1/stages/finalb0.json,
mode B0 = October data, the switch-off proof) call one subcommand per stage row. Every path is a flag;
each subcommand writes $STAGE_OUT/<name>.json (STAGE_OUT = --out):

  unpack    r1_pack_tree.py unpack of the October and the current thesis tree (record-checked) into
            --dest/{october,current}; both made read-only                                 -> unpack.json
  canon     (M only) restore_upstream.py lays the canon out of the pulled J1a/J1b stage sets (every
            file digest-checked against its upstream done marker), then CANON.json (switches from the
            run config), tools/r1_canon.py manifest + check (CANON_OK), and a top MANIFEST.sha256
            that tools/verify_manifest.py reads                                            -> canon.json
            (finalb0 has no canon; its B0-only row pairs_b0 is not a subcommand: restore_upstream.py
            lays J0's October pairs_unified.csv out of the pulled J0 stage set, check_pin.py pins it)
  paper     bash analysis/run_all.sh --stages <list> under the given paths config (canon M or the
            October roots); the canon mode is asserted first                               -> paper.json
  sentinel  tools/check_paper.py on a thesis tree (--phase pre: the current vault tree, plus the
            legacy thesis_report twice, default path and --thesis-root; --phase post: the scratch
            tree with the scratch check_paper.py)                                          -> sentinel.json
  repin     the scratch repin, never in the repo or a source tree: a git worktree of the commit,
            a writable copy of the current tree, install.py ledgers + exhibits, replace.py,
            sync_clean (main.tex's edits carried to main_clean.tex with zero fuzz), repin.py on the
            worktree's check_paper.py, check_paper_repin.patch, scratch_paths.yaml        -> repin.json
  compile   pdflatex / bibtex / pdflatex x2, then pdflatex until .aux/.toc/.out stop changing (at most
            --max-extra more), for main_clean.tex and main.tex of the October and the scratch tree,
            each in its own writable copy; the logs are scanned                          -> compile.json
  texts     count_words.py and check_draft_text.py on both main_clean PDFs (and count_words on the
            author's reference PDF), count_bor.py against the record, the main/main_clean
            invariant                                                                      -> texts.json
  red       red_diff_2026-10.py build (October -> scratch) and verify (--reference the scratch PDF),
            and a reference verify of the October PDF against the author's PDF (equal, or different
            only as red_diff explains: reference_equal)                                       -> red.json
  numbers   tools/r1_number_diff.py (old: the October base-tree ledgers; new: the scratch tree's) with
            --printed = the ledger keys check_paper's pins read                           -> numbers.json
  gate2     judges gate 2 from the stage reports (gate2()), copies the deliverables to --final-dir,
            packs tree_r1.tar, writes gate2.json, change_facts.json and final_report_gate2.json
            (codes and counts only: it reaches summary.json). Exit 1 on GATE2_FAIL / B0_FAIL, after
            the deliverables are written; 0 on PASS, PENDING_AUTHOR and B0_PASS.

Nothing is written under data/cal2026-10, data/frames, analysis/expected or the repo's tools/: the
repins happen in --scratch, the generated numbers go to output/ (git-ignored). Applying
check_paper_repin.patch and promoting M stay the author's call (F4).

Pure helpers (tests/test_r1_final.py): sync_clean, diff_signature, scan_log, parse_words, parse_hits,
printed_entries, scratch_paths, same_file_bytes, same_file, rooted_equal, dir_diff, b0_tree_diff,
output_paper_diff, canon_meta, edit_rows, reference_equal, gate2, final_report, load_paper_config, load_expected_b0.
"""
from __future__ import annotations

import argparse
import ast
import datetime as dt
import difflib
import hashlib
import json
import os
import pathlib
import re
import shutil
import stat
import subprocess
import sys

HOSTS = ("ec2-r1-test", "ec2-r1")
HERE = pathlib.Path(__file__).resolve().parent
MODES = ("M", "B0")
SUBCOMMANDS = ("unpack", "canon", "paper", "sentinel", "repin", "compile", "texts", "red", "numbers", "gate2")

#: the stages only the M job has; finalb0 is final.json without them (tests/test_r1_final.py)
M_ONLY_STAGES = ("canon", "custody", "canon_pack", "tree_unpack_r1", "sentinel_r1")
#: the stages only finalb0 has: pairs_b0 restores J0's rebuilt October pairs_unified.csv (git-ignored, never
#: uploaded: ruling R2) into the October cal_intermediates root, the B0 counterpart of stage:canon, which
#: supplies cal_intermediates in M (review R7 #1; config/r1/layouts/finalb0_from_j0.json)
B0_ONLY_STAGES = ("pairs_b0",)
#: the text substitutions that turn an M row into its B0 twin (applied in order)
B0_SUBST = (("--mode M", "--mode B0"),
            ("config/r1/jobs/final.json", "config/r1/jobs/finalb0.json"),
            ("config/r1/M.json", "config/r1/B0.json"),
            ("config/r1/paths_aws_m.yaml", "config/r1/paths_aws.yaml"),
            ("/work/canon_m/expected/P1_econ_fnfix.json", '"$REPO_DIR/analysis/expected/P1_econ_fnfix.json"'),
            # October's own current tree: the R1 Figure 7 caption edit (2026-10-18) is for M only
            ("--current-role current", "--current-role current_b0"), ("--role current ", "--role current_b0 "))
#: what a canon-reading row lists as its canon: the assembled canon in M; in B0 the October MANIFESTs and
#: pairs_b0's restored October pairs_unified.csv
CANON_INPUTS = {"M": ("stage:canon", "stage:custody"),
                "B0": ("repo:data/MANIFEST.sha256", "repo:analysis/expected/MANIFEST.sha256",
                       "repo:data/cal2026-10/MANIFEST.sha256", "repo:data/paper_inputs/MANIFEST.sha256",
                       "stage:pairs_b0")}
#: job-spec keys in which finalb0.json may differ from final.json
TWIN_JOB_KEYS = ("kind", "stages", "steps", "required_dests", "env", "root_gb")

CANON_KEYS = ("cal", "frames", "expected", "raw_verified", "paper_inputs", "cal_intermediates")
COMPILE_TARGETS = ("october/main_clean", "october/main", "scratch/main_clean", "scratch/main")
#: the four thesis ledgers check_paper section A compares, as r1_number_diff ledger names
A_LEDGERS = {"main": "main", "carried": "main", "p3afar": "p3afar", "p1p2": "p1p2", "robustness": "robustness"}
A_TAGS = {"p3afar ledger": "p3afar", "p1p2 ledger": "p1p2", "robustness ledger": "robustness"}
#: repin_lib logical ledger -> r1_number_diff ledger name (gold_p1_union is the frozen gold, not a ledger)
PRINTED_LEDGER = {"main": "main", "carried": "main", "funnel": "funnel", "p3afar": "p3afar", "p1p2": "p1p2",
                  "robustness": "robustness", "zenou": "gaps_zenou", "zero": "gaps_zero_dose",
                  "switchers": "gaps_switchers", "toy": "gaps_toy", "switchers_p1p2": "gaps_switchers_p1p2"}

EDITING = ("EDIT", "SIGN_CHANGED", "DECIMALS_CHANGED")          # replace.py writes these spans
REFUSED = ("NEEDS_MANUAL", "CONFLICT", "BLOCKED_BY_REFUSAL")    # replace.py leaves these to the author
VERDICTS = ("PASS", "PENDING_AUTHOR", "GATE2_FAIL", "B0_PASS", "B0_FAIL")
PENDING_CODES = ("REFUSED_SPANS", "WORDS_OVER", "NOTE_CLAIMS_FALSE", "PRINTED_P_CROSSES_005", "PRINTED_SIGN_CHANGED",
                 "LEDGER_KEYS_UNREPRODUCIBLE", "FIGURE_RULE_CHANGED", "PIN_LABEL_CONFLICT")
HARD_CODES = ("FAIL_SET_MISMATCH", "POST_FAIL", "SECTION_C_FAIL", "BOR_CHANGED", "CUSTODY_FAIL", "CANON_FAIL",
              "COMPILE_FAIL", "DRAFT_TEXT_NEW", "REPORT_MISSING", "DELIVERABLE_MISSING", "PACK_FAIL",
              "MAIN_CLEAN_DRIFT", "NUMBERS_FAIL", "RED_VERIFY_FAIL", "REFERENCE_PDF_DIFF",
              "REPLACE_VERIFY_FAIL", "REPIN_VERIFY_FAIL",
              "B0_OUTPUT_DIFF", "B0_SENTINEL_DIFF", "B0_THESIS_ROOT_DIFF", "B0_THESIS_REPORT_DIFF",
              "B0_SCRATCH_DIFF", "B0_WORDS_DIFF", "B0_RED_DIFF", "B0_NOTE_FLAG")
#: ledger_diff.csv's columns gate 2 reads (tools/r1_number_diff.py HEADER, without same_at_3dp)
NUMBER_DIFF_COLS = ("ledger", "key", "status", "old", "new", "sign_change", "p_crosses_005", "printed")
#: a flagged number_diff row as gate 2 lists it (details, change_facts.json)
FLAG_COLS = ("ledger", "key", "old", "new", "printed")
#: the detail check_paper's check_unreproducible writes for a key a generated ledger lists in _unreproducible
UNREP_DETAIL = "UNREPRODUCIBLE (asserted only): "
#: the draft table generator's note-claim checks (analysis/paper/draft_2026_09_13_tables.py), relative to
#: --output-paper: a claim that no longer holds is flagged there, never reworded (N10), and goes to the
#: author through gate 2 (review R7 #16)
NOTE_CHECKS_REL = "draft_2026_09_13/NOTE_CHECKS.json"
#: Figure 1's ledger, relative to --output-paper, and its key of the blocks that leave the caption's rule (rows of
#: ten): analysis/paper/fig_star_origins.py writes the key only when there are any (R1 M2 round 3, Codex STOP 2)
STAR_ORIGINS_LEDGER = "data_numbers_star_origins.json"
FIGURE_EXC_KEY = "figure_block_exceptions"
CODES = HARD_CODES + PENDING_CODES

PAPER_SCHEMA = "sar.r1.final_paper.v1"
B0_SCHEMA = "sar.r1.final_b0_expected.v1"
#: final_b0_expected.json sections -> the key that names each declared difference
B0_SECTIONS = {"output_paper": "path", "vault_sentinel_fail": "name", "thesis_report_sentinel_fail": "name",
               "scratch_edits": "file", "red_runs": "text"}
#: final_b0_expected.json's list of October snapshot files no staged run_all stage writes (not a section)
REF_ONLY_SECTION = "output_paper_reference_only"


class SyncStop(RuntimeError):
    """main.tex's edits cannot be carried to main_clean.tex with zero fuzz."""


class Stop(RuntimeError):
    """A stage that cannot continue; code is a short upper-case token."""

    def __init__(self, code, why):
        super().__init__(f"{code}: {why}")
        self.code = code


# ---- small utilities -------------------------------------------------------------------------------
def _py() -> str:
    return os.environ.get("PY") or sys.executable


def sha256_file(p) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_json(path, obj) -> None:
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False, default=str) + "\n",
                    encoding="utf-8")


def _load_json(path):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def _run(argv, *, log=None, cwd=None, env=None) -> tuple:
    """(rc, stdout+stderr); the text also goes to `log` (appended, with the command line first)."""
    r = subprocess.run([str(x) for x in argv], cwd=str(cwd) if cwd else None, env=env, capture_output=True,
                       text=True, errors="replace")
    out = (r.stdout or "") + (r.stderr or "")
    if log is not None:
        log = pathlib.Path(log)
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(f"$ {' '.join(str(x) for x in argv)}\n{out}\n[rc={r.returncode}]\n")
    return r.returncode, out


def _files(root) -> list:
    root = pathlib.Path(root)
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()) if root.is_dir() else []


def copy_tree_writable(src, dst) -> int:
    """A writable copy of `src` (a read-only tree stays read-only; the copy's files and dirs are the
    user's own). Refuses an existing non-empty `dst`."""
    src, dst = pathlib.Path(src), pathlib.Path(dst)
    if dst.exists() and any(dst.iterdir()):
        raise Stop("DEST_EXISTS", f"{dst} exists and is not empty")
    n = 0
    for rel in _files(src):
        d = dst / rel
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src / rel, d)
        n += 1
    dst.mkdir(parents=True, exist_ok=True)
    return n


def make_read_only(root) -> None:
    root = pathlib.Path(root)
    paths = [p for p in root.rglob("*")] + [root]
    for p in sorted(paths, key=lambda x: -len(x.parts)):
        if p.is_symlink():
            continue
        mode = p.stat().st_mode
        p.chmod(mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


#: matplotlib's wall-clock render date in a PDF's Info object (review R7 #13; NOT_REPRODUCIBLE.md row 19)
_PDF_DATE = re.compile(rb"/(CreationDate|ModDate) \(D:\d{14}(?:Z|[+-]\d{2}'\d{2}')?\)")
#: the last startxref value moves with the date's length (matplotlib writes Info last and no /ID)
_PDF_STARTXREF = re.compile(rb"startxref\r?\n\d+\r?\n%%EOF\r?\n?\Z")


def same_file_bytes(name, a: bytes, b: bytes) -> tuple:
    """(equal, masked) for two versions of the file `name`. Raw byte equality, except for a PDF (name
    '.pdf', both '%PDF-'): each /CreationDate and /ModDate value and the final startxref value are masked
    first, provided each key occurs equally often (0 or 1) on both sides, so a date on one side only stays
    a difference; masked is True when only the masking made them equal. Every drawn byte still counts."""
    if a == b:
        return True, False
    if not (str(name).endswith(".pdf") and a.startswith(b"%PDF-") and b.startswith(b"%PDF-")):
        return False, False
    for key in (b"CreationDate", b"ModDate"):
        ca = sum(1 for m in _PDF_DATE.finditer(a) if m.group(1) == key)
        cb = sum(1 for m in _PDF_DATE.finditer(b) if m.group(1) == key)
        if ca != cb or ca > 1 or a.count(b"/" + key) != ca or b.count(b"/" + key) != cb:
            return False, False

    def mask(x):
        x = _PDF_DATE.sub(rb"/\1 (D:MASKED)", x)
        return _PDF_STARTXREF.sub(b"startxref\nMASKED\n%%EOF\n", x)
    eq = mask(a) == mask(b)
    return eq, eq


#: B0 compares an instance (x86_64) run with the October snapshot the author's Mac (arm64) built, and a few
#: floats move in their last digits. Two kinds of such noise count as equal and are reported (noise_masked),
#: never declared: a JSON number under a max_abs_diff* key (how far a recomputation is from its gold) when
#: both sides are below the generators' own pass tolerance, and a PNG whose pixels differ by at most one
#: level per channel. Nothing else is relaxed.
NOISE_TOKEN = re.compile(rb'("max_abs_diff\w*"\s*:\s*)(-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)')
NOISE_TOL = 1e-6                                   # analysis/paper/gaps_switchers*.R: TOL


def _json_noise_equal(a: bytes, b: bytes) -> bool:
    """Equal bytes once each max_abs_diff* number is masked, and every masked pair below NOISE_TOL."""
    va = [float(m.group(2)) for m in NOISE_TOKEN.finditer(a)]
    vb = [float(m.group(2)) for m in NOISE_TOKEN.finditer(b)]
    if not va or len(va) != len(vb) or NOISE_TOKEN.sub(rb"\1#", a) != NOISE_TOKEN.sub(rb"\1#", b):
        return False
    return all(abs(x) < NOISE_TOL and abs(y) < NOISE_TOL for x, y in zip(va, vb))


def same_within_noise(name, a: bytes, b: bytes):
    """'float_noise' or 'png_noise' when two versions of `name` differ only by the noise above; else None."""
    name = str(name)
    if name.endswith(".json"):
        return "float_noise" if _json_noise_equal(a, b) else None
    if name.endswith(".png"):
        try:
            import io
            from PIL import Image, ImageChops
            ia, ib = Image.open(io.BytesIO(a)), Image.open(io.BytesIO(b))
            if ia.size != ib.size or ia.mode != ib.mode or ia.info != ib.info:
                return None
            bands = ImageChops.difference(ia.convert("RGBA"), ib.convert("RGBA")).getextrema()
        except Exception:                          # an unreadable image is a difference
            return None
        return "png_noise" if max(hi for _, hi in bands) <= 1 else None
    return None


def same_file(pa, pb) -> tuple:
    """same_file_bytes on two files (the name of `pa` decides whether the PDF date is masked)."""
    return same_file_bytes(pathlib.Path(pa).name, pathlib.Path(pa).read_bytes(), pathlib.Path(pb).read_bytes())


#: the repo root the October snapshot's provenance strings record (ledger_main FR; gaps_zenou REL/F1/F2/PAIRS/
#: STAR_SET; gaps_zero_dose FR): analysis/lib/paths.py makes every path absolute (review R7 #14)
def _recorded_repo_root() -> str:
    """The checkout beside `legacy_thesis` in the tracked config/paths.yaml (the only file that may name the
    Mac's paths). Empty when no paths file is found, so a B0 rooted comparison then refuses."""
    for base in (pathlib.Path(os.environ.get("REPO_DIR") or "/nonexistent"), *HERE.parents[2:3]):
        cfg = base / "config" / "paths.yaml"
        if cfg.is_file():
            m = re.search(r'^legacy_thesis:\s*"([^"]+)"', cfg.read_text(encoding="utf-8"), re.M)
            if m:
                return str(pathlib.PurePosixPath(m.group(1)).parent / "star_arrivals_replication")
    return ""


OCTOBER_REPO_ROOT = _recorded_repo_root()
#: output/paper files that carry it, with how often (counted in the October snapshot and the base tree)
B0_ROOTED = {"data_numbers_main.json": 30, "gaps_zenou.json": 13, "gaps_zero_dose.json": 3}


def b0_rooted_scratch(date) -> dict:
    """The same three files under the thesis tree's dated names (install.py ledgers)."""
    return {f"data_numbers_{date}.json": 30, f"data_numbers_{date}_gaps_zenou.json": 13,
            f"data_numbers_{date}_gaps_zero_dose.json": 3}


def rooted_equal(ref: bytes, new: bytes, new_root: str, n: int) -> bool:
    """True only if new_root is absolute, `ref` holds the October repo root (with its slash) exactly n
    times, and `ref` with it replaced by new_root equals `new` byte for byte. Any other difference (a
    number, the _source text, the count, a path under another root) gives False."""
    if not (isinstance(new_root, str) and os.path.isabs(new_root)) or not OCTOBER_REPO_ROOT:
        return False
    r, w = (OCTOBER_REPO_ROOT + "/").encode(), (new_root.rstrip("/") + "/").encode()
    return ref.count(r) == n and ref.replace(r, w) == new


def dir_diff(a, b, rooted=None, new_root=None, masked=None, noise=None) -> list:
    """Relative paths that differ between two trees `a` (new) and `b` (reference): only in one, or other
    bytes. A rel in `rooted` ({rel: n}) is equal iff rooted_equal(b's bytes, a's bytes, new_root, n); any
    other file is compared with same_file (a PDF's render date masked; such paths go to `masked`). With a
    `noise` list, a file equal within same_within_noise is not a difference and goes there with its kind."""
    a, b = pathlib.Path(a), pathlib.Path(b)
    fa, fb = set(_files(a)), set(_files(b))
    out = []
    for r in sorted(fa | fb):
        if r not in fa or r not in fb:
            out.append(r)
            continue
        if rooted and r in rooted:
            ba, bb = (a / r).read_bytes(), (b / r).read_bytes()
            if ba != bb and not rooted_equal(bb, ba, new_root, rooted[r]):
                out.append(r)
            continue
        eq, msk = same_file(a / r, b / r)
        why = same_within_noise(r, (a / r).read_bytes(), (b / r).read_bytes()) if not eq and noise is not None \
            else None
        if why:
            noise.append(f"{r} ({why})")
        elif not eq:
            out.append(r)
        elif msk and masked is not None:
            masked.append(r)
    return out


def b0_tree_diff(current, scratch, rearchive, rooted=None, new_root=None, masked=None, noise=None) -> list:
    """The scratch tree against the tree it was copied from (B0). The only excused differences are the
    dated ledgers install.py moved to _archive/<rearchive>/: each must equal the source tree's file of
    that name, and its absence at the top is then not a difference. Everything else is listed. Files are
    compared with same_file (a PDF's render date masked; the masked paths go to `masked`); a top-level rel
    in `rooted` with rooted_equal (current = reference). Archived copies are never root-mapped."""
    current, scratch = pathlib.Path(current), pathlib.Path(scratch)
    pre = f"_archive/{rearchive}/"
    fc, fs_ = set(_files(current)), set(_files(scratch))
    moved = {r[len(pre):] for r in fs_ if r.startswith(pre)}
    out = []

    def differs(pa, pb, rel, copy=False):
        eq, msk = same_file(pa, pb)
        if eq and msk and masked is not None:
            masked.append(rel)
        why = same_within_noise(rel, pa.read_bytes(), pb.read_bytes()) \
            if not eq and noise is not None and not copy else None     # an archived original is a copy
        if why:
            noise.append(f"{rel} ({why})")
        return not eq and not why
    for r in sorted(fc | fs_):
        if r.startswith(pre):
            base = r[len(pre):]
            if base not in fc or differs(current / base, scratch / r, r, copy=True):
                out.append(r)
        elif r in fc and r in fs_ and rooted and r in rooted:
            bc, bs = (current / r).read_bytes(), (scratch / r).read_bytes()
            if bc != bs and not rooted_equal(bc, bs, new_root, rooted[r]):
                out.append(r)
        elif r in fc and r in fs_:
            if differs(current / r, scratch / r, r):
                out.append(r)
        elif r in fc:
            if r not in moved:
                out.append(r)
        else:
            out.append(r)
    return out


# ---- configs ---------------------------------------------------------------------------------------
def load_paper_config(src) -> dict:
    """config/r1/final_paper.json: {schema, ledger_date (null until the launch sets it), words_limit,
    figures (9 names), rearchive, deliver [{name, from}]}; ValueError when malformed."""
    c = _load_json(src) if not isinstance(src, dict) else dict(src)
    ok = (c.get("schema") == PAPER_SCHEMA and isinstance(c.get("words_limit"), int)
          and not isinstance(c.get("words_limit"), bool) and c["words_limit"] > 0
          and isinstance(c.get("figures"), list) and c["figures"]
          and all(isinstance(f, str) and re.fullmatch(r"[a-z0-9_]+", f) for f in c["figures"])
          and isinstance(c.get("rearchive"), str) and re.fullmatch(r"[A-Za-z0-9_.-]+", c["rearchive"] or "")
          and (c.get("ledger_date") is None or (isinstance(c["ledger_date"], str)
                                                and re.fullmatch(r"\d{4}-\d{2}-\d{2}", c["ledger_date"])))
          and isinstance(c.get("deliver"), list)
          and all(isinstance(d, dict) and set(d) == {"name", "from"} and re.fullmatch(r"[A-Za-z0-9_.-]+", d["name"])
                  and isinstance(d["from"], str) and not d["from"].startswith("/") and ".." not in d["from"].split("/")
                  for d in c["deliver"]))
    if not ok:
        raise ValueError(f"not a {PAPER_SCHEMA} file: {src if not isinstance(src, dict) else '<dict>'}")
    return c


def load_expected_b0(src) -> dict:
    """config/r1/final_b0_expected.json: the only October-data differences finalb0 may show, each entry
    {<key>, what, owner, reason}; returns {section: [entries]}. ValueError when malformed."""
    c = _load_json(src) if not isinstance(src, dict) else dict(src)
    if c.get("schema") != B0_SCHEMA:
        raise ValueError(f"not a {B0_SCHEMA} file")
    out = {}
    for sec, key in B0_SECTIONS.items():
        rows = c.get(sec)
        if not isinstance(rows, list):
            raise ValueError(f"{sec}: want a list")
        for r in rows:
            if not (isinstance(r, dict) and set(r) == {key, "what", "owner", "reason"}
                    and all(isinstance(r[k], str) and r[k].strip() for k in r)):
                raise ValueError(f"{sec}: every entry is {{{key}, what, owner, reason}} (non-empty): {r!r}")
        out[sec] = rows
    # R7 #15: October snapshot files no staged stage writes; not a declaration section (kept out of
    # B0_SECTIONS, so the never-declared rule of output_paper stands); absent = none
    ref_only = c.get(REF_ONLY_SECTION, [])
    if not isinstance(ref_only, list):
        raise ValueError(f"{REF_ONLY_SECTION}: want a list")
    for r in ref_only:
        p = r.get("path") if isinstance(r, dict) else None
        if not (isinstance(r, dict) and set(r) == {"path", "sha256", "what", "owner", "reason"}
                and all(isinstance(r[k], str) and r[k].strip() for k in r)
                and re.fullmatch(r"[0-9a-f]{64}", r["sha256"])
                and not p.startswith("/") and ".." not in pathlib.PurePosixPath(p).parts):
            raise ValueError(f"{REF_ONLY_SECTION}: every entry is {{path (relative), sha256 (64 hex), what, owner, "
                             f"reason}} (non-empty): {r!r}")
    out[REF_ONLY_SECTION] = ref_only
    return out


def output_paper_diff(out, ref, reference_only, rooted=None, new_root=None, masked=None, noise=None) -> list:
    """dir_diff(out, ref) less the reference-only files (R7 #15): a listed path is excused only when the
    reference holds exactly its pinned bytes and the run did not write it. A listed path missing from the
    reference or off its pin, or written by the run with other bytes, stays a difference."""
    out, ref = pathlib.Path(out), pathlib.Path(ref)
    diff = set(dir_diff(out, ref, rooted=rooted, new_root=new_root, masked=masked, noise=noise))
    for e in reference_only or []:
        p = e["path"]
        if not (ref / p).is_file() or sha256_file(ref / p) != e["sha256"]:
            diff.add(p)
        elif not (out / p).exists():
            diff.discard(p)
        elif sha256_file(out / p) != e["sha256"]:
            diff.add(p)                            # written by the run: its exact pinned bytes, noise or not
    return sorted(diff)


def scratch_paths(src, repo) -> dict:
    """The paths config the scratch check_paper.py reads: the config in force with every relative value
    except repo_root and the six canon keys made absolute against the real clone (so output/ is the
    real clone's output/paper). The canon keys stay as written: absolute (/work/canon_m) in M, and
    relative in B0, where they resolve to the scratch worktree's own (byte-equal) October roots."""
    import yaml
    cfg = yaml.safe_load(pathlib.Path(src).read_text(encoding="utf-8")) or {}
    repo = pathlib.Path(repo)
    out = {}
    for k, v in cfg.items():
        v = str(v)
        if k == "repo_root" or k in CANON_KEYS or os.path.isabs(v):
            out[k] = v
        else:
            out[k] = str((repo / v).resolve())
    return out


def _paths_value(src, key) -> str | None:
    import yaml
    cfg = yaml.safe_load(pathlib.Path(src).read_text(encoding="utf-8")) or {}
    return None if cfg.get(key) is None else str(cfg[key])


# ---- sync_clean ------------------------------------------------------------------------------------
def _lines(s: str) -> list:
    return s.splitlines(keepends=True)


def _opcodes(a, b):
    return difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()


def diff_signature(a: str, b: str) -> list:
    """What differs between two texts, line blocks only (positions dropped)."""
    la, lb = _lines(a), _lines(b)
    return [(t, tuple(la[i1:i2]), tuple(lb[j1:j2])) for t, i1, i2, j1, j2 in _opcodes(la, lb) if t != "equal"]


def sync_clean(main_old: str, main_new: str, clean_old: str) -> str:
    """main_clean.tex after main.tex went from main_old to main_new (replace.py never edits main_clean.tex).
    Every changed block of main.tex must sit on lines that main.tex and main_clean.tex share (an insertion:
    between two shared lines that are adjacent in both files); it is applied there unchanged, with zero fuzz.
    Afterwards diff(main, main_clean) must be what it was. Anything else raises SyncStop with the reason."""
    mo, mn, co = _lines(main_old), _lines(main_new), _lines(clean_old)
    if mo == mn:
        return clean_old
    shared = {}
    for t, i1, i2, j1, j2 in _opcodes(mo, co):
        if t == "equal":
            for k in range(i2 - i1):
                shared[i1 + k] = j1 + k
    plan = []
    for t, i1, i2, j1, j2 in _opcodes(mo, mn):
        if t == "equal":
            continue
        if i2 > i1:
            idx = [shared.get(i) for i in range(i1, i2)]
            if None in idx or idx != list(range(idx[0], idx[0] + len(idx))):
                raise SyncStop(f"main.tex lines {i1 + 1}-{i2} differ from main_clean.tex (or are not contiguous "
                               "there): the edit cannot be carried with zero fuzz")
            c1, c2 = idx[0], idx[-1] + 1
        else:
            before = shared.get(i1 - 1) if i1 > 0 else -1
            after = shared.get(i1) if i1 < len(mo) else len(co)
            if before is None or after is None or after != before + 1:
                raise SyncStop(f"an insertion before main.tex line {i1 + 1} lands where main.tex and "
                               "main_clean.tex differ: the place in main_clean.tex is ambiguous")
            c1 = c2 = after
        plan.append((c1, c2, mn[j1:j2]))
    out = list(co)
    for c1, c2, new in sorted(plan, key=lambda x: (x[0], x[1]), reverse=True):
        out[c1:c2] = new
    clean_new = "".join(out)
    if diff_signature(main_new, clean_new) != diff_signature(main_old, clean_old):
        raise SyncStop("after carrying the edits, diff(main.tex, main_clean.tex) is no longer the October one")
    return clean_new


# ---- log / tool-output parsers ---------------------------------------------------------------------
_REF = re.compile(r"LaTeX Warning: Reference [`'](.+?)' on page \S+ undefined")
_CITE = re.compile(r"(?:LaTeX|Package natbib) Warning: Citation [`'](.+?)' on page \S+ undefined")


def _unwrap(text: str) -> str:
    """TeX hard-wraps log lines at 79 characters (max_print_line): join such a line with the next."""
    out, buf = [], ""
    for ln in text.split("\n"):
        buf += ln
        if len(ln) == 79:
            continue
        out.append(buf)
        buf = ""
    if buf:
        out.append(buf)
    return "\n".join(out)


def scan_log(text: str) -> dict:
    """Errors ('! ' lines), undefined references and undefined citations in a pdflatex log."""
    t = _unwrap(text)
    errors = sum(1 for ln in t.split("\n") if ln.startswith("! "))
    refs = len(_REF.findall(t))
    cites = len(_CITE.findall(t))
    if not refs and "There were undefined references" in t:
        refs = 1
    if not cites and "There were undefined citations" in t:
        cites = 1
    return {"errors": errors, "undefined_refs": refs, "undefined_cites": cites,
            "multiply_defined": "There were multiply-defined labels" in t,
            "rerun_asked": "Rerun to get" in t or "Label(s) may have changed" in t,
            "ok": errors == 0 and refs == 0 and cites == 0}


_TOTAL = re.compile(r"^TOTAL (\d+)\s+\(limit ([\d,]+); margin ([+-]?\d+)\)\s*$", re.M)


def parse_words(stdout: str) -> dict:
    """tools/count_words.py's last line 'TOTAL <n>  (limit 12,000; margin <+d>)'; ValueError otherwise."""
    hits = _TOTAL.findall(stdout or "")
    if not hits:
        raise ValueError("count_words output has no TOTAL line")
    total, limit, margin = int(hits[-1][0]), int(hits[-1][1].replace(",", "")), int(hits[-1][2])
    if margin != limit - total:
        raise ValueError(f"count_words TOTAL line is inconsistent: {total} / {limit} / {margin}")
    return {"total": total, "limit": limit, "margin": margin, "over": total > limit}


_HIT = re.compile(r"^\s+p\.\d+\s+('(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\")\s")
_HITS_N = re.compile(r"^FAIL: (\d+) hit\(s\) in ", re.M)


def parse_hits(stdout: str) -> dict:
    """tools/check_draft_text.py's output (a manuscript tool, not shipped) -> {phrase: hits}; ValueError if the hit lines and the count disagree."""
    out = {}
    for ln in (stdout or "").splitlines():
        m = _HIT.match(ln)
        if m:
            ph = ast.literal_eval(m.group(1))
            out[ph] = out.get(ph, 0) + 1
    n = _HITS_N.search(stdout or "")
    want = int(n.group(1)) if n else 0
    if not n and not (stdout or "").lstrip().startswith("PASS"):
        raise ValueError("check_draft_text output has neither PASS nor FAIL")
    if sum(out.values()) != want:
        raise ValueError(f"check_draft_text: {sum(out.values())} hit lines for a count of {want}")
    return out


def printed_entries(keys) -> list:
    """Pin provenance keys ('p3afar:econ.ate_pp', 'carried:n', ...) -> r1_number_diff --printed lines
    '<ledger>\\t<key>' (sorted, unique); the frozen gold (gold_p1_union) is not a ledger and is left out."""
    out = set()
    for k in keys:
        logical, _, path = str(k).partition(":")
        if logical in PRINTED_LEDGER and path:
            out.add(f"{PRINTED_LEDGER[logical]}\t{path}")
    return sorted(out)


def canon_meta(switches: dict) -> dict:
    return {"schema": "sar.r1.canon.v1", "canon": "M", "prefix": {k: k for k in CANON_KEYS},
            "switches": {str(k): bool(v) for k, v in sorted(switches.items())}}


def canon_switches(config, repo) -> dict:
    """{switch: on?} for every registry switch, from the run config (CANON.json switches; F7)."""
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    from pipeline.lib import r1_config
    cfg = r1_config.load(config, repo=repo)
    return {name: bool(cfg.is_on(name)) for name in r1_config.SWITCHES}


# ---- gate 2 ----------------------------------------------------------------------------------------
def _graded(checks):
    return [c for c in checks or [] if not c.get("unrep") and not c.get("retired")]


def _fails(checks):
    return [c for c in _graded(checks) if not c.get("ok")]


def _a_ledger(label: str):
    if label in A_LEDGERS:
        return A_LEDGERS[label]
    if label in A_TAGS:
        return A_TAGS[label]
    return "main" if re.fullmatch(r"\d{4}-\d{2}-\d{2} ledger", label) else None


def _top(key: str) -> str:
    return re.split(r"[.\[]", key, maxsplit=1)[0]


def _base(name: str) -> str:
    return pathlib.PurePosixPath(str(name)).name


#: a '% src:' source of a replace.py edit: 'src:<file>:<line> <logical>:<key>' (replace.py Edit.source)
SRC_RX = re.compile(r"src:(\S+?):(\d+) (\S+)")
_NUMBER_DIFF = None


def repin_rc_ok(rc: int, report) -> bool:
    """repin.py exits 1 on a label CONFLICT (two pins want different numbers in one pin label): with its report
    written that goes on to gate 2, as replace.py's rc 1 does; any other rc, or no report, stops the stage."""
    return rc in (0, 1) and pathlib.Path(report).is_file()


def _number_diff_path() -> pathlib.Path:
    """The checkout's tools/r1_number_diff.py: from $REPO_DIR on an instance (run_stages runs this file as a copy
    in $WORK), else from this file's own checkout."""
    bases = ([pathlib.Path(os.environ["REPO_DIR"])] if os.environ.get("REPO_DIR") else []) + list(HERE.parents[2:3])
    for base in bases:
        if (base / "tools" / "r1_number_diff.py").is_file():
            return base / "tools" / "r1_number_diff.py"
    raise FileNotFoundError("tools/r1_number_diff.py: neither $REPO_DIR nor this file's checkout holds it")


def _is_p_key(path: str) -> bool:
    """tools/r1_number_diff.py's is_p_key on a ledger key path (the name is p, p_*, *_p or holds 'pvalue')."""
    global _NUMBER_DIFF
    if _NUMBER_DIFF is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("r1_number_diff_for_gate2", _number_diff_path())
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)   # type: ignore[union-attr]
        _NUMBER_DIFF = mod
    return bool(_NUMBER_DIFF.is_p_key(path))


def src_p_crossings(edits, literals=()) -> list:
    """M2 round 2 (review 3): the replace.py edits, written or refused, whose '% src:' source names a p key and
    whose old and new values lie on opposite sides of 0.05. The base tree prints such p-values with no pin, so
    ledger_diff never marks them printed; each is listed with its file, source and status. Round 3 (Codex STOP
    3): also replace.py's src_p_literals, every '% src:' p-literal with its unrounded values, so a p whose
    printed digits stay (0.0504 -> 0.0496) is seen; a literal an edit already names is listed once, from the edit."""
    out = []
    rows = [e for e in edits or [] if e.get("status") in EDITING + REFUSED]
    seen = {m.group(0) for e in rows for m in SRC_RX.finditer(str(e.get("source") or ""))}
    rows += [r for r in literals or [] if str(r.get("source")) not in seen and r.get("status") != "ALREADY_NEW"]
    for e in rows:
        o, n = e.get("old_value"), e.get("new_value")
        if not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (o, n)) or (o < 0.05) == (n < 0.05):
            continue
        for m in SRC_RX.finditer(str(e.get("source") or "")):
            logical, _, path = m.group(3).partition(":")
            if path and not logical.startswith("100*") and _is_p_key(path):
                out.append({"ledger": PRINTED_LEDGER.get(logical, logical), "key": path, "old": o, "new": n,
                            "printed": "true", "file": e.get("file"), "source": m.group(0), "status": e.get("status")})
    return out


def _unrep_a(checks) -> dict:
    """{(ledger, top key): reason} of the section-A lines check_paper records as UNREPRODUCIBLE (a key a generated
    ledger lists in its _unreproducible block; ok, never FAIL). The reason is the ledger's, from the detail."""
    out = {}
    for c in checks or []:
        m = re.match(r"^\[([^\]]+)\] (.+)$", c.get("name", "")) if c.get("section") == "A" and c.get("unrep") else None
        led = _a_ledger(m.group(1)) if m else None
        if led:
            key, detail = m.group(2), str(c.get("detail") or "")
            pre = f"{UNREP_DETAIL}{key} — "
            out[(led, key)] = detail[len(pre):] if detail.startswith(pre) else detail
    return out


def valid_note_checks(nc) -> bool:
    """NOTE_CHECKS.json's shape: a non-empty list of {table, claim, holds (bool), detail} (str otherwise)."""
    return isinstance(nc, list) and bool(nc) and all(
        isinstance(c, dict) and isinstance(c.get("holds"), bool)
        and all(isinstance(c.get(k), str) for k in ("table", "claim", "detail")) for c in nc)


def valid_figure_exceptions(exc) -> bool:
    """figure_block_exceptions' shape: {rows_of: int, serpentine: [country code], wide: {country code: int}}."""
    return (isinstance(exc, dict) and isinstance(exc.get("rows_of"), int) and isinstance(exc.get("serpentine"), list)
            and all(isinstance(c, str) for c in exc["serpentine"]) and isinstance(exc.get("wide"), dict)
            and all(isinstance(c, str) and isinstance(n, int) for c, n in exc["wide"].items()))


def figure_caption(tree):
    """Figure 1's caption in a tree: {file, line, sentence}, the sentence that names the rows ('grouped in rows of
    ten'; the whole caption when none does), read only. None when no figure includes fig_star_origins."""
    tree = pathlib.Path(tree)
    for p in [tree / "main.tex"] + sorted((tree / "sections").glob("*.tex")):
        if not p.is_file():
            continue
        lines = p.read_text(encoding="utf-8").split("\n")
        at = next((i for i, ln in enumerate(lines) if "includegraphics" in ln and "fig_star_origins" in ln), None)
        if at is None:
            continue
        cap = next((i for i in range(at, min(at + 10, len(lines))) if "\\caption{" in lines[i]), None)
        if cap is None:
            return {"file": p.relative_to(tree).as_posix(), "line": None, "sentence": None}
        text = re.split(r"(?<!\\)%", lines[cap].split("\\caption{", 1)[1])[0]
        text = re.sub(r"\\(?:REV|BOR)\{", "", text).rstrip().rstrip("}").strip()
        rows = [x for x in re.split(r"(?<=\.)\s+", text) if "row" in x.lower()]
        return {"file": p.relative_to(tree).as_posix(), "line": cap + 1, "sentence": rows[0] if rows else text}
    return None


def gate2(inputs: dict, mode: str, expected_b0) -> tuple:
    """Gate 2. Returns (verdict, codes, details); codes keep CODES order, details hold the lists behind
    them (pin names, files; never in summary.json).

    inputs: pre/post (the vault sentinel's checks before and after the scratch repin: dicts with section,
    name, ok, retired, unrep, file), number_diff ([{ledger, key, status, old, new, sign_change, p_crosses_005,
    printed}]: ledger_diff.csv), changed_tables (tables
    install changed), edits (replace.py edits, one row each: {pins: [names], pin: pins[0]|None, file, status,
    ...}; edit_rows), renamed ({old pin name:
    new}, repin.py's label edits), bor_equal, compile ({target: {ok}}), draft_hits ({october, new}:
    {phrase: n}), words ({october, new, reference}), words_limit, reports_missing, deliverables_missing,
    pack_ok, main_clean_invariant, numbers_rc, red ({build_ok, verify_ok, reference_equal, reference_explained,
    red_runs}; reference_explained goes to details),
    note_checks (the draft tables' NOTE_CHECKS.json: a missing or malformed list is REPORT_MISSING; a claim
    that no longer holds is NOTE_CLAIMS_FALSE in M, B0_NOTE_FLAG in B0; R7 #16);
    M also custody_ok, canon_ok, replace_verify (replace.py's post-write check: {pins_not_new,
    edits_left_new_to_new, src_literals_not_matching_new_key, draft_verify_absent}), repin_verify (repin.py's:
    {renamed_missing, overlay_keys_unmatched}), src_p_literals (replace.py's every '% src:' p-literal, with
    its unrounded old and new values and status) and figure_exceptions / figure_caption (Figure 1's
    figure_block_exceptions and figure_caption(); absent when the figure keeps its rule); B0 also
    output_paper_diff, thesis_default, thesis_root, scratch_diff, pdf_date_masked and noise_masked (reported only).

    M: every pre-repin FAIL is explained (section A: a top-level key F24' marks changed; B: a table
    install changed; D: a pin replace.py edits or refuses, or a cell of a changed table, or a claim --
    check kind 'claim', a sentence no tool rewrites -- whose sentence is found: that claim is refused,
    it goes to the author; a claim whose sentence is gone stays unexplained) and every change shows
    (each changed key of the four A ledgers, each changed table the sentinel checks and each pin
    replace.py would edit has its FAIL; a key dropped because a generated ledger lists it in _unreproducible,
    which check_paper records as UNREPRODUCIBLE, goes to the author with that reason instead:
    LEDGER_KEYS_UNREPRODUCIBLE); section C has no FAIL; after the repin only refused spans and
    refused claims FAIL; replace.py's and repin.py's own post-write checks pass (else REPLACE_VERIFY_FAIL /
    REPIN_VERIFY_FAIL). Hard codes -> GATE2_FAIL; else refused spans or claims / words over the limit / a printed
    p that crosses 0.05 (PRINTED_P_CROSSES_005: a printed ledger_diff row, or a '% src:' p-literal, edited or
    not) / a printed sign change, as a SIGN_CHANGED edit or a ledger_diff row (PRINTED_SIGN_CHANGED) / Figure 1's
    blocks leaving the caption's rows of ten (FIGURE_RULE_CHANGED) / an unreproducible ledger key -> PENDING_AUTHOR
    (R1 M2: replace.py rewrites the number only, and the words around it may now be wrong; a printed '' is unknown
    and counts as printed); else PASS. B0: only the differences in final_b0_expected.json (both directions) ->
    B0_PASS/B0_FAIL; the M-only flags are not read."""
    if mode not in MODES:
        raise ValueError(f"mode {mode!r}")
    codes, det = set(), {"unexplained": [], "missing": [], "post_unexplained": [], "refused": [],
                         "sign_changed": [], "decimals_changed": [], "new_draft_hits": {}, "note_flags": []}
    pre, post = inputs.get("pre") or [], inputs.get("post") or []
    edits = inputs.get("edits") or []
    pin_status = {}
    for e in edits:                       # an edit carries pins: [names] (edit_rows; R7 #9), or a lone pin
        for p in (e.get("pins") if e.get("pins") is not None else ([e["pin"]] if e.get("pin") else [])):
            pin_status.setdefault(p, set()).add(e.get("status"))
    det["refused"] = [e for e in edits if e.get("status") in REFUSED]
    det["sign_changed"] = [e for e in edits if e.get("status") == "SIGN_CHANGED"]
    det["decimals_changed"] = [e for e in edits if e.get("status") == "DECIMALS_CHANGED"]
    renamed_back = {v: k for k, v in (inputs.get("renamed") or {}).items()}
    changed_tables = {_base(t) for t in inputs.get("changed_tables") or []}

    # -- checks both modes share
    if inputs.get("reports_missing"):
        codes.add("REPORT_MISSING")
    if inputs.get("deliverables_missing"):
        codes.add("DELIVERABLE_MISSING")
    if inputs.get("pack_ok") is not True:
        codes.add("PACK_FAIL")
    if inputs.get("bor_equal") is not True:
        codes.add("BOR_CHANGED")
    comp = inputs.get("compile") or {}
    if any((comp.get(t) or {}).get("ok") is not True for t in COMPILE_TARGETS):
        codes.add("COMPILE_FAIL")
    hits = inputs.get("draft_hits") or {}
    old_h, new_h = hits.get("october"), hits.get("new")
    if not isinstance(old_h, dict) or not isinstance(new_h, dict):
        codes.add("REPORT_MISSING")
    else:
        det["new_draft_hits"] = {p: n - old_h.get(p, 0) for p, n in new_h.items() if n > old_h.get(p, 0)}
        if det["new_draft_hits"]:
            codes.add("DRAFT_TEXT_NEW")
    if inputs.get("main_clean_invariant") is not True:
        codes.add("MAIN_CLEAN_DRIFT")
    if inputs.get("numbers_rc") != 0:
        codes.add("NUMBERS_FAIL")
    red = inputs.get("red") or {}
    if red.get("build_ok") is not True or red.get("verify_ok") is not True:
        codes.add("RED_VERIFY_FAIL")
    if red.get("reference_equal") is not True:
        codes.add("REFERENCE_PDF_DIFF")
    # what explained the October PDF's difference from the author's reference PDF, if any (reference_equal)
    det["reference_explained"] = red.get("reference_explained")
    if any(c.get("section") == "C" for c in _fails(pre) + _fails(post)):
        codes.add("SECTION_C_FAIL")
    # the draft tables' note claims (R7 #16): a claim that no longer holds is flagged by the generator,
    # never reworded; M sends it to the author, B0 (October ledgers: all hold) fails on it
    nc = inputs.get("note_checks")
    if not valid_note_checks(nc):
        codes.add("REPORT_MISSING")
    else:
        det["note_flags"] = [{"table": c["table"], "claim": c["claim"], "detail": c["detail"]}
                             for c in nc if c["holds"] is not True]
    words = inputs.get("words") or {}
    limit = inputs.get("words_limit")

    if mode == "M":
        if inputs.get("custody_ok") is not True:
            codes.add("CUSTODY_FAIL")
        if inputs.get("canon_ok") is not True:
            codes.add("CANON_FAIL")
        changed = [r for r in inputs.get("number_diff") or [] if r.get("status") != "unchanged"]
        changed_top = {(r["ledger"], _top(r["key"])) for r in changed}
        pre_fail = _fails(pre)
        a_fails, claims_refused = set(), set()
        for c in pre_fail:
            s, name = c.get("section"), c.get("name", "")
            ok = False
            if s == "A":
                m = re.match(r"^\[([^\]]+)\] (.+)$", name)
                led = _a_ledger(m.group(1)) if m else None
                if led:
                    a_fails.add((led, m.group(2)))
                    ok = (led, m.group(2)) in changed_top
            elif s == "B":
                ok = _base(name) in changed_tables or _base(c.get("file") or "") in changed_tables
            elif s == "C":
                continue                                   # SECTION_C_FAIL above
            elif s == "D":
                f = str(c.get("file") or "")
                # a cell of a table install changed: check_paper names a check on the tree's tables/
                # 'tables/<name>' (review R7 #10); no other path counts (output/paper's tab_robustness.tex
                # shares a name with a thesis table)
                ok = bool(pin_status.get(name, set()) & set(EDITING + REFUSED)) or \
                    (f.startswith("tables/") and _base(f) in changed_tables)
                if not ok and c.get("kind") == "claim" and c.get("anchor_found") is True:
                    # a sentence whose meaning follows the ledgers no longer holds (review R7 #8): no tool
                    # rewrites words, so it goes to the author like a refused span; its anchor is found
                    ok = True
                    claims_refused.add(name)
                    det["refused"].append({"pin": None, "claim": name, "file": c.get("file"),
                                           "status": "CLAIM_FALSE", "reason": c.get("detail")})
            if not ok:
                det["unexplained"].append(f"{s}:{name}")
        # every change shows: A keys, B tables the sentinel checks, D pins replace.py edits. A key that is gone
        # from the new ledger because a generated ledger lists it in _unreproducible (check_paper: UNREPRODUCIBLE,
        # never FAIL) is no missing FAIL: it goes to the author with that ledger's reason (M2 round 2)
        unrep_a = _unrep_a(pre)
        dropped = {}
        for r in changed:
            dropped.setdefault((r["ledger"], _top(r["key"])), set()).add(r.get("status"))
        det["unreproducible"] = []
        for led, key in sorted(changed_top):
            if led in set(A_LEDGERS.values()) and (led, key) not in a_fails:
                if (led, key) in unrep_a and dropped[(led, key)] == {"dropped"}:
                    det["unreproducible"].append({"ledger": led, "key": key, "reason": unrep_a[(led, key)]})
                else:
                    det["missing"].append(f"A:{led} {key}")
        b_names = {_base(c.get("name", "")) for c in pre if c.get("section") == "B"}
        b_failed = {_base(c.get("name", "")) for c in pre_fail if c.get("section") == "B"}
        for t in sorted((changed_tables & b_names) - b_failed):
            det["missing"].append(f"B:{t}")
        retired = {c.get("name") for c in pre if c.get("retired")}
        d_failed = {c.get("name") for c in pre_fail if c.get("section") == "D"}
        for pin, sts in sorted(pin_status.items()):
            if sts & set(EDITING) and pin not in retired and pin not in d_failed:
                det["missing"].append(f"D:{pin}")
        if det["unexplained"] or det["missing"]:
            codes.add("FAIL_SET_MISMATCH")
        refused_pins = {p for p, sts in pin_status.items() if sts & set(REFUSED)}
        for c in _fails(post):
            name = renamed_back.get(c.get("name"), c.get("name"))
            if c.get("section") == "C":
                continue
            if not (c.get("section") == "D" and (name in refused_pins or name in claims_refused)):
                det["post_unexplained"].append(f"{c.get('section')}:{c.get('name')}")
        if det["post_unexplained"]:
            codes.add("POST_FAIL")
        if det["refused"]:
            codes.add("REFUSED_SPANS")
        if det["note_flags"]:
            codes.add("NOTE_CLAIMS_FALSE")
        # R1 M2: printed numbers whose meaning may flip. A printed '' is unknown (numbers could not list the
        # printed keys): listed, never guessed away
        flagged = [r for r in inputs.get("number_diff") or [] if r.get("printed") in ("true", "")]
        det["p_crossings"] = [{k: r.get(k) for k in FLAG_COLS} for r in flagged if r.get("p_crosses_005") == "true"]
        listed = {(c.get("ledger"), c.get("key")) for c in det["p_crossings"]}
        det["p_crossings"] += [c for c in src_p_crossings(edits, inputs.get("src_p_literals"))  # no pin reads these
                               if (c.get("ledger"), c.get("key")) not in listed]
        det["printed_sign_changes"] = [{k: r.get(k) for k in FLAG_COLS} for r in flagged
                                       if r.get("sign_change") == "true"]
        if det["p_crossings"]:
            codes.add("PRINTED_P_CROSSES_005")
        if det["sign_changed"] or det["printed_sign_changes"]:
            codes.add("PRINTED_SIGN_CHANGED")
        if det["unreproducible"]:
            codes.add("LEDGER_KEYS_UNREPRODUCIBLE")
        # round 3 (Codex STOP 2): Figure 1's blocks leave the caption's rule at this run's counts (rows of 20, a
        # serpentine fill); the caption is never rewritten: the author decides
        exc = inputs.get("figure_exceptions")
        # a serpentine fill keeps 'rows of ten' true; only a block in wider rows breaks the caption
        det["figure_rule"] = [{"caption": inputs.get("figure_caption"), "exceptions": exc}] if exc and exc.get("wide") else []
        if det["figure_rule"]:
            codes.add("FIGURE_RULE_CHANGED")
        # final-05: two pins want different new numbers in one check_paper pin label (a pin name, not paper text)
        det["label_conflicts"] = list(inputs.get("label_conflicts") or [])
        if det["label_conflicts"]:
            codes.add("PIN_LABEL_CONFLICT")
        # R1 M2: replace.py and repin.py exit 0 on a failed post-write check; their reports say so
        for key, code in (("replace_verify", "REPLACE_VERIFY_FAIL"), ("repin_verify", "REPIN_VERIFY_FAIL")):
            det[key] = {k: v for k, v in (inputs.get(key) or {}).items() if v}
            if det[key]:
                codes.add(code)
        if not isinstance(limit, int) or not isinstance(words.get("new"), int) or not isinstance(words.get("october"), int):
            codes.add("REPORT_MISSING")
        elif words["new"] > limit or words["october"] > limit:
            codes.add("WORDS_OVER")
        hard = codes & set(HARD_CODES)
        verdict = "GATE2_FAIL" if hard else "PENDING_AUTHOR" if codes else "PASS"
        return verdict, [c for c in CODES if c in codes], det

    # ---- B0: exactly the declared differences
    exp = expected_b0 if expected_b0 is not None else {k: [] for k in B0_SECTIONS}
    det["pdf_date_masked"] = list(inputs.get("pdf_date_masked") or [])   # reported, never a difference (#13)
    det["noise_masked"] = list(inputs.get("noise_masked") or [])         # reported, never a difference

    def declared(sec):
        return {r[B0_SECTIONS[sec]] for r in exp.get(sec, [])}

    def both_ways(got, sec, code, label):
        want = declared(sec)
        extra, absent = sorted(set(got) - want), sorted(want - set(got))
        if extra or absent:
            codes.add(code)
            det[f"{label}_undeclared"], det[f"{label}_declared_absent"] = extra, absent

    both_ways(inputs.get("output_paper_diff") or [], "output_paper", "B0_OUTPUT_DIFF", "output_paper")
    both_ways([c.get("name") for c in _fails(pre)], "vault_sentinel_fail", "B0_SENTINEL_DIFF", "vault_sentinel")
    if _fails(post):
        codes.add("POST_FAIL")
        det["post_unexplained"] = [f"{c.get('section')}:{c.get('name')}" for c in _fails(post)]
    td, tr = inputs.get("thesis_default"), inputs.get("thesis_root")
    if td is None or tr is None:
        codes.add("REPORT_MISSING")
    else:
        def key(cs):
            return [(c.get("section"), c.get("name"), bool(c.get("ok")), c.get("detail")) for c in cs]
        if key(td) != key(tr):
            codes.add("B0_THESIS_ROOT_DIFF")
        both_ways([c.get("name") for c in _fails(td)], "thesis_report_sentinel_fail", "B0_THESIS_REPORT_DIFF",
                  "thesis_report")
    scratch = set(inputs.get("scratch_diff") or []) | {e.get("file") for e in edits
                                                       if e.get("status") in EDITING + REFUSED}
    both_ways(sorted(x for x in scratch if x), "scratch_edits", "B0_SCRATCH_DIFF", "scratch")
    both_ways(red.get("red_runs") or [], "red_runs", "B0_RED_DIFF", "red_runs")
    if not isinstance(words.get("october"), int) or words.get("october") != words.get("reference"):
        codes.add("B0_WORDS_DIFF")
    if det["note_flags"]:
        codes.add("B0_NOTE_FLAG")
    verdict = "B0_FAIL" if codes & set(HARD_CODES) else "B0_PASS"
    return verdict, [c for c in CODES if c in codes and c in HARD_CODES], det


def final_report(mode: str, verdict: str, codes, det, extra_counts=None) -> dict:
    """final_report_gate2.json: mode, verdict, codes and integer counts only (it reaches summary.json, and
    pin names can carry person names)."""
    if mode not in MODES or verdict not in VERDICTS or any(c not in CODES for c in codes):
        raise ValueError("final_report: unknown mode, verdict or code")
    counts = {"unexplained": len(det.get("unexplained", [])), "missing": len(det.get("missing", [])),
              "post_unexplained": len(det.get("post_unexplained", [])), "refused": len(det.get("refused", [])),
              "sign_changed": len(det.get("sign_changed", [])),
              "decimals_changed": len(det.get("decimals_changed", [])),
              "new_draft_hits": sum(det.get("new_draft_hits", {}).values()),
              "note_flags": len(det.get("note_flags", []))}
    for k in ("p_crossings", "printed_sign_changes", "unreproducible", "figure_rule", "label_conflicts"):   # M only
        if k in det:
            counts[k] = len(det[k])
    for k, v in (extra_counts or {}).items():
        if re.fullmatch(r"[a-z0-9][a-z0-9_]{0,63}", str(k)) and isinstance(v, (int, bool)):
            counts[str(k)] = v
    return {"mode": mode, "verdict": verdict, "codes": list(codes), "counts": counts}


# ---- subcommands -----------------------------------------------------------------------------------
def _host_guard() -> None:
    if os.environ.get("SAR_HOST", "").strip() not in HOSTS:
        raise SystemExit("R1 rule: final_stage.py runs only on an R1 instance ($SAR_HOST ec2-r1 / ec2-r1-test)")


def cmd_unpack(a) -> int:
    repo, dest, out = pathlib.Path(a.repo), pathlib.Path(a.dest), pathlib.Path(a.out)
    tool = repo / "tools" / "r1_pack_tree.py"
    rep = {"mode": a.mode, "result": "OK", "counts": {}}
    # the current tree is checked against --current-role (finalb0: current_b0) and lands in dest/current
    rep["current_role"] = a.current_role
    for role, key, tar in (("october", "october", a.tar_october), ("current", a.current_role, a.tar_current)):
        rc, _ = _run([_py(), tool, "unpack", "--tar", tar, "--record", a.record, "--role", key,
                      "--dest", dest / role], log=out / "unpack.log")
        if rc:
            rep.update(result="STOP", code="UNPACK_FAIL", stage=role)
            _write_json(out / "unpack.json", rep)
            return 1
        rep["counts"][role] = len(_files(dest / role))
        rep[f"tar_sha256_{role}"] = sha256_file(tar)
    for role in ("october", "current"):
        make_read_only(dest / role)
    rec = _load_json(a.record)
    rep["ledger_date_current"] = rec[a.current_role]["ledger_date"]
    _write_json(out / "unpack.json", rep)
    return 0


def cmd_canon(a) -> int:
    if a.mode != "M":
        raise SystemExit("canon runs in mode M only (finalb0 reads the October roots)")
    repo, dest, out, bindir = (pathlib.Path(x) for x in (a.repo, a.dest, a.out, a.bin))
    out.mkdir(parents=True, exist_ok=True)
    log = out / "canon.log"
    rep = {"mode": "M", "result": "STOP"}
    try:
        cal = _paths_value(a.paths, "cal")
        if not cal or pathlib.Path(cal).parent.resolve() != dest.resolve():
            raise Stop("BAD_PATH", f"the paths config's cal root {cal} is not under --dest {dest}")
        if dest.exists() and any(dest.iterdir()):
            raise Stop("DEST_EXISTS", f"{dest} is not empty")
        bindir.mkdir(parents=True, exist_ok=True)
        for f in ("restore_upstream.py", "run_stages.py"):          # never run a pipeline/ script in place
            shutil.copyfile(repo / "pipeline" / "aws" / "r1" / f, bindir / f)
        argv = [_py(), bindir / "restore_upstream.py"]
        for s in a.stages:
            argv += ["--stages", s]
        argv += ["--layout", a.layout, "--dest", dest, "--out", out, "--repo", repo]
        rc, _ = _run(argv, log=log)
        rr = _load_json(out / "report_restore.json") if (out / "report_restore.json").is_file() else {}
        if rc or rr.get("result") != "OK":
            rep.update(code=rr.get("code", "RESTORE_FAIL"), **({"stage": rr["stage"]} if rr.get("stage") else {}))
            raise Stop(rep["code"], "restore_upstream refused")
        _write_json(dest / "CANON.json", canon_meta(canon_switches(a.config, repo)))
        rc, _ = _run([_py(), repo / "tools" / "r1_canon.py", "manifest", dest], log=log)
        if rc:
            raise Stop("CANON_FAIL", "r1_canon.py manifest failed")
        rc, txt = _run([_py(), repo / "tools" / "r1_canon.py", "check", dest, "--tsv", a.tsv], log=log)
        if rc or not re.search(r"^CANON_OK \d+ rows$", txt, re.M):
            raise Stop("CANON_FAIL", "r1_canon.py check did not print CANON_OK")
        lines = []
        for k in CANON_KEYS:
            man = dest / k / "MANIFEST.sha256"
            if man.is_file():
                lines += [ln for ln in man.read_text(encoding="utf-8").splitlines() if ln.strip()]
        lines.append(f"{sha256_file(dest / 'CANON.json')}  CANON.json")
        (dest / "MANIFEST.sha256").write_text("".join(f"{ln}\n" for ln in sorted(lines, key=lambda x: x.split('  ', 1)[1])),
                                              encoding="utf-8")
        rc, txt = _run([_py(), repo / "tools" / "verify_manifest.py", dest / "MANIFEST.sha256"], log=log)
        if rc or "MANIFEST_OK" not in txt:
            raise Stop("CANON_FAIL", "the canon's top MANIFEST does not verify")
        # the stage's own products carry the canon's content, so stage:canon's digest follows it (resume)
        shutil.copyfile(dest / "MANIFEST.sha256", out / "canon_manifest.sha256")
        files = [r for r in _files(dest) if pathlib.PurePosixPath(r).name not in ("MANIFEST.sha256", "CANON.json")]
        rep.update(result="OK", code="OK", counts={"files": len(files), "rows": len(lines) - 1})
        rc = 0
    except Stop as e:
        rep.setdefault("code", e.code)
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(f"STOP {e}\n")
        rc = 1
    _write_json(out / "canon.json", rep)
    return rc


def cmd_paper(a) -> int:
    repo, out = pathlib.Path(a.repo), pathlib.Path(a.out)
    env = dict(os.environ, SAR_PATHS_CONFIG=str(a.paths),
               PATH=f"{pathlib.Path(_py()).parent}{os.pathsep}{os.environ.get('PATH', '')}")
    want = "M" if a.mode == "M" else "october"
    rc, txt = _run([_py(), "-c", "from analysis.lib import canon; print(canon.mode())"], cwd=repo, env=env,
                   log=out / "paper.log")
    if rc or txt.strip().splitlines()[-1:] != [want]:
        _write_json(out / "paper.json", {"mode": a.mode, "result": "STOP", "code": "CANON_MODE"})
        return 1
    # every generator runs (KEEP_GOING=1); a failed stage pushes nothing, so each failed step's log goes to
    # failures.log, which the stage log prints in full
    rc, txt = _run(["bash", "analysis/run_all.sh", "--stages", a.run_stages], cwd=repo,
                   env=dict(env, KEEP_GOING="1"), log=out / "run_all.log")
    failed = [ln.split("FAILED, see ", 1)[1].strip() for ln in txt.splitlines() if ln.startswith("FAILED, see ")]
    if failed:
        with open(out / "failures.log", "w", encoding="utf-8") as fh:
            for rel in failed:
                p = repo / rel
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines() if p.is_file() else ["(no log)"]
                fh.write(f"===== {rel} (last {min(40, len(lines))} of {len(lines)} lines)\n" + "\n".join(lines[-40:]) + "\n")
    paper = repo / "output" / "paper"
    _write_json(out / "paper.json", {"mode": a.mode, "result": "OK" if rc == 0 else "STOP",
                                     "code": "OK" if rc == 0 else "RUN_ALL_FAIL",
                                     "counts": {"files": len(_files(paper)), "rc": rc}})
    return 0 if rc == 0 else 1


def _ledger_date(a) -> str:
    if getattr(a, "ledger_date_from", None):
        return _load_json(a.ledger_date_from)["ledger_date"]
    return _load_json(a.record)[a.role]["ledger_date"]


def cmd_sentinel(a) -> int:
    out = pathlib.Path(a.out)
    env = dict(os.environ, SAR_PATHS_CONFIG=str(a.paths))
    date = _ledger_date(a)
    runs = {"vault": [_py(), a.check_paper, "--thesis-root", a.tree, "--tree", a.tree_kind, "--profile", a.profile,
                      "--ledger-date", date, "--no-regen", "--gold", a.gold]}
    if a.phase == "pre" and a.thesis_report:
        base = [_py(), a.check_paper, "--no-regen", "--gold", a.gold]
        runs["thesis_default"] = base
        runs["thesis_root"] = base + ["--thesis-root", a.thesis_report]
    rep = {"mode": a.mode, "phase": a.phase, "result": "OK", "counts": {}}
    for name, argv in runs.items():
        rc, _ = _run(argv + ["--report", out / f"{name}.md", "--json", out / f"{name}.json"],
                     cwd=a.repo, env=env, log=out / "sentinel.log")
        if rc not in (0, 1) or not (out / f"{name}.json").is_file():
            rep.update(result="STOP", code="REPORT_MISSING")
            continue
        checks = _load_json(out / f"{name}.json").get("checks", [])
        rep["counts"][f"{name}_checks"] = len(_graded(checks))
        rep["counts"][f"{name}_fail"] = len(_fails(checks))
    _write_json(out / "sentinel.json", rep)
    return 0 if rep["result"] == "OK" else 1


def cmd_repin(a) -> int:
    repo, out, scratch, tree = pathlib.Path(a.repo), pathlib.Path(a.out), pathlib.Path(a.scratch), pathlib.Path(a.tree)
    pc = load_paper_config(a.paper)
    tree_date = _load_json(a.record)[a.role]["ledger_date"]
    rep = {"mode": a.mode, "result": "STOP"}
    log = out / "repin.log"
    env = dict(os.environ, SAR_PATHS_CONFIG=str(a.paths))     # the tools read the same canon as the paper row
    try:
        if a.mode == "M":
            date = pc["ledger_date"]
            if not date:
                raise Stop("LEDGER_DATE_UNSET", "config/r1/final_paper.json ledger_date is set at launch")
            if not date > tree_date:
                raise Stop("LEDGER_DATE_NOT_LATER", f"{date} is not later than the tree's {tree_date}")
        else:
            date = tree_date                       # B0: the tree's own date, so the dated names do not move
        if scratch.exists() and any(scratch.iterdir()):
            raise Stop("DEST_EXISTS", f"{scratch} is not empty")
        repo_s, tree_s = scratch / "repo", scratch / "tree"
        rc, _ = _run(["git", "-C", repo, "worktree", "add", "--detach", repo_s, a.commit], log=log)
        if rc:
            raise Stop("WORKTREE_FAIL", "git worktree add failed")
        copy_tree_writable(tree, tree_s)
        before = {r: sha256_file(tree_s / "tables" / r) for r in _files(tree_s / "tables")}
        tools = repo / "tools" / "repin_thesis_2026-10"      # the manuscript re-pin tools (not shipped)
        common = ["--thesis-root", tree_s, "--draft-root", "none", "--out-dir", a.out_dir]
        # B0 keeps the tree's date: --keep-date archives the originals first and writes the same names, the
        # merged ledger with the original _source (review R7 #2); the M argv is unchanged
        keep = ["--keep-date"] if a.mode == "B0" else []
        rc, _ = _run([_py(), tools / "install.py", "ledgers", *common, "--date", date, "--rearchive", pc["rearchive"],
                      *keep, "--write"], cwd=repo, env=env, log=log)
        if rc:
            raise Stop("INSTALL_FAIL", "install.py ledgers")
        rc, _ = _run([_py(), tools / "install.py", "exhibits", *common, "--figures", ",".join(pc["figures"]), "--write"],
                     cwd=repo, env=env, log=log)
        if rc:
            raise Stop("INSTALL_FAIL", "install.py exhibits")
        after = {r: sha256_file(tree_s / "tables" / r) for r in _files(tree_s / "tables")}
        changed_tables = sorted(r for r in after if before.get(r) != after[r])
        rc, _ = _run([_py(), tools / "replace.py", "--old-ledger-dir", tree, "--new-ledger-dir", a.out_dir,
                      "--old-gold", a.old_gold, "--new-gold", a.new_gold, "--draft-root", tree_s, "--write",
                      "--backup-dir", out / "replace_backup", "--report", out / "replace_report.json"],
                     cwd=repo, env=env, log=log)
        if rc not in (0, 1) or not (out / "replace_report.json").is_file():
            raise Stop("REPLACE_FAIL", f"replace.py rc {rc}")             # rc 1 = CONFLICT/BLOCKED: gate 2's call
        replace_rc = rc
        main_old = (tree / "main.tex").read_text(encoding="utf-8")
        clean_old = (tree / "main_clean.tex").read_text(encoding="utf-8")
        if (tree_s / "main_clean.tex").read_text(encoding="utf-8") != clean_old:
            raise Stop("SYNC_CLEAN_STOP", "main_clean.tex changed before sync_clean (replace.py never edits it)")
        try:
            clean_new = sync_clean(main_old, (tree_s / "main.tex").read_text(encoding="utf-8"), clean_old)
        except SyncStop as e:
            raise Stop("SYNC_CLEAN_STOP", str(e)) from None
        (tree_s / "main_clean.tex").write_text(clean_new, encoding="utf-8")
        # the manuscript re-pin tool (not shipped)
        rc, _ = _run([_py(), repo_s / "tools" / "repin_thesis_2026-10" / "repin.py", "--old-ledger-dir", tree,
                      "--new-ledger-dir", a.out_dir, "--old-gold", a.old_gold, "--new-gold", a.new_gold,
                      "--target", repo_s / "tools" / "check_paper.py", "--write", "--backup-dir", out / "repin_backup",
                      "--report", out / "repin_report.json"], cwd=repo_s, env=env, log=log)
        if not repin_rc_ok(rc, out / "repin_report.json"):
            raise Stop("REPIN_FAIL", f"repin.py rc {rc}")
        r = subprocess.run(["git", "-C", str(repo_s), "diff"], capture_output=True, text=True)
        if r.returncode:
            raise Stop("WORKTREE_FAIL", "git diff in the scratch worktree")
        (out / "check_paper_repin.patch").write_text(r.stdout, encoding="utf-8")
        import yaml
        (out / "scratch_paths.yaml").write_text(yaml.safe_dump(scratch_paths(a.paths, repo), sort_keys=False,
                                                               allow_unicode=True), encoding="utf-8")
        rep.update(result="OK", code="OK", ledger_date=date, changed_tables=changed_tables,
                   counts={"changed_tables": len(changed_tables), "replace_rc": replace_rc,
                           "main_clean_lines_changed": sum(1 for _ in diff_signature(clean_old, clean_new))})
        rc = 0
    except Stop as e:
        rep["code"] = e.code
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(f"STOP {e}\n")
        rc = 1
    _write_json(out / "repin.json", rep)
    return rc


def _compile_one(d: pathlib.Path, stem: str, max_extra: int) -> dict:
    passes, res = 0, {"rc": None, "bibtex_rc": None, "stable": False}

    def tex():
        nonlocal passes
        passes += 1
        rc, _ = _run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", f"{stem}.tex"], cwd=d)
        return rc

    def snap():
        return tuple((d / f"{stem}{x}").read_bytes() if (d / f"{stem}{x}").is_file() else None
                     for x in (".aux", ".toc", ".out"))

    rc = tex()
    if rc == 0:
        aux = d / f"{stem}.aux"
        if aux.is_file() and "\\bibdata" in aux.read_text(encoding="utf-8", errors="replace"):
            res["bibtex_rc"], _ = _run(["bibtex", stem], cwd=d)
        rc = tex() or tex()
    if rc == 0:
        prev = snap()
        for _ in range(max_extra):
            rc = tex()
            if rc:
                break
            cur = snap()
            if cur == prev:
                res["stable"] = True
                break
            prev = cur
    log = d / f"{stem}.log"
    scan = scan_log(log.read_text(encoding="utf-8", errors="replace")) if log.is_file() else \
        {"errors": 1, "undefined_refs": 0, "undefined_cites": 0, "ok": False}
    pdf = d / f"{stem}.pdf"
    res.update(rc=rc, passes=passes, **{k: scan[k] for k in ("errors", "undefined_refs", "undefined_cites")},
               pdf=pdf.is_file())
    res["ok"] = bool(rc == 0 and res["stable"] and scan["ok"] and pdf.is_file()
                     and (res["bibtex_rc"] is None or res["bibtex_rc"] <= 1))
    return res


def cmd_compile(a) -> int:
    out, build = pathlib.Path(a.out), pathlib.Path(a.build)
    rep = {"mode": a.mode, "targets": {}}
    for label, src in (("october", a.october), ("scratch", a.scratch)):
        copy_tree_writable(src, build / label)
        for stem in ("main_clean", "main"):
            r = _compile_one(build / label, stem, a.max_extra)
            rep["targets"][f"{label}/{stem}"] = r
            (out / label).mkdir(parents=True, exist_ok=True)
            for ext in (".pdf", ".log"):
                f = build / label / f"{stem}{ext}"
                if f.is_file():
                    shutil.copyfile(f, out / label / f"{stem}{ext}")
    rep["counts"] = {"failed": sum(1 for r in rep["targets"].values() if not r["ok"])}
    _write_json(out / "compile.json", rep)
    return 0


def _words(repo, pdf, js) -> int | None:
    if not pathlib.Path(pdf).is_file():
        return None
    rc, txt = _run([_py(), pathlib.Path(repo) / "tools" / "count_words.py", pdf, "--json", js])
    try:
        return parse_words(txt)["total"] if rc == 0 else None
    except ValueError:
        return None


def _hits(repo, pdf) -> dict | None:
    if not pathlib.Path(pdf).is_file():
        return None
    rc, txt = _run([_py(), pathlib.Path(repo) / "tools" / "check_draft_text.py", pdf])
    try:
        return parse_hits(txt) if rc in (0, 1) else None
    except ValueError:
        return None


def cmd_texts(a) -> int:
    repo, out, comp = pathlib.Path(a.repo), pathlib.Path(a.out), pathlib.Path(a.compile)
    pdfs = {"october": comp / "october" / "main_clean.pdf", "new": comp / "scratch" / "main_clean.pdf"}
    words = {k: _words(repo, p, out / f"words_{k}.json") for k, p in pdfs.items()}
    words["reference"] = _words(repo, a.reference, out / "words_reference.json")
    hits = {k: _hits(repo, p) for k, p in pdfs.items()}
    rc, _ = _run([_py(), repo / "tools" / "count_bor.py", a.scratch, "--baseline", a.record, "--key", a.role,
                  "--json", out / "bor_vault.json"], log=out / "texts.log")
    bor_equal = rc == 0
    thesis_bor = None
    if a.thesis_report:
        rc2, txt = _run([_py(), repo / "tools" / "count_bor.py", a.thesis_report], log=out / "texts.log")
        m = re.search(r"count_bor: totals BOR=(\d+) BORdel=(\d+)", txt)
        thesis_bor = {"bor": int(m.group(1)), "bordel": int(m.group(2))} if m else None
    cur, scr = pathlib.Path(a.tree_current), pathlib.Path(a.scratch)

    def sig(root):
        return diff_signature((root / "main.tex").read_text(encoding="utf-8"),
                              (root / "main_clean.tex").read_text(encoding="utf-8"))
    invariant = sig(cur) == sig(scr)
    _write_json(out / "texts.json", {"mode": a.mode, "words": words, "draft_hits": hits, "bor_equal": bor_equal,
                                     "thesis_report_bor": thesis_bor, "main_clean_invariant": invariant})
    return 0


#: red_diff verify's two checks of a bw PDF against a reference PDF (verify --reference)
REF_IDENTICAL = "bw_same_pages_words_positions_as_reference"
REF_EXPLAINED = "bw_same_as_reference_except_explained_differences"


def reference_equal(rv: dict) -> bool:
    """reference_verify.json (the October PDF compiled here, verify --reference the author's PDF of it) ->
    True when the two are identical, or differ only as red_diff's explain_reference_diff explains: the
    author's contents page is one LaTeX pass stale and the numbers here are the heading pages, and
    typewriter text the author's TeX set in bitmap fonts sits at the same places here (finalb0-03). Any
    other difference is REFERENCE_PDF_DIFF."""
    checks = (rv or {}).get("checks") or {}
    if checks.get(REF_IDENTICAL) is True:
        return True
    ex = (rv or {}).get("bw_vs_reference_explained") or {}
    return checks.get(REF_EXPLAINED) is True and ex.get("explained") is True and not ex.get("unexplained")


def cmd_red(a) -> int:
    repo, out, comp, build = (pathlib.Path(x) for x in (a.repo, a.out, a.compile, a.build))
    tool = repo / "tools" / "red_diff_2026-10.py"
    red_dir = out / "red"
    rc_b, _ = _run([_py(), tool, "build", "--old", a.october, "--new", a.scratch, "--root", "main_clean.tex",
                    "--out", red_dir, "--build", build, "--stem", a.stem], log=out / "red.log")
    # verify --figures = the figure files the new PDF includes, as the build compiled them (its report's
    # figures[].file over the flattened main_clean.tex); never the glob of scratch/figures, which also
    # holds unused and dated PDFs (review R7 #12). No report: none (build_ok is then False anyway).
    br = build / f"{a.stem}_red_report.json"
    figs = sorted({str(pathlib.Path(a.scratch) / f["file"]) for f in _load_json(br).get("figures", [])}) \
        if br.is_file() else []
    rc_v, _ = _run([_py(), tool, "verify", "--bw", red_dir / f"{a.stem}_bw.pdf", "--red", red_dir / f"{a.stem}_red.pdf",
                    "--old", comp / "october" / "main_clean.pdf", "--figures", *figs,
                    "--reference", comp / "scratch" / "main_clean.pdf",
                    "--build-report", build / f"{a.stem}_red_report.json", "--report", out / "red_verify.json"],
                   log=out / "red.log")
    octo = comp / "october" / "main_clean.pdf"
    _run([_py(), tool, "verify", "--bw", octo, "--red", octo, "--old", octo, "--reference", a.reference,
          "--report", out / "reference_verify.json"], log=out / "red.log")
    rv = _load_json(out / "reference_verify.json") if (out / "reference_verify.json").is_file() else {}
    ref_equal = reference_equal(rv)
    verify_ok = rc_v == 0 and (out / "red_verify.json").is_file() and \
        _load_json(out / "red_verify.json").get("all_checks_pass") is True
    runs = _load_json(br).get("red_runs_text", []) if br.is_file() else None
    # the explained reference difference is recorded (gate2.json shows it to the author), never hidden
    _write_json(out / "red.json", {"mode": a.mode, "build_ok": rc_b == 0 and runs is not None, "verify_ok": verify_ok,
                                   "reference_equal": ref_equal, "reference_explained": rv.get("bw_vs_reference_explained"),
                                   "red_runs": runs or []})
    return 0


def _printed_keys(repo, new_dir, check_paper, gold) -> list:
    tools = pathlib.Path(repo) / "tools" / "repin_thesis_2026-10"   # the manuscript re-pin tools (not shipped)
    for p in (str(repo), str(tools)):
        if p not in sys.path:
            sys.path.insert(0, p)
    import repin_lib as L
    ls = L.LedgerSet.load(pathlib.Path(new_dir), pathlib.Path(gold))
    cp = L.load_check_paper(pathlib.Path(check_paper))
    # the pins graded on the scratch tree itself: a packed base tree gives the 'vault' profile and the
    # base-tree claims (review R7 #8); plus the base-tree keys printed untraced or as number words
    pins = L.pins_from_set(ls, cp, root=pathlib.Path(new_dir))
    extra = [f"{lg}:{k}" for lg, keys in (getattr(cp, "BASE_TREE_PRINTED_KEYS", None) or {}).items() for k in keys]
    return printed_entries([k for p in pins for k in p.keys] + extra)


def cmd_numbers(a) -> int:
    repo, out = pathlib.Path(a.repo), pathlib.Path(a.out)
    date = _load_json(a.ledger_date_from)["ledger_date"]
    rep = {"mode": a.mode}
    argv = [_py(), repo / "tools" / "r1_number_diff.py", "--old", a.old, "--old-date", a.old_date, "--new", a.new,
            "--new-date", date, "--out", out]
    try:
        entries = _printed_keys(repo, a.new, a.check_paper, a.gold)
        (out / "printed.tsv").write_text("".join(f"{e}\n" for e in entries), encoding="utf-8")
        argv += ["--printed", out / "printed.tsv"]
        rep["n_printed"] = len(entries)
    except Exception as e:                       # noqa: BLE001 - the printed column is then empty, never guessed
        rep["code"] = "PRINTED_UNAVAILABLE"
        with open(out / "numbers.log", "a", encoding="utf-8") as fh:
            fh.write(f"printed keys unavailable: {e!r}\n")
    rc, _ = _run(argv, log=out / "numbers.log")
    rows = []
    if (out / "ledger_diff.csv").is_file():
        import csv
        with open(out / "ledger_diff.csv", newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
    rep.update(rc=rc, counts={s: sum(1 for r in rows if r["status"] == s) for s in ("unchanged", "changed", "added", "dropped")})
    _write_json(out / "numbers.json", rep)
    return 0 if (out / "ledger_diff.csv").is_file() else 1


def edit_rows(replace: dict) -> list:
    """replace_report.json's edits -> gate 2's edit rows, ONE row per edit (never one per pin, or the
    refused / sign / decimals counts would double), with pins = every 'pin:' source of the edit (review R7 #9:
    replace.py merges a pin and a same-span '% src:' literal into one edit, source 'pin:<name> + src:...').
    The list comes from the edit's 'sources'; a report without it is split on ' + '. pin = pins[0] or None."""
    rows = []
    for e in replace.get("edits", []):
        src = str(e.get("source", ""))
        srcs = e.get("sources")
        if not isinstance(srcs, list):
            srcs = [s for s in src.split(" + ") if s]
        pins = [s[4:] for s in srcs if isinstance(s, str) and s.startswith("pin:")]
        rows.append({"pin": pins[0] if pins else None, "pins": pins, "source": src, "file": e.get("file"),
                     "status": e.get("status"), "reason": e.get("reason"), "old": e.get("old"), "new": e.get("new"),
                     "old_value": e.get("old_value"), "new_value": e.get("new_value")})
    return rows


def _collect(a, mode) -> dict:
    """The gate-2 inputs from the stage reports under --prod (each stage's STAGE_OUT)."""
    P = pathlib.Path(a.prod)
    missing = []

    def need(rel, default=None):
        p = P / rel
        if not p.is_file():
            missing.append(rel)
            return default
        try:
            return _load_json(p)
        except ValueError:
            missing.append(rel)
            return default

    pre = (need("sentinel_pre/vault.json") or {}).get("checks")
    post = (need("sentinel_post/vault.json") or {}).get("checks")
    repin = need("repin/repin.json") or {}
    replace = need("repin/replace_report.json") or {}
    repin_rep = need("repin/repin_report.json") or {}
    texts = need("texts/texts.json") or {}
    comp = need("compile/compile.json") or {}
    red = need("red/red.json") or {}
    numbers = need("numbers/numbers.json") or {}
    nd = []
    if (P / "numbers" / "ledger_diff.csv").is_file():
        import csv
        with open(P / "numbers" / "ledger_diff.csv", newline="", encoding="utf-8") as fh:
            nd = [{k: r.get(k, "") for k in NUMBER_DIFF_COLS} for r in csv.DictReader(fh)]
    else:
        missing.append("numbers/ledger_diff.csv")
    edits = edit_rows(replace)
    renamed, label_conflicts = {}, []
    for ed in repin_rep.get("label_edits", []):
        if ed.get("status") == "EDIT":
            for n in ed.get("pins", []):
                renamed[n] = n.replace(ed["old"], ed["new"])
        elif ed.get("status") == "CONFLICT":
            # repin.py writes LabelEdit with dataclasses.asdict: lineno, old, new, status, pins, reason
            label_conflicts.append({"line": ed.get("lineno"), "old": ed.get("old"), "pins": ed.get("pins"),
                                    "reason": ed.get("reason")})
    words = texts.get("words") or {}
    inp = {"pre": pre, "post": post, "number_diff": nd, "changed_tables": repin.get("changed_tables") or [],
           "edits": edits, "renamed": renamed, "label_conflicts": label_conflicts, "bor_equal": texts.get("bor_equal"),
           "compile": comp.get("targets") or {}, "draft_hits": texts.get("draft_hits") or {},
           "words": words, "words_limit": load_paper_config(a.paper)["words_limit"],
           "main_clean_invariant": texts.get("main_clean_invariant"), "numbers_rc": numbers.get("rc"),
           "red": red, "ledger_date": repin.get("ledger_date")}
    if pre is None or post is None:
        missing.append("sentinel checks")
    # the draft tables' note-claim checks (R7 #16), both modes; absent or malformed -> REPORT_MISSING
    ncp = pathlib.Path(a.output_paper) / NOTE_CHECKS_REL
    try:
        nc = _load_json(ncp) if ncp.is_file() else None
    except ValueError:
        nc = None
    if valid_note_checks(nc):
        inp["note_checks"] = nc
    else:
        missing.append(f"output_paper/{NOTE_CHECKS_REL}")
    if mode == "M":
        canon = need("canon/canon.json") or {}
        inp["canon_ok"] = canon.get("result") == "OK"
        # R1 M2: the two tools' own post-write checks (they exit 0 when these fail). A pin replace.py refused
        # still prints its old value, so its failed verify is that refusal, not a fault
        refused = {p for e in edits if e.get("status") in REFUSED for p in e.get("pins") or []}
        rv = {"pins_not_new": [v.get("pin") for v in replace.get("verify") or []
                               if not v.get("ok") and v.get("pin") not in refused]}
        dv = replace.get("draft_verify")
        if isinstance(dv, dict):
            rv.update({k: list(dv.get(k) or [])
                       for k in ("edits_left_new_to_new", "src_literals_not_matching_new_key")})
        elif replace:
            rv["draft_verify_absent"] = ["replace_report.json has no draft_verify (the final job always writes)"]
        inp["replace_verify"] = rv
        # round 3: every '% src:' p-literal with its unrounded values; a report without the list could drop a
        # crossing unseen
        lits = replace.get("src_p_literals")
        if isinstance(lits, list):
            inp["src_p_literals"] = lits
        elif replace:
            missing.append("repin/replace_report.json src_p_literals")
        # round 3 (Codex STOP 2): Figure 1's block exceptions, if any, and the caption that states the rule
        flp = pathlib.Path(a.output_paper) / STAR_ORIGINS_LEDGER
        try:
            fl = _load_json(flp) if flp.is_file() else None
        except ValueError:
            fl = None
        exc = fl.get(FIGURE_EXC_KEY) if isinstance(fl, dict) else None
        if not isinstance(fl, dict) or (exc is not None and not valid_figure_exceptions(exc)):
            missing.append(f"output_paper/{STAR_ORIGINS_LEDGER}")
        elif exc:
            inp["figure_exceptions"], inp["figure_caption"] = exc, figure_caption(a.scratch)
        pv = repin_rep.get("verify") or {}           # {} when repin.py wrote nothing
        gone = list(pv.get("renamed_missing") or [])
        if pv.get("all_renamed_present") is False and not gone:
            gone = ["all_renamed_present is false"]     # a report from before renamed_missing
        inp["repin_verify"] = {"renamed_missing": gone,
                               "overlay_keys_unmatched": list(pv.get("overlay_keys_unmatched") or [])}
        logs = [P / "custody" / f for f in ("custody.log", "manifest_canon.log", "manifest_frames.log",
                                            "manifest_expected.log")]
        texts_ = [f.read_text(encoding="utf-8", errors="replace") if f.is_file() else "" for f in logs]
        inp["custody_ok"] = bool(re.search(r"^CUSTODY_OK$", texts_[0], re.M)) and all(
            "MANIFEST_OK" in t for t in texts_[1:])
    else:
        inp["thesis_default"] = (need("sentinel_pre/thesis_default.json") or {}).get("checks")
        inp["thesis_root"] = (need("sentinel_pre/thesis_root.json") or {}).get("checks")
        m_out, m_scr = [], []           # equal only once the PDF render date is masked (R7 #13)
        n_out, n_scr = [], []           # equal within cross-architecture noise (same_within_noise)
        # the run's repo root, resolved as analysis/lib/paths.py resolves REPO_ROOT: the October provenance
        # strings' Mac root maps to it, in the six rooted ledgers only (R7 #14)
        new_root = str(pathlib.Path(a.repo).resolve())
        ld = repin.get("ledger_date")
        ref_only = load_expected_b0(a.expected_b0)[REF_ONLY_SECTION]      # R7 #15
        inp["output_paper_diff"] = output_paper_diff(a.output_paper, a.ref_output_paper, ref_only, rooted=B0_ROOTED,
                                                     new_root=new_root, masked=m_out, noise=n_out)
        inp["scratch_diff"] = b0_tree_diff(a.tree_current, a.scratch, load_paper_config(a.paper)["rearchive"],
                                           rooted=b0_rooted_scratch(ld) if ld else None, new_root=new_root,
                                           masked=m_scr, noise=n_scr)
        inp["pdf_date_masked"] = [f"output_paper/{r}" for r in m_out] + [f"scratch/{r}" for r in m_scr]
        inp["noise_masked"] = [f"output_paper/{r}" for r in n_out] + [f"scratch/{r}" for r in n_scr]
    inp["reports_missing"] = sorted(set(missing))
    return inp


def cmd_gate2(a) -> int:
    out, final = pathlib.Path(a.out), pathlib.Path(a.final_dir)
    pc = load_paper_config(a.paper)
    exp = load_expected_b0(a.expected_b0) if a.mode == "B0" else None
    inp = _collect(a, a.mode)
    final.mkdir(parents=True, exist_ok=True)
    gone = []
    for d in pc["deliver"]:
        src = pathlib.Path(a.prod) / d["from"]
        if src.is_file():
            shutil.copyfile(src, final / d["name"])
        else:
            gone.append(d["name"])
    inp["deliverables_missing"] = gone
    rc, _ = _run([_py(), pathlib.Path(a.repo) / "tools" / "r1_pack_tree.py", "pack", "--tree", a.scratch, "--role", "r1",
                  "--out", final / "tree_r1.tar"], log=out / "gate2.log")
    inp["pack_ok"] = rc == 0 and (final / "tree_r1.tar").is_file()
    verdict, codes, det = gate2(inp, a.mode, exp)
    words = inp.get("words") or {}
    extra = {"pre_fail": len(_fails(inp.get("pre"))), "post_fail": len(_fails(inp.get("post"))),
             "edits": len(inp.get("edits") or []), "changed_tables": len(inp.get("changed_tables") or []),
             "changed_keys": sum(1 for r in inp["number_diff"] if r["status"] != "unchanged"),
             "reports_missing": len(inp["reports_missing"]), "deliverables_missing": len(gone),
             "words_limit": pc["words_limit"], "pdf_date_masked": len(det.get("pdf_date_masked", [])),
             "noise_masked": len(det.get("noise_masked", []))}
    for k in ("october", "new", "reference"):
        if isinstance(words.get(k), int):
            extra[f"words_{k}"] = words[k]
    report = final_report(a.mode, verdict, codes, det, extra)
    _write_json(out / "final_report_gate2.json", report)
    facts = {"mode": a.mode, "verdict": verdict, "codes": codes, "ledger_date": inp.get("ledger_date"),
             "words": words, "words_limit": pc["words_limit"], "refused": det["refused"],
             "sign_changed": det["sign_changed"], "decimals_changed": det["decimals_changed"],
             "post_fail_at_refused_spans": [c.get("name") for c in _fails(inp.get("post"))
                                            if f"{c.get('section')}:{c.get('name')}" not in det["post_unexplained"]],
             "note_flags": det.get("note_flags", []),
             "number_table": "number_table.md",
             "note": "Facts for the one-page change note: each refused span and sign change gets a recommended "
                     "sentence there, and so does each flagged table-note sentence (note_flags: the generator "
                     "flags it and never rewords it); no sentence's meaning is changed unasked."}
    if a.mode == "M":                              # R1 M2; B0's change_facts.json is unchanged
        facts.update(p_crossings=det["p_crossings"], printed_sign_changes=det["printed_sign_changes"],
                     replace_verify=det["replace_verify"], repin_verify=det["repin_verify"],
                     unreproducible=det["unreproducible"], figure_rule=det["figure_rule"],
                     label_conflicts=det["label_conflicts"])
        facts["note"] += (" Each printed p-value that crosses 0.05 (p_crossings) and each printed sign change "
                          "(printed_sign_changes) gets one too: replace.py rewrote the number only. Each ledger key "
                          "listed as unreproducible (unreproducible, with the ledger's reason) has no value in the "
                          "new ledgers: its sentence is the author's call. Figure 1's blocks that leave the "
                          "caption's rule at this run's counts (figure_rule: the caption sentence and the "
                          "exceptions) get one too: the caption is not rewritten. A check_paper pin label whose "
                          "pins want different new numbers (label_conflicts) keeps its old name: the author names it.")
    _write_json(out / "change_facts.json", facts)
    if "note_checks" in inp:                       # delivered with gate2.json / change_facts.json (R7 #16)
        for d in (out, final):
            shutil.copyfile(pathlib.Path(a.output_paper) / NOTE_CHECKS_REL, d / "note_checks.json")
    _write_json(out / "gate2.json", {"mode": a.mode, "verdict": verdict, "codes": codes, "details": det,
                                     "inputs_summary": {k: v for k, v in report["counts"].items()},
                                     "generated_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    for f in ("gate2.json", "change_facts.json"):
        shutil.copyfile(out / f, final / f)
    print(f"final_stage gate2: {verdict} {' '.join(codes)}")
    return 1 if verdict in ("GATE2_FAIL", "B0_FAIL") else 0


# ---- CLI -------------------------------------------------------------------------------------------
def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="R1 final job driver (V3-FINAL)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, *flags, opt=()):
        p = sub.add_parser(name)
        p.add_argument("--mode", required=True, choices=MODES)
        p.add_argument("--out", required=True)
        for f in flags:
            p.add_argument(f, required=True)
        for f in opt:
            p.add_argument(f)
        return p

    add("unpack", "--repo", "--record", "--tar-october", "--tar-current", "--current-role", "--dest")
    p = add("canon", "--repo", "--layout", "--config", "--paths", "--dest", "--bin", "--tsv")
    p.add_argument("--stages", action="append", required=True, metavar="JOB=DIR")
    add("paper", "--repo", "--paths", "--run-stages")
    p = add("sentinel", "--phase", "--repo", "--check-paper", "--paths", "--tree", "--tree-kind", "--gold",
            opt=("--record", "--role", "--ledger-date-from", "--thesis-report"))
    p.add_argument("--profile", choices=("thesis", "vault", "r1"), default="vault")
    add("repin", "--repo", "--commit", "--paper", "--record", "--role", "--tree", "--scratch", "--out-dir",
        "--old-gold", "--new-gold", "--paths")
    p = add("compile", "--october", "--scratch", "--build")
    p.add_argument("--max-extra", type=int, required=True)
    add("texts", "--repo", "--compile", "--reference", "--record", "--role", "--tree-current", "--scratch",
        opt=("--thesis-report",))
    add("red", "--repo", "--october", "--scratch", "--compile", "--reference", "--build", "--stem")
    add("numbers", "--repo", "--old", "--old-date", "--new", "--ledger-date-from", "--check-paper", "--gold")
    add("gate2", "--repo", "--paper", "--expected-b0", "--prod", "--output-paper", "--ref-output-paper",
        "--tree-current", "--scratch", "--final-dir")
    return ap


def echo_failure(out: pathlib.Path, tail: int = 60) -> None:
    """A failed stage leaves no STAGE_OUT on S3 (run_stages pushes passed stages only). Print the stage's reports
    and the tail of its logs, so logs/<stage>.log, which is fetched, says why it stopped."""
    for p in sorted(out.iterdir()):
        if p.is_file() and p.suffix in (".json", ".log"):
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            n = len(lines) if p.name == "failures.log" else tail      # the failed steps' own logs, in full
            print(f"--- {p.name} (last {min(n, len(lines))} of {len(lines)} lines)")
            print("\n".join(lines[-n:]))
    sys.stdout.flush()


def main(argv=None) -> int:
    _host_guard()                                    # before parsing: off the instance nothing runs
    a = _parser().parse_args(argv)
    if a.cmd == "sentinel":
        if a.phase not in ("pre", "post"):
            raise SystemExit("--phase pre|post")
        if not (a.ledger_date_from or (a.record and a.role)):
            raise SystemExit("sentinel: --ledger-date-from FILE, or --record FILE --role ROLE")
    pathlib.Path(a.out).mkdir(parents=True, exist_ok=True)
    rc = {"unpack": cmd_unpack, "canon": cmd_canon, "paper": cmd_paper, "sentinel": cmd_sentinel,
          "repin": cmd_repin, "compile": cmd_compile, "texts": cmd_texts, "red": cmd_red,
          "numbers": cmd_numbers, "gate2": cmd_gate2}[a.cmd](a)
    if rc:
        echo_failure(pathlib.Path(a.out))
    return rc


if __name__ == "__main__":
    sys.exit(main())
