#!/usr/bin/env Rscript
# analysis/robustness/null_sim/run_null.R — REPO-AUTHORED, 2026-08-30.
#
# SLICE-AWARE no-effect simulation. The simulation itself is
# v2_output/p3_topicpair_2026-08-17/code/B0_null_test.R (2026-08-17): build a world with NO
# arrival effect that keeps only two real features of the panel, (1) the first-tie hazard varies
# with the age of the pair, so the risk set depletes on its own, and (2) the hazard varies with
# the calendar year, then run the paper's estimator on it. If the estimator returns something
# like the real number in a world where the star does nothing, the real number is an artefact of
# the design rather than an effect of the star.
#
# WHAT IS COPIED AND WHAT IS NEW. The hazard model, the exit-at-first-tie rule, the three
# estimates and the panel skeleton are line-for-line the 2026-08-17 script's. Two things are new:
#
#   1. SEEDING. The original called set.seed() once for the whole run, so simulation s depended
#      on how many simulations ran before it and the run could not be split. Here EVERY
#      simulation seeds itself, set.seed(seed_base + s), so simulation s is the same draw whether
#      it is computed alone, in a slice of ten, or in a serial run of two hundred. This makes the
#      result slice-invariant, which is what lets it run in parallel; it also means the numbers
#      are NOT bit-identical to a serial run of the 2026-08-17 script, and are not meant to be.
#      The 2026-08-17 run was nsim=3 on a population two calibrations old.
#   2. OUTPUT. One CSV row per simulation instead of one JSON per run, so slices merge by
#      concatenation. merge_null.py folds the slices into the JSON the paper ledger reads.
#
# The estimated hazard (fepois on age + year cells) uses no RNG and is refitted identically in
# every slice, so slices agree on it by construction.
#
# NOTE ON DIRECTION. Risk-set depletion removes the pairs most likely to collaborate first, which
# biases the estimate DOWNWARD. This simulation can therefore explain a negative estimate; it
# cannot manufacture a positive one.
#
# Usage:  Rscript run_null.R <label> <panel.parquet> <seed_base> <from> <to> [outdir]
#         writes <outdir>/<label>_null_<from>_<to>.csv
suppressMessages({ library(polars); library(data.table); library(fixest)
                   library(DIDmultiplegtDYN); library(jsonlite) })

a <- commandArgs(trailingOnly = TRUE)
lab <- a[1]; fn <- a[2]
seed_base <- as.integer(a[3]); s_from <- as.integer(a[4]); s_to <- as.integer(a[5])
OUT <- if (length(a) >= 6) a[6] else Sys.getenv("SAR_OUT", "out_null")
stopifnot(!is.na(seed_base), !is.na(s_from), !is.na(s_to), s_from <= s_to, s_from >= 1L)
dir.create(OUT, showWarnings = FALSE, recursive = TRUE)

d <- as.data.table(as.data.frame(pl$read_parquet(fn)))
d[, arrival := min(year[D == 1]), by = ev]
d[is.infinite(arrival), arrival := NA_integer_]
d <- d[!is.na(arrival)]
d[, tau := year - arrival][, age := tau + 6L]        # age = 0 on entry to the risk set

# ---- 1. the age x calendar-year multiplicative hazard, from the real panel, no treatment term ----
cells <- d[, .(n = .N, ties = sum(y)), by = .(age, year)]
fit <- fepois(ties ~ 1 | age + year, data = cells, offset = ~log(n))
cells[, h_hat := pmin(pmax(predict(fit, newdata = cells) / n, 1e-8), 0.9)]
setkey(cells, age, year)

sim_one <- function() {
  sk <- d[, .(grp, ev, year, age, D)]
  sk <- merge(sk, cells[, .(age, year, h_hat)], by = c("age", "year"), all.x = TRUE)
  sk[is.na(h_hat), h_hat := 0]
  sk[, u := runif(.N)][, hit := as.integer(u < h_hat)]
  setorder(sk, grp, year)
  sk[, firsthit := cumsum(hit), by = grp]
  keep <- sk[firsthit == 0 | (firsthit == 1 & hit == 1)]      # exit at first tie
  keep[, ysim := hit]
  keep[, .(grp, ev, year, y = ysim, D)]
}

f_out <- file.path(OUT, sprintf("%s_null_%d_%d.csv", lab, s_from, s_to))
rows <- list()
for (s in seq(s_from, s_to)) {
  set.seed(seed_base + s)                                     # slice-invariant: see header
  sim <- sim_one()
  m_b <- tryCatch(feglm(y ~ D | year, data = sim, family = binomial("cloglog"), cluster = ~grp),
                  error = function(e) NULL)
  m_a <- tryCatch(feglm(y ~ D | ev + year, data = sim, family = binomial("cloglog"), cluster = ~grp),
                  error = function(e) NULL)
  dd <- tryCatch(did_multiplegt_dyn(df = as.data.frame(sim[, .(grp, year, y, D)]), outcome = "y",
                   group = "grp", time = "year", treatment = "D", effects = 5, placebo = 4,
                   graph_off = TRUE), error = function(e) NULL)
  r <- data.table(label = lab, sim = s, seed = seed_base + s,
                  ratio_yearFE   = if (!is.null(m_b)) exp(coef(m_b)["D"]) else NA_real_,
                  ratio_evyearFE = if (!is.null(m_a)) exp(coef(m_a)["D"]) else NA_real_,
                  dcdh_ate_pp = if (!is.null(dd)) 100 * as.data.frame(dd$results$ATE)[1, "Estimate"]
                                else NA_real_,
                  ties = sum(sim$y), rows = nrow(sim))
  rows[[length(rows) + 1]] <- r
  fwrite(rbindlist(rows), f_out)                              # checkpoint every simulation
  cat(sprintf("  [sim %d] ratio(yearFE) %.3f | (ev+yearFE) %.3f | dCDH %+.4f pp | ties %d\n",
              s, r$ratio_yearFE, r$ratio_evyearFE, r$dcdh_ate_pp, r$ties)); flush.console()
}
cat(sprintf("[%s] slice %d-%d done -> %s\n", lab, s_from, s_to, f_out))
