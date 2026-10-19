# `pipeline/stars/` — star screening and the event gates

This is the layer that decides the paper's treatment. It answers two questions — *who counts as a
star* and *which arrivals count as events* — and every number downstream inherits its answers. The
port is byte-for-byte (see `tests/test_verbatim_pipeline.py`); nothing here was rewritten, tidied,
or "fixed", including the three inconsistencies recorded under **Findings** below.

Run it through the launcher, never in place:

```
python3 pipeline/stars/run_stars.py --list
python3 pipeline/stars/run_stars.py events-chemmath       # <1 s    — 67 candidates -> the 24 events
python3 pipeline/stars/run_stars.py events-econ           # <1 s    — 67 candidates -> the 38 events
python3 pipeline/stars/run_stars.py u4aug                 # 0.4 s   — 79 + 38 = 117
python3 pipeline/stars/run_stars.py restake  --execute    # 2.3-2.8 min — needs the data disk
python3 pipeline/stars/run_stars.py suspects --execute    # 3.1-3.6 min — needs the data disk
```

Runtimes are the range across independent runs on the author's machine (`restake` 136.5 s and
167.3 s; `suspects` 185 s and 214.8 s), and they are cross-pinned to `run_stars.py`'s `minutes`
field by a test so the two files cannot drift apart. The original 2026-08-15 `suspects` run took
about the same: `60`'s mtime 21:31:07 to the last suspect CSV at 21:34:13.

A ported script executed where it sits refuses at import (`pipeline/lib/paths.py`). `$SAR_OUT_ROOT`
moves the scratch root and must be an absolute, **empty** directory; without it the scratch root is
`<repo>/output/stars`, which the launcher clears first.

> **Point `$SAR_OUT_ROOT` at a local, non-synced disk for `restake` and `suspects`.** Both spill
> DuckDB temporaries into `<run dir>/data/_duck_tmp` for minutes. One review run on the default
> scratch root died at year 15 of 19 with `IO Error: Failed to create directory … /_duck_tmp: No
> such file or directory` — an ENOENT, the parent having gone out from under it — after 50 s; the
> same stage completed and reproduced byte-identically with `$SAR_OUT_ROOT` under `/private/tmp`.
> On the author's machine the repository sat inside a cloud-synced folder. Causation is not
> proven, but a multi-minute spill directory inside a synced folder is a real hazard and the
> failure is consistent with it.

---

## The four gates, verified against the code that runs

All four are evaluated at **Y = arrival_year − 1**. Each claim below names the file and line in this
directory that implements it; every one was read against the ported bytes, not against a summary.

### Gate ① citation stock, top 10 %

`multidisc_2026-07-24/code/star_screening/run_screening.py` `_POOL_SQL` builds the pool:

* `agg0` — **raw** `cited_by_count`, full counting, summed over every work with
  `publication_year <= Y`. Not FWCI, not fractional, not score-weighted.
* `sf_modal` — the person's **modal subfield** (`ROW_NUMBER() … ORDER BY n DESC, sf`, rank 1).
* the cell — `RANK() OVER (PARTITION BY subfield, age_bin ORDER BY stock DESC)` and
  `COUNT(*) OVER (PARTITION BY subfield, age_bin)`. `RANK()` is a competition rank, so ties enter or
  leave the decile as a block. The pool is the **whole snapshot population**, not the rostered
  candidates.

and the cut itself, `multidisc_gold_2026-08-10/code/60_poach_gate_false_negatives.py:88,92`:

```python
pct = 1 - rnk / cn
"pass_p10": (pct >= 0.90 and cn >= 30 and aage >= 2),
```

`cell_n >= 30` is `screening_lib.CELL_MIN_N["floor"]`; there is **no signed `pct_10` cell-size
gate** (`CELL_MIN_N` has `pct_1` and `pct_5` only), which `screening_lib.py` records as unsigned
decision **D2**. Economics forces `subfield = '2002'` and re-ranks inside that cell
(`60_…py:76-83`), keeping the deliberate off-by-one — the candidate is added to his own cell:
`(SELECT count(*) FROM cell c WHERE c.age_bin = me.age_bin) + 1`. Chemistry and math-stats use the
candidate's own modal subfield (decision **D1**).

### Gate ② seniority

`aage >= 2`, i.e. `screening_lib.MIN_ACADEMIC_AGE = 2`, where `aage = Y − robust_first_pub` and
`robust_first_pub` is the `rfp` CTE: leading papers separated from the rest of the career by more
than `ROBUST_FIRST_PUB_MAX_GAP = 10` years are dropped, so a mis-merged same-name work cannot
inflate academic age.

