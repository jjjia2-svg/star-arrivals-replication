#!/usr/bin/env Rscript
# gaps_switchers_p1p2.R — switcher counts for the six Panel 1 / Panel 2 headline cells
# (2026-08-30 P1+P2 exhibits).
#
# The frozen golds analysis/expected/{P1,P2}_*.json carry per-horizon est/se/n but NOT the
# estimator's Switchers column (their drivers never saved it), and the Panel 1/2 tables and
# ledger need it. Same recovery pattern as gaps_switchers.R (M2/T4): rerun each estimation
# EXACTLY as the verbatim drivers do (data-prep lines copied line-for-line from
# analysis/estimation/run_p1.R / run_p2.R; the verbatim drivers themselves are not touched),
# GATE on equality with the frozen gold (per-horizon estimates, per-horizon N, ATE — and for
# Panel 1 the placebo estimates too), and only then extract results$Effects[, "Switchers"]
# (Panel 1 also results$Placebos[, "Switchers"]). A coefficient mismatch aborts and writes
# nothing, so a stale-but-plausible extraction can never reach the ledger.
#
# Panel 1 = union channel (the paper's convention); Panel 2 has a single specification.
# Also recorded per Panel 1 cell: the switcher-weighted mean of the horizon coefficients
# (the "average change" companion to the per-unit-of-dose ATE) and the estimator-implied
# average dose among switchers (wavg / ATE — see gaps_switchers.R's header for why there is
# no direct field).
#
# Reads:  data/frames/p1_frame_{econ,chemistry,math_stats}.csv,
#         data/frames/p2_becoming_{econ,chemistry,math_stats}.csv,
#         analysis/expected/{P1,P2}_* golds
# Writes: output/paper/gaps_switchers_p1p2.json
# Run:    Rscript analysis/paper/gaps_switchers_p1p2.R   (repo root; ~1-2 min, 6 estimations)
suppressMessages({ library(polars); library(DIDmultiplegtDYN); library(data.table); library(jsonlite) }); set.seed(42)

argv <- commandArgs(trailingOnly = FALSE)
this <- sub("^--file=", "", argv[grep("^--file=", argv)][1])
this <- gsub("~+~", " ", this, fixed = TRUE)   # Rscript encodes spaces in --file= as ~+~
source(normalizePath(file.path(dirname(this), "..", "lib", "paths.R")))
p <- sar_paths()
OUT <- file.path(p$output, "paper"); dir.create(OUT, showWarnings = FALSE, recursive = TRUE)

TOL <- 1e-6
gold_of <- function(prefix, field)
  file.path(p$expected, sprintf("%s_%s.json", prefix,
            if (field == "econ") "econ_fnfix" else paste0("fnfix_", field)))

coef_gate <- function(cell, ef, A, gold, pl = NULL) {
  ok <- (max(abs(ef[, "Estimate"] - gold$effects$est)) < TOL) &&
        (abs(A[1, "Estimate"] - gold$ate) < TOL) &&
        identical(as.integer(ef[, "N"]), as.integer(gold$effects$n))
  if (!is.null(pl)) ok <- ok && (max(abs(pl[, "Estimate"] - gold$placebos$est)) < TOL)
  cat(sprintf("  [%s] coef check vs gold: max|d(effects)|=%.2e |d(ate)|=%.2e -> %s\n", cell,
              max(abs(ef[, "Estimate"] - gold$effects$est)), abs(A[1, "Estimate"] - gold$ate),
              ifelse(ok, "PASS", "FAIL")))
  list(pass = ok, ate = A[1, "Estimate"], expected_ate = gold$ate,
       max_abs_diff_effects = max(abs(ef[, "Estimate"] - gold$effects$est)))
}

