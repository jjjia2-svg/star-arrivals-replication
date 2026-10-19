# `pipeline/aws/` — the cloud steps, written down and never run

Two things in this project ran on rented hardware. Neither can run from this package, and neither
needs to: what they produced is frozen here with a chain of custody that checks in seconds.

| run | machine | when | billed | cost | what it produced |
|---|---|---|---|---|---|
| P3 main (`p3_main_2026-08-16`) | r6i.16xlarge, us-east-1 | 2026-08-15 18:15:52Z → 18:37:23Z | 21m31s | ≈ $1.50 | `P3_econ_fnfix`, `P3_fnfix_chemistry` |
| P3 event-cluster (`p3_evcl_2026-08-16`) | r6i.16xlarge, us-east-1 | 2026-08-16 09:09:51Z → 09:34:00Z | 24m09s | ≈ $1.60 | `P3evcl_econ`, `P3evcl_chemistry` |
| U1 snapshot fetch | i4i.4xlarge, us-east-1 | 2026-07-04 | 20.3 h | ≈ $30 | the 15.4 GB of narrow tables on the data disk |

The first two are `launch_p3_dcdh.sh`; the third is `launch_u1_fetch.sh`. **Both scripts print their
runbook and exit.** They contain no `aws` invocation that runs — the commands are inside a quoted
here-document, as text. That is deliberate: every line of them spends money on an account this
package knows nothing about, under a key and a security group only the operator has.

`pipeline/run_all.sh` cannot reach any of this under any flag.

## Why re-running is not what a replicator should do

**The four P3 cells.** The dCDH estimator materialises the whole panel; the measured peak for the
economics main cell was 289 GiB (304.9 GiB for the event-cluster variant), which is why a 512 GiB
machine was rented rather than preferred. What a rerun would establish is already established
without it:

```
python3 tools/verify_cloud_custody.py        ->  CUSTODY_OK
```

For each run that checks both ends of the wire. Every input shipped to the instance is byte-identical
to the frame this package ships (md5 against the `payload.md5` the instance itself verified before
starting), and every JSON fetched back equals the frozen estimate in `data/estimates/`. There is no
step in between that a rerun would expose and this does not.

**The U1 fetch.** 17 hours and about $30 to regenerate 15.4 GB of intermediate tables that live on
the data disk and are not part of this package at all. Its own manifests are frozen and pinned
(`data/fwci/scan_manifest.json`: 510,372,821 records, 2,446 shards, 0 bad lines, 0 shard mismatches),
and they are what the paper's funnel numbers are generated from.

## What is in `logs/`

Per run: `bootstrap.sh` (the environment recipe — r2u for the CRAN binaries, then a rustup source
build of R `polars`, because there is no binary), `driver.sh` (the cells in sequence under
`/usr/bin/time -v`, each with its own exit marker), `run_p3*.R` (the estimation script, md5-pinned in
`payload.md5`), `payload.md5`, `launch_time_utc.txt` / `terminate_time_utc.txt`, `watcher.log` (the
poll-and-fetch trail), and `fetch/` with the returned JSON, the console logs, `mem.log` and the full
`time -v` output.

Measured, from those `time -v` files:

| cell | wall clock | peak RSS |
|---|---|---|
| `P3_fnfix_chemistry` | 1:47 | 91.1 GiB |
| `P3_econ_fnfix` | 5:34 | 289.4 GiB |
| `P3evcl_chemistry` | 2:09 | 96.4 GiB |
| `P3evcl_econ` | 6:55 | 304.9 GiB |

No secrets are in these files. The instance IDs in `watcher.log` name machines that were terminated
in 2026; there are no keys and no account identifiers. In the public copy the public IPv4 addresses and
private host names of the October instances (in `data/cal2026-10/cloud*/`) are replaced by `<ip>` and
`<host>`; instance ids, the security-group id and the key-pair name are kept.

## The two rules the runbooks encode, because both were learned the hard way

**Salvage before terminate.** `watch_and_fetch.sh` pulls the results, the memory log, the `time -v`
output and the driver log back whatever the outcome — DONE, FAIL or TIMEOUT — and only then
terminates. An instance that dies with its logs on it teaches nothing.

**A hard shutdown fuse in user-data.** Every launch passes a two-line `userdata.txt`
(`#!/bin/bash` / `shutdown -h +600`), so a forgotten instance stops itself after ten hours. The
`terminate-instances` call is the plan; the fuse is what happens when the plan does not.
