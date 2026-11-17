# Back-test results

Generated 2026-11-16 from simulator seed 7. Every number below is computed by `python -m fabsim backtest` against `data/ground_truth/`.

## Ingestion

| Check | Result |
|---|---|
| Rows loaded / quarantined | 8,160,714 / 51,294 |
| Station mapping accuracy (loaded rows) | 8,160,714 / 8,160,714 (100.000%), 0 wrong |
| Rows with a non-canonical label mapped correctly | 5,778,785 / 5,778,785 |
| Ambiguous labels quarantined instead of guessed | 1,113 rows |
| Missing instrument imputed correctly | 39,694 / 39,694 |
| Missing-timestamp rows that leaked into the warehouse | 0 / 11,357 |
| Missing-station rows that leaked into the warehouse | 0 / 7,451 |
| Silent unit change: rows kept out of the warehouse | 8,813 / 8,813 |
| Clean rows quarantined anyway | 1,113 (0.014%): {'ambiguous_station': 1113} |

| Schema event | Planted | First alert | Delay (days) |
|---|---|---|---|
| CM1: column fw_version added and column order changed | 2026-03-06 | 2026-03-06 | 0 |
| CM2: measurement keys mtf50 -> MTF_50 and delta_uv -> dUV | 2026-04-10 | 2026-04-10 | 0 |
| CM3: column SN -> Serial No. | 2026-05-11 | 2026-05-11 | 0 |
| LAB-RD: vert_misalign exported in degrees instead of arcmin, header unchanged | 2026-05-05 | 2026-05-05 | 0 |

## Drift detectors

20 planted drift/step faults across 76 station x metric series (94.9 station-months monitored after the 30-day baseline). A fault counts as detected if an alarm lands within 45 days of onset. `raw` = daily mean golden residual; `operator_adjusted` = same, after subtracting each operator's baseline effect (pooled across the site).

| Series | Detector | Recall | Precision | False alarms / station-month | Median delay (days) |
|---|---|---|---|---|---|
| raw | EWMA (λ=0.2, L=3.5) | 19/20 (95%) | 54% | 0.17 | 10 |
| raw | CUSUM (k=0.5σ, h=8σ) | 20/20 (100%) | 65% | 0.12 | 10 |
| raw | PELT change-point (offline) | 19/20 (95%) | 93% | 0.03 | 4 (localisation error) |
| raw | EWMA or CUSUM | 20/20 (100%) | – | – | 10 |
| operator_adjusted | EWMA (λ=0.2, L=3.5) | 20/20 (100%) | 57% | 0.16 | 6 |
| operator_adjusted | CUSUM (k=0.5σ, h=8σ) | 20/20 (100%) | 77% | 0.06 | 7 |
| operator_adjusted | PELT change-point (offline) | 20/20 (100%) | 100% | 0.00 | 4 (localisation error) |
| operator_adjusted | EWMA or CUSUM | 20/20 (100%) | – | – | 6 |

Recall by fault size (size = step height, or drift height 30 days after onset, in repeatability σ):

| Series | Detector | <1σ | 1–2σ | >2σ |
|---|---|---|---|---|
| raw | ewma | 3/4 | 9/9 | 7/7 |
| raw | cusum | 4/4 | 9/9 | 7/7 |
| raw | pelt | 3/4 | 9/9 | 7/7 |
| operator_adjusted | ewma | 4/4 | 9/9 | 7/7 |
| operator_adjusted | cusum | 4/4 | 9/9 | 7/7 |
| operator_adjusted | pelt | 4/4 | 9/9 | 7/7 |

## Station correlation (golden units)

Planted biased series: 4. Flagged: 4. Recall 4/4, precision 4/4, out of 76 station x metric series checked.

## Gauge R&R

76 studies. Planted noisy stations rated unacceptable: 1/2. Healthy stations rated unacceptable: 0. Median |estimate − configured| = 1.4 %GRR points; the 95% CI contains the configured value in 84% of studies.

Bootstrap CI coverage, Monte Carlo over fresh simulated studies (3 operators × 3 trials):

| Metric | Station | Parts | True %GRR | Median estimate | Coverage (nominal 95%) | Median CI width |
|---|---|---|---|---|---|---|
