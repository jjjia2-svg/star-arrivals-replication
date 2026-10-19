#!/usr/bin/env Rscript
# R1 V3-ENV: install one R stack into a library (ruling R6). Args: <layer rmac|rcloud> <lib> <p3m url> <repo dir>
a <- commandArgs(trailingOnly = TRUE); layer <- a[1]; lib <- a[2]; p3m <- a[3]; repo <- a[4]
.libPaths(c(lib, .libPaths())); options(repos = c(CRAN = p3m), Ncpus = parallel::detectCores())
Sys.setenv(NOT_CRAN = "true", LIBR_POLARS_BUILD = "true")          # build polars from source with cargo
exp <- read.table(file.path(repo, "config/r1/expected_versions.txt"), sep = "\t", comment.char = "#",
                  col.names = c("layer", "name", "version"), stringsAsFactors = FALSE, quote = "")
want <- exp[exp$layer == layer & exp$name != "R", ]
lock <- jsonlite::fromJSON(file.path(repo, "setup/renv.lock"))$Packages
polars_sha <- lock$polars$RemoteSha
if (layer == "rmac") {
  install.packages("renv", lib = lib)
  renv::restore(lockfile = file.path(repo, "setup/renv.lock"), library = lib, repos = c(CRAN = p3m), prompt = FALSE)
} else {
  install.packages("remotes", lib = lib)
  for (i in seq_len(nrow(want))) if (want$name[i] != "polars")
    remotes::install_version(want$name[i], version = want$version[i], lib = lib, upgrade = "never", repos = p3m)
  remotes::install_github(paste0("pola-rs/r-polars@", polars_sha), lib = lib, upgrade = "never")
}
got <- vapply(want$name, function(p) tryCatch(as.character(packageVersion(p, lib.loc = lib)), error = function(e) "MISSING"), "")
bad <- want$name[got != want$version]
for (p in bad) cat("UNPINNABLE", layer, p, "want", want$version[want$name == p], "got", got[[p]], "\n")
quit(status = if (length(bad)) 1 else 0)
