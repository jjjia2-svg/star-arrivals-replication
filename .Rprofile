options(renv.config.synchronized.check = FALSE)  # external.libraries means renv's sync check always fires; suppress its stdout chatter
options(renv.config.external.libraries = .libPaths())  # keep this machine's pre-existing R libraries visible; machine-agnostic (no absolute path in tracked files); the project library is populated only by renv::restore (M5)
source("renv/activate.R")
