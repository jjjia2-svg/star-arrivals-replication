#!/usr/bin/env Rscript
# R1 N5 (W1-FIG4, 2026-10-16), repo-authored: the dCDH estimation sample behind Figure 4's
# comparison-relation counts. run_save_sample.R <label> <frame>, the run_cells.py grammar.
# The model comes from the label prefix: P1* = analysis/estimation/run_p1.R (three channels),
# P2* = run_p2.R, P3* (P3cut_pos_<field>) = run_p3_tp.R (both clusterings).
# Every "# ---- copied from" block below is that verbatim driver, line for line; the only change
# inside them is ", save_sample=TRUE" in each did_multiplegt_dyn call (tests/test_r1_fig4.py
# checks this as text). The option is read after the estimate, so $SAR_OUT/<label>.json is
# compare_json-EQUAL to the verbatim driver's (tests/test_r1_fig4_r.py on toy frames; J1b
# compares the M run with J1a's main JSON). The "sample writer" blocks add two files:
#   $SAR_OUT/<label>_sample.csv.gz  channel, grp_id, year, D, did_sample, did_effect, arrival, zero_dose
#   $SAR_OUT/<label>_switchers.csv  channel, kind, k, n, switchers (the package's Effects/Placebos N, Switchers)
# arrival = the group's first year with post (P1) or D > 0 (P2, P3) in the channel frame;
# zero_dose = dose_topic == 0 for every row of the group (P1 only; NA for P2 and P3).
# P2 and P3 have one channel, written as "all"; P3's sample is the pair-cluster run's.
# The counting rule is pipeline/aws/r1/fig4_counts.py; see README.md in this directory.
MODEL <- substr(commandArgs(trailingOnly=TRUE)[1], 1, 2)
if (!isTRUE(MODEL %in% c("P1", "P2", "P3"))) stop("run_save_sample.R: the label must start with P1, P2 or P3")
# ---- sample writer (repo-authored, N5)
fig4 <- new.env()
fig4$samples <- list(); fig4$switchers <- list()
fig4_table <- function(m, kind, channel) {
  if (is.null(m)) return(NULL)
  m <- as.data.frame(m)
  if (nrow(m) == 0) return(NULL)
  data.frame(channel=channel, kind=kind, k=seq_len(nrow(m)), n=m[["N"]],
             switchers=if ("Switchers" %in% names(m)) m[["Switchers"]] else NA_real_)
}
fig4_keep <- function(r, g, yr, on, dose, channel) {
  if (is.null(r) || is.null(r$save_sample)) return(invisible(NULL))
  s <- as.data.frame(r$save_sample)
  gid <- if ("grp_id" %in% names(s)) s[["grp_id"]] else s[["grp"]]
  key <- as.character(gid)
  on <- !is.na(on) & on > 0
  arr <- if (any(on)) tapply(yr[on], as.character(g[on]), min) else setNames(numeric(0), character(0))
  zd <- if (is.null(dose)) NULL else
    tapply(dose, as.character(g), function(v) if (anyNA(v)) NA else all(v == 0))
  fig4$samples[[channel]] <- data.frame(channel=channel, grp_id=gid, year=s[["year"]], D=s[["D"]],
    did_sample=as.character(s[["did_sample"]]), did_effect=as.numeric(s[["did_effect"]]),
    arrival=as.numeric(arr[key]), zero_dose=if (is.null(zd)) NA else as.logical(zd[key]))
  fig4$switchers[[channel]] <- rbind(fig4_table(r$results$Effects, "effect", channel),
                                     fig4_table(r$results$Placebos, "placebo", channel))
  invisible(NULL)
}
fig4_write <- function(lab) {
  smp <- if (length(fig4$samples)) do.call(rbind, unname(fig4$samples)) else
    data.frame(channel=character(), grp_id=integer(), year=integer(), D=numeric(), did_sample=character(),
               did_effect=numeric(), arrival=numeric(), zero_dose=logical())
  sw <- if (length(fig4$switchers)) do.call(rbind, unname(fig4$switchers)) else
    data.frame(channel=character(), kind=character(), k=integer(), n=numeric(), switchers=numeric())
  data.table::fwrite(smp, file.path(OUT, paste0(lab, "_sample.csv.gz")))
  data.table::fwrite(sw, file.path(OUT, paste0(lab, "_switchers.csv")))
  cat(sprintf("[%s] save_sample: %d rows, %d channel(s)\n", lab, nrow(smp), length(fig4$samples)))
  invisible(NULL)
}
if (MODEL == "P1") {
# ---- copied from analysis/estimation/run_p1.R
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
        treatment="D", effects=6, placebo=4, cluster="person_id", graph_off=TRUE, save_sample=TRUE),
        error=function(e){ cat(sprintf("  [%s/%s] FAIL: %s\n", lab, chlab, conditionMessage(e))); NULL })
# ---- sample writer (repo-authored, N5)
  fig4_keep(r, fr$grp_id, fr$year, fr$post_num, fr$dose_topic, chlab)
# ---- copied from analysis/estimation/run_p1.R
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
# ---- sample writer (repo-authored, N5)
fig4_write(lab)
} else if (MODEL == "P2") {
# ---- copied from analysis/estimation/run_p2.R
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
      cluster="person_id", graph_off=TRUE, save_sample=TRUE),
      error=function(e){ cat(sprintf("  [%s] FAIL: %s\n", lab, conditionMessage(e))); NULL })
# ---- sample writer (repo-authored, N5)
fig4_keep(r, p2$grp_id, p2$year, p2$D, NULL, "all")
# ---- copied from analysis/estimation/run_p2.R
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
# ---- sample writer (repo-authored, N5)
fig4_write(lab)
} else if (MODEL == "P3") {
# ---- copied from analysis/estimation/run_p3_tp.R
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
        time="year", treatment="D", effects=5, placebo=4, graph_off=TRUE, save_sample=TRUE),
        error=function(e){ cat("FAIL pair-cluster:", conditionMessage(e), "\n"); NULL })
g1 <- grab(r1, "pair")
# ---- sample writer (repo-authored, N5)
fig4_keep(r1, d$grp, d$year, d$D, NULL, "all")   # pair-cluster run; the event-cluster run tags the same cells
# ---- copied from analysis/estimation/run_p3_tp.R
r2 <- tryCatch(did_multiplegt_dyn(df=as.data.frame(d[,.(grp,year,y,D,ev)]), outcome="y", group="grp",
        time="year", treatment="D", effects=5, placebo=4, cluster="ev", graph_off=TRUE, save_sample=TRUE),
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
# ---- sample writer (repo-authored, N5)
fig4_write(lab)
}
