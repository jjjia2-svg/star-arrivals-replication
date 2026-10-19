#!/usr/bin/env Rscript
# analysis/robustness/inference/run_perm.R — REPO-AUTHORED (declared in
# tests/test_verbatim_pipeline.py::REPO_AUTHORED; pin refreshed via tools/repin.sh).
#
# Event-level permutation (randomization) inference for the headline cells — T5, 2026-08-29.
#
# WHY. Chemistry has 38 arrival events and math_stats 33 — few enough that conventional
# cluster-robust standard errors can mislead (the estimator's clusters are persons or pairs,
# but the treatment varies at the EVENT level, and there are only 33-116 events). The standard
# few-cluster remedy for a timing design is randomization inference on the treatment timing:
# hold every panel, outcome and dose fixed, reassign the observed arrival YEARS across the
# observed events (a random permutation of the arrival-year labels, so the multiset of arrival
# years and the event count are exactly preserved), re-estimate, and ask how often a world with
# scrambled timing produces an effect as large as the observed one.
#
# THE INTERFACE. Each verbatim driver consumes the arrival year only through the treatment
# column of its frozen frame:
#   p1    run_p1.R      derives arrival per event as min(year | post) and uses D = dose_topic*post,
#                       where post = 1{year >= arrival_e} (proved row-for-row by stopifnot below);
#   p2    run_p2.R      uses D = post = 1{tau >= 0} = 1{year >= arrival_e} (tau = year - arrival);
#   p3tp  run_p3_tp.R   uses the frozen D = 1{year >= arrival_ev} (arrival reconstructed per event
#                       as min(year | D==1), proved by stopifnot as in run_predate.R).
# The permutation therefore acts at exactly that interface: arrival'_e = arrival_{pi(e)} for a
# uniform random permutation pi of the events, and D is rebuilt from arrival' by the same rule.
# Doses, rosters, pair sets and calendar windows stay frozen; only the timing labels move.
#
# WHAT EACH MODE ESTIMATES per permutation (prep is a line-for-line copy of the corresponding
# verbatim driver, one change: D from the permuted arrivals):
#   p1    the UNION channel only (the paper's headline P1 cell), effects=6, placebo=4,
#         cluster=person_id — the verbatim run_p1.R spec;
#   p2    effects=5, placebo=4, cluster=person_id — the verbatim run_p2.R spec;
#   p3tp  effects=5, placebo=4, cluster=ev (event) — one estimation per permutation; the point
#         estimate is identical under pair clustering (measured property of the estimator, see
#         analysis/estimation/README.md on the *_evcl drivers), so the pair-cluster run is not
#         repeated 500 times. Event clustering also matches the permutation unit.
#
# PERM 0 IS THE IDENTITY CONTROL: it must reproduce the frozen gold (ate and se equal to the
# reference JSON within 1e-8 relative), proving the cloned prep is the verbatim prep.
#
# Usage ($SAR_OUT gives the output dir, as the verbatim drivers):
#   Rscript run_perm.R p1   <label> <p1_frame.csv>      <ref.json> <seed> <from> <to>
#   Rscript run_perm.R p2   <label> <becoming.csv>      <ref.json> <seed> <from> <to>
#   Rscript run_perm.R p3tp <label> <pairs_afar.parquet><ref.json> <seed> <from> <to>
# Permutation i uses set.seed(seed + i); results append to <label>_perm_<from>_<to>.csv.
suppressMessages({ library(polars); library(DIDmultiplegtDYN); library(data.table); library(jsonlite) })
a <- commandArgs(trailingOnly=TRUE)
mode <- a[1]; lab <- a[2]; fn <- a[3]; ref_fn <- a[4]
seed <- as.integer(a[5]); p_from <- as.integer(a[6]); p_to <- as.integer(a[7])
stopifnot(mode %in% c("p1","p2","p3tp"), !is.na(seed), !is.na(p_from), !is.na(p_to), p_from <= p_to)
OUT <- Sys.getenv("SAR_OUT", "out"); dir.create(OUT, showWarnings=FALSE, recursive=TRUE)
ref <- fromJSON(ref_fn)