### Gate ③ pure foreign poach — the gate the address back-fill broke

`run_screening.foreign_prescreen` (docstring plus the `win` CTE):

> any AU affiliation in `[arr−3, arr−1]` → **not** a foreign poach.

Implemented as `COUNT(*) FILTER (WHERE i.country_code = 'AU') n_au` over
`authorship_edges ⋈ works_affil ⋈ institutions` restricted to
`e.publication_year BETWEEN c.arr-3 AND c.arr-1`, then `if n_au and n_au > 0: (False, "")`. With no
affiliation rows at all in the window the prescreen passes conservatively, with a note.

**Why it broke.** OpenAlex back-fills an author's *current* institution onto their old works, so a
scholar who moved to Australia in 2019 carries an Australian address on 2016–2018 papers, `n_au > 0`
fires, and a genuine overseas hire is dropped. `60_…py`'s header states it on the named case
(A5086383420, Monash 2019: 99.86th percentile, past gate ②, still dropped).

**The repair, and the 62 events it added.** `60` re-runs gates ①② over every rostered person and
lists everyone who passes but is not in the event table (**264 econ / 266 chemistry / 141
math-stats**); `61_poach_fn_prescreen_v2.py` re-classifies each suspect from the *raw byline
strings* rather than the normalised institution ids (`rule()` at `61_…py:45-49`, golden cases
A5086383420 = CHECK, Zénou = CHECK, A5103238089 = drop) leaving **192 CHECK**; two human rounds adjudicate
them; `72_restake_fnfix_stars.py` re-ranks the survivors on the human-verified true arrival year
(**67 rows, 63 pass / 4 fail**); and the rebuild adds **econ 79 → 117 (+38)**, **chemistry 22 → 35
(+13)**, **math-stats 20 → 31 (+11)** — **62 events**.

### Gate ④ — and a numbering collision, kept

The four-gate list ends with *"arrival year is verifiable"*. A **different** rule is also
labelled gate 4 in the frame builders (`10_build_union_frame_gold.py`, `00_build_frame_econ920.py`):
*the star does not count as an incumbent before the star's own arrival year*. Same numeral, two rules, two
layers — screening versus frame construction. Neither is changed; this note is the
disambiguation.

---

## Findings — the code disagrees with itself in three places (reported, not fixed)

M3's rule is that a legacy defect is reported, never repaired. All three below were found by reading
the ported bytes and confirmed against the frozen artifacts.

**F1 (material). `72_restake_fnfix_stars.py`'s `pass_p10` omits gate ②.** Line 78 reads

```python
"pass_p10": (pct >= 1 - L.P10) and cn >= L.CELL_MIN_N["floor"],
```

— percentile and cell size, no `aage >= 2`, where `60_…py:92` and
`screening_lib.star_pass_flags` (which returns `False` for *every* percentile when the age gate
fails) both include it. It is not hypothetical: in the frozen
`fnfix_restake_2026-08-15.csv`, **A5044432173 (Melbourne, arrival 2006) has
`aage = 0`, `after_cell = "2002|0"` and `after_pass = True`**. The per-paper identity work moved the star's
stock from 342 to 274 and the robust first-publication year forward, pushing the star out of the `2-5`
age bin and below the signed seniority gate — and the re-stake's flag did not notice. She is one of
the 38 econ fn-fix additions, so the star is in the signed 117, admitted through a gate check that does
not test gate ②. `00_make_u4_aug.py` gates only on `after_pass == "True"` and then writes
`"age_eligible": True` for the synthesised row. It is the only such case among the 67 re-stake rows
and among the 38 additions.

Three further pieces of evidence, each of which makes the finding harder to wave away:

* **The frozen artifact records the contradiction.** In `u4_aug/star_set/star_set.parquet` this is
  the only row of 277 with `academic_age = 0 AND age_eligible = True`, and the only one with
  `is_star_1pct AND academic_age < 2`. The comment three lines above the code that writes it lists
  the caliber it believes it is applying — including **academic age ≥ 2**. The code and its own comment
  disagree.
* **The human evidence file dates the PhD to the arrival year.** `verify/fnfix_adjudication_econ.csv`
  and `fnfix_candidates_restake.csv` (private archive) record a PhD completed in **2006** and an
  entry-level post at arrival. The human round did not find a senior hire; it found a fresh PhD.
