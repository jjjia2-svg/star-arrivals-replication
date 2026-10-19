#!/usr/bin/env python3
"""R1 F2 (Mac code tool): class every tracked file under the October roots as base, product or r1_input.

  r1_classify_cal_tree.py                     # write config/r1/base_inputs.tsv
  r1_classify_cal_tree.py --check             # exit 1 when the committed TSV differs from a regeneration
  r1_classify_cal_tree.py --seed-allowlist    # print candidate rows for config/r1/read_allowlist_0828.txt

Reads only `git ls-files -s` (paths and blob ids), never a file's content; --seed-allowlist greps tracked code
with `git grep`. Roots: data/cal2026-10, data/frames, analysis/expected, data/cal2026-08-28. Each file takes the
first RULES row whose glob matches it ('**' crosses '/', '*' does not); an unmatched file, or a rule that wins no
file, is an error (exit 1).
Principle (design_final 'The sandbox rule'): product = written by a program from other inputs,
whether or not J0 rebuilds it - pipeline/aws/r1/sandbox.py moves it to the read-only reference copy
/work/ref/october; base = hand-made, fetched, signed or custody material - write-protected and fingerprinted.
Exception (ruling 'What runs in J0', 2026-10-15 plan): an upstream program's output that was signed or frozen as
an input and that J0 does not rebuild is base - J0 reads it as given and must not rewrite it. These rows name
their real producer: calls_2026-10.csv, star_id_corrections_2026-10.csv and recheck_uncertain_2026-10.csv
(build_calls.py), roster_econ_verified / roster_added / roster_merge_report (merge_network102.py), _invalid_run2/
(run_caliber.py run 2). None of these programs is a J0 step (pre-J0 sandbox review 2026-10-16, finding 4).
The fetched outputs of the October EC2 runs (cloud/, cloud_t5/) are product: they hold byte copies of four golds
and no J0 stage reads them. _invalid_run2/ stays base (write_events reads its verdicts table) and sandbox.py
watches it, so a read of anything else there is reported (pre-J0 sandbox review 2026-10-16, finding 1).
The signed R1 inputs (R1_INPUTS, outside the roots) are appended as r1_input rows and protected the same way.
TSV columns: path, class, git_blob, producer, reason (> 30 chars); rows sorted by path, then R1_INPUTS in order,
then the S3 row. The TSV format, the roots and the glob rule are pipeline/aws/r1/sandbox.py's own, so the instance
reads exactly what this tool writes. The rule tables are plain ' | '-separated text so a review can read them.
"""
from __future__ import annotations

import argparse
import dataclasses
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline" / "aws" / "r1"))
import sandbox  # noqa: E402

ROOTS = sandbox.ROOTS
OUT = pathlib.Path("config") / "r1" / "base_inputs.tsv"
SEP = " | "


@dataclasses.dataclass(frozen=True)
class Rule:
    glob: str
    cls: str
    producer: str
    reason: str


