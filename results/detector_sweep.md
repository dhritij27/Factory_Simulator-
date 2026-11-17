# Detector operating curve

Same planted faults and series as `backtest.md`; only the control-limit width changes. Textbook defaults are L = 3 (EWMA) and h = 5 (CUSUM); the pipeline uses L = 3.5 and h = 8.

| Series | Detector | Limit | Recall | False alarms / station-month | Median delay (days) |
|---|---|---|---|---|---|
| operator_adjusted | ewma | L = 2.5 | 17/20 | 1.15 | 4 |
| operator_adjusted | ewma | L = 2.75 | 17/20 | 0.82 | 5 |
| operator_adjusted | ewma | L = 3.0 | 18/20 | 0.48 | 5 |
| operator_adjusted | ewma | L = 3.25 | 20/20 | 0.28 | 5 |
| operator_adjusted | ewma | L = 3.5 | 20/20 | 0.13 | 6 |
| operator_adjusted | ewma | L = 4.0 | 20/20 | 0.07 | 6 |
| operator_adjusted | cusum | h = 4.0 | 18/20 | 1.08 | 2 |
| operator_adjusted | cusum | h = 5.0 | 19/20 | 0.56 | 5 |
| operator_adjusted | cusum | h = 6.0 | 20/20 | 0.33 | 6 |
| operator_adjusted | cusum | h = 7.0 | 19/20 | 0.20 | 6 |
| operator_adjusted | cusum | h = 8.0 | 20/20 | 0.14 | 6 |
| operator_adjusted | cusum | h = 10.0 | 20/20 | 0.02 | 7 |
| raw | ewma | L = 2.5 | 19/20 | 1.21 | 7 |
| raw | ewma | L = 2.75 | 19/20 | 0.81 | 8 |
| raw | ewma | L = 3.0 | 20/20 | 0.61 | 7 |
| raw | ewma | L = 3.25 | 20/20 | 0.45 | 8 |
| raw | ewma | L = 3.5 | 20/20 | 0.26 | 8 |
| raw | ewma | L = 4.0 | 20/20 | 0.12 | 10 |
| raw | cusum | h = 4.0 | 19/20 | 1.21 | 8 |
| raw | cusum | h = 5.0 | 19/20 | 0.74 | 8 |
| raw | cusum | h = 6.0 | 20/20 | 0.39 | 8 |
| raw | cusum | h = 7.0 | 20/20 | 0.23 | 10 |
| raw | cusum | h = 8.0 | 19/20 | 0.17 | 11 |
| raw | cusum | h = 10.0 | 20/20 | 0.09 | 12 |
