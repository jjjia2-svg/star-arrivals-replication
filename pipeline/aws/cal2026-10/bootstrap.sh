#!/bin/bash
# pipeline/aws/cal2026-10/bootstrap.sh — instance environment for the October (cal2026-10) batch.
# The 2026-08-28 recipe (data/cal2026-08-28/cloud/bootstrap.sh: r2u CRAN binaries + rustup source
# build of R polars, versions.txt, memory sentinel) with two additions, both written down:
#   * r-cran-fixest — analysis/robustness/null_sim/run_null.R needs fixest (A7 in cloudkit.py: the
#     08-30 bootstrap.log is apt -qq quiet and does not show how it was installed; r2u ships every
#     CRAN package as an Ubuntu binary, so the apt name is the assumption and PKG_OK asserts it);
#   * every log this script writes goes under ~/work (created here) so ONE tar of ~/work fetches
#     bootstrap.log, versions.txt and mem.log together with the results (08-28 kept them in ~).
# Launched by run_cloud.sh as `nohup bash bootstrap.sh > work/bootstrap.log 2>&1 < /dev/null &`
# and polled for work/bootstrap_ready.txt — the 08-28 watcher hung because the memory sentinel
# kept the ssh session's stdout open; detaching stdin/stdout/stderr avoids that.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
mkdir -p "$HOME/work"
sudo apt-get update -qq
sudo apt-get install -y -qq wget ca-certificates curl build-essential time >/dev/null
wget -qO- https://raw.githubusercontent.com/eddelbuettel/r2u/master/inst/scripts/add_cranapt_noble.sh | sudo bash
sudo apt-get install -y -qq r-cran-data.table r-cran-didmultiplegtdyn r-cran-jsonlite r-cran-fixest >/dev/null
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal >/dev/null
source "$HOME/.cargo/env"
export R_LIBS_USER="$HOME/Rlib"; mkdir -p "$R_LIBS_USER"
echo "R_LIBS_USER=$HOME/Rlib" >> ~/.Renviron
Rscript -e 'install.packages("polars", repos="https://rpolars.r-universe.dev", lib=Sys.getenv("R_LIBS_USER"))'
Rscript -e 'library(polars); library(DIDmultiplegtDYN); library(data.table); library(jsonlite); library(fixest); cat("PKG_OK\n")'
{ Rscript -e 'cat("R", as.character(getRversion()), "DIDmultiplegtDYN", as.character(packageVersion("DIDmultiplegtDYN")), "polars", as.character(packageVersion("polars")), "data.table", as.character(packageVersion("data.table")), "jsonlite", as.character(packageVersion("jsonlite")), "fixest", as.character(packageVersion("fixest")), "\n")'; apt-cache policy r-cran-didmultiplegtdyn | sed -n 1,3p; apt-cache policy r-cran-fixest | sed -n 1,3p; uname -a; } > "$HOME/work/versions.txt"
cat "$HOME/work/versions.txt"

# memory sentinel (M1 recipe): `free -g` every 30 s, into the work dir so it is fetched with the rest
( while true; do echo "$(date -u +%FT%TZ) $(free -g | sed -n 2p)" >> "$HOME/work/mem.log"; sleep 30; done ) &
echo $! > "$HOME/work/mem_pid.txt"

# environment ready; the driver is triggered separately, after payload md5 verification
echo BOOTSTRAP_DONE | tee "$HOME/work/bootstrap_ready.txt"