#: glob | class | producer | reason -- first match wins, so the base exceptions come before the product sweeps
RULES_TEXT = """
data/cal2026-08-28/** | base | frozen 08-28 canon (tag cal-2026-08-28) | the 2026-08-28 canon: frozen custody material read by October's controls, never rebuilt in R1
data/cal2026-10/calls_2026-10.csv | base | pipeline/stars/caliber_2026-10/build_calls.py draft, signed by the author | the author-signed October work-level calls: a signed decision table, not a rebuildable product
data/cal2026-10/star_id_corrections_2026-10.csv | base | pipeline/stars/caliber_2026-10/build_calls.py (its ID_CORRECTIONS list, ruling D5) | the signed star id corrections build_calls.py writes; not a J0 step, so the chain reads them as given and nothing may rewrite them
data/cal2026-10/roster_econ_verified_2026-10.parquet | base | pipeline/rosters/cal2026-10/merge_network102.py over hand-verified rosters | the verified economics roster: hand-checked custody input the econ frames read as given
data/cal2026-10/roster_added_2026-10.csv | base | pipeline/rosters/cal2026-10/merge_network102.py over the hand-verified network-102 results | the roster additions of the network-102 check merge_network102.py writes; not a J0 step, read by the econ920 frame as given
data/cal2026-10/roster_overrides_2026-10.csv | base | hand (network-102 roster check) | hand-made roster overrides of the network-102 check; signed input, never written by the chain
data/cal2026-10/roster_merge_report_2026-10.json | base | pipeline/rosters/cal2026-10/merge_network102.py | the custody record of the merge that made the verified roster; it travels with that roster
data/cal2026-10/recheck_uncertain_2026-10.csv | base | pipeline/stars/caliber_2026-10/build_calls.py (side table) | the works the 2026-09-22 recheck left uncertain, listed by build_calls.py and not excluded: signed review material, not a J0 step
data/cal2026-10/recheck_snapshot_gap_2026-10.csv | base | the 2026-09-22 snapshot-vs-live comparison of the rechecked stars (commit ee26649) | snapshot works missing from the live lists the 2026-09-22 adjudication used: review material, not rebuilt
data/cal2026-10/api_request_log_* | base | pipeline/frames/cal2026-10/fetch_star_id_supplement.py (live API) | the request log of a live OpenAlex fetch: fetched custody material that cannot be rebuilt offline
data/cal2026-10/edges_supplement_star_id_corrections_2026-10.jsonl | base | pipeline/frames/cal2026-10/fetch_star_id_supplement.py (live API) | edges fetched live from OpenAlex for the corrected star ids: fetched material, not rebuilt offline
data/cal2026-10/supplement_report_* | base | pipeline/frames/cal2026-10/fetch_star_id_supplement.py (live API) | the report of the live star-id supplement fetch: the custody record of fetched material
data/cal2026-10/works_A5091326353_2026-10.json | base | live OpenAlex works fetch (one author) | one author's works fetched live from OpenAlex: fetched custody material, not rebuildable offline
data/cal2026-10/patch_supplement_2026-10/** | base | pipeline/frames/cal2026-10/econ920/fetch_patch_supplement.py (live API) | the live-API patch supplement (works, request log, report) the econ920 frame reads as given
data/cal2026-10/_invalid_run2/** | base | pipeline/stars/caliber_2026-10/run_caliber.py run 2, moved aside by hand | run_caliber's invalid run-2 outputs, quarantined by hand: custody evidence that J0 must not overwrite
data/frames/README.md | base | hand | the hand-written README of the canon frames directory: documentation, not a program output
data/frames/p3_afar_speed_bracket.csv | base | carried by hand (pipeline/NOT_REPRODUCIBLE.md) | the speed-bracket table has no builder and is carried by hand: custody material, not a product
data/cal2026-10/MANIFEST.sha256 | product | pipeline/stars/caliber_2026-10/write_events.py | the manifest write_events.py writes over the top-level October files: a program output
data/cal2026-10/afar_control_0828_report_2026-09-23.json | product | pipeline/frames/cal2026-10/run_cal_afar.py (08-28 control run) | the Panel 3 control report run_cal_afar.py wrote against the 08-28 canon: a program output
data/cal2026-10/cloud/** | product | the October cloud kit (cloudkit.py launch + fetch of the EC2 cell, permutation and null runs) and its perm/null summaries | outputs of the October EC2 runs, fetched back with their custody; fetch/out holds byte copies of four golds, so they move to the reference copy (no J0 stage reads or rebuilds them)
data/cal2026-10/cloud_t5/** | product | the October cloud kit, T5 batch (cloudkit.py launch + fetch, prep_t5_batch.sh) and its perm summaries | outputs of the October T5 EC2 batch, fetched back with their custody: program outputs moved to the reference copy (no J0 stage reads or rebuilds them)
data/cal2026-10/controls_report_econ920_* | product | pipeline/frames/cal2026-10/econ920/run_econ920.py | the econ920 controls report run_econ920.py wrote; J0 writes its own copy to --controls-report
data/cal2026-10/controls_report_piece_a* | product | pipeline/frames/cal2026-10/run_controls.py | the Piece A controls reports run_controls.py wrote: program outputs, not rebuilt in J0
data/cal2026-10/econ_gold_control/** | product | pipeline/frames/cal2026-10/econ_gold/run_econ_gold.py | the economics gold-control run written by run_econ_gold.py: program outputs
data/cal2026-10/estimates/** | product | pipeline/stars/caliber_2026-10/run_cal_estimates.py (+ the EC2 cell fetch) | the October cell estimates: program outputs, promoted to analysis/expected for gate 1
data/cal2026-10/estimates_control_0828/** | product | pipeline/stars/caliber_2026-10/run_cal_estimates.py (08-28 control) | the 08-28 control cell estimates run_cal_estimates.py wrote: program outputs
data/cal2026-10/events_* | product | pipeline/stars/caliber_2026-10/write_events.py | the October event tables and events_decision written by write_events.py: rebuilt by J0
data/cal2026-10/expected_refreeze_2026-10.json | product | pipeline/frames/cal2026-10/promote.py | the refreeze record promote.py wrote when October became the canon: a program output
data/cal2026-10/frames/** | product | pipeline/frames/cal2026-10/assemble_frames.py | the assembled October frames and their MANIFEST written by assemble_frames.py: rebuilt by J0
data/cal2026-10/frames_afar/** | product | pipeline/frames/cal2026-10/run_cal_afar.py | the Panel 3 A_far frames and run report written by run_cal_afar.py: rebuilt by J0
data/cal2026-10/frames_chemistry/** | product | pipeline/frames/cal2026-10/run_cal_frames_chemmath.py | the chemistry frames and build reports written by run_cal_frames_chemmath.py: rebuilt by J0
data/cal2026-10/frames_econ/** | product | pipeline/frames/cal2026-10/econ920/run_econ920.py | the economics frames, build report and DEVIATION note written by run_econ920.py: rebuilt by J0
data/cal2026-10/frames_math_stats/** | product | pipeline/frames/cal2026-10/run_cal_frames_chemmath.py | the mathematics frames and build reports written by run_cal_frames_chemmath.py: rebuilt by J0
data/cal2026-10/frames_run_report_chemmath_* | product | pipeline/frames/cal2026-10/run_cal_frames_chemmath.py | the chemistry/mathematics run report written by run_cal_frames_chemmath.py: a program output
data/cal2026-10/frames_variants/** | product | analysis/robustness/threshold_p05/build_p3_full_variants.py | the p05 and dosebin3 slim variants and reports written by build_p3_full_variants.py: rebuilt by J0
data/cal2026-10/new_numbers/** | product | analysis/paper/ledger_new_2026_10.py | the new-number ledger written by ledger_new_2026_10.py: a program output
data/cal2026-10/paper_layer/** | product | the 2026-09-23 paper-layer workflow (analysis/paper, tools) | sync, replace and verify records written by the 09-23 paper-layer workflow: program outputs
data/cal2026-10/restake_control_* | product | pipeline/stars/caliber_2026-10/run_caliber.py | the E1/E2 restake controls written by run_caliber.py: program outputs, not rebuilt in J0
data/cal2026-10/restake_econ11_* | product | pipeline/stars/caliber_2026-10/restake_econ11.py | the economics restake tables and reports written by restake_econ11.py: J0 rebuilds aug and aug_all
data/cal2026-10/robustness/** | product | analysis/robustness drivers (October batteries) | the October robustness outputs written by the analysis/robustness drivers: program outputs
data/cal2026-10/yrebuild_chemmath/** | product | October chemmath Panel 1 run (copied unchanged) | the October y-rebuild reports the chemmath Panel 1 run wrote, copied unchanged: program outputs
data/frames/** | product | pipeline/frames/cal2026-10/promote.py | the canon frames promote.py copied from data/cal2026-10/frames: program outputs gate 1 compares
analysis/expected/** | product | pipeline/frames/cal2026-10/promote.py | the frozen October cell results promote.py wrote: program outputs the J0 cells compare against
"""
#: path | producer | reason -- signed R1 inputs outside the roots; no stage may rewrite them
R1_INPUTS_TEXT = """
data/cal2026-10r1/inputs/add_list_r1.json | signed R1 input (data/cal2026-10r1/inputs) | the R1 add list (P2/P3a): J1a builds the new star set from it, so a stage must never rewrite it
data/cal2026-10r1/inputs/flips_r1.json | signed R1 input (data/cal2026-10r1/inputs) | the R1 flips (P2): signed star-set decisions the J1a rank stages read as given
data/cal2026-10r1/inputs/p2_decisions.json | signed R1 input (data/cal2026-10r1/inputs) | the P2 decisions incl. the C rulings (author-signed, commit 87a7edc); read as given
data/cal2026-10r1/inputs/rulings_p1.json | signed R1 input (data/cal2026-10r1/inputs) | the P1 rulings the rank-request builder reads: signed decisions, never written by a stage
data/cal2026-10r1/inputs/author_rulings_p1.json | signed R1 input (data/cal2026-10r1/inputs) | the author's P1 rulings: signed decisions the R1 chain reads, never written by a stage
data/cal2026-10r1/inputs/person_overrides.csv | signed R1 input (data/cal2026-10r1/inputs) | hand-made person overrides for R1: signed input material, never written by a stage
data/cal2026-10r1/inputs/fixes_1001.csv | signed R1 input (data/cal2026-10r1/inputs) | the 10-01 fixes table: signed input material the R1 chain reads as given
data/cal2026-10r1/inputs/roster_overrides_r1.csv | signed R1 input (data/cal2026-10r1/inputs) | hand-made R1 roster overrides: signed input material, never written by a stage
"""
#: path | class | git_blob | producer | reason -- inputs that live in S3, pinned by name rather than by a git blob
S3_INPUTS_TEXT = """
s3:r1/patch_raw/ | r1_input | pin:patch_raw | Mac fetch (C7), uploaded unchanged to S3 r1/ | the raw patch records fetched on the Mac and uploaded unchanged (C7); computed on AWS only
"""


