#!/usr/bin/env Rscript
# analysis/robustness/sensitivity/run_honest.R — REPO-AUTHORED, 2026-08-30.
#
# WHY. Panel 1's pre-arrival placebo test rejects for economics (joint p = .010) and the
# date-shift test added on 2026-08-30 rejects too (union p = .0055). The standard answer to
# a failed pre-trend test is not "we checked and it is diffuse" but a number: HOW BIG would
# the violation of parallel trends have to be to overturn the estimate? Rambachan and Roth's
# honest-DiD gives that number as a breakdown value. The author's 2026-08-28 causal-gap audit
# (not shipped; item A1.2) lists this as a top-priority check that had never been run. This is it.
#
# WHAT. For one Panel 1 cell (field x channel):
#   1. run the verbatim run_p1.R prep and estimator, keeping r$coef$b and r$coef$vcov
#      (the estimator does expose the full covariance matrix; only the JSON writers drop it);
#   2. reorder to HonestDiD's convention — pre-periods first, chronological:
#      Placebo_4, Placebo_3, Placebo_2, Placebo_1, Effect_1 ... Effect_6;
#   3. run createSensitivityResults_relativeMagnitudes over a grid of Mbar. Mbar is the
#      largest post-arrival violation allowed, as a MULTIPLE of the largest observed
#      pre-arrival violation. Mbar = 0 is exact parallel trends; Mbar = 1 allows the
#      post-period violation to be as large as the worst pre-period one.
#   4. report the BREAKDOWN Mbar: the smallest Mbar at which the robust confidence set
#      first contains zero. Bigger = more robust.
#
# TARGET PARAMETER. l_vec puts equal weight on the six post-arrival horizons, so the target
# is the equally-weighted average post-arrival effect. The paper's headline is the
# switcher-weighted ATE of de Chaisemartin and D'Haultfoeuille; the two are close but not
# identical, and both are printed so the gap is visible.
#
# Usage:  Rscript run_honest.R <field> <channel> [outdir]
#         field   econ | chemistry | math_stats
#         channel union | network | dept
suppressMessages({ library(polars); library(DIDmultiplegtDYN); library(HonestDiD); library(jsonlite) })
set.seed(42)

a <- commandArgs(trailingOnly=TRUE)
field <- a[1]; channel <- if (length(a) >= 2) a[2] else "union"
OUT <- if (length(a) >= 3) a[3] else Sys.getenv("SAR_OUT", "out")
dir.create(OUT, showWarnings=FALSE, recursive=TRUE)
stopifnot(field %in% c("econ","chemistry","math_stats"), channel %in% c("union","network","dept"))

FR <- file.path("data/frames", paste0("p1_frame_", field, ".csv"))

# ---- prep: verbatim from analysis/estimation/run_p1.R ----
f0 <- read.csv(FR, stringsAsFactors=FALSE)
f0 <- f0[!is.na(f0$age_gap) & abs(f0$age_gap) <= 60, ]
ar <- aggregate(year~event_id, data=f0[tolower(f0$post)=="true",], FUN=min); names(ar)[2] <- "ay"
f0 <- merge(f0, ar, by="event_id")
f0$y <- log1p(f0$fwci_frac)
f0$post_num <- as.integer(tolower(f0$post)=="true")
f0$D <- f0$dose_topic * f0$post_num
fr <- switch(channel,
             union   = f0,
             network = f0[f0$channel %in% c("network","both"), ],
             dept    = f0[f0$channel %in% c("dept_only","both"), ])
fr$grp_id    <- as.integer(factor(paste(fr$incumbent_person_id, fr$event_id, sep="__")))
fr$person_id <- as.integer(factor(fr$incumbent_person_id))
d2 <- fr[!is.na(fr$y), c("grp_id","year","y","D","person_id")]

cat(sprintf("\n===== 敏感度界 面板一 %s/%s  obs=%d =====\n", field, channel, nrow(d2))); flush.console()
r <- did_multiplegt_dyn(df=d2, outcome="y", group="grp_id", time="year", treatment="D",
                        effects=6, placebo=4, cluster="person_id", graph_off=TRUE)

ate <- as.data.frame(r$results$ATE)[1,"Estimate"]
b   <- r$coef$b
V   <- r$coef$vcov
nm  <- trimws(names(b))
eff <- grep("^Effect_",  nm); plc <- grep("^Placebo_", nm)
stopifnot(length(eff) == 6, length(plc) == 4)

