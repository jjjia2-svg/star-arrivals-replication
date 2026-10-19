#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""econ920/make_clone.py — generate the repo-authored clone of the economics UNION rung and its DIFF.md.

The original is `<legacy>/v2_output/econ_fnfix_2026-08-15/code/00_build_frame_econ920.py` (489 lines),
the machine-generated clone that the 2026-08-15 chain actually ran (`02_clone_chain.py`, log
`logs/03_clone.log`; the frozen `analysis_frame_dept_p01_econ920_2026-08-13.csv` is its output,
`logs/04_frame.log` its run). It is pinned by sha256 below; anything else at that path is not the
audited code and this generator STOPS.

The clone `00_build_frame_econ920_cal.py` is produced by TEXTUAL SUBSTITUTION with an asserted hit
count per pattern — the discipline of `02_clone_chain.py` itself ("assert that every substitution hits; guards against silent misses").
Every substitution is PATH WIRING and nothing else:

  * the four absolute-literal input constants (OLD_FRAME, ROSTER, LEDGER, STAR_SET), the two patch
    files (PATCH_A, PATCH_B), the two supplements (SUP11, SUP_FNFIX) and the new-events table
    (`_NEW_EV`'s source) come from a JSON config named by `sys.argv[1]`;
  * the three outputs (`build_report.json`, the pre-y frame, `relationships.csv`) come from the same
    config instead of `{dirname(BASE)}/data/…`;
  * the data-disk root `SSD` and the legacy root `ROOT` resolve through `pipeline.lib.paths`
    (`derived_root()` = `<ssd_root>/derived` from config/paths.yaml or `$SAR_SSD_ROOT`, today the
    verified mirror; `legacy_thesis()`), exactly as the ported econ builders in
    `pipeline/frames/econ_fnfix_2026-08-15/code/` do. The SSD globs (PMAP, U1E, U1W, U1FP, U3P) and
    OUT_TBL keep their text and therefore follow SSD.
  * `sys.path.insert(0, f"{ROOT}/multiplex_pipeline/units/u0_foundation/src")` is kept verbatim: the
    launcher pre-imports `identity.dose` from THIS repository's ported units (origin-asserted, the
    run_frames arrangement), so the insert is inert and the line needs no change.

No computation line changes. DIFF.md is `difflib.unified_diff` of the pinned original against the
clone, written by this script — never by hand.

    setup/.venv/bin/python pipeline/frames/cal2026-10/econ920/make_clone.py          # regenerate
    setup/.venv/bin/python pipeline/frames/cal2026-10/econ920/make_clone.py --check  # assert current
