#!/usr/bin/env Rscript
# Verbatim copy of v2_output/fwci_fullsnapshot_rebuild_2026-08-09/code/run_p1.R (sha256 9666a5c64a3085f6e2710d2d3cea4093ae5dd02bbd8316deeb8d982ca98534ca), 2026-08-23; only change: SAR_OUT.
# run_p1.R <label> <frame.csv> - Panel 1 (output) dCDH, separate process
# Spec is a verbatim clone of the department-exposure driver 01_run_dept.R (the version that gives -0.194):
#   |age_gap|<=60, y=log1p(fwci_frac), D=dose_topic*post,
#   group=person x event, cluster=person_id, effects=6, placebo=4
# Same file as run_p1_selffwci.R; no parameter changed.
# NOTE: library(polars) must be loaded explicitly. DIDmultiplegtDYN uses `pl$...` internally; without it every
#   run fails with "object 'pl' not found" (hit on the first run; kept as in the original script)
suppressMessages({ library(polars); library(DIDmultiplegtDYN); library(jsonlite) }); set.seed(42)
a <- commandArgs(trailingOnly=TRUE); lab <- a[1]; fn <- a[2]
OUT <- Sys.getenv("SAR_OUT", "out"); dir.create(OUT, showWarnings=FALSE, recursive=TRUE)   # repo edit: output dir from env (was fixed "out")

f0 <- read.csv(fn, stringsAsFactors=FALSE)
n_raw <- nrow(f0)
f0 <- f0[!is.na(f0$age_gap) & abs(f0$age_gap) <= 60, ]

# NOTE: the original script's arrival-year merge is kept verbatim. It has a side effect (it reorders rows and
#   drops events that have no post row); it is left unchanged so the run stays identical to the -0.194 version.
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

cat(sprintf("\n===== 面板一 %s  原始=%d 行 清污染后=%d 行 =====\n", lab, n_raw, nrow(f0)))
res <- list(label=lab, panel="P1_output", file=basename(fn), rows_raw=n_raw, rows_kept=nrow(f0),
            spec=list(effects=6, placebo=4, cluster="person_id", group="person x event",
                      y="log1p(fwci_frac)", D="dose_topic * post", filter="|age_gap|<=60"),
            channels=list(
              union   = run_channel(f0, "union"),
              network = run_channel(f0[f0$channel %in% c("network","both"), ], "network"),
              dept    = run_channel(f0[f0$channel %in% c("dept_only","both"), ], "dept")))
write(toJSON(res, auto_unbox=TRUE, digits=8, na="null"), file.path(OUT, paste0(lab, ".json")))
cat(sprintf("[%s] 完成\n", lab))
