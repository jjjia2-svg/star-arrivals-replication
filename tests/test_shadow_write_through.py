# -*- coding: utf-8 -*-
"""frames_stage.Shadow must never write THROUGH a hard link into the file it linked (review finding
2026-09-23, econ920): `link_frozen` hard-links a legacy file into the shadow; a later `write` of the
same rel used to `write_bytes` onto that link and so truncated the shared inode — the read-only
legacy tree itself (edges_supplement_fnfix.jsonl took six appended copies of the 126-row supplement,
the 2026-08-13 API patch one 190-row supplement; both restored from their pinned bytes). The shadow
now unlinks first; the source keeps its bytes and its single link."""
from __future__ import annotations

import hashlib
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline" / "stars" / "caliber_2026-08-28"))
import frames_stage as fs08                                              # noqa: E402


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_write_after_link_frozen_leaves_the_linked_source_untouched(tmp_path):
    legacy = tmp_path / "legacy" / "econ_fnfix_2026-08-15" / "data" / "edges_supplement_fnfix.jsonl"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b'{"a": 1}\n{"a": 2}\n')
    pin = sha(legacy)
    sh = fs08.Shadow(tmp_path / "shadow" / "v2_output")
    rel = "econ_fnfix_2026-08-15/data/edges_supplement_fnfix.jsonl"
    sh.link_frozen(rel, legacy)
    assert legacy.stat().st_nlink == 2                     # a real hard link (same volume)
    sh.write(rel, legacy.read_bytes() + b'{"extra": 1}\n', "derived: frozen ⧺ extra")
    assert sha(legacy) == pin, "the legacy file was written through the shadow's hard link"
    assert legacy.stat().st_nlink == 1
    assert sh.path(rel).read_bytes().endswith(b'{"extra": 1}\n')
    assert sh.path(rel).stat().st_ino != legacy.stat().st_ino
    assert [e["rel"] for e in sh.entries] == [rel, rel]
    assert sh.entries[0]["sha256"] == pin and sh.entries[1]["sha256"] == sha(sh.path(rel))


def test_install_over_a_frozen_link_replaces_the_link_not_the_source(tmp_path):
    legacy = tmp_path / "legacy" / "f.csv"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"a,b\n1,2\n")
    pin = sha(legacy)
    produced = tmp_path / "produced.csv"
    produced.write_bytes(b"a,b\n3,4\n")
    sh = fs08.Shadow(tmp_path / "shadow")
    sh.link_frozen("x/f.csv", legacy)
    sh.install("x/f.csv", produced, "cal-stage:test")
    assert sha(legacy) == pin and legacy.stat().st_nlink == 1
    assert sh.path("x/f.csv").read_bytes() == b"a,b\n3,4\n"