* **The same gate was used to exclude other people.** An earlier batch dropped **A5045410390**
  on the seniority gate (age < 2), the same gate that had earlier removed A5020228087. The
  gate that removed those two is the one that failed to remove A5044432173.

**Consequence if the gate were applied consistently** (stated so the author can weigh it, NOT acted
on here): re-stake passers 63 → 62, econ new events 38 → 37, econ signed events **117 → 116**,
chemistry 35 and math-stats 31 unchanged, and the Panel-3 `A_far` cell 87 → 86 events /
23,831 → 23,830 pairs. Every printed count in the paper that cites 117 or 62 would move; the
estimate itself would barely. **Whether an exception to the signed seniority gate is granted is the
author's decision, not the repository's** — M3 reports it and changes nothing.

**F2 (latent). `72` rounds before comparing, `60` does not.** `72_…py:74` computes
`pct = round(1 - rnk / cn, 4)` and then tests `pct >= 1 - L.P10`; `60_…py:88,92` tests the unrounded
value. A candidate at `pct = 0.899951` passes in `72` and fails in `60`. Measured: no row of the 67
lies within 0.001 of the cut, so nothing turns on it today.

**F3 (latent). Three implementations of one cut.** `screening_lib.star_pass_flags` decides with
exact integer arithmetic (`Fraction(rank, cell_n) <= Fraction("0.10")`) and returns three states
(`False` on the age gate, `None` on a thin cell, otherwise the comparison); `60` and `72` both use
floats and two states. Same cut in exact arithmetic, different failure semantics.

---

## Provenance: which version of `00_make_u4_aug.py` produced the frozen `u4_aug/`

The recon report flagged this file because its mtime (2026-08-16 04:09:38) is **later** than the
`u4_aug/{events,star_set}` parquets it wrote (03:05:18), so the file on disk was not provably the
file that ran. mtime is an edit time and settles nothing — the same trap T5 fell into — so it was
settled from the record of the authoring instead.

The author's recorded command history (private) holds the file's complete history, three
operations:

| when (UTC / local AEST) | what |
|---|---|
| `2026-08-15T12:06:34Z` / 22:06:34 | file write, 3,642 chars — the first version |
| `2026-08-15T13:04:49Z` / 23:04:49 | in-place shell patch, 3 literal replacements — adds the `RESTAKE` gate, the synthesise/re-light branch, and the explanatory comment |
| — | **the run**: `logs/00_u4aug.log` + both parquets, 2026-08-16 03:05:18 local |
| `2026-08-15T18:09:38Z` / 04:09:38 | in-place shell patch, **1 literal replacement** |

Replaying all three (reading the shell patches with `ast`, never executing them) reproduces the
file on disk **byte for byte**, sha256 `84cfd6a5…f00fe` — so the disk file's whole history is
accounted for and no unrecorded edit exists. The producing version is the state after patch 2,
sha256 `e6faeeb6…085d99`, and it differs from the disk file by exactly one line:

```python
cfg["supplement_jsonl"] = f"{BASE}/data/edges_supplement_fnfix.jsonl"   # 星侧补数边（须先抓好；01_merge 会抓）
```

**Ruling: port the file on disk.** Three reasons, none of which is mtime:

1. The added line sits *after* both `pq.write_table(...)` calls and mutates only the `cfg` dict, so
   it cannot change either parquet — and the rerun confirms it: both are content-EQUAL to the
   frozen copies.
2. **The recorded command says so in its own words.** The patch is introduced in the recorded command by
   the comment `# make 00_make_u4_aug also write supplement into the config (so a from-scratch run next time does it too)`.
   That is direct authorial intent that the edited file be the producer going forward, and it is the
   strongest evidence available. (A weaker corollary: the producing version would emit a config
   **missing** that key, while the disk version emits the key set the frozen config actually has —
   though the frozen config has the key only because the same command also added it by hand.)
3. Recon's guess — "the post-hoc edit was almost certainly the explanatory comment at lines 43–45" —
   is **falsified**: that comment arrived in patch 2, before the run.

**Reconciling this with M1's opposite ruling.** M1 faced the same shape in `run_p3_tp.R` and chose
the *earlier* copy (`aws/`) over the later-patched one in `code/`. The rulings are not inconsistent,
and the difference is the only thing that matters: there the post-run patch **changed what the
script produces**, so the file on disk could not have made the frozen artifact; here the post-run
patch provably **cannot** touch either output — it adds one line after both `pq.write_table` calls
that mutates only the config dict, and the re-run confirms both parquets byte-identical. When the
edit changes the artifact, port the version that ran; when it demonstrably cannot, port the version
the author left in place.

