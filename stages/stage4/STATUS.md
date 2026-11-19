# Stage 4 — Expected goals (xG)

## Status: FEATURE CALCULATORS COMPLETE; EVALUATION BLOCKED

### Accepted
- Rolling team xG for/against, venue filter, per-fixture lookup
- Over/underperformance only when paired result + xG exist
- Fail-closed when data is missing
- Leakage-safe via `as_of`

### Still open
No licensed historical xG source with trustworthy pre-match availability timestamps is connected. Comparative evaluation against production MLE is therefore **NOT EVALUATED**.

Do not enable xG in any production probability path until a source + coverage audit + identical-fixture out-of-sample evidence exists.
