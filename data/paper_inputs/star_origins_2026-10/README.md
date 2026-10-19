# data/paper_inputs/star_origins_2026-10

Inputs of the star-origins world map (`analysis/paper/fig_star_origins.py`). No personal names:
stars appear only as OpenAlex author ids.

| File | Made by | What |
|---|---|---|
| `star_author_ids.csv` | `tools/star_origins_extract_2026-10.py` | the 184 stars' OpenAlex ids + the economics U2 fragments |
| `affiliation_years.csv` | same | author x institution x year from the offline snapshot, with U1 work counts |
| `institutions.csv` | same | name, country, type, city, coordinates of every institution used |
| `destinations.csv` | same | school -> hiring university |
| `extract_report.json` | same | counts, snapshot manifest hashes, 0 network requests |
| `human_origin_overrides.csv` | hand-curated 2026-09-23 | the human-verified origin of 89 events (below) |
| `MANIFEST.sha256` | the extract tool (it keeps this README and the override table in the list) | sha256 of every file here |

## human_origin_overrides.csv

Rule (2026-09-23): where a person has checked where a star came from, the map uses that; the
OpenAlex rule (generator docstring) covers the rest.

**Which events.** Every cal2026-10 event with a human record of the star's pre-arrival post: 89
events (59 economics, 17 chemistry, 13 mathematics and statistics). The records are the author's
verification notes, the verdict tables of the 2026-08 search for missed events and the 2026-09-22
star re-check; they name persons and are held back for the restricted-access deposit (not shipped).

**Alias ids.** A verdict file can list a star under another OpenAlex id than the event table; the
cross-check finds such a row by a unique match on field, name and arrival year. At cal2026-10 there
is one: chemistry event 12 is filed under `A5039408031`. The OpenAlex rule gives the same
institution as the record, so the drawn map does not change.

**Which post.** The post held just before arrival, read from the record. A visiting post is not a
post (the poach gate's rule), so one economics event keeps its home employer rather than a visiting
position abroad. Where two records cover one event they agree.

**Columns.** `discipline, event_row, star_id, school, arrival_year` identify the event (row of
`data/cal2026-10/events_{discipline}_cal2026-10.csv`; the generator stops if they do not match).
`placement`:

- `human_institution` (87) — the record names the institution; `institution_id` is its record in
  `institutions.csv` (all were already in the extract). Two named institutions have no record of
  their own in the snapshot: Harvard Medical School is filed under Harvard University (same
  metropolitan area), Schlumberger-Doll Research under Schlumberger (United States), which OpenAlex
  places in Houston; for that one event `coords_from` gives the snapshot record whose coordinates
  place the marker in Cambridge MA, the city the record names.
- `machine_institution_same_country` (1) — the record gives the country only; the OpenAlex rule's
  institution is in that country and is kept (`institution_id` empty).
- `country_main_city` (1) — the record gives the country only and the OpenAlex rule's institution
  is in another country; no institution is named and the marker goes to the country's main research
  city (the city with the most distinct institutions of that country in `institutions.csv`, ties
  alphabetical; point = median latitude and median longitude of those institutions).

`country_code` is the record's country. Public copy: the columns `human_evidence` (the post
restated in English) and `source_docs` (the records it comes from) were removed; no generator
reads them.

**Checks.** `tools/star_origins_crosscheck_2026-10.py` re-reads the records and verifies that every
event with a record has a row, that no row lacks a record, that each row's country is the record's
country and that the named institution appears in the record's text; it needs the records, which
are not shipped. `tests/test_star_origins_2026_10.py` checks the table's shape, counts and pins.