The same command also appended a label suffix to the frozen config by hand
(`c['label'] += "; network-side star edges = SSD 11school edges ∪ new-star API supplement edges (same gold chain)"`). No script writes
it, so a rerun cannot produce it; see the comparison table below.

**The other ten ported files.** No competing copy of any of them exists in either legacy tree, and
each precedes its own outputs: `star_screening/{run_screening,screening_lib}.py` (2026-07-24 21:12 /
21:05) are the shared ranking machine `60`/`72` import; `60` (08-15 21:31:07) precedes its three
suspect CSVs (21:32–21:34); `61` (21:42) precedes `poach_fn_prescreen_v2_2026-08-15.csv`; `72`
(23:05:05) precedes `fnfix_restake_2026-08-15.csv` (08-16 02:04:39); `71/73/74/75/76` are thin
parsers around the human rounds. `70_prep_fnfix_inputs.py` belongs to this chain but was already
ported in Task 5 and lives in `pipeline/rosters/`; it is not duplicated here.

---

## What was re-run, and what came back

| stage | artifact | mode | rows | verdict | runtime |
|---|---|---|---|---|---|
| `events-chemmath` | `data/fnfix_new_events.csv` | bytes | 24 (13 chem + 11 math) | **EQUAL, byte-identical** | <1 s |
| `events-chemmath` | `data/fnfix_new_events_wide_extra.csv` | bytes | 1 | **EQUAL, byte-identical** | — |
| `events-econ` | `data/new_events_econ.csv` | bytes | 38 | **EQUAL, byte-identical** vs legacy AND vs `data/raw_verified/events_econ_new38.csv` | <1 s |
| `u4aug` | `u4_aug/events/data.parquet` | content | 38 / 38 | **EQUAL** — and in fact byte-identical (`a935af71…`) | 0.4 s |
| `u4aug` | `u4_aug/star_set/star_set.parquet` | content | 277 / 277 | **EQUAL** — and in fact byte-identical (`b8a73d89…`) | — |
| `u4aug` | `config/econ_fnfix.json` | bytes | — | **NOT EQUAL — accounted for**, below | — |
| `restake` | `data/fnfix_restake_2026-08-15.csv` | bytes | 67 | **EQUAL, byte-identical** (7,527 B, `f11031ea…dbe`) | 2.3–2.8 min |
| `suspects` | `data/poach_fn_suspects_{econ,math_stats}.csv` | bytes | 264 / 141 | **EQUAL, byte-identical** | 3.1–3.6 min |
| `suspects` | `data/poach_fn_suspects_chemistry.csv` | bytes | 266 | **NOT byte-equal — a permutation**, below | (same run) |

The two `u4aug` parquets are recorded as content-EQUAL because that is the criterion (deviation D1);
that they also came back byte-identical, in each of two independent runs, is an observation and not
the gate.

The `restake` result is the strongest statement this layer can make: the ported ranking machine,
running this repository's `_POOL_SQL` and `screening_lib` (the launcher pre-imports both and prints
which file each came from), reproduces the signed re-stake **byte for byte** — the same 63/4 split
and the same four failing percentiles (A5014621753 .8832, A5016651378 .8956, A5027126744 .8753, A5105845982 .8675).

### The `config/econ_fnfix.json` non-equality

Four keys differ. Three (`events`, `run_dir`, `supplement_jsonl`) differ **only** in the `BASE`
prefix — the staged run directory instead of the legacy one, with byte-identical sub-paths. The
fourth, `label`, differs by exactly the suffix the 2026-08-15T18:09:38Z command appended to the
frozen file **by hand**; no script writes it, so no re-run can produce it. The key SETS are
identical. It is a run-local pointer file, not a data artifact.

### The `suspects` non-equality — all three rosters, not just chemistry

`60_…py` builds its candidate list with `SELECT author_id, min(year_start), string_agg(DISTINCT
dept_key, ';') … GROUP BY 1` — **no `ORDER BY` anywhere**, neither on the group output nor inside the
aggregate. Measured by running that exact query six times per field on fresh connections:

| roster | rows | distinct row ORDERS in 6 runs | distinct `depts` CONTENTS in 6 runs |
|---|---|---|---|
| econ | 920 | **6** | 1 (no econ person has two `dept_key`s) |
| chemistry | 518 | **6** | **4** |
| math-stats | 573 | **6** | **4** |

