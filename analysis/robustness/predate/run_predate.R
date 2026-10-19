#!/usr/bin/env Rscript
# analysis/robustness/predate/run_predate.R — REPO-AUTHORED (declared in
# tests/test_verbatim_pipeline.py::REPO_AUTHORED; pin refreshed via tools/repin.sh).
#
# Date-shift (anticipation) test for Panels 2 and 3 — Batch 2, 2026-08-28.
#
# WHY. The built-in placebo of the P2/P3 estimator is zero by construction: a relation
# enters the comparison for cohort a only if it is still unconnected in year a, so both
# sides have recorded no tie in any earlier year and the pre-arrival coefficients are
# structural zeros ("Some placebos could not be estimated" in every P2/P3 log). The DATA,
# however, carry pre-arrival variation — pairs can and do form first ties before the star
# arrives (they exit at the first tie): P2 pre-arrival ties econ/chem/math = 37/20/4,
# P3 A_far 560/136/54, P3 math_stats full panel 503 (measured 2026-08-28 on the frozen
# frames). Shifting the treatment start s years earlier, D' = 1{year >= arrival - s},
# makes horizons k=1..s fall on TRULY pre-arrival years, so their estimates are a real
# pre-trend / anticipation test: under no anticipation and parallel pre-trends they
# should be zero. The placebos of the shifted run (years arrival-s-1 and earlier) also
# become estimable and are reported as the estimator gives them.
#
# WHAT. One driver, three modes, each a line-for-line copy of the corresponding VERBATIM
# estimation driver's prep with the single change D -> D' (and, for s>0 only, an auxiliary
# effects=s run whose joint test covers exactly the shifted-in horizons — per-horizon
# estimates do not depend on the `effects` count, so its k=1..s estimates must equal the
# main run's):
#   p2    clone of analysis/estimation/run_p2.R    — arrival from tau: D' = 1{tau >= -s}
#   p3tp  clone of analysis/estimation/run_p3_tp.R — arrival = min year with D=1 per event
#   p3    clone of analysis/estimation/run_p3.R    — event ids joined from the _ev twin frame
#   p1    clone of analysis/estimation/run_p1.R    — arrival from the post-year merge (added 2026-08-30)
# Every run first PROVES the arrival reconstruction: 1{year >= arrival} rebuilt from the
# derived arrival must equal the frozen D on every row (stopifnot), before any shift is
# applied. shift=0 reproduces the verbatim driver EXACTLY and must be compare_json-EQUAL
# to the frozen gold in analysis/expected/ (run_all_predate.sh enforces this).
#
# Usage (output dir from $SAR_OUT, as the verbatim drivers):
#   Rscript run_predate.R p2   <label> <becoming.csv>       <shift>
#   Rscript run_predate.R p3tp <label> <pairs_afar.parquet> <shift>
#   Rscript run_predate.R p3   <label> <pairs_slim.parquet> <shift> <pairs_slim_ev.parquet>
#   Rscript run_predate.R p1   <label> <p1_frame.csv>        <shift>
suppressMessages({ library(polars); library(DIDmultiplegtDYN); library(data.table); library(jsonlite) })
a <- commandArgs(trailingOnly=TRUE)
mode <- a[1]; lab <- a[2]; fn <- a[3]; shift <- as.integer(a[4])
stopifnot(mode %in% c("p1","p2","p3tp","p3"), !is.na(shift), shift >= 0L)
OUT <- Sys.getenv("SAR_OUT", "out"); dir.create(OUT, showWarnings=FALSE, recursive=TRUE)
pp <- strsplit(lab, "_")[[1]]
FIELD <- if (length(pp)>=2) pp[2] else NA_character_
CLEAN <- if (length(pp)>=3) pp[3] else NA_character_

D_DESC <- function(shift) if (shift == 0L) "post(0/1)" else
  sprintf("1{year >= arrival-%d} (date shift)", shift)

# effect/placebo extraction, key-for-key as in run_p2.R / run_p3.R
eff_list <- function(ef) lapply(seq_len(nrow(ef)), function(i)
  list(k=i, est=ef[i,"Estimate"], se=ef[i,"SE"], lb=ef[i,"LB CI"], ub=ef[i,"UB CI"], n=ef[i,"N"]))
plc_list <- function(plc) {
  if (!inherits(plc,"try-error") && !is.null(plc) && nrow(plc)>0)
    lapply(seq_len(nrow(plc)), function(i)
      list(k=-i, est=plc[i,"Estimate"], se=plc[i,"SE"], lb=plc[i,"LB CI"], ub=plc[i,"UB CI"], n=plc[i,"N"]))
  else list()
}

