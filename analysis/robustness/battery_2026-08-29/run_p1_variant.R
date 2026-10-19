#!/usr/bin/env Rscript
# analysis/robustness/battery_2026-08-29/run_p1_variant.R — REPO-AUTHORED (declared in
# tests/test_verbatim_pipeline.py::REPO_AUTHORED; pin refreshed via tools/repin.sh).
#
# Panel 1 robustness battery T1-T4 (2026-08-29), all on the canon frames in data/frames.
# One driver, two modes; the prep is a line-for-line copy of analysis/estimation/run_p1.R
# (the verbatim driver, untouched), with ONE clearly-marked insertion per variant:
#
#   full <label> <frame.csv> <variant>   all three channels (union/network/dept), where
#        variant = none      no change at all — must be compare_json-EQUAL to the frozen
#                            gold in analysis/expected/ (run_all_battery.sh enforces this)
#                  fill0     T2: missing fwci_frac filled with 0 before y = log1p(...)
#                  fillmean  T2: missing fwci_frac filled with the person's own average
#                            over their observed years (unique person-years, value-constant
#                            within person-year — measured 2026-08-29: 0 value-vs-value
#                            conflicts in all three frames)
#                  levels    T3: y = fwci_frac (no log transform); everything else identical
#                  neverexp  T4: comparison pool restricted to relations of incumbents not
#                            yet exposed to any arrival (rule below)
#                  fill0leave T7 (2026-08-31): the leaver check — put back ONLY the
#                            post-arrival years in which the incumbent was off the roster
#                            AND published nothing anywhere, as genuine zeros (rule below)
#   loeo <label> <frame.csv> <event_id|NONE>   union channel only, dropping every row of
#        one event (T1 leave-one-event-out). NONE drops nothing and must equal the union
#        channel of the frozen gold exactly.
#
# WHAT THE THESIS PROMISES (quoted verbatim; text and computation must agree):
#
# T2 (bounds under missing output) — sections/sec2_data.tex:
#   "so the robustness checks re-estimate the model with every missing value filled in as
#    zero and again as the person's own average, bounding the result from both sides."
# and sections/sec3_strategy.tex (fifth concern):
#   "the estimates are bounded by treating missing output as zero and as the incumbent's
#    own average over observed years"
# Implementation: fwci_frac is NA on a row exactly when the FWCI outcome is missing for
# that person-year in that event's window; fill0 sets those NA to 0, fillmean sets them to
# mean(fwci_frac) over the person's OBSERVED person-years (deduplicated across events; the
# value is constant within person-year). Persons with no observed year at all keep NA and
# drop as in the verbatim driver (their count is recorded in the JSON). The 2026-08-09 run
# used the SAMPLE mean — that computation disagreed with the thesis text and is superseded
# by this driver.
#
# T3 (levels) — sections/sec3_strategy.tex (fifth concern):
#   "because effects on a log-of-one-plus outcome depend on the units of the outcome when
#    many observations are zero \citep{chen2024logs}, they are repeated with output in
#    levels."
# Implementation: y <- fwci_frac instead of y <- log1p(fwci_frac). Nothing else changes.
#
# T4 (never-exposed comparison pool) — sections/sec3_strategy.tex (fourth concern):
#   "And the comparison pool is restricted to relations of incumbents not yet exposed to
#    any arrival."
# The sentence names no panel; it is the third of the three boundary tests, of which only
# the channel split is scoped ("Every Panel 1 and Panel 2 estimate"). It is implemented
# here for Panel 1 (the audit's reading); the P3 population is fixed pre-arrival by design
# and its frames carry no person ids. Implementation: first_expo(p) = earliest arrival
# year over ALL events the incumbent belongs to in the estimation frame (any dose,
# including zero — an arrival in the incumbent's own department or network is an
# exposure). A row (p, e, t) stays iff
#     t < first_expo(p)                                (the incumbent is not yet exposed
#                                                       to any arrival in year t), or
#     dose_topic > 0  and  ay(e) == first_expo(p)      (the relation's own treated path,
#         and t >= ay(e)                                when this event IS the person's
#                                                       first exposure).
# So the comparison side consists only of never-yet-exposed person-years; switchers whose
# incumbent was already exposed to an earlier arrival lose their pre-period at the first
# exposure and cannot be classified — they contribute only their clean early control years
# (their count is recorded in the JSON).
#
# ★ The prep below (read, |age_gap|<=60 filter, the side-effectful arrival merge, y,
#   post_num, D, run_channel) is copied from run_p1.R one character at a time; each variant
#   is a single marked insertion. The verbatim driver itself is untouched.
suppressMessages({ library(polars); library(DIDmultiplegtDYN); library(jsonlite) }); set.seed(42)
a <- commandArgs(trailingOnly=TRUE)
mode <- a[1]; lab <- a[2]; fn <- a[3]; varg <- a[4]
stopifnot(mode %in% c("full","loeo"), !is.na(varg))
if (mode == "full") stopifnot(varg %in% c("none","fill0","fillmean","levels","neverexp","fill0leave","dosebin3"))
OUT <- Sys.getenv("SAR_OUT", "out"); dir.create(OUT, showWarnings=FALSE, recursive=TRUE)

