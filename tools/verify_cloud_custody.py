"""Four cells were estimated on EC2 (r6i.16xlarge) and are not rerun here: the P3 main econ/chem
runs and the P3 event-cluster-robustness econ/chem runs. Since the 2026-08-28 freeze the canonical
chain is the CALIBER cloud run (data/cal2026-08-28/cloud/, instance i-0ec873f66546a0b87,
2026-08-28): this proves, for each cell, that the parquet frames in data/frames and the R drivers
in analysis/estimation are byte-identical (md5) to the payload that was shipped (payload.md5 —
which the instance itself re-verified, `md5sum -c` OK lines in fetch/driver.log), and that the
JSON fetched back from EC2 equals the frozen gold in analysis/expected/.

The PRE-caliber chain (pipeline/aws/logs/p3_main_2026-08-16/ + p3_evcl_2026-08-16/) is NOT deleted:
its records stay tracked and pinned in data/MANIFEST.sha256, and they verify the pre-caliber canon,
which is kept in the author's private repository (tag `pre-cal-freeze`). They are no longer checked against the live
tree here because the live tree's frames and golds are the 2026-08-28 caliber artifacts.

Run: python3 tools/verify_cloud_custody.py -> CUSTODY_OK (exit 0) or CUSTODY_FAIL (exit 1).

2026-09-23 (cal2026-10 promoted): data/frames holds the October frames and analysis/expected the
October golds, including the four cloud cells, which come from the October cloud run
(data/cal2026-10/cloud). `tools/compare_all.py` (run_all stage 2) therefore checks
`--custody data/cal2026-10/cloud`: 19 payload md5 pairs (frames, reference estimates, R drivers) and
six fetched results (the four cells and two date-shift controls) compare_json-EQUAL to
analysis/expected. The DEFAULT block below still verifies the 2026-08-28 run against the 08-28 canon
where it is frozen — data/cal2026-08-28/frames/ and data/cal2026-08-28/estimates/ (which differ from
analysis/expected since the promotion) — and stays covered by the tests.

Generalised 2026-09-22 for the October (cal2026-10) batch: `--custody DIR` names another custody
directory. The default (data/cal2026-08-28/cloud) keeps the hard-coded caliber block above so the
existing tests and the run_all sentinel are unchanged. Any other directory must carry a custody
JSON written by pipeline/aws/cal2026-10/cloudkit.py (`custody_cal2026-10.json`, or `--spec FILE`)
whose "verify" block lists the same two kinds of pairs: `frame_pairs` [[local path, payload
name], ...] md5-checked against DIR/payload.md5, and `fetched_pairs` [[fetch-relative result,
gold filename], ...] compare_json-checked against `gold_dir`; `require_marker` is asserted on
DIR/fetch/RESULT.txt. Nothing is relaxed for the new directory: the same verify_block, the same
exact JSON comparison.

Optional: --root PATH points ROOT elsewhere (used only to demonstrate the missing-file path
safely, without touching real repo files; analysis.lib.compare_json is always imported from
this real repo regardless of --root)."""
import argparse, hashlib, json, pathlib, sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from analysis.lib.compare_json import compare

DEFAULT_CUSTODY = "data/cal2026-08-28/cloud"
ROOT = REPO_ROOT


def md5(p):
    return hashlib.md5(p.read_bytes()).hexdigest()


def verify_block(log_rel, frame_pairs, fetched_pairs, gold_dir):
    """Defensive custody check for one cloud run directory. frame_pairs: [(local_rel, payload_name)]
    to md5 against log_rel/payload.md5. fetched_pairs: [(fetched_filename, gold_filename)] compared
    (compare_json) between log_rel/fetch/<fetched_filename> and gold_dir/<gold_filename>. Returns ok."""
    log = ROOT / log_rel
    ok = True
    want = {}
    payload_md5 = log / "payload.md5"
    if not payload_md5.exists():
        print(f"BAD {log_rel}/payload.md5 missing")
        ok = False
    else:
        try:
            for line in payload_md5.read_text().splitlines():
                if line.strip():
                    h, name = line.split()[0], line.split()[-1]
                    want[pathlib.Path(name).name] = h
        except (OSError, UnicodeDecodeError, IndexError) as e:
            print(f"BAD {log_rel}/payload.md5 unparsable: {e}")
            ok = False

    for local, payload_name in frame_pairs:
        p = ROOT / local
        if not p.exists():
            print(f"BAD {local} missing")
            ok = False
            continue
        got = md5(p)
        exp = want.get(payload_name)
        print(f"{'OK ' if got == exp else 'BAD'} {local}  md5={got}  payload={exp}")
        ok &= got == exp

    # The fetched EC2 result filenames are known exactly (recorded in the custody log) — no
    # glob needed.
    for fetched, gold in fetched_pairs:
        src = log / "fetch" / fetched
        if not src.exists():
            print("BAD no fetched", fetched)
            ok = False
            continue
        gold_path = ROOT / gold_dir / gold
        if not gold_path.exists():
            print(f"BAD {gold_dir}/{gold} missing")
            ok = False
            continue
        d = compare(json.load(open(src)), json.load(open(gold_path)))
        verdict = "OK " if not d else "BAD"
        try:
            shown = src.relative_to(ROOT)
        except ValueError:
            shown = src
        print(f"{verdict} fetched {shown} vs {gold_dir}/{gold}" + ("" if not d else " :: " + "; ".join(d[:3])))
        ok &= not d

    return ok