def _table(text: str, width: int) -> tuple:
    rows = tuple(tuple(f.strip() for f in ln.split(SEP)) for ln in text.strip("\n").splitlines() if ln.strip())
    bad = [r for r in rows if len(r) != width]
    if bad:
        raise ValueError(f"rule table rows need {width} ' | ' fields: {bad[:3]}")
    return rows


RULES = tuple(Rule(*r) for r in _table(RULES_TEXT, 4))
R1_INPUTS = _table(R1_INPUTS_TEXT, 3)          # (path, producer, reason)
S3_INPUTS = _table(S3_INPUTS_TEXT, 5)          # whole rows
SEED_DIRS = ("pipeline/frames/cal2026-10", "pipeline/stars/caliber_2026-10", "pipeline/aws/r1", "analysis/robustness")
SEED_GREP = r"cal2026-08-28|CAL08|caliber_2026-08-28"
SEED_TOKEN = re.compile(r"data/cal2026-08-28/[A-Za-z0-9_.{}*<>/-]+|data/raw_verified/[A-Za-z0-9_.{}*<>/-]*cal2026-08-28"
                        r"[A-Za-z0-9_.{}*<>/-]*|pipeline/stars/caliber_2026-08-28/[A-Za-z0-9_.-]+|CAL08\s*/\s*f?\"[^\"]+\"")