f0 <- read.csv(fn, stringsAsFactors=FALSE)
n_raw <- nrow(f0)

# [T2 fillmean, step 1] person's own average over observed years, from the raw frame
# (a property of the person, computed before any estimation filter), deduplicated to one
# value per person-year (fwci_frac is value-constant within person-year, measured above)
pm <- NULL; n_all_na_persons <- NA_integer_
if (mode == "full" && varg == "fillmean") {
  u  <- unique(f0[!is.na(f0$fwci_frac), c("incumbent_person_id","year","fwci_frac")])
  pm <- aggregate(fwci_frac~incumbent_person_id, data=u, FUN=mean)
  n_all_na_persons <- length(setdiff(unique(f0$incumbent_person_id), pm$incumbent_person_id))
}

# [T1 loeo] drop every row of one event; NONE drops nothing (the faithfulness control)
n_dropped_rows <- NA_integer_
if (mode == "loeo" && varg != "NONE") {
  stopifnot(varg %in% f0$event_id)
  n_dropped_rows <- sum(f0$event_id == varg)
  f0 <- f0[f0$event_id != varg, ]
}

f0 <- f0[!is.na(f0$age_gap) & abs(f0$age_gap) <= 60, ]

# NOTE: the original script's arrival-year merge is kept verbatim. It has a side effect (it reorders rows and
#   drops events that have no post row); it is left unchanged so the run stays identical to the -0.194 version.
ar <- aggregate(year~event_id, data=f0[tolower(f0$post)=="true",], FUN=min); names(ar)[2] <- "ay"
f0 <- merge(f0, ar, by="event_id")

# [T2 fill0 / fillmean, step 2] fill missing output BEFORE the outcome is built
n_filled <- NA_integer_
if (mode == "full" && varg %in% c("fill0","fillmean")) {
  idx <- is.na(f0$fwci_frac)
  if (varg == "fill0") {
    f0$fwci_frac[idx] <- 0
    n_filled <- sum(idx)
  } else {
    fill <- pm$fwci_frac[match(f0$incumbent_person_id[idx], pm$incumbent_person_id)]
    f0$fwci_frac[idx] <- fill                       # persons with no observed year stay NA
    n_filled <- sum(!is.na(fill))
  }
}

# [T7 fill0leave, 2026-08-31] the leaver check. WHAT THE THESIS PROMISES —
# sections/sec3_strategy.tex (sixth concern): "following each incumbent's output regardless
# of where they publish from, so that leavers stay in the panel"; and (A5): "incumbents do
# not leave ... in a way related to treatment status".
# Measured 2026-08-31 on p1_frame_econ.csv: output is aggregated by author_id with NO
# affiliation predicate (10_build_union_frame_gold.py:511-513), so a leaver who keeps
# publishing is ALREADY in the panel — that half of the sentence is a property of the frame,
# not a test. What the main sample leaves empty is the other half: pub_count is 0 (not NA)
# for an employed person-year with no publications, so is.na(pub_count) marks exactly the
# years OUTSIDE employment, and on those rows fwci_frac is NA too. This variant fills those
# post-arrival rows with 0, i.e. counts a departed incumbent's publication-free years as the
# zeros they are, instead of dropping them.
# Deliberately NOT filled: rows where the person DID publish but FWCI could not be computed
# (is.na(fwci_frac) & !is.na(pub_count)). Those belong to the fifth concern's T2 bounds;
# mixing them in would confound missing-measurement with attrition.
n_leave_filled <- NA_integer_
if (mode == "full" && varg == "fill0leave") {
  idx <- is.na(f0$fwci_frac) & is.na(f0$pub_count) & tolower(f0$post)=="true"
  f0$fwci_frac[idx] <- 0
  n_leave_filled <- sum(idx)
}

