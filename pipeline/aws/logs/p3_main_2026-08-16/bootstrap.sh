#!/bin/bash
# bootstrap_dep.sh — R packages through r2u + polars built from source with rustup (the working recipe of frame_dept bootstrap3.sh)
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
Rscript -e 'library(polars); library(DIDmultiplegtDYN); library(data.table); library(jsonlite); cat("PKG_OK\n"); cat("lcse_arg:", "less_conservative_se" %in% names(formals(did_multiplegt_dyn)), "\n")'

# memory watchdog
( while true; do echo "$(date -u +%FT%TZ) $(free -g | sed -n 2p)" >> ~/mem.log; sleep 30; done ) &
echo $! > ~/mem_pid.txt

# environment ready; driver_dep.sh is started separately from the local side once the data md5 check passes
echo BOOTSTRAP_DONE | tee ~/bootstrap_ready.txt