# the s>0 auxiliary block: joint test over exactly the shifted-in horizons
pd_meta <- function(shift, arrival_src, ra) {
  b <- list(shift=shift, arrival_source=arrival_src,
            note=sprintf(paste0("horizons k=1..%d fall on truly pre-arrival years ",
                                "(arrival-%d..arrival-1); p_joint_shifted is the joint test of ",
                                "exactly those horizons, from an effects=%d run on the same data"),
                         shift, shift, shift))
  if (is.null(ra)) { b$aux_status <- "FAILED"; return(b) }
  b$p_joint_shifted <- ra$results$p_jointeffects
  b$shifted_effects <- eff_list(as.data.frame(ra$results$Effects))
  b
}

if (mode == "p2") {
  # ---- prep copied from analysis/estimation/run_p2.R; one change: D <- 1{tau >= -shift} ----
  set.seed(42)                                                     # run_p2.R seeds at load
  p2 <- fread(fn)
  p2$grp_id <- as.integer(factor(paste(p2$pid, p2$event_id)))
  p2$person_id <- as.integer(factor(p2$pid))
  stopifnot(identical(as.integer(p2$post), as.integer(p2$tau >= 0)))  # arrival encoding proof
  p2$D <- as.integer(p2$tau >= -shift)                             # verbatim line: p2$D <- p2$post
  if (shift == 0L) stopifnot(identical(p2$D, as.integer(p2$post)))
  meta <- list(label=lab, field=FIELD, clean=CLEAN, panel="P2_becoming", file=basename(fn),
               rows=nrow(p2), rels=uniqueN(p2$grp_id), persons=uniqueN(p2$pid),
               events=uniqueN(p2$event_id), first_ties=sum(p2$y),
               spec=list(effects=5, placebo=4, cluster="person_id", group="person x star-rel",
                         D=D_DESC(shift)))
  cat(sprintf("\n===== 面板二[date-shift %d] %s 行=%d 关系=%d 首连=%d =====\n",
      shift, lab, nrow(p2), uniqueN(p2$grp_id), sum(p2$y)))
  t0 <- Sys.time()
  r <- tryCatch(did_multiplegt_dyn(df=as.data.frame(p2[,.(grp_id,year,y,D,person_id)]), outcome="y",
        group="grp_id", time="year", treatment="D", effects=5, placebo=4,
        cluster="person_id", graph_off=TRUE),
        error=function(e){ cat(sprintf("  [%s] FAIL: %s\n", lab, conditionMessage(e))); NULL })
  meta$secs <- as.numeric(difftime(Sys.time(), t0, units="secs"))
  if (is.null(r)) { meta$status <- "FAILED" } else {
    A <- as.data.frame(r$results$ATE); ef <- as.data.frame(r$results$Effects)
    plc <- try(as.data.frame(r$results$Placebos), silent=TRUE)
    meta$status <- "OK"
    meta <- c(meta, list(ate=A[1,"Estimate"], se=A[1,"SE"], lb=A[1,"LB CI"], ub=A[1,"UB CI"],
      p_joint_effects=r$results$p_jointeffects, p_joint_placebo=r$results$p_jointplacebo,
      effects=eff_list(ef), placebos=plc_list(plc)))
    cat(sprintf("%-34s 效应联合p=%.4f 安慰剂p=%.4f ATE=%+.6f (SE %.6f, CI %.6f~%.6f)\n",
        lab, meta$p_joint_effects, meta$p_joint_placebo, meta$ate, meta$se, meta$lb, meta$ub))
  }
  if (shift > 0L && !is.null(r)) {
    ra <- tryCatch(did_multiplegt_dyn(df=as.data.frame(p2[,.(grp_id,year,y,D,person_id)]), outcome="y",
          group="grp_id", time="year", treatment="D", effects=as.numeric(shift), placebo=4,
          cluster="person_id", graph_off=TRUE),
          error=function(e){ cat(sprintf("  [%s] AUX FAIL: %s\n", lab, conditionMessage(e))); NULL })
    meta$predate <- pd_meta(shift, "tau (year - arrival), exact from the frame", ra)
  }
  write(toJSON(meta, auto_unbox=TRUE, digits=8, na="null"), file.path(OUT, paste0(lab, ".json")))
  cat(sprintf("[%s] 完成\n", lab))

} else if (mode == "p3tp") {
  # ---- prep copied from analysis/estimation/run_p3_tp.R; arrival derived per event ----
  d <- as.data.table(as.data.frame(pl$read_parquet(fn)))
  arrtab <- d[D==1L, .(arr=min(year)), by=ev]
  d[arrtab, on="ev", arr := i.arr]
  stopifnot(identical(as.integer(!is.na(d$arr) & d$year >= d$arr), as.integer(d$D)))  # reconstruction proof
  d[, D := as.integer(!is.na(arr) & year >= arr - shift)]
  cat(sprintf("\n===== 面板三[主题相近对 date-shift %d] %s 行=%d 组=%d 首连=%d 事件=%d =====\n",
      shift, lab, nrow(d), uniqueN(d$grp), sum(d$y), uniqueN(d$ev))); flush.console()
  meta <- list(label=lab, panel="P3_topicpair", file=basename(fn), rows=nrow(d), grps=uniqueN(d$grp),
               first_ties=sum(d$y), events=uniqueN(d$ev),
               spec=list(effects=5, placebo=4, group="pair x event", D=D_DESC(shift),
                         clone_of="multidisc_v2_2026-08-04/aws/run_p3.R (pair set restricted)"))
  grab <- function(r, tag, with_placebo=FALSE) {
    if (is.null(r)) return(list(status=paste0("FAILED_", tag)))
    A <- as.data.frame(r$results$ATE); ef <- as.data.frame(r$results$Effects)
    out <- list(ate=A[1,"Estimate"], se=A[1,"SE"], lb=A[1,"LB CI"], ub=A[1,"UB CI"],
         p_joint_effects=r$results$p_jointeffects,
         effects=lapply(seq_len(nrow(ef)), function(i)
           list(k=i, est=ef[i,"Estimate"], se=ef[i,"SE"], n=ef[i,"N"], switchers=ef[i,"Switchers"])))
    if (with_placebo) {                       # only in shifted runs; shift=0 keeps the verbatim keys
      plc <- try(as.data.frame(r$results$Placebos), silent=TRUE)
      out$p_joint_placebo <- r$results$p_jointplacebo
      out$placebos <- if (!inherits(plc,"try-error") && !is.null(plc) && nrow(plc)>0)
        lapply(seq_len(nrow(plc)), function(i)
          list(k=-i, est=plc[i,"Estimate"], se=plc[i,"SE"], n=plc[i,"N"])) else list()
    }
    out
  }
  t0 <- Sys.time()
  r1 <- tryCatch(did_multiplegt_dyn(df=as.data.frame(d[,.(grp,year,y,D)]), outcome="y", group="grp",
          time="year", treatment="D", effects=5, placebo=4, graph_off=TRUE),
          error=function(e){ cat("FAIL pair-cluster:", conditionMessage(e), "\n"); NULL })
  g1 <- grab(r1, "pair", with_placebo = shift > 0L)
  r2 <- tryCatch(did_multiplegt_dyn(df=as.data.frame(d[,.(grp,year,y,D,ev)]), outcome="y", group="grp",
          time="year", treatment="D", effects=5, placebo=4, cluster="ev", graph_off=TRUE),
          error=function(e){ cat("FAIL event-cluster:", conditionMessage(e), "\n"); NULL })
  g2 <- grab(r2, "event", with_placebo = shift > 0L)
  meta$secs <- as.numeric(difftime(Sys.time(), t0, units="secs"))
  meta$pair_cluster <- g1; meta$event_cluster <- g2
  if (shift > 0L) {
    ra <- tryCatch(did_multiplegt_dyn(df=as.data.frame(d[,.(grp,year,y,D)]), outcome="y", group="grp",
            time="year", treatment="D", effects=as.numeric(shift), placebo=4, graph_off=TRUE),
            error=function(e){ cat(sprintf("  [%s] AUX FAIL: %s\n", lab, conditionMessage(e))); NULL })
    meta$predate <- pd_meta(shift, "min year with D==1 per event (reconstruction proved by stopifnot)", ra)
  }
  if (!is.null(g1$ate))
    cat(sprintf("%-28s ATE=%+.6f (对聚类 SE %.6f, CI %.6f~%.6f) 效应联合p=%.4f | 事件聚类 SE %s\n",
        lab, g1$ate, g1$se, g1$lb, g1$ub, g1$p_joint_effects,
        ifelse(is.null(g2$se), "NA", sprintf("%.6f", g2$se))))
  write(toJSON(meta, auto_unbox=TRUE, digits=8, na="null"), file.path(OUT, paste0(lab, ".json")))
  cat(sprintf("[%s] 完成 用时=%.1f 分钟\n", lab, meta$secs/60))

} else if (mode == "p3") {
  # ---- prep copied from analysis/estimation/run_p3.R (no frac); event ids from the _ev twin ----
  evfn <- if (length(a) >= 5) a[5] else NA_character_
  stopifnot(!is.na(evfn))
  if (grepl("\\.parquet$", fn)) {
    d <- as.data.table(as.data.frame(pl$read_parquet(fn)))
  } else {
    d <- fread(fn, colClasses=list(integer=c("grp","year","y","D")))
  }
  rows_full <- nrow(d); grps_full <- uniqueN(d$grp)
  evmap <- unique(as.data.table(as.data.frame(pl$read_parquet(evfn)))[, .(grp, ev)])
  stopifnot(anyDuplicated(evmap$grp) == 0L, all(d$grp %in% evmap$grp))
  d[evmap, on="grp", ev := i.ev]
  arrtab <- d[D==1L, .(arr=min(year)), by=ev]
  d[arrtab, on="ev", arr := i.arr]
  stopifnot(identical(as.integer(!is.na(d$arr) & d$year >= d$arr), as.integer(d$D)))  # reconstruction proof
  d[, D := as.integer(!is.na(arr) & year >= arr - shift)]
  d <- d[, .(grp, year, y, D)]                # exactly the slim frame's columns, same row order
  cat(sprintf("\n===== 面板三[date-shift %d] %s 行=%d 组=%d 首连=%d =====\n",
      shift, lab, nrow(d), uniqueN(d$grp), sum(d$y))); flush.console()
  meta <- list(label=lab, field=FIELD, clean=CLEAN, panel="P3_interconnect", file=basename(fn),
               frac=1, rows=nrow(d), rows_full=rows_full, grps=uniqueN(d$grp), grps_full=grps_full,
               first_ties=sum(d$y),
               spec=list(effects=5, placebo=4, cluster="grp (pair x event, dCDH default)",
                         group="pair x event", D=D_DESC(shift)))
  t0 <- Sys.time()
  r <- tryCatch(did_multiplegt_dyn(df=as.data.frame(d), outcome="y", group="grp",
        time="year", treatment="D", effects=5, placebo=4, graph_off=TRUE),
        error=function(e){ cat(sprintf("  [%s] FAIL: %s\n", lab, conditionMessage(e))); NULL })
  meta$secs <- as.numeric(difftime(Sys.time(), t0, units="secs"))
  if (is.null(r)) { meta$status <- "FAILED" } else {
    A <- as.data.frame(r$results$ATE); ef <- as.data.frame(r$results$Effects)
    pl2 <- try(as.data.frame(r$results$Placebos), silent=TRUE)
    meta$status <- "OK"
    meta <- c(meta, list(ate=A[1,"Estimate"], se=A[1,"SE"], lb=A[1,"LB CI"], ub=A[1,"UB CI"],
      p_joint_effects=r$results$p_jointeffects, p_joint_placebo=r$results$p_jointplacebo,
      effects=eff_list(ef), placebos=plc_list(pl2)))
    cat(sprintf("%-34s 效应联合p=%.4f 安慰剂p=%.4f ATE=%+.6f (SE %.6f, CI %.6f~%.6f)\n",
        lab, meta$p_joint_effects, meta$p_joint_placebo, meta$ate, meta$se, meta$lb, meta$ub))
  }
  if (shift > 0L && !is.null(r)) {
    ra <- tryCatch(did_multiplegt_dyn(df=as.data.frame(d), outcome="y", group="grp",
          time="year", treatment="D", effects=as.numeric(shift), placebo=4, graph_off=TRUE),
          error=function(e){ cat(sprintf("  [%s] AUX FAIL: %s\n", lab, conditionMessage(e))); NULL })
    meta$predate <- pd_meta(shift, "min year with D==1 per event, events joined from the _ev twin frame", ra)
  }
  write(toJSON(meta, auto_unbox=TRUE, digits=8, na="null"), file.path(OUT, paste0(lab, ".json")))
  cat(sprintf("[%s] 完成 用时=%.1f 分钟\n", lab, meta$secs/60))

} else if (mode == "p1") {
  # ---- prep copied from analysis/estimation/run_p1.R; one change: post -> 1{year >= ay-shift} ----
  # Added 2026-08-30. Section 3 says the arrivals are re-dated two years earlier "for all three
  # panels"; only p2/p3tp/p3 existed, so that sentence was a written promise with no code behind it
  # (searched: this repo, the legacy v2_output tree, and every cloud result file — no P1 predate
  # anywhere). shift=0 must reproduce analysis/expected/P1_{field}_fnfix.json exactly.
  set.seed(42)                                                      # run_p1.R seeds at load
  f0 <- read.csv(fn, stringsAsFactors=FALSE)
  n_raw <- nrow(f0)
  f0 <- f0[!is.na(f0$age_gap) & abs(f0$age_gap) <= 60, ]
  ar <- aggregate(year~event_id, data=f0[tolower(f0$post)=="true",], FUN=min); names(ar)[2] <- "ay"
  f0 <- merge(f0, ar, by="event_id")                                # verbatim: reorders rows, drops post-less events
  f0$y <- log1p(f0$fwci_frac)
  f0$post_num <- as.integer(tolower(f0$post)=="true")
  stopifnot(identical(f0$post_num, as.integer(f0$year >= f0$ay)))   # arrival reconstruction proof
  f0$D <- f0$dose_topic * as.integer(f0$year >= f0$ay - shift)      # verbatim line: dose_topic * post_num
  if (shift == 0L) stopifnot(identical(f0$D, f0$dose_topic * f0$post_num))

  run_channel <- function(fr, chlab, eff){
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
          treatment="D", effects=eff, placebo=4, cluster="person_id", graph_off=TRUE),
          error=function(e){ cat(sprintf("  [%s/%s] FAIL: %s\n", lab, chlab, conditionMessage(e))); NULL })
    meta$secs <- as.numeric(difftime(Sys.time(), t0, units="secs"))
    if (is.null(r)) { meta$status <- "FAILED"; return(meta) }
    A <- as.data.frame(r$results$ATE); ef <- as.data.frame(r$results$Effects)
    plc <- try(as.data.frame(r$results$Placebos), silent=TRUE)
    meta$status <- "OK"
    out <- c(meta, list(ate=A[1,"Estimate"], se=A[1,"SE"], lb=A[1,"LB CI"], ub=A[1,"UB CI"],
      p_joint_effects=r$results$p_jointeffects, p_joint_placebo=r$results$p_jointplacebo,
      effects=eff_list(ef), placebos=plc_list(plc)))
    cat(sprintf("%-40s obs=%-7d rel=%-6d 效应联合p=%.4f 安慰剂p=%.4f ATE=%+.5f (SE %.5f, CI %.5f~%.5f)\n",
        paste0(lab,"/",chlab), meta$obs, meta$rels, out$p_joint_effects, out$p_joint_placebo,
        out$ate, out$se, out$lb, out$ub))
    out
  }
  SPLIT <- list(union=function(d) d,
                network=function(d) d[d$channel %in% c("network","both"), ],
                dept=function(d) d[d$channel %in% c("dept_only","both"), ])
  cat(sprintf("\n===== 面板一[date-shift %d] %s 原始=%d 行 清污染后=%d 行 =====\n",
      shift, lab, n_raw, nrow(f0)))
  # key order and shape follow run_p1.R exactly (no field/clean; spec.D verbatim at shift 0)
  # so a shift-0 run is compare_json-EQUAL to analysis/expected/P1_*.json
  meta <- list(label=lab, panel="P1_output", file=basename(fn),
               rows_raw=n_raw, rows_kept=nrow(f0),
               spec=list(effects=6, placebo=4, cluster="person_id", group="person x event",
                         y="log1p(fwci_frac)",
                         D=if (shift == 0L) "dose_topic * post"
                           else sprintf("dose_topic * 1{year >= arrival-%d} (date shift)", shift),
                         filter="|age_gap|<=60"),
               channels=lapply(names(SPLIT), function(k) run_channel(SPLIT[[k]](f0), k, 6)))
  names(meta$channels) <- names(SPLIT)
  if (shift > 0L) {
    aux <- lapply(names(SPLIT), function(k) run_channel(SPLIT[[k]](f0), k, as.numeric(shift)))
    names(aux) <- names(SPLIT)
    meta$predate <- list(shift=shift,
      arrival_source="min year with post==true per event (the run_p1.R merge), reconstruction proved",
      note=sprintf(paste0("horizons k=1..%d fall on truly pre-arrival years (arrival-%d..arrival-1); ",
                          "p_joint_shifted is the joint test of exactly those horizons, from an ",
                          "effects=%d run on the same data, per channel"), shift, shift, shift),
      p_joint_shifted=lapply(aux, function(a) a$p_joint_effects),
      shifted_effects=lapply(aux, function(a) a$effects))
  }
  write(toJSON(meta, auto_unbox=TRUE, digits=8, na="null"), file.path(OUT, paste0(lab, ".json")))
  cat(sprintf("[%s] 完成\n", lab))
}