if (mode == "full" && varg == "levels") {
  f0$y <- f0$fwci_frac                              # [T3] output in levels, no log transform
} else {
  f0$y <- log1p(f0$fwci_frac)
}
f0$post_num <- as.integer(tolower(f0$post)=="true")
f0$D <- f0$dose_topic * f0$post_num

# [D7 dosebin3, 2026-09-22] the three-bin dose. The dose enters Model 1 linearly (dose_topic x
# post). This variant replaces the continuous dose by its tercile RANK among relations with a
# positive dose (one dose per relation = person x event; zero-dose relations stay at 0), so the
# treatment is 1/2/3 x post and the "per unit" effect is per tercile step. Cut points are the
# 1/3 and 2/3 quantiles (type 7) of the positive relation doses of THIS frame, recorded in the
# JSON. Everything else is the verbatim prep.
dosebin_cuts <- NULL; n_bin_rels <- NA_integer_
if (mode == "full" && varg == "dosebin3") {
  rel <- unique(f0[f0$dose_topic > 0, c("incumbent_person_id","event_id","dose_topic")])
  dosebin_cuts <- as.numeric(quantile(rel$dose_topic, c(1/3, 2/3), type=7, names=FALSE))
  bin <- ifelse(f0$dose_topic <= 0, 0L,
         ifelse(f0$dose_topic <= dosebin_cuts[1], 1L, ifelse(f0$dose_topic <= dosebin_cuts[2], 2L, 3L)))
  n_bin_rels <- c(sum(rel$dose_topic <= dosebin_cuts[1]),
                  sum(rel$dose_topic > dosebin_cuts[1] & rel$dose_topic <= dosebin_cuts[2]),
                  sum(rel$dose_topic > dosebin_cuts[2]))
  f0$D <- bin * f0$post_num
}

# [T4 neverexp] restrict the comparison pool to never-yet-exposed person-years (rule above)
n_secondexp_rels <- NA_integer_; rows_before_nex <- NA_integer_
if (mode == "full" && varg == "neverexp") {
  rows_before_nex <- nrow(f0)
  fe <- aggregate(ay~incumbent_person_id, data=f0, FUN=min); names(fe)[2] <- "first_expo"
  f0$first_expo <- fe$first_expo[match(f0$incumbent_person_id, fe$incumbent_person_id)]
  n_secondexp_rels <- length(unique(paste(f0$incumbent_person_id, f0$event_id)[
    f0$dose_topic > 0 & f0$ay > f0$first_expo]))
  f0 <- f0[f0$year < f0$first_expo |
           (f0$dose_topic > 0 & f0$ay == f0$first_expo & f0$year >= f0$ay), ]
}

grab <- function(r){
  if (is.null(r)) return(NULL)
  A <- as.data.frame(r$results$ATE)
  ef <- as.data.frame(r$results$Effects)
  pl <- try(as.data.frame(r$results$Placebos), silent=TRUE)
  list(ate=A[1,"Estimate"], se=A[1,"SE"], lb=A[1,"LB CI"], ub=A[1,"UB CI"],
       p_joint_effects=r$results$p_jointeffects, p_joint_placebo=r$results$p_jointplacebo,
       effects=lapply(seq_len(nrow(ef)), function(i)
         list(k=i, est=ef[i,"Estimate"], se=ef[i,"SE"], lb=ef[i,"LB CI"], ub=ef[i,"UB CI"], n=ef[i,"N"])),
       placebos=if (!inherits(pl,"try-error") && !is.null(pl) && nrow(pl)>0)
         lapply(seq_len(nrow(pl)), function(i)
           list(k=-i, est=pl[i,"Estimate"], se=pl[i,"SE"], lb=pl[i,"LB CI"], ub=pl[i,"UB CI"], n=pl[i,"N"]))
         else list())
}

