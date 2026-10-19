#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""basemap_etopo5_mask_2026-10.py — write the 1-degree land/sea mask the star-origins map draws as
its grey land (analysis/paper/fig_star_origins.py). Repo-authored 2026-09-23. No network.

Why this source. The map needs a public-domain land outline that is already on this machine. A disk
search on 2026-09-23 found no Natural Earth vector file (no countries-110m / land-110m / ne_110m_*
anywhere: home, /Applications, Homebrew, R and TeX libraries, both data disks). The one Natural
Earth product on disk is MATLAB's raster tile set
(/Applications/MATLAB_R2025b.app/toolbox/matlab/maps/mapdata/maptiles/NaturalEarth); its
copyright.txt says "Copyright 2017 The MathWorks, Inc. Modified from Natural Earth datasets", so
those tiles are a MathWorks work, not public domain, and are NOT used. What IS on disk is MATLAB's
demo file toolbox/matlab/demos/topo.mat, which MATLAB's own example (earthmap.m) documents as data
"available from the National Geophysical Data Center, NOAA US Department of Commerce under data
announcement 88-MGG-02" — ETOPO5, a US federal government dataset (public domain). This tool reads
that file with the Python standard library (MAT v5, zlib-compressed elements), keeps ONLY the fact
"elevation >= 0 m" at each 1-degree point, and writes that 0/1 grid as text. The MATLAB file itself
is not copied into the repo. The same mask can be rebuilt from NOAA's own ETOPO5 distribution.

Grid convention: row k (0-based, k = 0..179) runs south to north, column j (0..359) west to east
from 0 degrees. Cell geometry (corrected 2026-09-23): topo.mat's own georeference (topolegend =
[1 90 0], topolatlim = [-90 90], topolonlim = [0 360]) puts cell edges on whole degrees, so cell
(k, j) is centred on latitude -89.5 + k and longitude 0.5 + j. The header line written below keeps
the labels of MATLAB's contour demo (contour(0:359, -89:90, topo)), half a degree north-west of the
centres, so that the mask file stays byte-identical; data/paper_inputs/basemap/README.md explains.

Writes data/paper_inputs/basemap/land_mask_etopo5_1deg.txt (+ MANIFEST.sha256 covering it and the
README). Run:  setup/.venv/bin/python tools/basemap_etopo5_mask_2026-10.py [--topo PATH]
"""
from __future__ import annotations

import argparse
import array
import hashlib
import pathlib
import struct
import zlib

REPO = pathlib.Path(__file__).resolve().parents[1]
TOPO = pathlib.Path("/Applications/MATLAB_R2025b.app/toolbox/matlab/demos/topo.mat")
OUT = REPO / "data" / "paper_inputs" / "basemap"
MASK = "land_mask_etopo5_1deg.txt"
_TYPES = {1: "b", 2: "B", 3: "h", 4: "H", 5: "i", 6: "I", 7: "f", 9: "d"}


def _elements(buf: bytes):
    o = 0
    while o < len(buf):
        t, n = struct.unpack("<II", buf[o:o + 8])
        if t >> 16:                       # small data element: size in the upper 16 bits
            n, t = t >> 16, t & 0xFFFF
            yield t, buf[o + 4:o + 4 + n]
            o += 8
            continue
        yield t, buf[o + 8:o + 8 + n]
        o += 8 + n + ((8 - n % 8) % 8)


def read_mat_v5(path: pathlib.Path) -> dict[str, tuple[tuple[int, ...], array.array]]:
    """Numeric matrices of a MAT v5 file whose elements are all miCOMPRESSED (topo.mat is)."""
    b = path.read_bytes()
    if not b[:10].startswith(b"MATLAB 5.0") or b[126:128] != b"IM":
        raise SystemExit(f"not a little-endian MAT v5 file: {path}")
    out, off = {}, 128
    while off < len(b):
        t, n = struct.unpack("<II", b[off:off + 8])
        if t != 15:
            raise SystemExit(f"unexpected top-level element type {t} in {path}")
        d = zlib.decompress(b[off + 8:off + 8 + n])
        off += 8 + n
        mt, mn = struct.unpack("<II", d[:8])
        if mt != 14:
            continue
        subs = list(_elements(d[8:8 + mn]))
        dims = struct.unpack("<%di" % (len(subs[1][1]) // 4), subs[1][1])
        name = subs[2][1].decode("ascii")
        rt, rd = subs[3]
        a = array.array(_TYPES[rt])
        a.frombytes(rd)
        out[name] = (dims, a)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topo", type=pathlib.Path, default=TOPO)
    a = ap.parse_args()
    m = read_mat_v5(a.topo)
    (nr, nc), z = m["topo"]
    if (nr, nc) != (180, 360):
        raise SystemExit(f"topo is {nr}x{nc}, expected 180x360")
    # column-major storage: element (r, c) = z[c * nr + r]
    lines = ["".join("1" if z[c * nr + r] >= 0 else "0" for c in range(nc)) for r in range(nr)]
    OUT.mkdir(parents=True, exist_ok=True)
    head = ("# land/sea mask, 1 = elevation >= 0 m; NOAA NGDC ETOPO5 (data announcement 88-MGG-02) "
            "via MATLAB R2025b toolbox/matlab/demos/topo.mat sha256 "
            + hashlib.sha256(a.topo.read_bytes()).hexdigest() + "\n"
            "# rows: latitude -89..90 (south to north, one per line); columns: longitude 0..359 east\n")
    (OUT / MASK).write_text(head + "\n".join(lines) + "\n", encoding="utf-8")
    names = [MASK, "README.md"]
    (OUT / "MANIFEST.sha256").write_text(
        "".join(f"{hashlib.sha256((OUT / n).read_bytes()).hexdigest()}  {(OUT / n).relative_to(REPO)}\n"
                for n in names if (OUT / n).exists()), encoding="utf-8")
    land = sum(l.count("1") for l in lines)
    print(f"wrote {(OUT / MASK).relative_to(REPO)}: {nr}x{nc}, land points {land} ({land / (nr * nc):.3f})")


if __name__ == "__main__":
    main()
