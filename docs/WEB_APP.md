# ALEA web app

The web app is a plain HTML/CSS/JS front end in `web/`, served by the same read-only server as the API (`scripts/serve_api.py`). It has no build step, no third-party scripts, no trackers and no external requests. Everything it shows comes from the prospective ledger written by the scheduled workflow.

## What a visitor can do

| Screen | Contents |
|---|---|
| **Matches** (`#/`) | Upcoming Premier League fixtures grouped by day. Each published forecast shows home/draw/away probabilities (rounded so the three always add up to 100%), the most likely scoreline, and a "prior only" chip when a team had no top-flight history. Fixtures that are not forecast yet are listed under "Later fixtures", with the scheduled run that will forecast them. A status pill shows Live, Data may be stale or Unavailable, plus the time of the last successful run. |
| **Match detail** (`#/match/<key>`) | Probabilities with exact values, the five most likely scorelines, the model's expected goals (the Poisson means from final scores, labelled "not shot-based xG"), a factual explanation of what the model used, and the forecast record: model version, publication time, results source revision, training fingerprint. Experimental challenger forecasts are folded away and labelled as not the published forecast. |
| **Results** (`#/history`) | Every forecast with its status (awaiting result, settled, postponed, etc.) and the actual score once settled. Performance (log loss, Brier, accuracy) appears only once matches are settled, with a "preliminary" warning under 300 settled matches. The historical benchmark (champion v market, 1,140 matches) is shown with the market's advantage stated plainly. |
| **How it works** (`#/about`) | Method, what the model does not know (injuries, line-ups, transfers, odds, news), accuracy, not-betting-advice notice, sources and licences. |

## Honesty rules built into the app

- Only the frozen champion's ledger probabilities are shown as the forecast. There is no mock, sample or random data anywhere in `web/` (a test checks for `Math.random`).
- Forecasts are read from the append-only ledger and are never recomputed or edited by the app.
- Expected goals and scorelines are recorded at forecast time from the champion's own `predict()` output, only for forecasts made from this release on. The pipeline refuses to record them if that output's 1X2 differs from the published probabilities by more than 1e-6. Older forecasts show "Scorelines not recorded for this forecast"; they are never backfilled.
- No "confidence" percentages. The most likely outcome is called "most likely", never certain.
- Error messages never contain file paths, stack traces or secrets.

## Installing on an iPhone

Open the site in Safari, tap Share, then **Add to Home Screen**. It opens full-screen with the ALEA icon. The service worker caches only the app shell (HTML, CSS, JS, icons, font). **Forecasts are never cached and the app does not work offline**: without a connection it shows "You appear to be offline".

## Local development

```bash
python scripts/serve_api.py --ledger results/prospective/ledger.sqlite --port 8080
# open http://127.0.0.1:8080/
```

Restart the server after editing files in `web/` (files are loaded into memory at start-up from an allowlist). To serve the API without the web app, set `ALEA_WEB_DIR=none`. To point the front end at an API on another origin, set the `alea-api-base` meta tag in `web/index.html` and extend the CSP `connect-src`.

## Security headers

Every response carries a strict Content-Security-Policy (`default-src 'self'`, no inline scripts or styles, `frame-ancestors 'none'`), `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`, `Permissions-Policy` and `Cross-Origin-Opener-Policy`. API responses are `Cache-Control: no-store`. Only allowlisted regular files in `web/` are served; symlinks, dotfiles and path traversal return 404.

## Tested

See `RELEASE_1.0_READINESS.md` for what was and was not tested (notably: Chromium emulation of iPhone/iPad/desktop was tested; real Safari and a real iPhone were not).
