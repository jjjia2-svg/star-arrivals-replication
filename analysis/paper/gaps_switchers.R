#!/usr/bin/env Rscript
# gaps_switchers.R — measure the appendix's switcher counts and average dose (M2/T4).
#
# appendix_estimator.tex (tab:agg) prints, for the economics Panel 1 union channel,
# per-horizon "Switching relations" 7,543/7,070/6,990/6,791/6,618/6,364 (sum 41,376)
# and an average dose among switchers of 0.374 — with NO surviving generator script.
# This script measures the truth: it reruns the P1 econ union-channel estimation
# EXACTLY as analysis/estimation/run_p1.R does (its data-prep lines are copied below
# verbatim; the verbatim driver itself is not touched), first checks the coefficients
# against the frozen gold analysis/expected/P1_econ_fnfix.json channels$union (proof
# the estimation was replicated), then extracts the Switchers column of
# results$Effects and results$delta_D_avg_total, and compares them with the
# appendix's hand numbers. A coefficient mismatch aborts (exit 1); an appendix
# mismatch is NOT an error here — it is recorded in the JSON as matches_appendix
# flags (a real finding that feeds the Task 7 errata).
#
# Which field holds the "average dose 0.374": NONE directly. str(r$results) has no
# average-dose field, and results$delta_D_avg_total is the average TOTAL treatment
# (3.54 here; 1.4286 in the toy, whose average dose the appendix calls 0.5). The
# appendix's average dose is the estimator-implied one — (switcher-weighted mean of
# the horizon coefficients) / (the per-unit-of-dose ATE) — which reproduces the
# toy's 0.5 exactly. Both quantities are written to the JSON.
#
# Reads:  data/frames/p1_frame_econ.csv, analysis/expected/P1_econ_fnfix.json
# Writes: output/paper/gaps_switchers.json
# Run:    Rscript analysis/paper/gaps_switchers.R   (from the repo root; ~15 s)
suppressMessages({ library(polars); library(DIDmultiplegtDYN); library(jsonlite) }); set.seed(42)

# repo root from --file= so every path comes from config/paths.yaml
argv <- commandArgs(trailingOnly = FALSE)
this <- sub("^--file=", "", argv[grep("^--file=", argv)][1])
this <- gsub("~+~", " ", this, fixed = TRUE)   # Rscript encodes spaces in --file= as ~+~
source(normalizePath(file.path(dirname(this), "..", "lib", "paths.R")))
p <- sar_paths()
OUT <- file.path(p$output, "paper"); dir.create(OUT, showWarnings = FALSE, recursive = TRUE)

# ---- data prep: copied line-for-line from analysis/estimation/run_p1.R (union channel) ----
fn <- file.path(p$frames, "p1_frame_econ.csv")
f0 <- read.csv(fn, stringsAsFactors=FALSE)
n_raw <- nrow(f0)
f0 <- f0[!is.na(f0$age_gap) & abs(f0$age_gap) <= 60, ]
ar <- aggregate(year~event_id, data=f0[tolower(f0$post)=="true",], FUN=min); names(ar)[2] <- "ay"
f0 <- merge(f0, ar, by="event_id")
f0$y <- log1p(f0$fwci_frac)
f0$post_num <- as.integer(tolower(f0$post)=="true")
f0$D <- f0$dose_topic * f0$post_num
fr <- f0                                        # union channel = the whole frame
fr$grp    <- paste(fr$incumbent_person_id, fr$event_id, sep="__")
fr$grp_id <- as.integer(factor(fr$grp))
fr$person_id <- as.integer(factor(fr$incumbent_person_id))
d2 <- fr[!is.na(fr$y), c("grp_id","year","y","D","person_id")]
r <- did_multiplegt_dyn(df=d2, outcome="y", group="grp_id", time="year",
      treatment="D", effects=6, placebo=4, cluster="person_id", graph_off=TRUE)

ef <- as.data.frame(r$results$Effects)
A  <- as.data.frame(r$results$ATE)

# ---- sanity: the frozen gold must be replicated before the extraction means anything ----
gold <- fromJSON(file.path(p$expected, "P1_econ_fnfix.json"))$channels$union
gold_est <- gold$effects$est
diff_eff <- abs(ef[,"Estimate"] - gold_est)
n_match  <- identical(as.integer(ef[,"N"]), as.integer(gold$effects$n))
ate_diff <- abs(A[1,"Estimate"] - gold$ate)
coef_pass <- (max(diff_eff) < 1e-6) && (ate_diff < 1e-6) && n_match
cat(sprintf("coef check vs gold: max|d(effects)|=%.2e |d(ate)|=%.2e N match=%s -> %s\n",
            max(diff_eff), ate_diff, n_match, ifelse(coef_pass, "PASS", "FAIL")))

