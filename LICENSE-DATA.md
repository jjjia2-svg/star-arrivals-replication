# Data licence

**Scope.** The derived data in this repository: everything under `data/` and `analysis/expected/`,
except the third-party files listed in note 3. Code is licensed separately under the MIT License
(`LICENSE`).

**Licence.** Copyright 2026 Jia Jia. The derived data are licensed under the
[Creative Commons Attribution 4.0 International licence (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/).
You may share and adapt them for any purpose, provided you give appropriate credit (see
`CITATION.cff`), link to the licence and indicate if changes were made.

## Notes

1. **Upstream OpenAlex data are CC0.** The panels, benchmarks and author ids are derived from the
   OpenAlex snapshot released on 26 June 2026 and from OpenAlex API pages fetched on 13 August,
   23 September and 16 October 2026. OpenAlex (OurResearch) distributes both under CC0 1.0.
   CC BY 4.0 applies to the derivation (the rosters, event definitions, panels, estimates and
   benchmarks built for this project), not to the underlying OpenAlex records, which remain CC0.
2. **Department rosters.** The rosters were built from department staff pages archived by the
   Internet Archive (Wayback Machine) and the Australian Web Archive, university handbooks and
   annual reports, the Australian Mathematical Society Gazette, ORCID records and CVs. Those
   documents belong to their publishers and are **not** redistributed here. The published rosters
   contain only OpenAlex author ids, department and school codes, years and fixed codes.
3. **Third-party files, not covered by CC BY 4.0.** The Natural Earth land polygons
   (`ne_50m_land.geojson` under `paper_inputs/basemap/`) are public domain, and so is the NOAA
   ETOPO5 relief behind the 1-degree land mask next to them. The two Australian Bureau of Statistics
   figures in `paper_inputs/external_stats_2026-09-11.json` are quoted from the ABS release named in
   that file (CC BY 4.0, ABS).
4. **Not covered and not included.** Australian Research Council grant records, used only to
   cross-check a few arrival dates, are not part of this repository; the ARC website's own terms
   apply to them. The 15 GB OpenAlex extraction, the OpenAlex API pages and the verification
   originals are not part of this repository either. Contact the author to request access.
5. **Ids are de-named, not anonymous.** Names are removed, but an OpenAlex author id can be resolved
   to a name through the public OpenAlex API. Please do not use these data to single out or contact
   individuals.
6. **Third-party software** in `setup/vendor/` (the `DIDmultiplegtDYN` R package source) keeps its own
   licence and is not covered by this data licence (see `THIRD_PARTY.md`).
