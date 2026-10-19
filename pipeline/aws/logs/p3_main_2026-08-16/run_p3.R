#!/usr/bin/env Rscript
# run_p3.R <label> <pairs_slim.{csv,parquet}> [frac] — 面板三（互连）dCDH，独立进程
# spec 逐字克隆 frame_dept_2026-07-31/12_run_panel3_slim.R + aws/remote_run3.R:
#   group=grp(对×事件) → dCDH 默认按组=按对聚类, D=post(0/1), effects=5, placebo=4
# frac<1 → 按 grp（对）抽样，set.seed(42)，用于内存测量；按对抽不是按行抽。
suppressMessages({ library(polars); library(DIDmultiplegtDYN); library(data.table); library(jsonlite) })
a <- commandArgs(trailingOnly=TRUE); lab <- a[1]; fn <- a[2]
frac <- if (length(a) >= 3) as.numeric(a[3]) else NA_real_
dir.create("out", showWarnings=FALSE)
pp <- strsplit(lab, "_")[[1]]
FIELD <- if (length(pp)>=2) pp[2] else NA_character_
CLEAN <- if (length(pp)>=3) pp[3] else NA_character_


if (grepl("\\.parquet$", fn)) {
  d <- as.data.table(as.data.frame(pl$read_parquet(fn)))   # polars 1.14: 用 as.data.frame，无 $to_data_frame()
} else {
  d <- fread(fn, colClasses=list(integer=c("grp","year","y","D")))
}
rows_full <- nrow(d); grps_full <- uniqueN(d$grp)

if (!is.na(frac) && frac < 1) {
  g <- unique(d$grp); set.seed(42)
  keep <- sample(g, floor(length(g) * frac))
  d <- d[grp %in% keep]
  gc()
}
cat(sprintf("\n===== 面板三 %s frac=%s 行=%d/%d 组=%d/%d 首连=%d =====\n",
    lab, ifelse(is.na(frac),"1.0",format(frac)), nrow(d), rows_full,
    uniqueN(d$grp), grps_full, sum(d$y)))
flush.console()

meta <- list(label=lab, field=FIELD, clean=CLEAN, panel="P3_interconnect", file=basename(fn),
             frac=if (is.na(frac)) 1 else frac,
             rows=nrow(d), rows_full=rows_full, grps=uniqueN(d$grp), grps_full=grps_full,
             first_ties=sum(d$y),
             spec=list(effects=5, placebo=4, cluster="grp (pair x event, dCDH default)",
                       group="pair x event", D="post(0/1)"))
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
    effects=lapply(seq_len(nrow(ef)), function(i)
      list(k=i, est=ef[i,"Estimate"], se=ef[i,"SE"], lb=ef[i,"LB CI"], ub=ef[i,"UB CI"], n=ef[i,"N"])),
    placebos=if (!inherits(pl2,"try-error") && !is.null(pl2) && nrow(pl2)>0)
      lapply(seq_len(nrow(pl2)), function(i)
        list(k=-i, est=pl2[i,"Estimate"], se=pl2[i,"SE"], lb=pl2[i,"LB CI"], ub=pl2[i,"UB CI"], n=pl2[i,"N"]))
      else list()))
  cat(sprintf("%-34s 效应联合p=%.4f 安慰剂p=%.4f ATE=%+.6f (SE %.6f, CI %.6f~%.6f)\n",
      lab, meta$p_joint_effects, meta$p_joint_placebo, meta$ate, meta$se, meta$lb, meta$ub))
}
write(toJSON(meta, auto_unbox=TRUE, digits=8, na="null"), file.path("out", paste0(lab, ".json")))
cat(sprintf("[%s] 完成 用时=%.1f 分钟\n", lab, meta$secs/60))