So **all three suspect CSVs are order-nondeterministic, and chemistry and math-stats additionally
have order-nondeterministic `depts` strings.** A byte mismatch in any of the three is expected and is
*not* a port defect; econ and math-stats matching on a given run is luck, not a property. Do not
read the shape of one run as fixed either: across runs the chemistry difference has appeared both as
"5 rows differing only in `depts` order plus 4 transposed `pct` ties" and as "0 rows differing in any
field, a pure permutation at 5 tie positions". Invariant across every run: identical `author_id`
sets, identical multisets once the `;`-joined `depts` is sorted, and both files correctly sorted
descending by `pct`.

This is deviation D1 in a new place — byte-equality is unreachable because the producer never asked
for a deterministic order. The comparison was **not** relaxed: the CSV verdict stands as NOT EQUAL,
and the characterisation is what carries the evidence.

---

## The event-selection rung, recovered (T6 review BLOCKER-1)

`72` re-stakes 67 candidates; `00_make_u4_aug.py` consumes 38 econ events and
`70_prep_fnfix_inputs.py` consumes 24 chem/math events. **Nothing on disk turns the first into the
other two** — and that is the step where a human-confirmed candidate becomes an event. Both
selectors ran once as a heredoc inside a shell call and were never files anywhere, which is why
every on-disk search misses them and why the first pass of this task treated their outputs as given
inputs. Both were replayed from the author's recorded command history, declared in `RECOVERED`, and
re-run:

| recovered file | recorded op | replay sha256 | re-run vs frozen |
|---|---|---|---|
| `code/00_select_new_events_econ.py` | `2026-08-15T16:04:57.679Z` | `e12a1314…1d04a2` | `new_events_econ.csv` **byte-identical** |
| `code/00_select_new_events_chemmath.py` | `2026-08-15T12:51:58.422Z` | `49a5039f…f14ca8` (private original; the published file differs by one comment, see `HASH_CROSSWALK.md`) | `fnfix_new_events.csv` + `_wide_extra.csv` **byte-identical** |

Both basenames are this repository's choice; the originals had none. Both run with the working
directory set to the staged gold run directory, because that is where they ran (`cd "<gold>" &&
python3 - <<EOF`) and every path inside them but one is relative to it.

**Two substantive rules live only in these files, and nowhere else in the package.**

### (a) `in_window` is TWO rules, not one — and that asymmetry *is* the A5062352558 question

The selectors read a boolean column, `in_window`, off `fnfix_candidates_restake.csv`. That column is
not computed once. It is computed **per discipline, with different bounds AND a different column**,
in the recovered builders of that table:

| discipline | recorded op | the expression, exactly as the code has it |
|---|---|---|
| chemistry | `2026-08-15T12:31:37.988Z` | `inwin = 2005 <= int(c['arrival_roster']) <= 2023` |
| math-stats | `2026-08-15T12:37:31.739Z` | `inwin = 2005 <= int(c['arrival_roster']) <= 2023` |
| economics | `2026-08-15T12:46:25.282Z` | `"in_window": 1999 <= int(r['arrival_true']) <= 2024` |
| economics, the 5 late U4-flagged rows | `2026-08-15T16:02:54.597Z` | `"in_window": True` — **set literally, no test at all** |

Chemistry and math-stats bound the **roster** arrival year to **2005–2023**. Economics bounds the
**human-verified true** arrival year to **1999–2024** — a window 8 years wider at the bottom, on a
different column. And the last five economics rows are admitted with the flag hard-coded `True`.

**The worked example, from the frozen files:**

| person | field | `arrival_true` | `arrival_roster` | `in_window` | after the gates | one of the events? |
|---|---|---|---|---|---|---|
| **A5062352558** | chemistry | 2003 | 2003 | **False** | `after_pass True`, pct .9717 | **no** |
| **A5018518935** | econ | 2003 | 2003 | **True** | `after_pass True`, pct .9830 | **yes — one of the 38** |
| **A5006190609** | econ | 2003 | 2003 | **True** (literal) | `after_pass True`, pct .9731 | **yes — one of the 38** |

Three people with the same arrival year, 2003. Two are events; one is not. Nothing separates them
except which discipline's window their row was written by. Measured over the whole candidate table:
**all 14 chemistry candidates fall inside economics' window**, and A5062352558 is the only chemistry
candidate outside that field's own window; conversely 4 economics candidates fall outside chemistry's.