class ClassifyError(Exception):
    """An unmatched file, a dead rule, a bad rule or an untracked r1 input."""


def classify(entries: dict, rules) -> list[tuple]:
    """(path, class, git_blob, producer, reason) for every entry, first matching rule wins."""
    bad = [r.glob for r in rules if r.cls not in ("base", "product") or len(r.reason) <= 30 or not r.producer]
    if bad:
        raise ClassifyError("bad rules (class base|product, producer, reason > 30 chars):\n  " + "\n  ".join(bad))
    won, rows, unmatched = [0] * len(rules), [], []
    for path in sorted(entries):
        for i, r in enumerate(rules):
            if sandbox.glob_re(r.glob).fullmatch(path):
                won[i] += 1
                rows.append((path, r.cls, entries[path], r.producer, r.reason))
                break
        else:
            unmatched.append(path)
    dead = [r.glob for r, n in zip(rules, won) if n == 0]
    if unmatched or dead:
        raise ClassifyError("".join([f"unmatched file: {p}\n" for p in unmatched] + [f"dead rule: {g}\n" for g in dead]))
    return rows


def build(repo, rules, r1_inputs) -> str:
    rows = classify(sandbox.tracked(repo, ROOTS), rules)
    bad = [p for p, _producer, reason in r1_inputs if len(reason) <= 30]
    blobs = sandbox.tracked(repo, [p for p, _, _ in r1_inputs]) if r1_inputs else {}
    missing = [p for p, _, _ in r1_inputs if p not in blobs]
    if bad or missing:
        raise ClassifyError("".join([f"r1 input reason must be > 30 chars: {p}\n" for p in bad]
                                    + [f"r1 input not tracked by git: {p}\n" for p in missing]))
    rows += [(p, "r1_input", blobs[p], producer, reason) for p, producer, reason in r1_inputs]
    rows += list(S3_INPUTS)
    return sandbox.render_tsv(rows)


