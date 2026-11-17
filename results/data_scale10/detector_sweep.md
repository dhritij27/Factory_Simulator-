# Detector operating curve

Same planted faults and series as `backtest.md`; only the control-limit width changes. Textbook defaults are L = 3 (EWMA) and h = 5 (CUSUM); the pipeline uses L = 3.5 and h = 8.

| Series | Detector | Limit | Recall | False alarms / station-month | Median delay (days) |
|---|---|---|---|---|---|
| operator_adjusted | ewma | L = 2.5 | 16/20 | 1.19 | 6 |
| operator_adjusted | ewma | L = 2.75 | 18/20 | 0.83 | 6 |
| operator_adjusted | ewma | L = 3.0 | 18/20 | 0.54 | 6 |
| operator_adjusted | ewma | L = 3.25 | 20/20 | 0.28 | 6 |
| operator_adjusted | ewma | L = 3.5 | 20/20 | 0.16 | 6 |
| operator_adjusted | ewma | L = 4.0 | 20/20 | 0.06 | 7 |
| operator_adjusted | cusum | h = 4.0 | 16/20 | 1.13 | 6 |
| operator_adjusted | cusum | h = 5.0 | 18/20 | 0.57 | 6 |
| operator_adjusted | cusum | h = 6.0 | 20/20 | 0.26 | 6 |
| operator_adjusted | cusum | h = 7.0 | 20/20 | 0.13 | 7 |
| operator_adjusted | cusum | h = 8.0 | 20/20 | 0.06 | 7 |
| operator_adjusted | cusum | h = 10.0 | 20/20 | 0.03 | 8 |
| raw | ewma | L = 2.5 | 18/20 | 1.03 | 6 |
| raw | ewma | L = 2.75 | 19/20 | 0.61 | 7 |
| raw | ewma | L = 3.0 | 19/20 | 0.42 | 8 |
| raw | ewma | L = 3.25 | 19/20 | 0.26 | 10 |
| raw | ewma | L = 3.5 | 19/20 | 0.17 | 10 |
| raw | ewma | L = 4.0 | 19/20 | 0.03 | 10 |
| raw | cusum | h = 4.0 | 19/20 | 0.89 | 6 |
| raw | cusum | h = 5.0 | 19/20 | 0.44 | 8 |
| raw | cusum | h = 6.0 | 20/20 | 0.28 | 9 |
| raw | cusum | h = 7.0 | 20/20 | 0.20 | 10 |
| raw | cusum | h = 8.0 | 20/20 | 0.12 | 10 |
| raw | cusum | h = 10.0 | 19/20 | 0.04 | 11 |
