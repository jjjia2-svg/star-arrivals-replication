#!/usr/bin/env Rscript
# Verbatim copy of v2_output/cluster_event_2026-08-16/code/run_p1_evcl.R (sha256 69f68c6e643cc8811213edabe73093b6355b9252faff59dc0b6143801d729b80), 2026-08-23; only change: SAR_OUT.
# run_p1_evcl.R <label> <frame.csv> <ref.json> - Panel 1 (output) dCDH, robustness with **event-level clustering**
# Verbatim clone of run_p1.R; the only change is cluster="person_id" -> cluster="event_num"
#   (event_num = as.integer(factor(event_id)); grp = person x event is nested in the event, and dCDH allows clustering coarser than group)
# Self-check: the point estimates (ATE / per-period Effects) must equal ref.json (the person-clustered main run) bit for bit - clustering changes only the SE, not the point estimates.
suppressMessages({ library(polars); library(DIDmultiplegtDYN); library(jsonlite) }); set.seed(42)
a <- commandArgs(trailingOnly=TRUE); lab <- a[1]; fn <- a[2]; ref <- if (length(a) >= 3) a[3] else NA
OUT <- Sys.getenv("SAR_OUT", "out"); dir.create(OUT, showWarnings=FALSE, recursive=TRUE)   # repo edit: output dir from env (was fixed "out")

f0 <- read.csv(fn, stringsAsFactors=FALSE)
n_raw <- nrow(f0)
f0 <- f0[!is.na(f0$age_gap) & abs(f0$age_gap) <= 60, ]
ar <- aggregate(year~event_id, data=f0[tolower(f0$post)=="true",], FUN=min); names(ar)[2] <- "ay"
f0 <- merge(f0, ar, by="event_id")
f0$y <- log1p(f0$fwci_frac)
f0$post_num <- as.integer(tolower(f0$post)=="true")
f0$D <- f0$dose_topic * f0$post_num

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
  fr$event_num <- as.integer(factor(fr$event_id))
  d2 <- fr[!is.na(fr$y), c("grp_id","year","y","D","event_num")]
  meta <- list(channel=chlab, obs=nrow(d2), rels=length(unique(fr$grp)),
               rels_with_dose=length(unique(fr$grp[fr$dose_topic>0])),
               persons=length(unique(fr$incumbent_person_id)),
               events=length(unique(fr$event_id)), clusters=length(unique(d2$event_num)))
  t0 <- Sys.time()
  r <- tryCatch(did_multiplegt_dyn(df=d2, outcome="y", group="grp_id", time="year",
        treatment="D", effects=6, placebo=4, cluster="event_num", graph_off=TRUE),
        error=function(e){ cat(sprintf("  [%s/%s] FAIL: %s\n", lab, chlab, conditionMessage(e))); NULL })
  g <- grab(r)
  meta$secs <- as.numeric(difftime(Sys.time(), t0, units="secs"))
  if (is.null(g)) { meta$status <- "FAILED"; return(meta) }
  meta$status <- "OK"
  cat(sprintf("%-40s obs=%-7d rel=%-6d clusters=%-4d 效应联合p=%.4f 安慰剂p=%.4f ATE=%+.5f (SE %.5f, CI %.5f~%.5f)\n",
      paste0(lab,"/",chlab), meta$obs, meta$rels, meta$clusters, g$p_joint_effects, g$p_joint_placebo,
      g$ate, g$se, g$lb, g$ub))
  c(meta, g)
}

cat(sprintf("\n===== 面板一[事件层聚类] %s  原始=%d 行 清污染后=%d 行 =====\n", lab, n_raw, nrow(f0)))
res <- list(label=lab, panel="P1_output", file=basename(fn), rows_raw=n_raw, rows_kept=nrow(f0),
            spec=list(effects=6, placebo=4, cluster="event_num (event_id)", group="person x event",
                      y="log1p(fwci_frac)", D="dose_topic * post", filter="|age_gap|<=60",
                      clone_of="fwci_fullsnapshot_rebuild_2026-08-09/code/run_p1.R (only cluster changed)"),
            channels=list(
              union   = run_channel(f0, "union"),
              network = run_channel(f0[f0$channel %in% c("network","both"), ], "network"),
              dept    = run_channel(f0[f0$channel %in% c("dept_only","both"), ], "dept")))

# ---- Self-check: point estimates identical to the person-clustered main run ----
if (!is.na(ref) && file.exists(ref)) {
  R0 <- fromJSON(ref, simplifyVector=FALSE)
  chk <- list()
  for (ch in c("union","network","dept")) {
    a1 <- res$channels[[ch]]$ate; a0 <- R0$channels[[ch]]$ate
    if (is.null(a1) || is.null(a0)) { chk[[ch]] <- "NA"; next }
    ok <- isTRUE(abs(a1 - a0) < 1e-8)
    e1 <- sapply(res$channels[[ch]]$effects, function(x) x$est); e0 <- sapply(R0$channels[[ch]]$effects, function(x) x$est)
    ok <- ok && length(e1)==length(e0) && all(abs(e1-e0) < 1e-8)
    chk[[ch]] <- if (ok) "MATCH" else sprintf("MISMATCH ate %.8f vs %.8f", a1, a0)
    cat(sprintf("  [自检 %s/%s] 点估计 vs 人聚类主跑: %s | SE 人聚类=%.5f 事件聚类=%.5f\n", lab, ch, chk[[ch]],
                R0$channels[[ch]]$se, res$channels[[ch]]$se))
  }
  res$point_estimate_check <- chk
}
write(toJSON(res, auto_unbox=TRUE, digits=8, na="null"), file.path(OUT, paste0(lab, ".json")))
cat(sprintf("[%s] 完成\n", lab))
