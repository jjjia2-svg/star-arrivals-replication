"""Where a caliber (2026-08-28) frame lives in the public package.

The caliber rebuild froze 29 files under `data/cal2026-08-28/frames/`, and the public package ships
all 29 there: since the October recalibration `data/frames/` holds the cal2026-10 canon, so none of
them duplicates a canonical frame. Records written at freeze time name the
`data/cal2026-08-28/frames/<file>` location; these helpers resolve such a name to the shipped file
(falling back to `data/frames/` only if a caliber copy were absent) and to the manifest line that
pins it.
"""
from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]
CAL_FRAMES = REPO / "data" / "cal2026-08-28" / "frames"
CANON_FRAMES = REPO / "data" / "frames"


def _manifest(path: pathlib.Path) -> dict[str, str]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            h, rel = line.split("  ", 1)
            out[rel] = h
    return out


def cal_frame_rel(name: str) -> str:
    """Repository-relative path of a caliber frame: its caliber-only copy if shipped, else the
    byte-identical canonical copy in data/frames/."""
    rel = f"data/cal2026-08-28/frames/{name}"
    return rel if (REPO / rel).is_file() else f"data/frames/{name}"


def cal_frame(name: str) -> pathlib.Path:
    return REPO / cal_frame_rel(name)


def pinned_sha(name: str) -> str | None:
    """The sha256 a manifest records for the shipped copy of caliber frame `name`."""
    rel = cal_frame_rel(name)
    man = (REPO / "data" / "cal2026-08-28" / "MANIFEST.sha256") if rel.startswith("data/cal") \
        else (REPO / "data" / "MANIFEST.sha256")
    return _manifest(man).get(rel)
