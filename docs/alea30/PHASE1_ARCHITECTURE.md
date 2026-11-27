# ALEA 3.0 — Phase 1 Architecture Verification

**Branch:** `dev/alea-3.0`  
**Date:** 2026-11-27  
**Production champion:** `alea-dc-v2.4.1`  
**SHA-256:** `4cfc61085ae742a550944a410ec81a1b21a47cc8ab7688bde0d879c7c24f022a`

## Verified production components

| Component | Status |
|-----------|--------|
| Frozen champion module | Present, hash verified |
| Model registry | Champion frozen; Elo + DC+Elo challengers registered |
| Prospective ledger branch | Protected; append-only policy unchanged |
| Stage 1 data store | OpenFootball + Wikipedia pipeline operational |
| Stage 3 team features | Elo + form + H2H leakage-safe calculators exist |
| Stage 4–6 | Scaffolding only; **blocked on licensed timestamped data** |
| Web app / prediction service | Continues on production track |
| Promotion rule | ≥300 settled paired fixtures; no automatic promotion |

## ALEA 3.0 tracks

**PRODUCTION (unchanged)**  
- Champion `alea-dc-v2.4.1` continues all live forecasts and ledger writes.

**DEVELOPMENT (`dev/alea-3.0`)**  
- Independent challengers and feature experiments.
- Shadow forecasts stored separately from the prospective ledger.
- No automatic promotion.

## Phase prioritisation (from roadmap)

1. **Phase 2 (this delivery):** recent form + home/away performance features; form-based challenger; controlled comparisons vs champion.
2. **Phase 3:** xG — research only until a licensed timestamped source is wired (Stage 4 remains blocked).
3. **Phase 4:** Elo independent evaluation (Stage 3 Elo already exists; expand comparative backtests).
4. **Phase 5:** Player availability — blocked (Stage 5).
5. **Phase 6:** Ensemble — only after independent components show value.
6. **Phase 7:** Full evaluation + dashboard.

## Non-negotiable rules

- Never modify `alea_predictor_v2_4_1.py`.
- Never write experimental forecasts into the production prospective ledger.
- Never rewrite Git history or perform the odds cleanup without explicit authorisation.
- All evaluation uses chronological cutoffs and identical fixtures.
- Report statistical uncertainty; do not promote on nominal improvements alone.