"""
from __future__ import annotations

import difflib
import hashlib
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[3]
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))
from analysis.lib.paths import load_paths                                 # noqa: E402

ORIGINAL_REL = "econ_fnfix_2026-08-15/code/00_build_frame_econ920.py"
#: sha256 of the audited original (measured 2026-09-22 on the read-only legacy tree)
ORIGINAL_SHA = "233485392b8e9ca7c17e3f5b72c7a66c347ef3b60aefdf81c50699f740dda4c3"
CLONE = HERE / "00_build_frame_econ920_cal.py"
DIFF = HERE / "DIFF.md"

HEADER = '''#!/usr/bin/env python3
# cal2026-10 econ920 clone of <legacy>/v2_output/econ_fnfix_2026-08-15/code/00_build_frame_econ920.py
# (the machine-generated clone the 2026-08-15 chain ran; verbatim pin {sha}).
# Repo-authored 2026-09-22 by make_clone.py (textual substitution, hit counts asserted). The ONLY
# changes are path wiring: the inputs/outputs come from the JSON config named by sys.argv[1], the
# data-disk root and the legacy root resolve through pipeline.lib.paths. Every computation line is
# byte-identical to the pinned original; DIFF.md next to this file lists every changed line. The
# launcher (run_econ920.py) pre-imports identity.dose from this repository's ported units, so the
# original sys.path insert on the legacy units tree is inert. Public copy: three comment lines of the
# original carry reworded process wording (make_clone.WORDING_RX); no code line is affected.
'''

WIRING = '''# --- cal2026-10 econ920 wiring (repo-authored; see the header and DIFF.md) --------------------------
import pathlib as _sar_pl, sys as _sar_sys
_sar_repo = next((p for p in _sar_pl.Path(__file__).resolve().parents
                  if (p / "pipeline" / "lib" / "paths.py").is_file()), None)
if _sar_repo is not None and str(_sar_repo) not in _sar_sys.path:
    _sar_sys.path.append(str(_sar_repo))
from pipeline.lib.paths import (derived_root as _sar_derived_root,  # noqa: E402
                                legacy_thesis as _sar_legacy_thesis,
                                require_readable as _sar_rd)
_CFG = json.load(open(_sar_sys.argv[1]))
'''

# (pattern, replacement, expected hit count) — applied in order to the ORIGINAL text. The original's
# absolute literals are rendered from config/paths.yaml (legacy_thesis, ssd_root/derived), so this file
# carries no machine path (2026-09-23; the port's absolute-path scan).
_LT = str(load_paths()["legacy_thesis"])
_SSD = str(pathlib.Path(load_paths()["ssd_root"]) / "derived")
SUBS: list[tuple[str, str, int]] = [
    (f'ROOT = "{_LT}"\n'
     'BASE = os.path.dirname(os.path.abspath(__file__))\n'
     f'SSD = "{_SSD}"\n',
     WIRING +
     'ROOT = str(_sar_rd(_sar_legacy_thesis()))\n'
     'BASE = os.path.dirname(os.path.abspath(__file__))\n'
     'SSD = str(_sar_rd(_sar_derived_root()))\n', 1),
    (f'OLD_FRAME = "{_LT}/v2_output/econ_fnfix_2026-08-15/data/network_frame_fnfix.csv"   # fnfix: 老 79 起逐字节 + 新事件 prodlib 行\n',
     'OLD_FRAME = _CFG["OLD_FRAME"]   # fnfix: 老 79 起逐字节 + 新事件 prodlib 行 (cal2026-10: the FILTERED network frame)\n', 1),
    ('ROSTER = f"{ROOT}/v2_output/econ_roster_verify_2026-08-09/roster_clean_11school_verified.parquet"   # 2026-08-13: 920 人核金标（AWS 重跑）\n',
     'ROSTER = _CFG["ROSTER"]   # 2026-08-13: 920 人核金标（AWS 重跑）(cal2026-10: the verified October roster, 1,008)\n', 1),
    (f'LEDGER = "{_LT}/v2_output/econ_fnfix_2026-08-15/data/event_ledger_fnfix.csv"\n',
     'LEDGER = _CFG["LEDGER"]\n', 1),
    (f'STAR_SET = "{_LT}/v2_output/econ_fnfix_2026-08-15/u4_aug/star_set/star_set.parquet"   # fnfix: U4 冻结表 ∪ 补漏星合成/翻亮行\n',
     'STAR_SET = _CFG["STAR_SET"]   # fnfix: U4 冻结表 ∪ 补漏星合成/翻亮行\n', 1),
    ('SUP11 = f"{ROOT}/v2_output/netbase_supplement_2026-07-23/edges_supplement_stars11.jsonl"\n',
     'SUP11 = _CFG["SUP11"]\n', 1),
    (f'PATCH_A = "{_LT}/v2_output/econ_final_2026-08-13/patch/works_by_author.jsonl"   # 2026-08-13: 旧包+4 新人扩展\n',
     'PATCH_A = _CFG["PATCH_A"]   # 2026-08-13: 旧包+4 新人扩展\n', 1),
    (f'PATCH_B = "{_LT}/v2_output/econ_final_2026-08-13/patch/works_meta.jsonl"\n',
     'PATCH_B = _CFG["PATCH_B"]\n', 1),
    (f'SUP_FNFIX = "{_LT}/v2_output/econ_fnfix_2026-08-15/data/edges_supplement_fnfix.jsonl"\n',
     'SUP_FNFIX = _CFG["SUP_FNFIX"]\n', 1),
    ('_csv0.DictReader(open(f"{os.path.dirname(BASE)}/data/new_events_econ.csv"))',
     '_csv0.DictReader(open(_CFG["NEW_EVENTS"]))', 1),
    ('json.dump(report, open(f"{os.path.dirname(BASE)}/data/build_report.json", "w"), indent=1, default=str)',
     'json.dump(report, open(_CFG["OUT_REPORT"], "w"), indent=1, default=str)', 1),
    ('out_path = f"{os.path.dirname(BASE)}/data/analysis_frame_dept_p01_econ920_2026-08-13.csv"',
     'out_path = _CFG["OUT_FRAME"]', 1),
    ('    f"{os.path.dirname(BASE)}/data/relationships.csv", index=False)',
     '    _CFG["OUT_REL"], index=False)', 1),
]
#: Public copy (2026-09-23): the original's comments record who decided what, and when ("the author
#: ruled on <date>", "the author's own words", "the author ordered an AWS re-run"). That process
#: wording is neutralised BEFORE the wiring is applied: three comment lines, hit count asserted; no code
#: line is touched. DIFF.md shows the original's side with the same wording (like its machine paths).
WORDING_RX = re.compile(r"作者\s*(\d{4}-\d{2}-\d{2})?\s*(拍板|原话|令)\s*")
WORDING_HITS = 3


def wording(text: str) -> tuple[str, int]:
    """the original's process wording -> neutral wording; returns (text, number of hits)"""
    neutral = {"拍板": lambda m: f"{m.group(1)} 定", "原话": lambda m: "原始表述", "令": lambda m: ""}
    return WORDING_RX.subn(lambda m: neutral[m.group(2)](m), text)


