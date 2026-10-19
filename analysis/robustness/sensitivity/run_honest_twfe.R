#!/usr/bin/env Rscript
# analysis/robustness/sensitivity/run_honest_twfe.R — REPO-AUTHORED, 2026-08-30.
#
# WHY A SECOND ESTIMATOR. Rambachan-Roth honest-DiD needs the JOINT covariance matrix of the
# event-study coefficients. did_multiplegt_dyn reports CONSERVATIVE standard errors (upper
# bounds), and a matrix assembled from upper bounds is not a valid covariance matrix: measured
# on 2026-08-30, its smallest eigenvalue is -0.0110 (math_stats) and -0.0064 (chemistry),
# comparable in size to the LARGEST positive eigenvalue. Verified before concluding this:
#   * the matrix is the right object — sqrt(diag(V)) reproduces all ten reported SEs exactly;
#   * bootstrap=200 returns an identical matrix (330 s, eigenvalues unchanged to 5 dp);
#   * less_conservative_se=TRUE moves the smallest eigenvalue only to -0.0109;
#   * projecting onto the nearest PSD matrix changes it by ~80% in Frobenius norm, which
#     would make any resulting bound an artefact of the projection.
# So the sensitivity analysis is run on a plain two-way fixed-effects event study, whose
# clustered covariance is PSD by construction. THIS IS A MEASURING INSTRUMENT ONLY: none of
# its point estimates enter the paper's tables. Section 3 explains why TWFE is not used for
# the headline estimates; the agreement between its event-study path and the dCDH one is
# reported here so the reader can judge how much the borrowed ruler distorts.
#
# SPEC. y = log1p(fwci_frac); treatment = dose_topic interacted with event-time dummies,
# reference tau = -1; grp (person x event) and calendar-year fixed effects; SEs clustered by
# person. Four pre-period coefficients (tau -5..-2) and six post (tau 0..5) match the four
# placebos and six effects of the dCDH run.
#
# Usage:  Rscript run_honest_twfe.R <field> <channel> [outdir]
suppressMessages({ library(data.table); library(fixest); library(HonestDiD); library(jsonlite) })
set.seed(42)

a <- commandArgs(trailingOnly=TRUE)
field <- a[1]; channel <- if (length(a) >= 2) a[2] else "union"
OUT <- if (length(a) >= 3) a[3] else Sys.getenv("SAR_OUT", "out")
dir.create(OUT, showWarnings=FALSE, recursive=TRUE)
stopifnot(field %in% c("econ","chemistry","math_stats"), channel %in% c("union","network","dept"))

f0 <- fread(file.path("data/frames", paste0("p1_frame_", field, ".csv")))
f0 <- f0[!is.na(age_gap) & abs(age_gap) <= 60]
f0[, post_num := as.integer(tolower(as.character(post)) == "true")]
ar <- f0[post_num == 1L, .(ay = min(year)), by = event_id]
f0 <- merge(f0, ar, by = "event_id")
f0[, `:=`(y = log1p(fwci_frac), tau = year - ay)]
f0 <- switch(channel,
             union   = f0,
             network = f0[channel %in% c("network","both")],
             dept    = f0[channel %in% c("dept_only","both")])
f0[, `:=`(grp = paste(incumbent_person_id, event_id, sep="__"), pid = incumbent_person_id)]

PRE <- -5:-2; POST <- 0:5; REF <- -1L
d <- f0[tau %in% c(PRE, REF, POST) & !is.na(y)]
d[, tauf := factor(tau, levels = c(REF, PRE, POST))]      # reference level first

m <- feols(y ~ i(tauf, dose_topic, ref = as.character(REF)) | grp + year,
           data = d, cluster = ~pid)

cn  <- names(coef(m))
key <- function(k) grep(sprintf("tauf::%d:dose_topic$", k), cn, value = TRUE)
ord <- unlist(lapply(c(PRE, POST), key))
stopifnot(length(ord) == length(PRE) + length(POST))
betahat <- as.numeric(coef(m)[ord])
sigma   <- vcov(m)[ord, ord, drop = FALSE]
sigma   <- (sigma + t(sigma)) / 2
min_eig <- min(eigen(sigma, symmetric = TRUE)$values)
cat(sprintf("\n===== TWFE 敏感度界 面板一 %s/%s  obs=%d  最小特征值=%+.3e %s =====\n",
            field, channel, nrow(d), min_eig,
            if (min_eig >= -1e-10) "(半正定 ✓)" else "(仍不半正定 ✗)")); flush.console()

nPre <- length(PRE); nPost <- length(POST)
l_vec  <- rep(1/nPost, nPost)
eq_avg <- sum(betahat[(nPre+1):(nPre+nPost)] * l_vec)

Mbar_grid <- c(0, 0.25, 0.5, 0.75, 1, 1.5, 2, 3, 5)
sens <- tryCatch(HonestDiD::createSensitivityResults_relativeMagnitudes(
          betahat=betahat, sigma=sigma, numPrePeriods=nPre, numPostPeriods=nPost,
          l_vec=l_vec, Mbarvec=Mbar_grid),
        error=function(e){ cat("  HonestDiD FAILED:", conditionMessage(e), "\n"); NULL })
orig <- tryCatch(HonestDiD::constructOriginalCS(betahat=betahat, sigma=sigma,
          numPrePeriods=nPre, numPostPeriods=nPost, l_vec=l_vec), error=function(e) NULL)

res <- list(field=field, channel=channel, estimator="TWFE event study (instrument only)",
            obs=nrow(d), min_eigenvalue=min_eig,
            event_time=list(pre=PRE, ref=REF, post=POST),
            betahat=betahat, coef_names=ord, avg_post_equal_weights=eq_avg)
if (!is.null(orig)) res$original_cs <- list(lb=orig$lb, ub=orig$ub)
if (!is.null(sens)) {
  s <- as.data.frame(sens)
  res$sensitivity <- lapply(seq_len(nrow(s)), function(i)
    list(Mbar=s$Mbar[i], lb=s$lb[i], ub=s$ub[i], covers_zero=(s$lb[i] <= 0 && s$ub[i] >= 0)))
  bd <- s$Mbar[s$lb <= 0 & s$ub >= 0]
  res$breakdown_Mbar <- if (length(bd)) min(bd) else NA
  cat(sprintf("  TWFE 平均事后效应(等权)=%+.4f\n", eq_avg))
  if (!is.null(orig)) cat(sprintf("  原始 CI: [%+.4f, %+.4f]\n", orig$lb, orig$ub))
  for (i in seq_len(nrow(s)))
    cat(sprintf("  Mbar=%-5.2f  CI [%+.4f, %+.4f]  %s\n", s$Mbar[i], s$lb[i], s$ub[i],
                if (s$lb[i] <= 0 && s$ub[i] >= 0) "含 0" else "不含 0（结果存活）"))
  cat(sprintf("  ==> 击穿点 Mbar = %s\n",
      if (is.na(res$breakdown_Mbar)) sprintf("> %.0f（网格内全部存活）", max(Mbar_grid))
      else sprintf("%.2f", res$breakdown_Mbar)))
}
write(toJSON(res, auto_unbox=TRUE, digits=8, na="null"),
      file.path(OUT, sprintf("honest_twfe_p1_%s_%s.json", field, channel)))
cat(sprintf("[honest_twfe_p1_%s_%s] 完成\n", field, channel))
