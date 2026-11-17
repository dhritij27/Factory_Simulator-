# Detector operating curve

Same planted faults and series as `backtest.md`; only the control-limit width changes. Textbook defaults are L = 3 (EWMA) and h = 5 (CUSUM); the pipeline uses L = 3.5 and h = 8.

| Series | Detector | Limit | Recall | False alarms / station-month | Median delay (days) |
|---|---|---|---|---|---|
| operator_adjusted | ewma | L = 2.5 | 17/20 | 1.38 | 6 |
| operator_adjusted | ewma | L = 2.75 | 19/20 | 0.92 | 6 |
| operator_adjusted | ewma | L = 3.0 | 20/20 | 0.61 | 8 |
| operator_adjusted | ewma | L = 3.25 | 20/20 | 0.33 | 8 |
| operator_adjusted | ewma | L = 3.5 | 20/20 | 0.20 | 8 |
| operator_adjusted | ewma | L = 4.0 | 20/20 | 0.09 | 8 |
| operator_adjusted | cusum | h = 4.0 | 17/20 | 1.17 | 5 |
| operator_adjusted | cusum | h = 5.0 | 20/20 | 0.58 | 6 |
| operator_adjusted | cusum | h = 6.0 | 20/20 | 0.34 | 6 |
| operator_adjusted | cusum | h = 7.0 | 20/20 | 0.18 | 8 |
| operator_adjusted | cusum | h = 8.0 | 20/20 | 0.09 | 8 |
| operator_adjusted | cusum | h = 10.0 | 20/20 | 0.05 | 9 |
| raw | ewma | L = 2.5 | 18/20 | 1.18 | 6 |
| raw | ewma | L = 2.75 | 19/20 | 0.75 | 9 |
| raw | ewma | L = 3.0 | 20/20 | 0.50 | 9 |
| raw | ewma | L = 3.25 | 20/20 | 0.28 | 9 |
| raw | ewma | L = 3.5 | 20/20 | 0.14 | 10 |
| raw | ewma | L = 4.0 | 20/20 | 0.01 | 10 |
| raw | cusum | h = 4.0 | 19/20 | 1.11 | 6 |
| raw | cusum | h = 5.0 | 20/20 | 0.58 | 8 |
| raw | cusum | h = 6.0 | 20/20 | 0.30 | 9 |
| raw | cusum | h = 7.0 | 20/20 | 0.17 | 10 |
| raw | cusum | h = 8.0 | 20/20 | 0.11 | 10 |
| raw | cusum | h = 10.0 | 20/20 | 0.03 | 12 |
