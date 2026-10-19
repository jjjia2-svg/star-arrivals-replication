#!/usr/bin/env Rscript
# Verbatim copy of v2_output/cluster_event_2026-08-16/code/run_p2_evcl.R (sha256 ed7deb839a776206ca471bb181d31516389aecfe25de5183caf2392d4bc2d0a9), 2026-08-23; only change: SAR_OUT.
# run_p2_evcl.R <label> <becoming.csv> <ref.json> - Panel 2 (first tie to the star) dCDH, robustness with **event-level clustering**
# Verbatim clone of run_p2.R; the only change is cluster="person_id" -> cluster="event_num"
# Self-check: the point estimates (ATE / per-period Effects) must equal ref.json (the person-clustered main run) bit for bit.
suppressMessages({ library(polars); library(DIDmultiplegtDYN); library(data.table); library(jsonlite) }); set.seed(42)
a <- commandArgs(trailingOnly=TRUE); lab <- a[1]; fn <- a[2]; ref <- if (length(a) >= 3) a[3] else NA
OUT <- Sys.getenv("SAR_OUT", "out"); dir.create(OUT, showWarnings=FALSE, recursive=TRUE)   # repo edit: output dir from env (was fixed "out")
pp <- strsplit(lab, "_")[[1]]
FIELD <- if (length(pp)>=2) pp[2] else NA_character_

p2 <- fread(fn)
p2$grp_id <- as.integer(factor(paste(p2$pid, p2$event_id)))
p2$event_num <- as.integer(factor(p2$event_id))
p2$D <- p2$post
meta <- list(label=lab, field=FIELD, panel="P2_becoming", file=basename(fn),
             rows=nrow(p2), rels=uniqueN(p2$grp_id), persons=uniqueN(p2$pid),
             events=uniqueN(p2$event_id), first_ties=sum(p2$y), clusters=uniqueN(p2$event_num),
             spec=list(effects=5, placebo=4, cluster="event_num (event_id)", group="person x star-rel", D="post(0/1)",
                       clone_of="multidisc_v2_2026-08-04/aws/run_p2.R (only cluster changed)"))
cat(sprintf("\n===== 面板二[事件层聚类] %s 行=%d 关系=%d 首连=%d 簇=%d =====\n", lab, nrow(p2), uniqueN(p2$grp_id), sum(p2$y), meta$clusters))

t0 <- Sys.time()
r <- tryCatch(did_multiplegt_dyn(df=as.data.frame(p2[,.(grp_id,year,y,D,event_num)]), outcome="y",
      group="grp_id", time="year", treatment="D", effects=5, placebo=4,
      cluster="event_num", graph_off=TRUE),
      error=function(e){ cat(sprintf("  [%s] FAIL: %s\n", lab, conditionMessage(e))); NULL })
meta$secs <- as.numeric(difftime(Sys.time(), t0, units="secs"))

if (is.null(r)) { meta$status <- "FAILED" } else {
  A <- as.data.frame(r$results$ATE); ef <- as.data.frame(r$results$Effects)
  pl <- try(as.data.frame(r$results$Placebos), silent=TRUE)
  meta$status <- "OK"
  meta <- c(meta, list(ate=A[1,"Estimate"], se=A[1,"SE"], lb=A[1,"LB CI"], ub=A[1,"UB CI"],
    p_joint_effects=r$results$p_jointeffects, p_joint_placebo=r$results$p_jointplacebo,
    effects=lapply(seq_len(nrow(ef)), function(i)
      list(k=i, est=ef[i,"Estimate"], se=ef[i,"SE"], lb=ef[i,"LB CI"], ub=ef[i,"UB CI"], n=ef[i,"N"])),
    placebos=if (!inherits(pl,"try-error") && !is.null(pl) && nrow(pl)>0)
      lapply(seq_len(nrow(pl)), function(i)
        list(k=-i, est=pl[i,"Estimate"], se=pl[i,"SE"], lb=pl[i,"LB CI"], ub=pl[i,"UB CI"], n=pl[i,"N"]))
      else list()))
  cat(sprintf("%-34s 效应联合p=%.4f 安慰剂p=%.4f ATE=%+.6f (SE %.6f, CI %.6f~%.6f)\n",
      lab, meta$p_joint_effects, meta$p_joint_placebo, meta$ate, meta$se, meta$lb, meta$ub))
  if (!is.na(ref) && file.exists(ref)) {
    R0 <- fromJSON(ref, simplifyVector=FALSE)
    e1 <- sapply(meta$effects, function(x) x$est); e0 <- sapply(R0$effects, function(x) x$est)
    ok <- isTRUE(abs(meta$ate - R0$ate) < 1e-8) && length(e1)==length(e0) && all(abs(e1-e0) < 1e-8)
    meta$point_estimate_check <- if (ok) "MATCH" else sprintf("MISMATCH ate %.8f vs %.8f", meta$ate, R0$ate)
    cat(sprintf("  [自检 %s] 点估计 vs 人聚类主跑: %s | SE 人聚类=%.6f 事件聚类=%.6f\n", lab, meta$point_estimate_check, R0$se, meta$se))
  }
}
write(toJSON(meta, auto_unbox=TRUE, digits=8, na="null"), file.path(OUT, paste0(lab, ".json")))
cat(sprintf("[%s] 完成\n", lab))