# ---- load the frame once and derive the event -> arrival table, prep cloned per mode ---------
if (mode == "p1") {
  # ---- prep copied from analysis/estimation/run_p1.R (union channel) ----
  f0 <- read.csv(fn, stringsAsFactors=FALSE)
  f0 <- f0[!is.na(f0$age_gap) & abs(f0$age_gap) <= 60, ]
  ar <- aggregate(year~event_id, data=f0[tolower(f0$post)=="true",], FUN=min); names(ar)[2] <- "ay"
  f0 <- merge(f0, ar, by="event_id")                                # verbatim side effects kept
  stopifnot(identical(as.integer(tolower(f0$post)=="true"),
                      as.integer(f0$year >= f0$ay)))                 # arrival encoding proof
  f0$y <- log1p(f0$fwci_frac)
  f0$grp    <- paste(f0$incumbent_person_id, f0$event_id, sep="__")
  f0$grp_id <- as.integer(factor(f0$grp))
  f0$person_id <- as.integer(factor(f0$incumbent_person_id))
  events <- ar$event_id; arr0 <- ar$ay
  ref_ate <- ref$channels$union$ate; ref_se <- ref$channels$union$se
  EFFECTS <- 6
  estimate <- function(arr_new) {
    ay2 <- arr_new[match(f0$event_id, events)]
    f0$D <- f0$dose_topic * as.integer(f0$year >= ay2)
    d2 <- f0[!is.na(f0$y), c("grp_id","year","y","D","person_id")]
    set.seed(42)                                                    # run_p1.R seeds at load
    r <- tryCatch(did_multiplegt_dyn(df=d2, outcome="y", group="grp_id", time="year",
          treatment="D", effects=6, placebo=4, cluster="person_id", graph_off=TRUE),
          error=function(e){ cat(sprintf("  [%s] FAIL: %s\n", lab, conditionMessage(e))); NULL })
    list(r=r, n_treated=sum(tapply(f0$D>0, f0$event_id, any)))
  }
} else if (mode == "p2") {
  # ---- prep copied from analysis/estimation/run_p2.R ----
  set.seed(42)                                                      # run_p2.R seeds at load
  p2 <- fread(fn)
  p2$grp_id <- as.integer(factor(paste(p2$pid, p2$event_id)))
  p2$person_id <- as.integer(factor(p2$pid))
  stopifnot(identical(as.integer(p2$post), as.integer(p2$tau >= 0)))  # arrival encoding proof
  arr_tab <- unique(p2[, .(a=year - tau), by=event_id][, .(event_id, a)])
  stopifnot(nrow(arr_tab) == uniqueN(p2$event_id))                    # one arrival per event
  events <- arr_tab$event_id; arr0 <- arr_tab$a
  ref_ate <- ref$ate; ref_se <- ref$se
  EFFECTS <- 5
  estimate <- function(arr_new) {
    a2 <- arr_new[match(p2$event_id, events)]
    p2$D <- as.integer(p2$year >= a2)                               # verbatim line: p2$D <- p2$post
    set.seed(42)
    r <- tryCatch(did_multiplegt_dyn(df=as.data.frame(p2[,.(grp_id,year,y,D,person_id)]), outcome="y",
          group="grp_id", time="year", treatment="D", effects=5, placebo=4,
          cluster="person_id", graph_off=TRUE),
          error=function(e){ cat(sprintf("  [%s] FAIL: %s\n", lab, conditionMessage(e))); NULL })
    list(r=r, n_treated=p2[, any(D==1), by=event_id][, sum(V1)])
  }
} else {  # p3tp
  # ---- prep copied from analysis/estimation/run_p3_tp.R via run_predate.R's reconstruction ----
  d <- as.data.table(as.data.frame(pl$read_parquet(fn)))
  arrtab <- d[D==1L, .(arr=min(year)), by=ev]
  d[arrtab, on="ev", arr := i.arr]
  stopifnot(identical(as.integer(!is.na(d$arr) & d$year >= d$arr), as.integer(d$D)))  # proof
  setorder(arrtab, ev)
  events <- arrtab$ev; arr0 <- arrtab$arr
  ref_ate <- ref$pair_cluster$ate; ref_se <- ref$event_cluster$se   # ATE identical across clusterings
  EFFECTS <- 5
  estimate <- function(arr_new) {
    a2 <- arr_new[match(d$ev, events)]
    d$D <- as.integer(d$year >= a2)
    r <- tryCatch(did_multiplegt_dyn(df=as.data.frame(d[,.(grp,year,y,D,ev)]), outcome="y",
          group="grp", time="year", treatment="D", effects=5, placebo=4,
          cluster="ev", graph_off=TRUE),
          error=function(e){ cat(sprintf("  [%s] FAIL: %s\n", lab, conditionMessage(e))); NULL })
    list(r=r, n_treated=d[, any(D==1L), by=ev][, sum(V1)])
  }
}
n_ev <- length(events)
cat(sprintf("\n===== permutation %s %s events=%d perms=%d..%d seed=%d =====\n",
    mode, lab, n_ev, p_from, p_to, seed))

