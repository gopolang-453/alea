# ALEA prospective ledger (data branch)

This branch holds the live, append-only prospective forecast ledger (`ledger.sqlite`) and the reports produced by `.github/workflows/weekly-prospective-forecast.yml`. That workflow is its only writer. Code lives on the main branches.

- `ledger.sqlite` was seeded on 24 Nov 2026 as a byte-identical copy of `results/prospective/ledger.sqlite`, which held 10 forecasts for 28 Nov 2026 with fingerprint `cf486e7d…381b8`. The history in this branch is the audit trail; never force-push it.
- **Licensing:**
  - Forecast probabilities are ALEA's own output.
  - Result observations come from Wikipedia ("2026–27 Premier League", revision ids recorded per run) under CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/). Redistributed result data stays under that licence with attribution.
  - Fixtures come from OpenFootball (CC0).
- **Recovery:** see `docs/OPERATIONS.md` on the code branch.