def verify_caliber_2026_08_28():
    # The caliber cloud run (2026-08-28) shipped one payload for all four cells: the four slim pair
    # panels plus the two verbatim R drivers. custody_2026-08-28.json carries the full chain
    # (three-way sha before upload, the instance's own md5sum -c, per-cell exits, result hashes,
    # termination proof); tests/test_cal_cloud_2026_08_28.py re-verifies it link by link.
    # 2026-09-23: the frames and golds are the FROZEN 2026-08-28 copies (data/frames and
    # analysis/expected are the October caliber since 73777aa; see the module docstring).
    return verify_block(
        log_rel=DEFAULT_CUSTODY,
        frame_pairs=[
            ("data/cal2026-08-28/frames/p3_slim_econ.parquet", "p3_slim_econ.parquet"),
            ("data/cal2026-08-28/frames/p3_slim_chemistry.parquet", "p3_slim_chemistry.parquet"),
            ("data/cal2026-08-28/frames/p3_slim_ev_econ.parquet", "p3_slim_ev_econ.parquet"),
            ("data/cal2026-08-28/frames/p3_slim_ev_chemistry.parquet", "p3_slim_ev_chemistry.parquet"),
            ("analysis/estimation/run_p3.R", "run_p3.R"),
            ("analysis/estimation/run_p3_evcl.R", "run_p3_evcl.R"),
        ],
        fetched_pairs=[
            ("P3_econ_fnfix.json", "P3_econ_fnfix.json"),
            ("P3_fnfix_chemistry.json", "P3_fnfix_chemistry.json"),
            ("P3evcl_econ.json", "P3evcl_econ.json"),
            ("P3evcl_chemistry.json", "P3evcl_chemistry.json"),
        ],
        gold_dir="data/cal2026-08-28/estimates",
    )


def verify_from_spec(custody_dir, spec_path):
    """A custody directory described by its own custody JSON (cloudkit.py `custody`)."""
    cdir = pathlib.Path(custody_dir)
    if not cdir.is_absolute():
        cdir = ROOT / cdir
    if spec_path is None:
        cands = [c for c in sorted(cdir.glob("custody_*.json")) if c.name != "custody_preflight.json"]
        if not cands:
            print(f"BAD {cdir}: no custody_*.json (run cloudkit.py custody first)")
            return False
        spec_path = cands[-1]
    spec = json.load(open(spec_path))
    v = spec.get("verify")
    if not isinstance(v, dict):
        print(f"BAD {spec_path}: no 'verify' block")
        return False
    ok = True
    marker = v.get("require_marker")
    if marker:
        rp = cdir / "fetch" / "RESULT.txt"
        got = rp.read_text().strip() if rp.is_file() else "<missing>"
        print(f"{'OK ' if got == marker else 'BAD'} RESULT.txt {got!r} (want {marker!r})")
        ok &= got == marker
    if spec.get("ok") is False:
        print(f"BAD {spec_path.name} recorded problems: {spec.get('problems')}")
        ok = False
    frame_pairs = [tuple(x) for x in v.get("frame_pairs", [])]
    fetched_pairs = [tuple(x) for x in v.get("fetched_pairs", [])]
    if not frame_pairs:
        print("BAD verify.frame_pairs is empty — nothing ties the payload to the tree")
        ok = False
    ok &= verify_block(log_rel=cdir, frame_pairs=frame_pairs, fetched_pairs=fetched_pairs,
                       gold_dir=v.get("gold_dir") or ".")
    if not fetched_pairs:
        print("NOTE no fetched_pairs: the results are not yet frozen against a gold dir "
              "(payload side verified only)")
    return ok


def main(argv=None):
    global ROOT
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(REPO_ROOT), help="repo root to check (default: this repo)")
    parser.add_argument("--custody", default=DEFAULT_CUSTODY,
                        help=f"custody directory (default {DEFAULT_CUSTODY}: the hard-coded caliber "
                             f"block; any other directory is read from its custody JSON)")
    parser.add_argument("--spec", default=None, help="explicit custody JSON for --custody")
    args = parser.parse_args(argv)
    ROOT = pathlib.Path(args.root).resolve()
    if args.custody == DEFAULT_CUSTODY and args.spec is None:
        ok = verify_caliber_2026_08_28()
    else:
        ok = verify_from_spec(args.custody, pathlib.Path(args.spec) if args.spec else None)
    print("CUSTODY_OK" if ok else "CUSTODY_FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