# ---- Panel 1, union channel: data prep copied line-for-line from analysis/estimation/run_p1.R ----
run_p1_union <- function(field) {
  fn <- file.path(p$frames, sprintf("p1_frame_%s.csv", field))
  f0 <- read.csv(fn, stringsAsFactors=FALSE)
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
  ef <- as.data.frame(r$results$Effects); pl <- as.data.frame(r$results$Placebos)
  A  <- as.data.frame(r$results$ATE)
  gold <- fromJSON(gold_of("P1", field))$channels$union
  chk <- coef_gate(paste0("P1 ", field), ef, A, gold, pl)
  sw <- as.numeric(ef[, "Switchers"]); swp <- as.numeric(pl[, "Switchers"])
  wavg <- sum(sw * ef[, "Estimate"]) / sum(sw)
  list(horizons = lapply(seq_len(nrow(ef)), function(i) list(
         k = i, ell = i - 1, switchers = sw[i], n = as.integer(ef[i, "N"]))),
       placebos = lapply(seq_len(nrow(pl)), function(i) list(
         k = -i, ell = -(i + 1), switchers = swp[i], n = as.integer(pl[i, "N"]))),
       switchers_total = sum(sw),
       ate_row_switchers = as.numeric(A[1, "Switchers"]),
       weighted_avg_effect = wavg,
       avg_dose_switchers = wavg / A[1, "Estimate"],
       coef_check = chk)
}

# ---- Panel 2: data prep copied line-for-line from analysis/estimation/run_p2.R ----
run_p2 <- function(field) {
  fn <- file.path(p$frames, sprintf("p2_becoming_%s.csv", field))
  p2 <- fread(fn)
  p2$grp_id <- as.integer(factor(paste(p2$pid, p2$event_id)))
  p2$person_id <- as.integer(factor(p2$pid))
  p2$D <- p2$post
  r <- did_multiplegt_dyn(df=as.data.frame(p2[,.(grp_id,year,y,D,person_id)]), outcome="y",
        group="grp_id", time="year", treatment="D", effects=5, placebo=4,
        cluster="person_id", graph_off=TRUE)
  ef <- as.data.frame(r$results$Effects); A <- as.data.frame(r$results$ATE)
  gold <- fromJSON(gold_of("P2", field))
  # P2 placebos are structural zeros (see sec3_strategy.tex) and are not gated or extracted
  chk <- coef_gate(paste0("P2 ", field), ef, A, gold)
  sw <- as.numeric(ef[, "Switchers"])
  wavg <- sum(sw * ef[, "Estimate"]) / sum(sw)
  list(horizons = lapply(seq_len(nrow(ef)), function(i) list(
         k = i, ell = i - 1, switchers = sw[i], n = as.integer(ef[i, "N"]))),
       switchers_total = sum(sw),
       ate_row_switchers = as.numeric(A[1, "Switchers"]),
       weighted_avg_effect = wavg,
       placebo_note = "structurally zero, not extracted (Section 3, Models 2-3)",
       coef_check = chk)
}

FIELDS <- c("econ", "chemistry", "math_stats")
res <- list(
  label = "P1 union + P2, all disciplines (rerun; run_p1.R / run_p2.R data prep copied verbatim)",
  p1 = setNames(lapply(FIELDS, run_p1_union), FIELDS),
  p2 = setNames(lapply(FIELDS, run_p2), FIELDS))

# gold gate BEFORE the JSON lands (gaps_switchers.R pattern): a single failed replication
# means every extraction is meaningless — write nothing.
ok <- all(vapply(FIELDS, function(f) isTRUE(res$p1[[f]]$coef_check$pass) &&
                                     isTRUE(res$p2[[f]]$coef_check$pass), logical(1)))
if (!ok) stop("a rerun does NOT replicate its frozen gold — gaps_switchers_p1p2.json NOT written")

write(toJSON(res, auto_unbox=TRUE, digits=10, na="null"),
      file.path(OUT, "gaps_switchers_p1p2.json"))
cat("wrote", file.path(OUT, "gaps_switchers_p1p2.json"), "\n")
for (f in FIELDS)
  cat(sprintf("  %-11s P1 switchers %s (total %d)  P2 switchers %s (total %d)\n", f,
      paste(vapply(res$p1[[f]]$horizons, function(h) h$switchers, numeric(1)), collapse="/"),
      as.integer(res$p1[[f]]$switchers_total),
      paste(vapply(res$p2[[f]]$horizons, function(h) h$switchers, numeric(1)), collapse="/"),
      as.integer(res$p2[[f]]$switchers_total)))
