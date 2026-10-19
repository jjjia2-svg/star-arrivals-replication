# data/paper_inputs/basemap

The land under the star-origins map, Figure 1 (`analysis/paper/fig_star_origins.py`, drawing in
`analysis/paper/fig_star_origins_dots.py`). Two files:

- `ne_50m_land.geojson` — **what the figure draws** since 2026-10-01 (the unit-dot design): Natural
  Earth 1:50m land polygons. Section "Natural Earth" below.
- `land_mask_etopo5_1deg.txt` — the 1-degree ETOPO5 land mask. The figure no longer draws it; the
  generator still reads it for the ledger's sea-side marker counts (`*_origin_markers_at_sea*`,
  `pooled_destination_markers_at_sea*`, `_land_rule`), which are unchanged. Sections "File" to "Why
  not Natural Earth" below (written 2026-09-23 for the arc design, kept as they were).

## Natural Earth (added 2026-10-01)

- **File:** `ne_50m_land.geojson` — Natural Earth 1:50m physical vectors, land polygons, as GeoJSON
  (a FeatureCollection of 1,420 Polygon / MultiPolygon features in longitude / latitude degrees,
  CRS84). Stored byte-for-byte as downloaded.
- **Source:** downloaded on 2026-10-01 from
  `https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_land.geojson`
  (the Natural Earth project's own GitHub repository, nvkelso/natural-earth-vector).
- **Licence:** public domain, per the terms of use on naturalearthdata.com (the Natural Earth
  raster and vector data are placed in the public domain; crediting is not required). The figure
  has no credit line (the course word count includes figure text); this README is the record.
- **sha256:** `e874b27a51d146452be360cafb3cc50c86001074a67d534113e6534682f9826b` (1,636,166 bytes).
  The generator pins it (`PINS` in `fig_star_origins.py`, so it is in the ledger's
  `_inputs_sha256`), checks the feature count (1,420) and stops on any change.
- **How the figure uses it:** every polygon north of 60 S is projected with the panel's own Robinson
  projection (world map centred on 150 E; the Europe panel centred on its own meridian); rings that
  cross a panel's antimeridian are split there; rings smaller than 0.2 mm on the page are dropped;
  the coastline is stroked only along real coast (not along clip edges or Natural Earth's 180 E
  seams). The same polygons serve the drawing's placement checks (no dot on Australian land, the
  UK and US blocks on their own land, the New Zealand block clear of New Zealand).

## File (the ETOPO5 mask)

`land_mask_etopo5_1deg.txt` — a 180 x 360 grid of `0`/`1`, one text line per latitude band.
`1` = elevation at or above 0 m. Row k (0-based, after the two `#` header lines) runs south to
north, column j west to east from 0 degrees.

**Cell geometry (corrected 2026-09-23).** topo.mat carries its own georeference: `topolegend =
[1 90 0]`, `topolatlim = [-90 90]`, `topolonlim = [0 360]` — one cell per degree with edges on whole
degrees, so row k covers latitudes -90 + k .. -89 + k and column j longitudes j .. j + 1: cell
(k, j) is centred on latitude **-89.5 + k**, longitude **0.5 + j**. The header's "latitude -89..90 /
longitude 0..359" and the first version of this README followed MATLAB's contour demo
(`contour(0:359,-89:90,topo)` in earthmap.m), which labels the same cells half a degree north-west
of their centres; the map drew land that far north-west until the 2026-09-23 revision. The mask
file itself is unchanged.

How the map draws it (`analysis/paper/fig_star_origins.py`, 2026-09-23): the grid is split into
half-degree cells, expanded by one of them (3 x 3 maximum) and smoothed (3 x 3 mean), and filled at
the 0.5 contour, so the drawn coast lies half a 1-degree cell further out than the raw 0.5 contour
and coastal cities (Sydney, Brisbane, Perth, most origin ports) sit on land. The generator's ledger
counts the markers still on the sea side, before and after the expansion.

## Source and licence

- **Data:** NOAA National Geophysical Data Center, ETOPO5 global relief, data announcement
  88-MGG-02. A US federal government dataset: **public domain** (not subject to copyright in the
  United States, 17 U.S.C. 105).
- **Carrier on this machine:** MATLAB R2025b `toolbox/matlab/demos/topo.mat`
  (sha256 `efbc3a8f21bb790799b389f5b596101b44706965af77f265f7a3e924601bcc88`). MATLAB's own
  example `toolbox/matlab/demos/earthmap.m` (sha256
  `4238e2063d8ae5425d84365e0aa5d09c0a1ccd316addefe392d478cb46179da5`) states: "The data in this
  example is available from the National Geophysical Data Center, NOAA US Department of Commerce
  under data announcement 88-MGG-02."
- **What is stored here:** only the derived fact "land or sea" at each 1-degree point. The MATLAB
  file is not copied. Anyone can rebuild the same mask from NOAA's ETOPO5 without MATLAB.
- **Built by:** `tools/basemap_etopo5_mask_2026-10.py` (standard-library MAT-file reader; no
  network). The mask file's first header line repeats the topo.mat sha256.

## Why not Natural Earth

The task asked for a Natural Earth vector outline if one is already on the machine. A disk search
on 2026-09-23 (home directory, /Applications, Homebrew, R and TeX libraries, npm cache, both data
disks) found none. The only Natural Earth product on disk is MATLAB's raster tile set
`toolbox/matlab/maps/mapdata/maptiles/NaturalEarth`; the folder's `copyright.txt` (one level up, at
`toolbox/matlab/maps/mapdata/copyright.txt`; path corrected 2026-09-23; sha256
`ab413c48f1650e6117b9cf4d4cb11db44d0ae147ae3c3b97b1addb2e175a8018`) reads "Copyright 2017 The
MathWorks, Inc. Modified from Natural Earth datasets", so those tiles are a MathWorks work, not
public domain, and are not used. Swapping in Natural Earth `ne_110m_land` later (public domain)
needs a small GeoJSON reader in the generator and a new pin; nothing else changes.

(2026-10-01: done, with the 1:50m file instead of 1:110m — section "Natural Earth" above. The
GeoJSON reader is in `analysis/paper/fig_star_origins_dots.py`.)

## Integrity

`MANIFEST.sha256` pins this README, the mask and the Natural Earth file; `fig_star_origins.py` also
pins the sha256 of both data files and refuses to run on a changed file. Re-running
`tools/basemap_etopo5_mask_2026-10.py` rewrites the manifest with only the mask and this README;
run `setup/.venv/bin/python tools/write_manifest.py data/paper_inputs/basemap` afterwards to list
all three files again.
