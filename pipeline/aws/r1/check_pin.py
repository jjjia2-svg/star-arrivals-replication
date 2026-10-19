#!/usr/bin/env python3
"""R1 F1: a file rebuilt on AWS must equal its pin in a committed build report (sha256, bytes, one link).
  check_pin.py --file PATH --report JSON --key october.pairs_unified --out DIR     (exit 0 only on MATCH)
Ruling R2: pairs_unified.csv is rebuilt inside J0, never uploaded; a difference stops J0."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import sys

HOSTS = ("ec2-r1-test", "ec2-r1")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    for k in ("--file", "--report", "--key", "--out"):
        ap.add_argument(k, required=True)
    a = ap.parse_args(argv)
    if os.environ.get("SAR_HOST", "").strip() not in HOSTS:
        raise SystemExit("R1 rule: check_pin.py runs only on an R1 instance ($SAR_HOST)")
    pin = json.loads(pathlib.Path(a.report).read_text(encoding="utf-8"))
    for part in a.key.split("."):
        pin = pin[part]
    f = pathlib.Path(a.file)
    rec = {"key": a.key, "want_sha256": pin["sha256"], "want_bytes": pin["bytes"],
           "got_sha256": None, "got_bytes": None, "nlink": None}
    if f.is_symlink():
        verdict = "SYMLINK"
    elif not f.is_file():
        verdict = "MISSING"
    else:
        st = f.stat()
        rec["nlink"], rec["got_bytes"] = st.st_nlink, st.st_size
        h = hashlib.sha256()
        with open(f, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        rec["got_sha256"] = h.hexdigest()
        verdict = ("HARDLINK" if st.st_nlink != 1 else "SIZE_DIFF" if st.st_size != pin["bytes"]
                   else "SHA_DIFF" if rec["got_sha256"] != pin["sha256"] else "MATCH")
    rec["verdict"] = verdict
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "pin_check.json").write_text(json.dumps(rec, indent=1) + "\n", encoding="utf-8")
    print(f"PIN {a.key} {verdict}")
    return 0 if verdict == "MATCH" else 1


if __name__ == "__main__":
    sys.exit(main())
