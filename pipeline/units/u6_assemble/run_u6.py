"""run_u6: U6 thin CLI top-level orchestration: m7b-assemble -> m7c-gates ->
m7d-power. Products go to the given out_root (a real run creates only a brand-new u6_ship_* directory and never overwrites an existing one).

Double anchor (kept): u4 = u4_ship_2026-07-10c / u5 = u5_ship_2026-07-10;
the loading layer verifies the 4-tuple of each artifact (HALT on mismatch); rule_version consistency gate (pins == current
redlines rule_version, to prevent version drift between the upstream freeze and this run's definitions).

Exit code mapping (identity/exit_codes, B6-EXITCODE discipline: named constants, not bare numbers):
  ProvenanceMismatch -> 13 | structural (FrameAssembly/RejoinDrift/PKCoverage/
  SoleProducerDrift) -> 14 | TallyImbalance -> 15 | GoldenStructuralFail -> 18.
resume: ledger idempotency key = stage|config_sha|stars_set_hash|merkle|rule_version;
if the upstream anchor changes, the key flips and nothing is wrongly skipped.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import time

_HERE = pathlib.Path(__file__).resolve().parent
_UNITS = _HERE.parent
for _p in (_UNITS / "u0_foundation" / "src", _UNITS / "u1_fetch" / "src",
           _UNITS / "u6_assemble" / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import io_real                                            # noqa: E402
from common.atomic_io import atomic_write_bytes           # noqa: E402
from common.ledger import Ledger                          # noqa: E402
from common.manifest import ProvenanceMismatch, dataset_is_valid  # noqa: E402
from identity import exit_codes                           # noqa: E402
from m7b_assemble import assemble as m7b                  # noqa: E402
from m7c_gates import run_gates as m7c                    # noqa: E402
from m7c_gates.frame_gate import FramePKCoverageError, \
    FrameRejoinDrift                                      # noqa: E402
from m7c_gates.golden_gate import GoldenStructuralFail    # noqa: E402
from m7c_gates.reconcile_gate import TallyImbalance       # noqa: E402
from m7d_power import run_power as m7d                    # noqa: E402
from m7d_power.load_frame import SoleProducerDrift        # noqa: E402
from m7d_power.run_manifest import config_sha_of          # noqa: E402

# Double anchor (pinned byte for byte; verified key by key against the on-disk _frozen/manifest_header.json)
PINNED_U4_10C: dict = {
    "source_snapshot_merkle":
        "snap:da78e4b9b706d48d3d4f0353302f8f1ba86fd9d3afdab948d88001205bc4dd89",
    "config_sha":
        "45c57627a8b433064fed76d27e40dcd608a18466125c21480b260357fc229de1",
    "rule_version": "redlines_v4_signed_2026-07-05",
    "stars_set_hash":
        "2ae9ab57076e32da0a311a490ee2f7187e6afe8677117c85c65ddec6d6751009",
}
PINNED_U5_SHIP: dict = {
    "source_snapshot_merkle": PINNED_U4_10C["source_snapshot_merkle"],
    "config_sha":
        "3415679a198c237b576694ea6b5d3bfd9e0e7a91b889e0b43409d3623dee0d6b",
    "rule_version": "redlines_v4_signed_2026-07-05",
    "stars_set_hash": PINNED_U4_10C["stars_set_hash"],
}

# --- M3 port: repo path resolution (legacy hard-coded the author's machine) — config/paths.yaml ---
import pathlib as _sar_pl, sys as _sar_sys
_sar_repo = next(p for p in _sar_pl.Path(__file__).resolve().parents if p.name == "units").parents[1]
if str(_sar_repo) not in _sar_sys.path:
    _sar_sys.path.append(str(_sar_repo))
from pipeline.lib.paths import derived_root as _sar_derived_root  # noqa: E402
DEFAULT_DATA_ROOT = str(_sar_derived_root())


def default_paths(data_root: str = DEFAULT_DATA_ROOT) -> dict:
    r = pathlib.Path(data_root)
    u5 = r / "u5_ship_2026-07-10"
    u4 = r / "u4_ship_2026-07-10c"
    roster = r / "u0p5_roster"
    return {
        "person_map": str(r / "u2_person_map_2026-07-05" / "person_map"
                          / "data.parquet"),
        "star_set_dir": str(u4 / "star_set"),
        "events_dir": str(u4 / "events"),
        "dose_p01_dir": str(u5 / "dose_p01"),
        "dose_p05_dir": str(u5 / "dose_p05"),
        "output_dir": str(u5 / "output"),
        "roster_files": [
            str(roster / "roster_v2026-07-10_starfix"
                / "dept_roster_panel_monash.parquet"),
            str(roster / "roster_v2026-07-10_starfix"
                / "dept_roster_panel_unsw.parquet"),
        ],
        "registry": str(roster / "econ_dept_registry.parquet"),
        "panel_dir": str(r / "u3_panel_2026-07-06" / "panel"),
        "work_first_pub_glob": str(r / "u1_edges_full_2026-07-05"
                                   / "work_first_pub" / "**" / "*.parquet"),
        "u5_diag_files": {
            "dose_p01": str(u5 / "dose_p01" / "diag.json"),
            "dose_p05": str(u5 / "dose_p05" / "diag.json"),
            "output": str(u5 / "output" / "output_diag.json"),
        },
    }


def build_config(*, pins_u4: dict, pins_u5: dict,
                 redlines_path: pathlib.Path) -> dict:
    cfg = {
        "mnar_missing_threshold": 0.20,     # C2 caveat
        "source_snapshot_merkle": pins_u4["source_snapshot_merkle"],
        "rule_version": pins_u4["rule_version"],
        "stars_set_hash": pins_u4["stars_set_hash"],
        "pins_u4": dict(pins_u4), "pins_u5": dict(pins_u5),
        "redlines_config_sha": config_sha_of([redlines_path]),
    }
    blob = json.dumps(cfg, sort_keys=True, ensure_ascii=False).encode("utf-8")
    cfg["config_sha"] = hashlib.sha256(blob).hexdigest()
    return cfg


def run_all(inputs, *, out_root, config: dict, force: bool = False) -> dict:
    """Already-loaded inputs -> m7b -> m7c -> m7d (synthetic inputs can be fed directly for tests)."""
    t0 = time.time()
    out_root = pathlib.Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    ledger_path = out_root / "_ledger" / "u6_run" / "events.jsonl"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(ledger_path)
    idem_key = "|".join(("u6_assemble", config["config_sha"],
                         config["stars_set_hash"],
                         config["source_snapshot_merkle"],
                         config["rule_version"]))
    if (not force) and ledger.already_done(idem_key) \
            and dataset_is_valid(out_root / "frame"):
        return {"skipped": True, "idempotency_key": idem_key}

    m7b_rep = m7b.assemble_frames(inputs, out_root=out_root, config=config)
    t1 = time.time()
    gates_res = m7c.run_gates(out_root, inputs, config=config)
    t2 = time.time()
    power_rep = m7d.run_power(out_root, inputs, config=config,
                              gates_result=gates_res)
    t3 = time.time()

    report = {
        "skipped": False,
        "idempotency_key": idem_key,
        "io": dict(inputs.report),
        "m7b": m7b_rep,
        "gates_verdict": gates_res["verdict"],
        "gates": gates_res.get("gates"),
        "attrition": gates_res.get("attrition"),
        "power": power_rep,
        "timings_s": {"m7b": round(t1 - t0, 1), "m7c": round(t2 - t1, 1),
                      "m7d": round(t3 - t2, 1), "total": round(t3 - t0, 1)},
    }
    reports_dir = out_root / "_reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(reports_dir / "run_summary_u6.json",
                       json.dumps(report, ensure_ascii=False, sort_keys=True,
                                  indent=1, default=str).encode("utf-8"))
    from datetime import datetime, timezone

    ledger.append(op_id="u6_assemble", status="ok", shard_id="p01+p05",
                  idempotency_key=idem_key,
                  ts=datetime.now(timezone.utc).isoformat(), reason="")
    return report


def exit_code_for(exc: BaseException) -> int:
    if isinstance(exc, ProvenanceMismatch):
        return exit_codes.PROVENANCE_MISMATCH
    if isinstance(exc, (m7b.FrameAssemblyError, FrameRejoinDrift,
                        FramePKCoverageError, SoleProducerDrift)):
        return exit_codes.STRUCTURAL_GATE_FAIL
    if isinstance(exc, TallyImbalance):
        return exit_codes.TALLY_IMBALANCE
    if isinstance(exc, GoldenStructuralFail):
        return exit_codes.GOLDEN_FAIL
    return 1


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="U6 assembly (2-university real-data pilot)")
    ap.add_argument("--out-root", required=True,
                    help="output root (only creates a new directory, never touches an existing one)")
    ap.add_argument("--data-root", default=DEFAULT_DATA_ROOT)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)

    from common._redlines import RED, REDLINES_YAML

    for pins in (PINNED_U4_10C, PINNED_U5_SHIP):
        if str(RED.get("rule_version")) != str(pins["rule_version"]):
            raise ValueError(
                f"rule_version drift: redlines={RED.get('rule_version')!r} != "
                f"pins={pins['rule_version']!r} — HALT, a person must decide")

    cfg = build_config(pins_u4=PINNED_U4_10C, pins_u5=PINNED_U5_SHIP,
                       redlines_path=REDLINES_YAML)
    try:
        inputs = io_real.build_real_inputs(default_paths(args.data_root),
                                           pins_u4=PINNED_U4_10C,
                                           pins_u5=PINNED_U5_SHIP)
        report = run_all(inputs, out_root=args.out_root, config=cfg,
                         force=args.force)
    except Exception as exc:                          # noqa: BLE001
        print(f"[run_u6] HALT: {type(exc).__name__}: {exc}", file=sys.stderr)
        return exit_code_for(exc)
    print(json.dumps({
        "frame_rows": report.get("m7b", {}).get("n_rows"),
        "gates_verdict": report.get("gates_verdict"),
        "G_treated": report.get("power", {}).get("G_treated"),
        "timings_s": report.get("timings_s"),
        "skipped": report.get("skipped"),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
