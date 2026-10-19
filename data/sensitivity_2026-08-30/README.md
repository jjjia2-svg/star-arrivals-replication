# Panel 1 — parallel-trends sensitivity bounds, 2026-08-30

Closes the causal-gap audit's A1 item 2 (the author's causal-gap audit of 2026-08-28, private working notes),
logged there as **P0** and never done.

## The question

Panel 1's pre-arrival placebo test rejects for economics (joint p = .010), and the date-shift
test added the same day rejects too (union p = .0055). The standard answer is not "we checked
and the violation is diffuse" but a number: **how large would a violation of parallel trends
have to be to overturn the estimate?** Rambachan–Roth honest-DiD gives that as a breakdown
value, `Mbar` — the largest post-arrival violation allowed, expressed as a MULTIPLE of the
largest violation actually observed before arrival. `Mbar = 1` is the natural benchmark: the
post-period violation is no worse than the pre-period one we can see.

## Why a second estimator was needed

`did_multiplegt_dyn` reports **conservative** standard errors (upper bounds). A matrix
assembled from upper bounds is not a valid covariance matrix, and honest-DiD takes square
roots of quadratic forms in it. Measured smallest eigenvalues: **−0.0110** (math_stats),
**−0.0064** (chemistry) — comparable to the *largest* positive eigenvalue, so this is not
numerical noise.

Ruled out before concluding, each measured rather than assumed:

| checked | result |
|---|---|
| Is it the right matrix? | Yes — `sqrt(diag(V))` reproduces all ten reported SEs to 5 dp |
| `bootstrap = 200` | identical eigenvalues, 330 s spent |
| `less_conservative_se = TRUE` | smallest eigenvalue moves only to −0.0109 |
| project onto nearest PSD | changes the matrix ~80% in Frobenius norm — any bound would be an artefact of the projection |

So the bound is computed on a **plain two-way fixed-effects event study** (`fixest`), whose
clustered covariance is PSD by construction (measured smallest eigenvalue +9e-05 to +2e-03
across all nine cells). **This is a measuring instrument only — none of its point estimates
enter the paper.** `run_honest_twfe.R` carries the same warning in its header.

## Spec

`y = log1p(fwci_frac)`; `dose_topic` interacted with event-time dummies, reference `tau = -1`;
person×event and calendar-year fixed effects; SEs clustered by person. Four pre-period
coefficients (`tau` −5..−2) and six post (`tau` 0..5), matching the four placebos and six
effects of the dCDH run. Target parameter: equally-weighted average post-arrival effect.

## Result

| field/channel | dCDH ATE (paper) | TWFE avg post | TWFE significant? | breakdown `Mbar` |
|---|---|---|---|---|
| econ / **union** | −0.378 | −0.236 | yes | **0.75** |
| econ / network | −0.517 | −0.285 | yes | 0.50 |
| econ / dept | −0.368 | −0.142 | yes | 0.50 |
| chemistry / union | −0.234 | −0.054 | **no** | 0.00 |
| chemistry / network | −0.214 | −0.051 | **no** | 0.00 |
| chemistry / dept | −0.229 | −0.047 | **no** | 0.00 |
| math_stats / union | −0.127 | +0.006 | no | 0.00 |
| math_stats / network | −0.207 | +0.084 | no | 0.00 |
| math_stats / dept | −0.031 | −0.011 | no | 0.00 |

**Economics breaks down at `Mbar = 0.75`** — below the natural benchmark of 1. The economics
Panel 1 estimate does not survive a post-arrival violation as large as the pre-arrival
violation we can already see.

**Chemistry and mathematics cannot be assessed this way.** TWFE does not find their effects at
all (all six confidence intervals cross zero), so `Mbar = 0.00` records "nothing to overturn",
not "fragile". The borrowed ruler is too blunt for them: TWFE attenuates the chemistry estimate
by a factor of four (−0.234 → −0.054), which is the very failure mode Section 3 cites as the
reason for not using TWFE.

## Cross-check on the paper's own estimator

A simpler check that needs no covariance matrix, so it runs on dCDH's own placebo
coefficients: fit a line through the four placebos, extrapolate it across the six post
horizons, and ask what share of the ATE it accounts for.

| field/channel | share of ATE explained | steeper by |
|---|---|---|
| econ / union | 27% | 3.7× |
| econ / network | 10% | 9.8× |
| econ / dept | **68%** | **1.5×** |
| chemistry (all three) | negative — the pre-trend runs the OTHER way | — |

**The two approaches disagree for economics** (3.7× versus 0.75×) and the reason is not a bug:
the linear extrapolation asks only whether a *straight continuation* of the pre-trend accounts
for the estimate, while honest-DiD allows the violation to take **any shape** up to the bound.
The second is far more conservative, and is the standard. Where they agree is chemistry: the
pre-trend there runs against the finding, so the dCDH estimate is if anything conservative.

## Files

- `honest_twfe_p1_{field}_{channel}.json` — nine cells: betahat, PSD check, original CS,
  the full `Mbar` grid, breakdown value.
- Drivers: `analysis/robustness/sensitivity/run_honest_twfe.R` (used) and
  `run_honest.R` (the dCDH-native attempt, kept because its PSD diagnostics are the evidence
  for why the TWFE route was necessary).