So the honest statement of this case is **not** "outside the analysis window". It is: *the
candidate is outside the window chemistry uses, and inside the one economics uses; under the
economics rule the candidate would be one of the events.* That asymmetry is the question, and it is what goes to the author.
**Neither window is changed here**, and neither is the literal `True`.

### A residual the write barrier cannot cover

Four of the recovered scripts — the three candidate-table rungs and the chem/math selector — hold
**no absolute path at all**: every input and output is relative to the working directory the heredoc
ran in. That is why they need no path hunk, and it is also why `refuse_unstaged_in_place_run()`
cannot attach to them: that guard fires from the resolver calls a ported script makes at import, and
these make none. The verbatim rule forbids adding a guard to a line that never held a path — that is
precisely the T5 smuggle shape — so this is documented and pinned rather than closed.

**What an in-place run of one of them actually does**, stated so the bound is checkable rather than
assumed: it reads `data/…csv` relative to *your* working directory. In a normal directory those do
not exist and you get `FileNotFoundError` before anything is written. In a directory that happens to
contain them, it writes its CSVs **into your working directory** — and that is the whole blast
radius. It can never reach a frozen artifact by way of a constant, because it has no constants: the
one path that could do that, rung 4's task-output file, is absolute, declared, and checked
separately. `tests/test_verbatim_pipeline.py` pins all of it — none of the four may acquire a
resolver, an `os.chdir`, or an `open()` on an absolute path without the test failing.

`run_stars.py` is the only supported entry point, and it is what sets the working directory.

### (b) A dead hard-coded person-level exclusion

The chem/math selector contains `borderline = aid=='A5016651378'  # A5016651378 SRF`, which would drop a
single person by id. The branch is unreachable: `if not ok: continue` fires first, and A5016651378 is
a math-stats candidate with `after_pass False` (.8956) — dropped as a re-stake failure,
never as "borderline". A hard-coded exclusion that never fires is exactly the kind of thing that must
be written down before someone re-runs the step believing it does. Reported; the line is not removed.

### The rung above: `fnfix_candidates_restake.csv` itself

The file that carries `in_window`, `arrival_true` and `arrival_roster` — the input `72` re-stakes on
and both selectors read — was **also never a file**. Four heredocs recorded the same day build it by
appending, in order: chemistry, math-stats, economics, and a fourth pass that records the nine
U4-flagged economics verdicts and appends the five confirmed ones. All four are ported under
`RECOVERED`, and **all four run** as `run_stars.py candidates`: the chain reproduces the frozen
67-row table **byte for byte**. (The first three alone give a byte-exact 62-row prefix; the fourth
adds the last five.)

The fourth rung **also runs**, and correcting that is the T6 final review's REOPEN-3. Its input is
an agent task output in a temporary directory the OS reclaimed, and Task 6 first registered it as a
lost input and the rung as un-runnable. That was wrong: the *file* is gone, the *content* is not. The
completion record of that task carried the whole result envelope inline and named the exact path, and
the envelope is frozen in this package as `data/stage_payloads/u4_star_events.json` (person-identifying
fields removed for the public copy). `run_stars.py` parses it **as data — nothing from the payload is
ever executed** — reconstructs the file at the path the ported script reads (parsed out of the
script's own source, so the two cannot drift; in the public copy that path is
`/private/tmp/removed-session-directory/tasks/u4_star_events.output`), runs the rung, and deletes it
again.

On the author's machine, with the unredacted payload, the full chain reproduces **all 67 rows byte
for byte** (sha256 `a1c6b34c…a8c1`), and the rung's other output,
`poach_fn_recheck_econ_U4flagged9_2026-08-16.csv` (9 rows: 5 confirmed / 3 fake_merged_id / 1
prior_AU), is byte-identical too. In the public copy the verdict records embedded in the rung and in
the frozen payload no longer carry names, posts, evidence URLs or free-text reasons, so those
free-text columns of the rebuilt CSVs are empty; `author_id`, `verdict` and `arrival_true` are
unchanged.

---

## The event arithmetic, checkable without any rerun

`data/raw_verified/event_ledger_econ79.csv` **79** + `data/raw_verified/events_econ_new38.csv`
**38** = `data/frames/p1_events_ledger_econ.csv` **117**; `events_chemistry_fnfix.csv` **35**;
`events_math_stats_fnfix.csv` **31**. Pinned in `tests/test_pipeline_rebuild.py`.

## What cannot be re-run

The human identity work, and the one destroyed input, are registered with their evidence in
`pipeline/NOT_REPRODUCIBLE.md`.