run_channel <- function(fr, chlab){
  if (nrow(fr)==0) return(list(channel=chlab, status="EMPTY"))
  fr$grp    <- paste(fr$incumbent_person_id, fr$event_id, sep="__")
  fr$grp_id <- as.integer(factor(fr$grp))
  fr$person_id <- as.integer(factor(fr$incumbent_person_id))
  d2 <- fr[!is.na(fr$y), c("grp_id","year","y","D","person_id")]
  meta <- list(channel=chlab, obs=nrow(d2), rels=length(unique(fr$grp)),
               rels_with_dose=length(unique(fr$grp[fr$dose_topic>0])),
               persons=length(unique(fr$incumbent_person_id)),
               events=length(unique(fr$event_id)))
  t0 <- Sys.time()
  r <- tryCatch(did_multiplegt_dyn(df=d2, outcome="y", group="grp_id", time="year",
        treatment="D", effects=6, placebo=4, cluster="person_id", graph_off=TRUE),
        error=function(e){ cat(sprintf("  [%s/%s] FAIL: %s\n", lab, chlab, conditionMessage(e))); NULL })
  g <- grab(r)
  meta$secs <- as.numeric(difftime(Sys.time(), t0, units="secs"))
  if (is.null(g)) { meta$status <- "FAILED"; return(meta) }
  meta$status <- "OK"
  cat(sprintf("%-40s obs=%-7d rel=%-6d 效应联合p=%.4f 安慰剂p=%.4f ATE=%+.5f (SE %.5f, CI %.5f~%.5f)\n",
      paste0(lab,"/",chlab), meta$obs, meta$rels, g$p_joint_effects, g$p_joint_placebo,
      g$ate, g$se, g$lb, g$ub))
  c(meta, g)
}

cat(sprintf("\n===== 面板一[%s/%s] %s  原始=%d 行 清污染后=%d 行 =====\n", mode, varg, lab, n_raw, nrow(f0)))
if (mode == "loeo") {
  res <- list(label=lab, panel="P1_output", file=basename(fn), rows_raw=n_raw, rows_kept=nrow(f0),
              spec=list(effects=6, placebo=4, cluster="person_id", group="person x event",
                        y="log1p(fwci_frac)", D="dose_topic * post", filter="|age_gap|<=60"),
              channels=list(union = run_channel(f0, "union")))
  if (varg != "NONE") res <- c(res, list(loeo_event=varg, loeo_dropped_rows=n_dropped_rows))
} else {
  res <- list(label=lab, panel="P1_output", file=basename(fn), rows_raw=n_raw, rows_kept=nrow(f0),
              spec=list(effects=6, placebo=4, cluster="person_id", group="person x event",
                        y=if (varg=="levels") "fwci_frac (levels)" else "log1p(fwci_frac)",
                        D=if (varg=="dosebin3") "dosebin3(dose_topic) * post" else "dose_topic * post",
                        filter=if (varg=="neverexp")
                          "|age_gap|<=60; comparison pool = never-yet-exposed person-years"
                        else "|age_gap|<=60"),
              channels=list(
                union   = run_channel(f0, "union"),
                network = run_channel(f0[f0$channel %in% c("network","both"), ], "network"),
                dept    = run_channel(f0[f0$channel %in% c("dept_only","both"), ], "dept")))
  if (varg != "none") res <- c(res, list(variant=varg))
  if (varg %in% c("fill0","fillmean")) res <- c(res, list(filled_rows=n_filled))
  if (varg == "fill0leave") res <- c(res, list(leave_filled_rows=n_leave_filled))
  if (varg == "fillmean") res <- c(res, list(all_na_persons=n_all_na_persons))
  if (varg == "neverexp")
    res <- c(res, list(rows_before_restriction=rows_before_nex,
                       second_exposure_switcher_rels=n_secondexp_rels))
  if (varg == "dosebin3")
    res <- c(res, list(dose_bins=list(cuts=dosebin_cuts, relations_per_bin=n_bin_rels,
                                      D="tercile rank of dose_topic (1/2/3; 0 for zero dose) x post")))
}
write(toJSON(res, auto_unbox=TRUE, digits=8, na="null"), file.path(OUT, paste0(lab, ".json")))
cat(sprintf("[%s] 完成\n", lab))
