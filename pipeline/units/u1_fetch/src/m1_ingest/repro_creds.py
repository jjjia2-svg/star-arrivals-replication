"""M1 repro_creds - deterministic reproduction credentials of a full real run (run_full requires all 4 non-None, otherwise ValueError).

Never contaminate the reproduction anchors of run_manifest with placeholders. The 4 credentials:
  source_snapshot_merkle = "snap:"+sha256(snapshot manifest.json) - pins the OpenAlex snapshot release / file set;
  rule_version           = "redlines:"+sha256(redlines.yaml)  - pins the version of the identification rules (drift is traceable);
  code_version           = "code:"+sha256(concatenated sha of the key pipeline source files) - pins the code version;
  config_sha             = "cfg:"+sha256(sorted econ_dept_ids + bucket parameters) - pins the run configuration.

Neutral on identification choices: only computes sha stamps, never reads or changes any identification threshold. Dependencies are injected as paths (testable).
"""
from __future__ import annotations

import hashlib
import json
from typing import Iterable


def _sha_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def compute_repro_creds(
    *,
    snapshot_manifest_path,
    redlines_path,
    code_src_paths: Iterable,
    econ_dept_ids,
    n_workers: int,
    bucket_row_cap: int,
) -> dict:
    """Compute the 4 deterministic reproduction credentials (all non-empty strings). Dependencies are injected as paths.

    code_src_paths: sequence of key pipeline source file paths (order-sensitive -> concatenated sha; changing any one changes code_version).
    econ_dept_ids: a set -> pinned by sorted() (independent of insertion order).
    """
    code_blob = "".join(_sha_file(p) for p in code_src_paths)
    cfg = json.dumps(
        {"econ_dept_ids": sorted(econ_dept_ids), "n_workers": n_workers,
         "bucket_row_cap": bucket_row_cap},
        sort_keys=True, ensure_ascii=False,
    )
    return {
        "source_snapshot_merkle": "snap:" + _sha_file(snapshot_manifest_path),
        "rule_version": "redlines:" + _sha_file(redlines_path),
        "code_version": "code:" + _sha_text(code_blob),
        "config_sha": "cfg:" + _sha_text(cfg),
    }
