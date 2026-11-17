# Back-test results

Generated 2026-11-17 from simulator seed 7. Every number below is computed by `python -m fabsim backtest` against `data/ground_truth/`.

## Ingestion

| Check | Result |
|---|---|
| Rows loaded / quarantined | 1,042,946 / 7,810 |
| Station mapping accuracy (loaded rows) | 1,042,946 / 1,042,946 (100.000%), 0 wrong |
| Rows with a non-canonical label mapped correctly | 749,922 / 749,922 |
| Ambiguous labels quarantined instead of guessed | 224 rows |
| Missing instrument imputed correctly | 5,197 / 5,197 |
| Missing-timestamp rows that leaked into the warehouse | 0 / 1,574 |
| Missing-station rows that leaked into the warehouse | 0 / 1,075 |
| Silent unit change: rows kept out of the warehouse | 1,948 / 1,948 |
| Clean rows quarantined anyway | 224 (0.021%): {'ambiguous_station': 224} |

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
| raw | EWMA (λ=0.2, L=3.5) | 20/20 (100%) | 44% | 0.26 | 8 |
| raw | CUSUM (k=0.5σ, h=8σ) | 19/20 (95%) | 54% | 0.17 | 11 |
| raw | PELT change-point (offline) | 20/20 (100%) | 94% | 0.03 | 5 (localisation error) |
| raw | EWMA or CUSUM | 20/20 (100%) | – | – | 8 |
| operator_adjusted | EWMA (λ=0.2, L=3.5) | 20/20 (100%) | 62% | 0.13 | 6 |
| operator_adjusted | CUSUM (k=0.5σ, h=8σ) | 20/20 (100%) | 61% | 0.14 | 6 |
| operator_adjusted | PELT change-point (offline) | 20/20 (100%) | 95% | 0.03 | 5 (localisation error) |
| operator_adjusted | EWMA or CUSUM | 20/20 (100%) | – | – | 5 |

Recall by fault size (size = step height, or drift height 30 days after onset, in repeatability σ):

| Series | Detector | <1σ | 1–2σ | >2σ |
|---|---|---|---|---|
| raw | ewma | 4/4 | 9/9 | 7/7 |
| raw | cusum | 4/4 | 8/9 | 7/7 |
| raw | pelt | 4/4 | 9/9 | 7/7 |
| operator_adjusted | ewma | 4/4 | 9/9 | 7/7 |
| operator_adjusted | cusum | 4/4 | 9/9 | 7/7 |
| operator_adjusted | pelt | 4/4 | 9/9 | 7/7 |

## Station correlation (golden units)

Planted biased series: 4. Flagged: 4. Recall 4/4, precision 4/4, out of 76 station x metric series checked.

## Gauge R&R

76 studies. Planted noisy stations rated unacceptable: 2/2. Healthy stations rated unacceptable: 0. Median |estimate − configured| = 1.7 %GRR points; the 95% CI contains the configured value in 86% of studies.

Bootstrap CI coverage, Monte Carlo over fresh simulated studies (3 operators × 3 trials):

| Metric | Station | Parts | True %GRR | Median estimate | Coverage (nominal 95%) | Median CI width |
|---|---|---|---|---|---|---|
| mtf50 | healthy | 20 | 11.6 | 11.7 | 95% (n=300) | 9.1 |
| mtf50 | noisy | 20 | 34.9 | 35.2 | 93% (n=300) | 22.4 |
| lum_uniformity | healthy | 20 | 11.9 | 12.3 | 93% (n=300) | 9.7 |
| lum_uniformity | noisy | 20 | 35.4 | 36.0 | 93% (n=300) | 22.6 |
| delta_uv | healthy | 20 | 11.7 | 12.0 | 97% (n=300) | 9.3 |
| delta_uv | noisy | 20 | 35.4 | 35.6 | 94% (n=300) | 22.3 |
| vert_misalign | healthy | 10 | 11.8 | 12.4 | 94% (n=300) | 15.0 |
| vert_misalign | noisy | 10 | 35.0 | 36.6 | 91% (n=300) | 34.7 |
