# Watch vs. act: escalation threshold

A drift alarm escalates to a ticket once its trailing 7-day mean shift reaches τ × repeatability σ. τ = 0 escalates every alarm.

| τ (σ) | Planted faults escalated | Median delay from onset (days) | False escalations | per station-month |
|---|---|---|---|---|
| 0.0 | 19/20 | 9 | 28 | 0.30 |
| 0.25 | 20/20 | 8 | 35 | 0.37 |
| 0.5 | 20/20 | 10 | 5 | 0.05 |
| 0.75 | 20/20 | 14 | 0 | 0.00 |
| 1.0 | 20/20 | 17 | 0 | 0.00 |
| 1.5 | 15/20 | 23 | 0 | 0.00 |
