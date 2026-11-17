# Back-test results

Generated 2026-11-17 from simulator seed 11. Every number below is computed by `python -m fabsim backtest` against `data/ground_truth/`.

## Ingestion

| Check | Result |
|---|---|
| Rows loaded / quarantined | 1,043,233 / 7,103 |
| Station mapping accuracy (loaded rows) | 1,043,233 / 1,043,233 (100.000%), 0 wrong |
| Rows with a non-canonical label mapped correctly | 748,873 / 748,873 |
| Ambiguous labels quarantined instead of guessed | 98 rows |
| Missing instrument imputed correctly | 5,123 / 5,123 |
| Missing-timestamp rows that leaked into the warehouse | 0 / 1,496 |
| Missing-station rows that leaked into the warehouse | 0 / 951 |
| Silent unit change: rows kept out of the warehouse | 1,977 / 1,977 |
| Clean rows quarantined anyway | 101 (0.010%): {'ambiguous_station': 98, 'out_of_range': 3} |

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
| raw | EWMA (λ=0.2, L=3.5) | 20/20 (100%) | 63% | 0.14 | 10 |
| raw | CUSUM (k=0.5σ, h=8σ) | 20/20 (100%) | 71% | 0.11 | 10 |
| raw | PELT change-point (offline) | 20/20 (100%) | 98% | 0.01 | 4 (localisation error) |
| raw | EWMA or CUSUM | 20/20 (100%) | – | – | 10 |
| operator_adjusted | EWMA (λ=0.2, L=3.5) | 20/20 (100%) | 51% | 0.20 | 8 |
| operator_adjusted | CUSUM (k=0.5σ, h=8σ) | 20/20 (100%) | 69% | 0.09 | 8 |
| operator_adjusted | PELT change-point (offline) | 20/20 (100%) | 96% | 0.02 | 3 (localisation error) |
| operator_adjusted | EWMA or CUSUM | 20/20 (100%) | – | – | 8 |

Recall by fault size (size = step height, or drift height 30 days after onset, in repeatability σ):

| Series | Detector | <1σ | 1–2σ | >2σ |
|---|---|---|---|---|
| raw | ewma | 7/7 | 9/9 | 4/4 |
| raw | cusum | 7/7 | 9/9 | 4/4 |
| raw | pelt | 7/7 | 9/9 | 4/4 |
| operator_adjusted | ewma | 7/7 | 9/9 | 4/4 |
| operator_adjusted | cusum | 7/7 | 9/9 | 4/4 |
| operator_adjusted | pelt | 7/7 | 9/9 | 4/4 |

## Station correlation (golden units)

Planted biased series: 4. Flagged: 4. Recall 4/4, precision 4/4, out of 76 station x metric series checked.

## Gauge R&R

76 studies. Planted noisy stations rated unacceptable: 2/2. Healthy stations rated unacceptable: 1. Median |estimate − configured| = 1.8 %GRR points; the 95% CI contains the configured value in 91% of studies.

Bootstrap CI coverage, Monte Carlo over fresh simulated studies (3 operators × 3 trials):

| Metric | Station | Parts | True %GRR | Median estimate | Coverage (nominal 95%) | Median CI width |
|---|---|---|---|---|---|---|
