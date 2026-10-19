#!/usr/bin/env Rscript
# Verbatim copy of v2_output/multidisc_v2_2026-08-04/aws/run_p2.R (sha256 ec2fdd4c3ad2095f1c20406646292cbee6d842a5809a19860b7873f3d88a2ffd), 2026-08-23; only change: SAR_OUT.
# run_p2.R <label> <becoming.csv> - Panel 2 (first tie to the star) dCDH, separate process
# Spec is a verbatim clone of the department-exposure Panel 2 driver 13_run_panel2.R:
#   group=person x star-relation, cluster=person_id, D=post(0/1), effects=5, placebo=4
suppressMessages({ library(polars); library(DIDmultiplegtDYN); library(data.table); library(jsonlite) }); set.seed(42)
a <- commandArgs(trailingOnly=TRUE); lab <- a[1]; fn <- a[2]
OUT <- Sys.getenv("SAR_OUT", "out"); dir.create(OUT, showWarnings=FALSE, recursive=TRUE)   # repo edit: output dir from env (was fixed "out")
pp <- strsplit(lab, "_")[[1]]
FIELD <- if (length(pp)>=2) pp[2] else NA_character_
CLEAN <- if (length(pp)>=3) pp[3] else NA_character_


p2 <- fread(fn)
p2$grp_id <- as.integer(factor(paste(p2$pid, p2$event_id)))
p2$person_id <- as.integer(factor(p2$pid))
p2$D <- p2$post
meta <- list(label=lab, field=FIELD, clean=CLEAN, panel="P2_becoming", file=basename(fn),
             rows=nrow(p2), rels=uniqueN(p2$grp_id), persons=uniqueN(p2$pid),
             events=uniqueN(p2$event_id), first_ties=sum(p2$y),
             spec=list(effects=5, placebo=4, cluster="person_id", group="person x star-rel", D="post(0/1)"))
cat(sprintf("\n===== 面板二 %s 行=%d 关系=%d 首连=%d =====\n", lab, nrow(p2), uniqueN(p2$grp_id), sum(p2$y)))

t0 <- Sys.time()
r <- tryCatch(did_multiplegt_dyn(df=as.data.frame(p2[,.(grp_id,year,y,D,person_id)]), outcome="y",
      group="grp_id", time="year", treatment="D", effects=5, placebo=4,
      cluster="person_id", graph_off=TRUE),
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
}
write(toJSON(meta, auto_unbox=TRUE, digits=8, na="null"), file.path(OUT, paste0(lab, ".json")))
cat(sprintf("[%s] 完成\n", lab))
