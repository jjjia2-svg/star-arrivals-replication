# Single source of truth for locations (R side). Usage: source("analysis/lib/paths.R"); p <- sar_paths()
#
# Deviation from the original brief (documented per brief's own fallback clause): sys.frame(1)$ofile
# only resolves to this file's path while it is evaluated as top-level source() code; once wrapped
# inside a function and called later (after source() has returned), that frame is gone and the lookup
# returns NULL. So the path is captured HERE, at top level (i.e. at source() time), into
# .sar_paths_this_file, and sar_paths() below just reads that captured value instead of re-deriving it.
`%||%` <- function(a, b) if (is.null(a)) b else a
.sar_paths_this_file <- sys.frame(1)$ofile %||% "analysis/lib/paths.R"

sar_paths <- function() {
  this <- normalizePath(.sar_paths_this_file, mustWork = FALSE)
  root <- normalizePath(file.path(dirname(this), "..", ".."), mustWork = TRUE)
  # $SAR_PATHS_CONFIG names an alternative paths.yaml, exactly as analysis/lib/paths.py honours it
  # (M3 T8 review): "run this package the way a replicator would" has to be a switch, not a file edit.
  cfg <- Sys.getenv("SAR_PATHS_CONFIG", "")
  if (nzchar(cfg)) {
    if (!startsWith(cfg, "/")) stop("$SAR_PATHS_CONFIG must be an absolute path, got ", cfg)
    if (!file.exists(cfg)) stop("$SAR_PATHS_CONFIG names a file that does not exist: ", cfg)
  } else {
    cfg <- file.path(root, "config", "paths.yaml")
  }
  raw <- yaml::read_yaml(cfg)
  # `${VAR:-default}` -> $VAR if set and non-empty, else default (same rule as analysis/lib/paths.py)
  expand <- function(v) {
    m <- regmatches(v, regexec("\\$\\{([A-Za-z_][A-Za-z0-9_]*):-([^}]*)\\}", v))[[1]]
    while (length(m) == 3) {
      val <- trimws(Sys.getenv(m[2], ""))
      v <- sub(m[1], if (nzchar(val)) val else m[3], v, fixed = TRUE)
      m <- regmatches(v, regexec("\\$\\{([A-Za-z_][A-Za-z0-9_]*):-([^}]*)\\}", v))[[1]]
    }
    path.expand(v)
  }
  out <- lapply(raw, function(v) { v <- expand(as.character(v)); if (startsWith(v, "/")) v else normalizePath(file.path(root, v), mustWork = FALSE) })
  out$repo_root <- root
  out
}
