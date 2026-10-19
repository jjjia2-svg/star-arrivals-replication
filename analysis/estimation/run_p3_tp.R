#!/usr/bin/env Rscript
# Verbatim copy of v2_output/p3_topicpair_2026-08-17/aws/run_p3_tp.R (sha256 9e79d98c1bbdb144ab1644d523a9d83456b86c0146a80d29dae2fa47cfc5e940), 2026-08-23; only change: SAR_OUT.
# NOTE: a later copy, code/run_p3_tp.R, was patched with review fixes (status/p_joint_placebo/placebos/n_event_clusters)
# AFTER the frozen results P3lb_*_A_far.json had been produced, so it no longer reproduces the frozen gold
# byte for byte (extra JSON keys; point estimates are unaffected). This pre-fix version is structurally
# identical to the archived gold and was verified to reproduce all three A_far JSONs EQUAL.
# run_p3_tp.R <label> <pairs_slim_tp.parquet> - Panel 3, "topic-matched pairs" cut
# Spec is a verbatim clone of the main Panel 3 driver run_p3.R: group=grp (pair x event), D=post(0/1), effects=5, placebo=4,
# clustered by grp by default; a second run clusters by event (column ev); both SEs are reported.
suppressMessages({ library(polars); library(DIDmultiplegtDYN); library(data.table); library(jsonlite) })
a <- commandArgs(trailingOnly=TRUE); lab <- a[1]; fn <- a[2]
OUT <- Sys.getenv("SAR_OUT", "out"); dir.create(OUT, showWarnings=FALSE, recursive=TRUE)   # repo edit: output dir from env (was fixed "out")
d <- as.data.table(as.data.frame(pl$read_parquet(fn)))
cat(sprintf("\n===== 面板三[主题相近对] %s 行=%d 组=%d 首连=%d 事件=%d =====\n",
    lab, nrow(d), uniqueN(d$grp), sum(d$y), uniqueN(d$ev))); flush.console()
meta <- list(label=lab, panel="P3_topicpair", file=basename(fn), rows=nrow(d), grps=uniqueN(d$grp),
             first_ties=sum(d$y), events=uniqueN(d$ev),
             spec=list(effects=5, placebo=4, group="pair x event", D="post(0/1)",
                       clone_of="multidisc_v2_2026-08-04/aws/run_p3.R (pair set restricted)"))
grab <- function(r, tag) {
  if (is.null(r)) return(list(status=paste0("FAILED_", tag)))
  A <- as.data.frame(r$results$ATE); ef <- as.data.frame(r$results$Effects)
  list(ate=A[1,"Estimate"], se=A[1,"SE"], lb=A[1,"LB CI"], ub=A[1,"UB CI"],
       p_joint_effects=r$results$p_jointeffects,
       effects=lapply(seq_len(nrow(ef)), function(i)
         list(k=i, est=ef[i,"Estimate"], se=ef[i,"SE"], n=ef[i,"N"], switchers=ef[i,"Switchers"])))
}
t0 <- Sys.time()
r1 <- tryCatch(did_multiplegt_dyn(df=as.data.frame(d[,.(grp,year,y,D)]), outcome="y", group="grp",
        time="year", treatment="D", effects=5, placebo=4, graph_off=TRUE),
        error=function(e){ cat("FAIL pair-cluster:", conditionMessage(e), "\n"); NULL })
g1 <- grab(r1, "pair")
r2 <- tryCatch(did_multiplegt_dyn(df=as.data.frame(d[,.(grp,year,y,D,ev)]), outcome="y", group="grp",
        time="year", treatment="D", effects=5, placebo=4, cluster="ev", graph_off=TRUE),
        error=function(e){ cat("FAIL event-cluster:", conditionMessage(e), "\n"); NULL })
g2 <- grab(r2, "event")
meta$secs <- as.numeric(difftime(Sys.time(), t0, units="secs"))
meta$pair_cluster <- g1; meta$event_cluster <- g2
if (!is.null(g1$ate))
  cat(sprintf("%-28s ATE=%+.6f (对聚类 SE %.6f, CI %.6f~%.6f) 效应联合p=%.4f | 事件聚类 SE %s\n",
      lab, g1$ate, g1$se, g1$lb, g1$ub, g1$p_joint_effects,
      ifelse(is.null(g2$se), "NA", sprintf("%.6f", g2$se))))
write(toJSON(meta, auto_unbox=TRUE, digits=8, na="null"), file.path(OUT, paste0(lab, ".json")))
cat(sprintf("[%s] 完成 用时=%.1f 分钟\n", lab, meta$secs/60))