# HonestDiD order: pre-periods first, chronological (Placebo_4 is the earliest)
ord      <- c(rev(plc), eff)
betahat  <- as.numeric(b[ord])
sigma    <- V[ord, ord, drop=FALSE]
sigma    <- (sigma + t(sigma)) / 2                     # enforce exact symmetry

# The clustered covariance from did_multiplegt_dyn is not always positive semi-definite
# (measured: smallest eigenvalue -0.011 on math_stats/union). HonestDiD takes square roots
# of quadratic forms in sigma, so a negative eigenvalue produces NaN confidence sets. Project
# onto the nearest PSD matrix by clipping negative eigenvalues to zero, and RECORD how large
# the clip was so the intervention is visible rather than silent.
ev <- eigen(sigma, symmetric=TRUE)
psd_min_eig <- min(ev$values)
psd_clipped <- sum(ev$values < 0)
if (psd_min_eig < 0) {
  vals  <- pmax(ev$values, 0)
  sigma <- ev$vectors %*% diag(vals) %*% t(ev$vectors)
  sigma <- (sigma + t(sigma)) / 2
  cat(sprintf("  [PSD 投影] 最小特征值 %.6f，裁掉 %d 个负特征值；相对 Frobenius 改动 %.3f%%\n",
              psd_min_eig, psd_clipped,
              100 * sqrt(sum((ev$values - vals)^2)) / sqrt(sum(ev$values^2))))
}
nPre <- 4L; nPost <- 6L
l_vec <- rep(1/nPost, nPost)                            # equally-weighted average post effect
eq_avg <- sum(betahat[(nPre+1):(nPre+nPost)] * l_vec)

Mbar_grid <- c(0, 0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3)
sens <- tryCatch(
  HonestDiD::createSensitivityResults_relativeMagnitudes(
    betahat=betahat, sigma=sigma, numPrePeriods=nPre, numPostPeriods=nPost,
    l_vec=l_vec, Mbarvec=Mbar_grid),
  error=function(e){ cat("  HonestDiD FAILED: ", conditionMessage(e), "\n"); NULL })

orig <- tryCatch(
  HonestDiD::constructOriginalCS(betahat=betahat, sigma=sigma,
    numPrePeriods=nPre, numPostPeriods=nPost, l_vec=l_vec),
  error=function(e) NULL)

res <- list(field=field, channel=channel, obs=nrow(d2),
            psd_projection=list(min_eigenvalue=psd_min_eig, n_clipped=psd_clipped),
            ate_switcher_weighted=ate, avg_post_equal_weights=eq_avg,
            betahat=betahat, names=nm[ord], numPrePeriods=nPre, numPostPeriods=nPost)
if (!is.null(orig)) res$original_cs <- list(lb=orig$lb, ub=orig$ub)
if (!is.null(sens)) {
  s <- as.data.frame(sens)
  res$sensitivity <- lapply(seq_len(nrow(s)), function(i)
    list(Mbar=s$Mbar[i], lb=s$lb[i], ub=s$ub[i], covers_zero=(s$lb[i] <= 0 && s$ub[i] >= 0)))
  bd <- s$Mbar[s$lb <= 0 & s$ub >= 0]
  res$breakdown_Mbar <- if (length(bd)) min(bd) else NA   # NA = robust over the whole grid
  cat(sprintf("  ATE(switcher-wtd)=%+.4f  avg post(equal-wtd)=%+.4f\n", ate, eq_avg))
  if (!is.null(orig)) cat(sprintf("  原始 CI: [%+.4f, %+.4f]\n", orig$lb, orig$ub))
  for (i in seq_len(nrow(s)))
    cat(sprintf("  Mbar=%-5.2f  CI [%+.4f, %+.4f]  %s\n", s$Mbar[i], s$lb[i], s$ub[i],
                if (s$lb[i] <= 0 && s$ub[i] >= 0) "含 0（结果被解释掉）" else "不含 0（结果存活）"))
  cat(sprintf("  ==> 击穿点 Mbar = %s\n",
              if (is.na(res$breakdown_Mbar)) "> 3（网格内全部存活）" else sprintf("%.2f", res$breakdown_Mbar)))
}
write(toJSON(res, auto_unbox=TRUE, digits=8, na="null"),
      file.path(OUT, sprintf("honest_p1_%s_%s.json", field, channel)))
cat(sprintf("[honest_p1_%s_%s] 完成\n", field, channel))
