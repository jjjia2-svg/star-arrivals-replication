#!/usr/bin/env Rscript
# Install the R packages at the versions recorded in setup/R_VERSIONS.txt (measured on the results machine).
# DIDmultiplegtDYN 2.3.3 is installed from the vendored tarball (CRAN now ships 2.4.0, untested here).
# polars (R) comes from r-universe (not CRAN): the recorded version is a development build; install from the
# r-universe repo and check the version printed at the end against setup/R_VERSIONS.txt.
repos <- c(CRAN = "https://cloud.r-project.org")
want <- read.table("setup/R_VERSIONS.txt", sep = "=", strip.white = TRUE, col.names = c("pkg", "eq", "ver"), stringsAsFactors = FALSE)
want <- setNames(want$ver, want$pkg)
if (!requireNamespace("remotes", quietly = TRUE)) install.packages("remotes", repos = repos)
for (p in c("data.table", "jsonlite", "fixest", "yaml")) {
  if (!requireNamespace(p, quietly = TRUE) || as.character(packageVersion(p)) != want[[p]])
    remotes::install_version(p, version = want[[p]], repos = repos, upgrade = "never")
}
if (!requireNamespace("polars", quietly = TRUE))
  install.packages("polars", repos = c("https://community.r-multiverse.org", "https://rpolars.r-universe.dev", repos))
if (!requireNamespace("DIDmultiplegtDYN", quietly = TRUE) || as.character(packageVersion("DIDmultiplegtDYN")) != "2.3.3")
  install.packages("setup/vendor/DIDmultiplegtDYN_2.3.3.tar.gz", repos = NULL, type = "source")
for (p in c("DIDmultiplegtDYN", "polars", "data.table", "jsonlite", "fixest", "yaml"))
  cat(sprintf("%-18s installed %-12s recorded %s\n", p, as.character(packageVersion(p)), want[[p]]))
