#!/bin/bash
# bootstrap.sh — cal2026-08-28 T5: r2u CRAN binaries + rustup source build of R polars — the
# recipe of pipeline/aws/logs/p3_main_2026-08-16/bootstrap.sh verbatim, plus a versions.txt
# record (M1 gap: no version string was written to any cloud log; closed for the cal run).
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
sudo apt-get update -qq
sudo apt-get install -y -qq wget ca-certificates curl build-essential time >/dev/null
wget -qO- https://raw.githubusercontent.com/eddelbuettel/r2u/master/inst/scripts/add_cranapt_noble.sh | sudo bash
sudo apt-get install -y -qq r-cran-data.table r-cran-didmultiplegtdyn r-cran-jsonlite >/dev/null
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal >/dev/null
source "$HOME/.cargo/env"
export R_LIBS_USER="$HOME/Rlib"; mkdir -p "$R_LIBS_USER"
echo "R_LIBS_USER=$HOME/Rlib" >> ~/.Renviron
Rscript -e 'install.packages("polars", repos="https://rpolars.r-universe.dev", lib=Sys.getenv("R_LIBS_USER"))'
Rscript -e 'library(polars); library(DIDmultiplegtDYN); library(data.table); library(jsonlite); cat("PKG_OK\n")'
{ Rscript -e 'cat("R", as.character(getRversion()), "DIDmultiplegtDYN", as.character(packageVersion("DIDmultiplegtDYN")), "polars", as.character(packageVersion("polars")), "data.table", as.character(packageVersion("data.table")), "jsonlite", as.character(packageVersion("jsonlite")), "\n")'; apt-cache policy r-cran-didmultiplegtdyn | sed -n 1,3p; uname -a; } > ~/versions.txt
cat ~/versions.txt

# memory sentinel (M1 recipe)
( while true; do echo "$(date -u +%FT%TZ) $(free -g | sed -n 2p)" >> ~/mem.log; sleep 30; done ) &
echo $! > ~/mem_pid.txt

# environment ready; the driver is triggered separately, after payload md5 verification
echo BOOTSTRAP_DONE | tee ~/bootstrap_ready.txt