# ---- the measured truth: Switchers per horizon + the appendix's average dose ----
# Freeze-wave Task 8 (2026-08-28): the appendix numbers below are the ones printed by the
# caliber-updated thesis (tab:agg regenerated from this script's own measurement on the promoted
# frames; every changed cell \REV-marked). Pre-caliber appendix: 7543/7070/6990/6791/6618/6364,
# total 41376, wavg -0.139, avg dose 0.374.
# cal2026-10 (2026-09-23, the October caliber is the canon): the constants below are the October
# measurement of this script on the promoted October frames (analysis/expected/P1_econ_fnfix.json is
# the October gold, and the coefficient gate above must pass first); the thesis prints them once the
# cal2026-10 repin lands. 2026-08-28 appendix (kept in the JSON as _pre_october_appendix):
# 7506/7035/6955/6757/6581/6332, total 41166, wavg -0.142, avg dose 0.375.
APX <- c(5264, 4944, 4840, 4668, 4475, 4282); APX_TOTAL <- 28473
APX_AVG_DOSE <- 0.383; APX_WAVG <- -0.141
PRE_OCT <- list(switchers = c(7506, 7035, 6955, 6757, 6581, 6332), switchers_total = 41166,
                weighted_avg = -0.142, avg_dose = 0.375)
sw  <- as.numeric(ef[,"Switchers"])
wavg <- sum(sw * ef[,"Estimate"]) / sum(sw)     # the appendix's "Summary" coefficient
avg_dose <- wavg / A[1,"Estimate"]              # estimator-implied average dose (see header)
horizons <- lapply(seq_len(nrow(ef)), function(i) list(
  k = i, switchers = sw[i], n = as.numeric(ef[i,"N"]),
  appendix_switchers = APX[i], matches_appendix = isTRUE(sw[i] == APX[i])))

res <- list(
  label = "P1_econ_fnfix / union (rerun, run_p1.R data prep copied verbatim)",
  spec  = list(effects=6, placebo=4, cluster="person_id", group="person x event",
               y="log1p(fwci_frac)", D="dose_topic * post", filter="|age_gap|<=60"),
  rows_raw = n_raw, rows_kept = nrow(f0),
  horizons = horizons,
  switchers_total = sum(sw),
  appendix_switchers_total = APX_TOTAL,
  switchers_total_matches_appendix = isTRUE(sum(sw) == APX_TOTAL),
  ate_row_switchers = as.numeric(A[1,"Switchers"]),
  weighted_avg_effect = wavg,
  appendix_weighted_avg = APX_WAVG,
  weighted_avg_matches_appendix = isTRUE(round(wavg, 3) == APX_WAVG),
  avg_dose_switchers = avg_dose,
  avg_dose_field = paste("no direct field: (sum(Switchers*Estimate)/sum(Switchers)) / ATE;",
                          "results$delta_D_avg_total is the average TOTAL treatment, kept below"),
  delta_D_avg_total = r$results$delta_D_avg_total,
  appendix_avg_dose = APX_AVG_DOSE,
  avg_dose_matches_appendix = isTRUE(round(avg_dose, 3) == APX_AVG_DOSE),
  coef_check = list(pass = coef_pass, ate = A[1,"Estimate"], expected_ate = gold$ate,
                    max_abs_diff_effects = max(diff_eff), n_match = n_match),
  `_pre_october_appendix` = PRE_OCT)

cat("\n  horizon   measured  appendix  match\n")
for (i in seq_along(sw))
  cat(sprintf("  l=%d       %-9d %-9d %s\n", i-1, sw[i], APX[i], sw[i]==APX[i]))
cat(sprintf("  total     %-9d %-9d %s\n", sum(sw), APX_TOTAL, sum(sw)==APX_TOTAL))
cat(sprintf("  wavg eff  %-9.4f %-9.3f %s\n", wavg, APX_WAVG, round(wavg,3)==APX_WAVG))
cat(sprintf("  avg dose  %-9.4f %-9.3f %s   (delta_D_avg_total=%.4f, a different quantity)\n",
            avg_dose, APX_AVG_DOSE, round(avg_dose,3)==APX_AVG_DOSE, r$results$delta_D_avg_total))

# gold gate BEFORE the JSON lands (T4-review MINOR-2, fixed in the M2 milestone fix wave):
# if the rerun does not replicate the frozen gold, no gaps_switchers.json is written, so a
# stale-but-plausible extraction can never be left on disk for the sentinel to read.
if (!coef_pass) stop("estimation does NOT replicate the frozen gold — extraction is meaningless; gaps_switchers.json NOT written")

write(toJSON(res, auto_unbox=TRUE, digits=10, na="null"),
      file.path(OUT, "gaps_switchers.json"))
cat("wrote", file.path(OUT, "gaps_switchers.json"), "\n")

if (!res$switchers_total_matches_appendix || !res$avg_dose_matches_appendix ||
    !res$weighted_avg_matches_appendix || !all(sw == APX))
  cat("NOTE: measured values differ from the appendix's hand numbers — erratum candidate.\n")
