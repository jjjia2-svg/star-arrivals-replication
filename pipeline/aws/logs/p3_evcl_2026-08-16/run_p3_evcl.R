#!/usr/bin/env Rscript
# run_p3_evcl.R <label> <pairs_slim_ev.parquet> [ref.json] — 面板三（互连）dCDH，**事件层聚类**稳健性（2026-08-16 作者拍 A）
# 逐字克隆 multidisc_v2_2026-08-04/aws/run_p3.R，唯一改动：加 cluster="ev"（事件编号；grp=对×事件 嵌套于事件）
# 自检（给 ref.json 时）：点估计必须与按对聚类主跑逐位一致。
suppressMessages({ library(polars); library(DIDmultiplegtDYN); library(data.table); library(jsonlite) })
a <- commandArgs(trailingOnly=TRUE); lab <- a[1]; fn <- a[2]; ref <- if (length(a) >= 3) a[3] else NA
dir.create("out", showWarnings=FALSE)
pp <- strsplit(lab, "_")[[1]]
FIELD <- if (length(pp)>=2) pp[2] else NA_character_

d <- as.data.table(as.data.frame(pl$read_parquet(fn)))
cat(sprintf("\n===== 面板三[事件层聚类] %s 行=%d 组=%d 首连=%d 簇=%d =====\n",
    lab, nrow(d), uniqueN(d$grp), sum(d$y), uniqueN(d$ev)))
flush.console()
meta <- list(label=lab, field=FIELD, panel="P3_interconnect", file=basename(fn),
             rows=nrow(d), grps=uniqueN(d$grp), first_ties=sum(d$y), clusters=uniqueN(d$ev),
             spec=list(effects=5, placebo=4, cluster="ev (event)", group="pair x event", D="post(0/1)",
                       clone_of="multidisc_v2_2026-08-04/aws/run_p3.R (only cluster added)"))
t0 <- Sys.time()
r <- tryCatch(did_multiplegt_dyn(df=as.data.frame(d[,.(grp,year,y,D,ev)]), outcome="y", group="grp",
      time="year", treatment="D", effects=5, placebo=4, cluster="ev", graph_off=TRUE),
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
  if (!is.na(ref) && file.exists(ref)) {
    R0 <- fromJSON(ref, simplifyVector=FALSE)
    e1 <- sapply(meta$effects, function(x) x$est); e0 <- sapply(R0$effects, function(x) x$est)
    ok <- isTRUE(abs(meta$ate - R0$ate) < 1e-8) && length(e1)==length(e0) && all(abs(e1-e0) < 1e-8)
    meta$point_estimate_check <- if (ok) "MATCH" else sprintf("MISMATCH ate %.8f vs %.8f", meta$ate, R0$ate)
    cat(sprintf("  [自检 %s] 点估计 vs 按对聚类主跑: %s | SE 对聚类=%.6f 事件聚类=%.6f\n", lab, meta$point_estimate_check, R0$se, meta$se))
  }
}
write(toJSON(meta, auto_unbox=TRUE, digits=8, na="null"), file.path("out", paste0(lab, ".json")))
cat(sprintf("[%s] 完成 用时=%.1f 分钟\n", lab, meta$secs/60))