CONFIG_KEYS = ("OLD_FRAME", "ROSTER", "LEDGER", "STAR_SET", "SUP11", "SUP_FNFIX", "PATCH_A", "PATCH_B",
               "NEW_EVENTS", "OUT_FRAME", "OUT_REPORT", "OUT_REL")


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def original_path() -> pathlib.Path:
    return pathlib.Path(load_paths()["legacy_v2_output"]) / ORIGINAL_REL


def render(original: str) -> str:
    s, n = wording(original)
    assert n == WORDING_HITS, f"process wording hit {n} times (expected {WORDING_HITS})"
    for old, new, cnt in SUBS:
        n = s.count(old)
        assert n == cnt, f"pattern hit {n} times (expected {cnt}):\n{old}"
        s = s.replace(old, new)
    assert _LT not in s and _SSD not in s, "an absolute machine path survived"
    assert "os.path.dirname(BASE)" not in s, "an output path still hangs off BASE"
    for k in CONFIG_KEYS:
        assert f'_CFG["{k}"]' in s, k
    return s


def diff_md(original: str, clone: str, orig_sha: str) -> str:
    a, b = original.splitlines(keepends=True), clone.splitlines(keepends=True)
    ud = "".join(difflib.unified_diff(a, b, fromfile=f"<legacy>/v2_output/{ORIGINAL_REL}",
                                      tofile="pipeline/frames/cal2026-10/econ920/00_build_frame_econ920_cal.py",
                                      n=2))
    # 2026-09-23: the original's machine paths are shown as placeholders (the port's absolute-path scan);
    # the rendered clone itself carries none, so only "-" lines are affected
    ud = ud.replace(_LT, "<legacy_thesis>").replace(_SSD, "<ssd_root>/derived")
    ud = wording(ud)[0]   # public copy: the original's process wording, as in the clone (WORDING_RX)
    changed = [ln for ln in ud.splitlines() if (ln.startswith("+") or ln.startswith("-"))
               and not ln.startswith("+++") and not ln.startswith("---")]
    minus = sum(1 for ln in changed if ln.startswith("-"))
    plus = sum(1 for ln in changed if ln.startswith("+"))
    return (
        "# DIFF.md — the econ920 union-rung clone against its pinned original\n\n"
        f"Generated by `make_clone.py` (`difflib.unified_diff`, context 2) — never edited by hand.\n\n"
        f"* original: `<legacy>/v2_output/{ORIGINAL_REL}` — sha256 `{orig_sha}`, {len(a)} lines\n"
        f"* clone: `00_build_frame_econ920_cal.py` — sha256 `{sha(clone.encode('utf-8'))}`, {len(b)} lines\n"
        f"* lines removed {minus}, lines added {plus} (the header comment block and the wiring block are\n"
        f"  pure additions; every other hunk replaces ONE absolute-path constant or ONE output path with\n"
        f"  a config lookup, or is one of the {WORDING_HITS} comment lines whose process wording the public copy\n"
        f"  rewords, shown as a -/+ pair with equal text). No computation line changes; the substitution\n"
        f"  table with its asserted hit counts is `make_clone.SUBS`, the wording rule `make_clone.WORDING_RX`.\n"
        f"  Placeholders: `<legacy_thesis>` = config/paths.yaml `legacy_thesis`, `<ssd_root>` = `ssd_root`\n"
        f"  (the original carries the machine paths verbatim).\n\n"
        "```diff\n" + ud + "```\n")


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    src = original_path()
    if not src.is_file():
        print(f"[make_clone] original not on this machine: {src}", file=sys.stderr)
        return 2
    raw = src.read_bytes()
    got = sha(raw)
    if ORIGINAL_SHA != "REPLACED_AT_FIRST_RUN" and got != ORIGINAL_SHA:
        print(f"[make_clone] STOP: the original no longer matches its pin: {got} != {ORIGINAL_SHA}",
              file=sys.stderr)
        return 3
    original = raw.decode("utf-8")
    clone = HEADER.format(sha=got) + render(original)
    md = diff_md(original, clone, got)
    if "--check" in argv:
        ok = CLONE.read_text(encoding="utf-8") == clone and DIFF.read_text(encoding="utf-8") == md
        print("CLONE_OK" if ok else "CLONE_STALE")
        return 0 if ok else 1
    CLONE.write_text(clone, encoding="utf-8")
    DIFF.write_text(md, encoding="utf-8")
    print(f"[make_clone] original sha256 {got}\n[make_clone] wrote {CLONE.name} ({len(clone.splitlines())} lines) and {DIFF.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