out_fn <- file.path(OUT, sprintf("%s_perm_%d_%d.csv", lab, p_from, p_to))
con <- file(out_fn, "w")
writeLines("label,mode,perm,seed_used,n_events,n_treated_events,status,ate,se,t,p_joint_effects,p_joint_placebo,secs", con)

for (i in p_from:p_to) {
  if (i == 0L) { arr_new <- arr0; seed_used <- NA_integer_ }
  else { seed_used <- seed + i; set.seed(seed_used); arr_new <- arr0[sample.int(n_ev)] }
  t0 <- Sys.time()
  z <- estimate(arr_new)
  secs <- as.numeric(difftime(Sys.time(), t0, units="secs"))
  if (is.null(z$r)) {
    writeLines(sprintf("%s,%s,%d,%s,%d,%d,FAILED,,,,,,%.2f", lab, mode, i,
               ifelse(is.na(seed_used),"",seed_used), n_ev, z$n_treated, secs), con)
    flush(con); next
  }
  A <- as.data.frame(z$r$results$ATE)
  ate <- A[1,"Estimate"]; se <- A[1,"SE"]
  pje <- z$r$results$p_jointeffects
  pjp <- z$r$results$p_jointplacebo; if (is.null(pjp)) pjp <- NA_real_
  if (i == 0L) {  # identity control: must reproduce the frozen gold
    # the reference JSONs are written with jsonlite digits=8 (8 decimal places), so equality
    # holds up to that rounding: |diff| < 5.1e-9
    stopifnot(abs(ate - ref_ate) < 5.1e-9, abs(se - ref_se) < 5.1e-9)
    cat(sprintf("  CONTROL EQUAL: ate=%.10f se=%.10f == ref (to the gold's 8-decimal rounding)\n",
        ate, se))
  }
  writeLines(sprintf("%s,%s,%d,%s,%d,%d,OK,%.10g,%.10g,%.6g,%.6g,%s,%.2f",
             lab, mode, i, ifelse(is.na(seed_used),"",seed_used), n_ev, z$n_treated,
             ate, se, ate/se, pje, ifelse(is.na(pjp),"",sprintf("%.6g",pjp)), secs), con)
  flush(con)
  if (i %% 25 == 0) cat(sprintf("  [%s] perm %d done (%.1fs)\n", lab, i, secs))
}
close(con)
cat(sprintf("[%s] %d..%d done -> %s\n", lab, p_from, p_to, out_fn))
