#!/usr/bin/env python3
"""R1 F9: check the run config on the instance, as the first stage after verify_inputs. Standard library only.

  config_check.py check --config P --out DIR [--repo DIR]
      load P through pipeline/lib/r1_config.py (every STOP rule: rulings signed and equal to the signed
      lists, switches known and complete, B0 switches off, M's add list OK, pins, inputs, path tokens),
      then write DIR/resolved.json (every section with its repo:/work: tokens resolved, as strings) and
      DIR/config_report.json (result, code and counts; no person names). Exit 0, or 3 with the ConfigStop
      code (config_report.json is written either way; resolved.json only on success).

--repo defaults to $REPO_DIR (set by run_stages.py), else the checkout this file sits in.
Runs only on an R1 instance ($SAR_HOST), from its copy under /work/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import sys

HOSTS = ("ec2-r1-test", "ec2-r1")
EXIT_STOP = 3


def _strings(obj):
    """Resolved section values as JSON: Paths become strings, lists and dicts keep their shape."""
    if isinstance(obj, pathlib.Path):
        return str(obj)
    if isinstance(obj, list):
        return [_strings(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _strings(v) for k, v in obj.items()}
    return obj


def _write(path: pathlib.Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def check(config: pathlib.Path, out: pathlib.Path, repo: pathlib.Path) -> int:
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    from pipeline.lib import r1_config

    if not config.is_absolute():
        config = repo / config
    out.mkdir(parents=True, exist_ok=True)
    (out / "resolved.json").unlink(missing_ok=True)
    report = {"schema": "sar.r1.config_report.v1", "config": None, "sha256": None,
              "result": "STOP", "code": None, "counts": {}}
    if config.is_file():
        report["sha256"] = hashlib.sha256(config.read_bytes()).hexdigest()
    try:
        cfg = r1_config.load(config, repo=repo)
        sections = {name: _strings(cfg.resolved(name)) for name in sorted(cfg.raw["sections"])}
    except r1_config.ConfigStop as e:
        report["code"] = e.code
        _write(out / "config_report.json", report)
        print(f"CONFIG_STOP {e}", file=sys.stderr)
        return EXIT_STOP
    _write(out / "resolved.json", {"schema": "sar.r1.config_resolved.v1", "config": cfg.name,
                                   "sha256": cfg.sha256, "repo": str(repo), "sections": sections})
    report.update(config=cfg.name, sha256=cfg.sha256, result="OK", counts={
        "switches": len(r1_config.SWITCHES),
        "switches_on": sum(cfg.is_on(s) for s in r1_config.SWITCHES),
        "rulings": len(cfg.raw["rulings"]),
        "required_rulings": len(r1_config.REQUIRED_RULINGS),
        "signed": len(cfg.raw["signed"]),
        "pins": len(cfg.raw["pins"]),
        "inputs": len(cfg.raw["inputs"]),
        "sections": len(sections),
    })
    _write(out / "config_report.json", report)
    print(f"CONFIG_OK {cfg.name} {cfg.sha256}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="R1 run-config check (instance)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="load and check a run config; write resolved.json and config_report.json")
    c.add_argument("--config", required=True, type=pathlib.Path)
    c.add_argument("--out", required=True, type=pathlib.Path)
    c.add_argument("--repo", type=pathlib.Path, default=None)
    a = ap.parse_args(argv)
    if os.environ.get("SAR_HOST", "").strip() not in HOSTS:
        raise SystemExit("R1 rule: config_check.py runs only on an R1 instance ($SAR_HOST)")
    repo = a.repo or pathlib.Path(os.environ.get("REPO_DIR", "").strip() or pathlib.Path(__file__).resolve().parents[3])
    return check(a.config, a.out, repo.resolve())


if __name__ == "__main__":
    sys.exit(main())
