# Watch vs. act: escalation threshold

A drift alarm escalates to a ticket once its trailing 7-day mean shift reaches τ × repeatability σ. τ = 0 escalates every alarm.

| τ (σ) | Planted faults escalated | Median delay from onset (days) | False escalations | per station-month |
|---|---|---|---|---|
| 0.0 | 20/20 | 10 | 18 | 0.19 |
| 0.25 | 20/20 | 10 | 17 | 0.18 |
| 0.5 | 20/20 | 10 | 9 | 0.09 |
| 0.75 | 20/20 | 14 | 1 | 0.01 |
| 1.0 | 18/20 | 19 | 0 | 0.00 |
| 1.5 | 11/20 | 18 | 0 | 0.00 |
