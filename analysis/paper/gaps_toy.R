#!/usr/bin/env Rscript
# gaps_toy.R — the appendix's five-relation worked example (M2/T4).
#
# appendix_estimator.tex (tab:toy) prints a 5-relation, 6-year toy panel and the
# estimator numbers it produces: Effect_1 -0.20833, Effect_2 0.00000,
# Av_tot_eff -0.23810, Placebo_1 -0.75000, delta_D_avg_total 1.4286. The script
# that produced them (/tmp/dcdh_toy/toy.R) vanished; a surviving cousin is
# v2_output/cluster_event_2026-08-16/checks/toy.R, whose panel this reproduces.
# The panel is hard-coded from tab:toy (g1..g5; g4 has dose 0 and never treats),
# run through did_multiplegt_dyn(effects=2, placebo=1) as the appendix describes,
# and every number is asserted at the precision the appendix prints (exit 1 on
# any mismatch — a mismatch is reported, never tuned away).
#
# Reads:  nothing (the panel is the appendix table itself)
# Writes: output/paper/gaps_toy.json
# Run:    Rscript analysis/paper/gaps_toy.R   (from the repo root; a few seconds)
suppressMessages({ library(polars); library(DIDmultiplegtDYN); library(jsonlite) }); set.seed(42)

argv <- commandArgs(trailingOnly = FALSE)
this <- sub("^--file=", "", argv[grep("^--file=", argv)][1])
this <- gsub("~+~", " ", this, fixed = TRUE)   # Rscript encodes spaces in --file= as ~+~
source(normalizePath(file.path(dirname(this), "..", "lib", "paths.R")))
p <- sar_paths()
OUT <- file.path(p$output, "paper"); dir.create(OUT, showWarnings = FALSE, recursive = TRUE)

# tab:toy — rows are relations, columns 2013..2018; bold years in the table are post-arrival
d <- data.frame(
  g    = rep(1:5, each = 6),
  year = rep(2013:2018, 5),
  dose = rep(c(0.6, 0.4, 0.5, 0.0, 0.5), each = 6),
  arr  = rep(c(2016, 2016, 2017, 9999, 2018), each = 6),   # 9999 = never treated (g4, dose 0)
  y    = c( 8,  9, 10, 10, 11, 11,     # g1 (dose .6, arrives 2016)
           10, 11, 12, 12, 13, 12,     # g2 (dose .4, arrives 2016)
            5,  6,  7,  9, 11, 12,     # g3 (dose .5, arrives 2017)
            4,  5,  6,  6,  7,  8,     # g4 (dose 0, never)
            6,  7,  8,  8, 10, 11))    # g5 (dose .5, arrives 2018)
d$D <- ifelse(d$year >= d$arr, d$dose, 0)

r <- did_multiplegt_dyn(df = d[, c("g", "year", "y", "D")], outcome = "y", group = "g",
      time = "year", treatment = "D", effects = 2, placebo = 1, graph_off = TRUE)
ef <- as.data.frame(r$results$Effects)
A  <- as.data.frame(r$results$ATE)
pl <- as.data.frame(r$results$Placebos)

got <- list(effect_1 = ef[1, "Estimate"], effect_2 = ef[2, "Estimate"],
            av_tot_eff = A[1, "Estimate"], placebo_1 = pl[1, "Estimate"],
            delta_D_avg_total = r$results$delta_D_avg_total)
# the appendix's printed values, at its printed precision
want <- list(effect_1 = list(-0.20833, 5), effect_2 = list(0.00000, 5),
             av_tot_eff = list(-0.23810, 5), placebo_1 = list(-0.75000, 5),
             delta_D_avg_total = list(1.4286, 4))

fails <- character(0)
for (k in names(want)) {
  w <- want[[k]]
  cat(sprintf("%-18s = %+.7f  (appendix %+.5f)  %s\n", k, got[[k]], w[[1]],
              ifelse(round(got[[k]], w[[2]]) == w[[1]], "OK", "MISMATCH")))
  if (round(got[[k]], w[[2]]) != w[[1]])
    fails <- c(fails, sprintf("%s: got %.7f, appendix prints %.5f", k, got[[k]], w[[1]]))
}

res <- c(got, list(`_note` = paste("5-relation toy panel hard-coded from appendix_estimator.tex tab:toy;",
                                   "did_multiplegt_dyn(effects=2, placebo=1); cousin script:",
                                   "v2_output/cluster_event_2026-08-16/checks/toy.R")))
write(toJSON(res, auto_unbox = TRUE, digits = 10, na = "null"), file.path(OUT, "gaps_toy.json"))
cat("wrote", file.path(OUT, "gaps_toy.json"), "\n")
if (length(fails)) stop("toy example does not reproduce the appendix: ", paste(fails, collapse = "; "))
