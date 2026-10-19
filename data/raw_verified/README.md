# data/raw_verified

Verified human inputs: the department rosters (economics, chemistry,
math/stats), the arrival-event lists, the economics edge supplement, and the
economics relationships table.

**Event tables — two generations, both kept (2026-08-28 freeze).** The
CANONICAL event tables since the author-approved caliber correction are
`events_econ_cal2026-08-28.csv` (116), `events_chemistry_cal2026-08-28.csv`
(38) and `events_math_stats_cal2026-08-28.csv` (33) — byte copies of the signed
tables in `data/cal2026-08-28/` (authority: the author's decision record of 2026-08-28, private archive; diff vs the old set =
exactly {A5044432173 out; A5027778630, A5091826237, A5062352558, A5017222669, A5090916445 in}). The PRE-caliber
signed set — `events_econ_new38.csv` (38), `events_chemistry_fnfix.csv` (35),
`events_math_stats_fnfix.csv` (31), plus the original `event_ledger_econ79.csv`
(79) — is superseded 2026-08-28 but stays in place: it is the evidence base the
caliber layer (`pipeline/stars/caliber_2026-08-28/`) starts from, and several
recovered producers rebuild it byte-for-byte. These are frozen copies — byte-identical to the legacy source,
verified against `data/MANIFEST.sha256` — imported from the legacy
`v2_output/` trees `econ_roster_verify_2026-08-09/`,
`multidisc_roster_econ_grade_2026-08-09/`, `multidisc_gold_2026-08-10/`,
`econ_fnfix_2026-08-15/`, and `event_ledger_2026-07-27/` (see
`tools/import_frozen.py` for the exact per-file mapping). Rosters and events
were built with LLM-assisted, human-reviewed verification.

**Public copy.** Personal names, evidence URLs and free-text verification notes were removed
from this directory (and from the October roster additions in `data/cal2026-10/`) before
publication. The rosters keep `dept_key`, `school`, `author_id`,
`year_start`, `year_end`, `year_start_orig`, `year_end_orig`, `year_corrected`, `confidence`,
`human_verified` and `verify_source` (the chemistry/math-stats roster also keeps the structural
columns `field`, `rank_tag` and `event_keys`, the last now holding event ids
`<author_id>:<school>`); the event tables keep identifiers, schools, years and verdict codes.
No estimate reads a removed column. `verify_source` takes only these codes:

| code | meaning |
|---|---|
| `human_batch_2026-08-09` | verified by a person in the 2026-08-09 economics roster batch |
| `human_prior_not_rechecked` | verified by a person in an earlier round; not re-checked in 2026-08-09 |
| `human_batch_2026-08-10` | verified by a person in the 2026-08-10 chemistry / math-stats batches |
| `llm_two_round_2026-09-13` | two-round LLM check of 2026-09-13 with the author's rulings of 2026-09-22 (October roster additions) |
| `collected_2026-10` | added from the 2026-10 staff-list collection (archived department pages and handbooks), with checked OpenAlex ids; not checked by a person (human_verified is false) |

The verification originals (names, evidence links, notes) are held back for a planned
restricted-access deposit. OpenAlex author ids are public, so these files are de-named, not
anonymous.

The report's canon (`data/report/`) carries `roster_chemmath_verified.parquet` from this directory
unchanged as `raw_verified/roster_chemmath_verified.parquet`; its economics roster additions use
the code `collected_2026-10`.

**What "cannot be regenerated" does and does not mean here (corrected by M3 Task 5).** The human
VERDICTS cannot be regenerated — 840 economics and 2,593 chemistry/math-stats judgements, each a
person reading a staff page, an ORCID employment record or a Wayback capture. The *rosters built
from them* can: `pipeline/rosters/run_rosters.py` re-runs the producer of all four files in this
directory and `tools/content_equal.py` reports EQUAL for every one (the two merges are byte-identical
as well). Two of those producers had to be recovered from the author's working records; see
`pipeline/rosters/README.md`, which labels that provenance explicitly. The rebuilds read the human
evidence out of the read-only legacy tree, which this repository does not ship — so a
package-only replicator checks these files by sha256 and by their internal distributions, not by
re-running. (The EQUAL checks refer to the private originals; the public copies differ
from them only by the removed columns.)

`incfel/` holds the middle rung of the chemistry/math-stats population ladder
(`include ∪ fellow-level`, 396 and 552 rows) — the input to the stage that produces
`roster_gold_*.parquet`. It is frozen for inspection and is also rebuilt by
`run_rosters.py incfel`.

Deferred to M3 (`pipeline/stars`): the star set and the exclusion list are not yet
imported.