def seed(repo) -> str:
    """Candidate allowlist globs: every 08-28 path the October-layer code names, with where it is named."""
    r = subprocess.run(["git", "-C", str(repo), "grep", "-n", "-E", SEED_GREP, "--", *SEED_DIRS],
                       capture_output=True, text=True)
    if r.returncode not in (0, 1):
        raise ClassifyError(f"git grep failed: {r.stderr.strip()[:200]}")
    where: dict = {}
    for ln in r.stdout.splitlines():
        src, num, text = ln.split(":", 2)
        for tok in SEED_TOKEN.findall(text):
            where.setdefault(tok, []).append(f"{src}:{num}")
    out = ["# candidates for config/r1/read_allowlist_0828.txt (glob<TAB>configs<TAB>stages<TAB>reason); review each"]
    out += [f"{tok}\t# {', '.join(srcs[:3])}{' ...' if len(srcs) > 3 else ''}" for tok, srcs in sorted(where.items())]
    return "\n".join(out) + "\n"


def main(argv=None, *, rules=RULES, r1_inputs=R1_INPUTS) -> int:
    ap = argparse.ArgumentParser(description="R1 F2: classify the October trees into config/r1/base_inputs.tsv")
    ap.add_argument("--repo", default=str(REPO))
    ap.add_argument("--out", help=f"default: <repo>/{OUT.as_posix()}")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="exit 1 when the TSV differs from a regeneration")
    mode.add_argument("--seed-allowlist", action="store_true", help="print candidate 08-28 allowlist rows")
    a = ap.parse_args(argv)
    repo = pathlib.Path(a.repo)
    out = pathlib.Path(a.out) if a.out else repo / OUT
    try:
        if a.seed_allowlist:
            sys.stdout.write(seed(repo))
            return 0
        text = build(repo, rules, r1_inputs)
    except (ClassifyError, sandbox.Stop) as e:
        print(f"CLASSIFY_FAIL\n{e}", file=sys.stderr)
        return 1
    if a.check:
        old = out.read_text(encoding="utf-8") if out.is_file() else ""
        if old != text:
            diff = sorted({ln.split("\t", 1)[0] for ln in set(text.splitlines()) ^ set(old.splitlines())})
            print(f"BASE_INPUTS_STALE {out}: {len(diff)} paths differ, e.g. {diff[:5]}; rerun "
                  f"tools/r1_classify_cal_tree.py", file=sys.stderr)
            return 1
        print(f"BASE_INPUTS_OK {out} is current")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out} ({text.count(chr(10)) - 1} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
