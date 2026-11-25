/* ALEA web app: a read-only view of the forecasts frozen in the prospective ledger.
 * Every number shown comes from the ALEA API. Nothing is generated, smoothed or
 * re-computed in the browser except presentation (percent rounding, dates). */
(function () {
  'use strict';

  var API = (document.querySelector('meta[name="alea-api-base"]') || {}).content || '';
  var main = document.getElementById('main');
  var statusbar = document.getElementById('statusbar');
  var TIMEOUT_MS = 15000;
  var cache = {};

  var TEAM_NAMES = {
    'arsenal': 'Arsenal', 'aston villa': 'Aston Villa', 'bournemouth': 'Bournemouth', 'brentford': 'Brentford',
    'brighton and hove albion': 'Brighton & Hove Albion', 'chelsea': 'Chelsea', 'coventry city': 'Coventry City',
    'crystal palace': 'Crystal Palace', 'everton': 'Everton', 'fulham': 'Fulham', 'hull city': 'Hull City',
    'ipswich town': 'Ipswich Town', 'leeds united': 'Leeds United', 'liverpool': 'Liverpool',
    'manchester city': 'Manchester City', 'manchester united': 'Manchester United',
    'newcastle united': 'Newcastle United', 'nottingham forest': 'Nottingham Forest', 'sunderland': 'Sunderland',
    'tottenham': 'Tottenham Hotspur', 'west ham united': 'West Ham United', 'wolverhampton wanderers': 'Wolves'
  };

  var STATUS_LABEL = { settled: 'Settled', pending: 'Awaiting result', overdue: 'Result overdue', void: 'Void',
    conflict: 'Sources disagree', postponed: 'Postponed', abandoned: 'Abandoned' };

  // ------------------------------------------------------------------ helpers
  function esc(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function team(name) {
    if (!name) return '';
    return TEAM_NAMES[name] || name.replace(/\b\w/g, function (c) { return c.toUpperCase(); });
  }
  /* Largest-remainder rounding so the three displayed percentages always add to 100. */
  function pct3(p) {
    var raw = [p.home * 100, p.draw * 100, p.away * 100];
    var fl = raw.map(Math.floor);
    var left = 100 - fl.reduce(function (a, b) { return a + b; }, 0);
    raw.map(function (v, i) { return { i: i, r: v - fl[i] }; })
      .sort(function (a, b) { return b.r - a.r; })
      .slice(0, left).forEach(function (x) { fl[x.i] += 1; });
    return { home: fl[0], draw: fl[1], away: fl[2] };
  }
  function pct1(x) { return (x * 100).toFixed(1) + '%'; }
  var fmtDay = new Intl.DateTimeFormat(undefined, { weekday: 'long', day: 'numeric', month: 'long' });
  var fmtShort = new Intl.DateTimeFormat(undefined, { weekday: 'short', day: 'numeric', month: 'short' });
  var fmtTime = new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit' });
  var fmtStamp = new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZoneName: 'short' });
  var fmtUtc = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'UTC' });
  var fmtUk = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'Europe/London' });
  function d(s) { return new Date(s); }
  function dayKey(date) { return date.getFullYear() + '-' + (date.getMonth() + 1) + '-' + date.getDate(); }
  function relHours(iso) {
    var h = (Date.now() - d(iso).getTime()) / 36e5;
    if (h < 1) return 'less than an hour ago';
    if (h < 48) return Math.round(h) + ' hours ago';
    return Math.round(h / 24) + ' days ago';
  }
  function favourite(p) {
    var arr = [['home', p.home], ['draw', p.draw], ['away', p.away]].sort(function (a, b) { return b[1] - a[1]; });
    return arr[0][0];
  }
  function outcomeLabel(code, f) {
    return code === 'H' ? team(f.home) + ' win' : code === 'A' ? team(f.away) + ' win' : 'Draw';
  }
  /* Scheduled runs: Tuesday and Friday 06:00 UTC; a fixture is forecast by the first run
   * that is between 48 hours and 7 days before its listed kickoff. Shown as "expected". */
  function expectedForecastRun(kickoffIso) {
    var k = d(kickoffIso).getTime(), now = Date.now();
    var t = new Date(); t.setUTCHours(6, 0, 0, 0);
    for (var i = 0; i < 21; i++) {
      var day = t.getUTCDay();
      var ms = t.getTime();
      if ((day === 2 || day === 5) && ms >= now) {
        var lead = (k - ms) / 36e5;
        if (lead <= 168 && lead > 48) return t;
        if (lead <= 48) return null;
      }
      t = new Date(ms + 864e5);
    }
    return null;
  }

  // ------------------------------------------------------------------ API
  function ApiFailure(kind, message, status) { this.kind = kind; this.message = message; this.status = status; }
  function get(path, opts) {
    opts = opts || {};
    if (!opts.fresh && cache[path] && Date.now() - cache[path].t < 60000) return Promise.resolve(cache[path].v);
    var ctl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var timer = setTimeout(function () { if (ctl) ctl.abort(); }, TIMEOUT_MS);
    return fetch(API + path, { headers: { Accept: 'application/json' }, signal: ctl ? ctl.signal : undefined, cache: 'no-store' })
      .then(function (r) {
        clearTimeout(timer);
        return r.json().catch(function () { return null; }).then(function (body) {
          if (!r.ok) {
            var msg = body && body.error && body.error.message;
            if (r.status === 404) throw new ApiFailure('not_found', msg || 'Not found', 404);
            if (r.status === 503) throw new ApiFailure('unavailable', msg || 'Service unavailable', 503);
            throw new ApiFailure('error', msg || ('Request failed (' + r.status + ')'), r.status);
          }
          if (!body) throw new ApiFailure('error', 'The server returned an unreadable response', r.status);
          cache[path] = { t: Date.now(), v: body };
          return body;
        });
      }, function (e) {
        clearTimeout(timer);
        if (typeof navigator !== 'undefined' && navigator.onLine === false) throw new ApiFailure('offline', 'You appear to be offline.');
        if (e && e.name === 'AbortError') throw new ApiFailure('timeout', 'The server took too long to respond.');
        throw new ApiFailure('network', 'Could not reach the ALEA server.');
      });
  }

  // ------------------------------------------------------------------ chrome
  var ICON_INFO = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/></svg>';
  var ICON_WARN = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 2 20h20zM12 10v4M12 17v.5"/></svg>';

  function setNav(name) {
    document.querySelectorAll('[data-nav]').forEach(function (a) {
      if (a.getAttribute('data-nav') === name) a.setAttribute('aria-current', 'page');
      else a.removeAttribute('aria-current');
    });
  }
  function renderStatus(health) {
    if (!health) { statusbar.innerHTML = ''; return; }
    var f = health.freshness || {};
    var dot = health.status === 'ok' ? '' : health.status === 'degraded' ? ' dot--warn' : ' dot--error';
    var label = health.status === 'ok' ? 'Live' : health.status === 'degraded' ? 'Data may be stale' : 'Unavailable';
    var html = '<span class="pill"><span class="dot' + dot + '" aria-hidden="true"></span>' + label + '</span>';
    if (f.last_successful_run_at) {
      html += '<span class="pill" title="' + esc(fmtStamp.format(d(f.last_successful_run_at))) + '">Updated ' +
        esc(fmtShort.format(d(f.last_successful_run_at))) + ', ' + esc(fmtTime.format(d(f.last_successful_run_at))) + '</span>';
    }
    statusbar.innerHTML = html;
    statusbar.setAttribute('aria-label', 'Service status: ' + label);
  }
  function errorView(err, retry) {
    var text = {
      offline: ['You are offline', 'Forecasts need an internet connection. ALEA does not store predictions for offline use.'],
      timeout: ['The server is slow to respond', 'Please try again in a moment.'],
      network: ['Cannot reach ALEA', 'The server could not be reached. Check your connection and try again.'],
      unavailable: ['Forecasts are temporarily unavailable', 'The server is running but refused to serve forecasts because a safety check failed. This protects you from unverified numbers.'],
      not_found: ['Not found', 'There is no forecast with this link.'],
      error: ['Something went wrong', 'The request could not be completed.']
    }[err && err.kind] || ['Something went wrong', 'The request could not be completed.'];
    var detail = err && err.message && err.kind !== 'offline' && err.kind !== 'network' ? '<p class="xs muted">Server message: ' + esc(err.message) + '</p>' : '';
    main.innerHTML = '<div class="notice notice--error" role="alert">' + ICON_WARN + '<div class="stack"><p><strong>' + esc(text[0]) +
      '</strong></p><p>' + esc(text[1]) + '</p>' + detail +
      (retry ? '<p><button type="button" class="btn" data-retry>Try again</button></p>' : '') + '</div></div>';
    var b = main.querySelector('[data-retry]');
    if (b) b.addEventListener('click', function () { cache = {}; route(); });
  }
  function loading() { main.innerHTML = '<div class="loading" aria-busy="true"><span class="sr-only">Loading</span></div>'; }

  function probBar(p, big) {
    var r = pct3(p);
    return '<div class="bar' + (big ? ' bar--lg' : '') + '" role="img" aria-label="Home win ' + r.home + ' percent, draw ' + r.draw + ' percent, away win ' + r.away + ' percent">' +
      '<span class="h" data-w="' + (p.home * 100).toFixed(2) + '"></span><span class="d" data-w="' + (p.draw * 100).toFixed(2) +
      '"></span><span class="a" data-w="' + (p.away * 100).toFixed(2) + '"></span></div>';
  }

  function matchCard(f) {
    var p = f.probabilities, r = pct3(p), k = d(f.kickoff_at_listed);
    var top = f.top_scorelines && f.top_scorelines[0];
    return '<a class="match" href="#/match/' + encodeURIComponent(f.fixture_key) + '">' +
      '<div class="match__meta"><span>' + esc(fmtTime.format(k)) + ' · Premier League</span><span>Forecast ' + esc(fmtShort.format(d(f.predicted_at))) + '</span></div>' +
      '<div class="teams">' +
      '<div class="team-row"><span class="team">' + esc(team(f.home)) + '</span><span class="team-pct">' + r.home + '%</span></div>' +
      '<div class="team-row team-row--draw"><span class="team">Draw</span><span class="team-pct">' + r.draw + '%</span></div>' +
      '<div class="team-row"><span class="team">' + esc(team(f.away)) + '</span><span class="team-pct">' + r.away + '%</span></div>' +
      '</div>' + probBar(p) +
      '<div class="match__foot">' +
      (top ? '<span>Most likely score ' + esc(top.score) + ' (' + pct1(top.probability) + ')</span>' : '<span>Scorelines not recorded for this forecast</span>') +
      (f.prior_only ? '<span class="chip chip--warn">New team: league-average prior</span>' : '') +
      '</div></a>';
  }

  // ------------------------------------------------------------------ views
  function viewMatches() {
    setNav('matches');
    loading();
    return Promise.all([get('/v1/predictions/upcoming?days=14'), get('/v1/fixtures/upcoming?days=21').catch(function () { return null; })])
      .then(function (res) {
        var up = res[0], fx = res[1];
        var html = '<div class="page-head"><span class="eyebrow">Premier League 2026–27</span><h1>Upcoming matches</h1>' +
          '<p>Win, draw and loss probabilities from the ALEA model, published 2 to 7 days before kickoff and never changed afterwards.</p></div>';
        html += '<div class="notice">' + ICON_INFO + '<p><strong>Probabilities, not predictions of certainty.</strong> A 55% home win still fails 45 times in 100. In past seasons the bookmakers\u2019 closing odds were more accurate than ALEA; see <a href="#/history">Results</a>.</p></div>';
        (up.warnings || []).forEach(function (w) {
          html += '<div class="notice notice--warn mt-3">' + ICON_WARN + '<p><strong>Data warning.</strong> ' + esc(w) + '</p></div>';
        });
        html += '<section class="section" aria-labelledby="h-fc"><h2 id="h-fc">Forecasts</h2>';
        if (!up.predictions.length) {
          html += '<p class="sub">No published forecasts for the next 14 days yet. Forecasts appear after the scheduled run on Tuesday or Friday morning.</p>';
        } else {
          html += '<p class="sub">' + up.predictions.length + ' match' + (up.predictions.length === 1 ? '' : 'es') + '. Times shown in your time zone; listed kickoff times can change.</p>' +
            '<div class="legend mb-4" aria-hidden="true"><span><i class="lg-h"></i>Home win</span><span><i class="lg-d"></i>Draw</span><span><i class="lg-a"></i>Away win</span></div>';
          var groups = {}, order = [];
          up.predictions.slice().sort(function (a, b) { return d(a.kickoff_at_listed) - d(b.kickoff_at_listed); }).forEach(function (f) {
            var key = dayKey(d(f.kickoff_at_listed));
            if (!groups[key]) { groups[key] = []; order.push(key); }
            groups[key].push(f);
          });
          order.forEach(function (key) {
            html += '<div class="day"><h3>' + esc(fmtDay.format(d(groups[key][0].kickoff_at_listed))) + '</h3><div class="grid grid--2">' +
              groups[key].map(matchCard).join('') + '</div></div>';
          });
        }
        html += '</section>';
        if (fx && fx.available) {
          var waiting = fx.fixtures.filter(function (f) { return f.forecast_status !== 'forecast_published'; });
          html += '<section class="section" aria-labelledby="h-next"><h2 id="h-next">Later fixtures</h2>' +
            '<p class="sub">Listed fixtures without a forecast yet. Forecasts are made only 2 to 7 days ahead, using every result available at that time.</p>';
          if (!waiting.length) html += '<p class="muted small">Every listed fixture in the next three weeks already has a forecast.</p>';
          else {
            var byDay = {}, days = [];
            waiting.forEach(function (f) {
              var key = dayKey(d(f.kickoff_at_listed));
              if (!byDay[key]) { byDay[key] = []; days.push(key); }
              byDay[key].push(f);
            });
            days.forEach(function (key, i) {
              var list = byDay[key];
              var labels = list.map(function (f) {
                if (f.forecast_status === 'not_forecast') return 'No forecast (under 48 h)';
                var run = expectedForecastRun(f.kickoff_at_listed);
                return run ? 'Forecast due ' + fmtShort.format(run) : 'Awaiting forecast';
              });
              var same = labels.every(function (l) { return l === labels[0]; });
              var block = '<div class="day"><h3 class="day__head"><span>' + esc(fmtDay.format(d(list[0].kickoff_at_listed))) + '</span>' +
                (same ? '<span class="chip">' + esc(labels[0]) + '</span>' : '') + '</h3><div class="rows">' +
                list.map(function (f, j) {
                  var k = d(f.kickoff_at_listed);
                  return '<div class="row"><div class="row__teams">' + esc(team(f.home)) + ' v ' + esc(team(f.away)) + '</div><div class="row__when">' +
                    esc(fmtTime.format(k)) + (same ? '' : '<br>' + esc(labels[j])) + '</div></div>';
                }).join('') + '</div></div>';
              html += i < 2 ? block : (i === 2 ? '<details class="more"><summary>Show ' + (days.length - 2) + ' more matchday' + (days.length - 2 === 1 ? '' : 's') + '</summary>' : '') + (i >= 2 ? block : '');
            });
            if (days.length > 2) html += '</details>';
          }
          html += '</section>';
        } else if (fx && !fx.available) {
          html += '<section class="section"><h2>Later fixtures</h2><p class="sub">' + esc(fx.message) + '</p></section>';
        }
        main.innerHTML = html;
      });
  }

  function explanation(f) {
    var fav = favourite(f.probabilities), r = pct3(f.probabilities);
    var favText = fav === 'home' ? team(f.home) + ' win' : fav === 'away' ? team(f.away) + ' win' : 'a draw';
    var favPct = r[fav];
    var parts = [];
    parts.push('The single most likely outcome is ' + esc(favText) + ' at ' + favPct + '%. That is the model\u2019s best estimate of how often this result happens in matches like this one, not a guarantee; the other outcomes together have ' + (100 - favPct) + '%.');
    if (f.expected_goals) {
      parts.push('The model expects about ' + f.expected_goals.home.toFixed(2) + ' goals for ' + esc(team(f.home)) + ' and ' + f.expected_goals.away.toFixed(2) + ' for ' + esc(team(f.away)) +
        '. These come from each side\u2019s estimated attacking and defensive strength plus a home-advantage term.');
    }
    parts.push('ALEA is a Dixon\u2013Coles goals model fitted to ' + (f.training_matches ? esc(f.training_matches.toLocaleString()) + ' ' : '') +
      'past Premier League results, with recent matches weighted more. It uses final scores only. It does not know about injuries, suspensions, line-ups, transfers, managers, weather, betting odds or news.');
    if (f.prior_only) parts.push('At least one team had no previous results in the training data, so its strength is a league-average prior. Treat this forecast as especially uncertain.');
    return parts.map(function (p) { return '<p>' + p + '</p>'; }).join('');
  }

  function viewMatch(key) {
    setNav('matches');
    loading();
    return get('/v1/predictions/' + encodeURIComponent(key)).then(function (f) {
      var p = f.probabilities, r = pct3(p), k = d(f.kickoff_at_listed), fav = favourite(p);
      var settled = f.status === 'settled' && f.result;
      var html = '<a class="back" href="#/">\u2190 All matches</a>';
      html += '<div class="fixture-head"><span class="eyebrow">Premier League 2026–27 · ' + esc(fmtDay.format(k)) + '</span>' +
        '<h1>' + esc(team(f.home)) + '<span class="vs">v</span>' + esc(team(f.away)) + '</h1>' +
        '<p class="muted small">Listed kickoff ' + esc(fmtTime.format(k)) + ' your time (' + esc(fmtUk.format(k)) + ' UK). Broadcasters can move kickoffs.</p></div>';
      if (settled) {
        html += '<div class="notice mb-4">' + ICON_INFO + '<p><strong>Final score ' + esc(team(f.home)) + ' ' + f.result.home_goals + '\u2013' + f.result.away_goals + ' ' + esc(team(f.away)) +
          '.</strong> ALEA had given this result ' + pct1(p[{ H: 'home', D: 'draw', A: 'away' }[f.result.outcome]]) + '. The forecast below is exactly as published before kickoff.</p></div>';
      } else if (f.status && f.status !== 'pending') {
        html += '<div class="notice notice--warn mb-4">' + ICON_WARN + '<p><strong>' + esc(STATUS_LABEL[f.status] || f.status) + '.</strong> ' + esc(f.status_reason || '') + '</p></div>';
      }
      html += '<div class="grid">';
      html += '<section class="panel" aria-labelledby="h-p"><h2 id="h-p">Outcome probabilities</h2><div class="probs">' +
        '<div class="prob prob--h' + (fav === 'home' ? ' prob--top' : '') + '"><div class="prob__label">' + esc(team(f.home)) + ' win</div><div class="prob__value">' + r.home + '%</div></div>' +
        '<div class="prob' + (fav === 'draw' ? ' prob--top' : '') + '"><div class="prob__label">Draw</div><div class="prob__value">' + r.draw + '%</div></div>' +
        '<div class="prob prob--a' + (fav === 'away' ? ' prob--top' : '') + '"><div class="prob__label">' + esc(team(f.away)) + ' win</div><div class="prob__value">' + r.away + '%</div></div>' +
        '</div>' + probBar(p, true) + '<p class="xs muted mt-2">Rounded to whole percentages that add to 100. Exact values: ' + pct1(p.home) + ' / ' + pct1(p.draw) + ' / ' + pct1(p.away) + '.</p></section>';

      html += '<div class="grid grid--2">';
      html += '<section class="panel" aria-labelledby="h-s"><h2 id="h-s">Most likely scorelines</h2>';
      if (f.top_scorelines && f.top_scorelines.length) {
        var max = f.top_scorelines[0].probability;
        html += '<div class="scores">' + f.top_scorelines.map(function (s) {
          return '<div class="score"><b>' + esc(s.score) + '</b><div class="score__bar"><span data-w="' + (s.probability / max * 100).toFixed(1) + '"></span></div><span class="score__p">' + pct1(s.probability) + '</span></div>';
        }).join('') + '</div><p class="xs muted mt-3">Home score first. Exact scores are hard to call: even the most likely one, ' + esc(f.top_scorelines[0].score) + ', has only ' + pct1(f.top_scorelines[0].probability) + '.</p>';
      } else {
        html += '<p class="muted small">Not recorded for this forecast. Scorelines and expected goals are stored for forecasts published from release 1.0 onwards; earlier forecasts are never recalculated after publication.</p>';
      }
      html += '</section>';
      html += '<section class="panel" aria-labelledby="h-x"><h2 id="h-x">Expected goals (model)</h2>';
      if (f.expected_goals) {
        html += '<div class="xg"><div><div class="xg__n">' + f.expected_goals.home.toFixed(2) + '</div><div class="xg__t">' + esc(team(f.home)) + '</div></div><div class="muted">v</div><div><div class="xg__n">' + f.expected_goals.away.toFixed(2) + '</div><div class="xg__t">' + esc(team(f.away)) + '</div></div></div>' +
          '<p class="xs muted mt-3">The model\u2019s scoring rates for this match, derived from past results. Not shot-based xG.</p>';
      } else {
        html += '<p class="muted small">Not recorded for this forecast.</p>';
      }
      html += '</section></div>';

      html += '<section class="panel" aria-labelledby="h-w"><h2 id="h-w">What this forecast is based on</h2>' + explanation(f) + '</section>';

      html += '<section class="panel" aria-labelledby="h-d"><h2 id="h-d">Forecast record</h2><dl class="kv">' +
        '<dt>Model</dt><dd>' + esc(f.model_version) + ' (frozen champion)</dd>' +
        '<dt>Published</dt><dd>' + esc(fmtStamp.format(d(f.predicted_at))) + '</dd>' +
        '<dt>Status</dt><dd>' + esc(STATUS_LABEL[f.status] || f.status || 'Awaiting result') + '</dd>' +
        (f.training_matches ? '<dt>Training results</dt><dd>' + esc(f.training_matches.toLocaleString()) + ' matches</dd>' : '') +
        (f.results_source_revision ? '<dt>Results source</dt><dd><a href="https://en.wikipedia.org/w/index.php?oldid=' + encodeURIComponent(f.results_source_revision) + '" rel="noopener">Wikipedia revision ' + esc(f.results_source_revision) + '</a></dd>' : '') +
        (f.training_data_sha256 ? '<dt>Training data hash</dt><dd class="mono">' + esc(f.training_data_sha256.slice(0, 16)) + '\u2026</dd>' : '') +
        (f.code_sha ? '<dt>Code version</dt><dd class="mono">' + esc(f.code_sha.slice(0, 12)) + '</dd>' : '') +
        '</dl></section>';

      if (f.challengers && f.challengers.length) {
        html += '<details class="panel"><summary>Experimental challenger models</summary><p class="small muted">Recorded for research only. They are not validated and are not ALEA\u2019s forecast. A challenger is only considered after 300 settled paired matches.</p><div class="table-wrap"><table><thead><tr><th>Model</th><th class="num">Home</th><th class="num">Draw</th><th class="num">Away</th></tr></thead><tbody>' +
          f.challengers.map(function (c) { var q = pct3(c.probabilities); return '<tr><td>' + esc(c.model_id) + '</td><td class="num">' + q.home + '%</td><td class="num">' + q.draw + '%</td><td class="num">' + q.away + '%</td></tr>'; }).join('') +
          '</tbody></table></div></details>';
      }
      html += '</div>';
      main.innerHTML = html;
      document.title = team(f.home) + ' v ' + team(f.away) + ' · ALEA';
    });
  }

  function viewHistory(filter) {
    setNav('history');
    loading();
    filter = filter || 'all';
    return Promise.all([get('/v1/predictions/history?limit=500'), get('/v1/evaluation')]).then(function (res) {
      var hist = res[0], ev = res[1];
      var ch = ev.champion || {}, n = ch.n || 0;
      var html = '<div class="page-head"><span class="eyebrow">Track record</span><h1>Results</h1><p>Every forecast ALEA has published, the real result and how the model scored. Forecasts are stored in an append-only ledger and are never edited once published.</p></div>';
      html += '<section aria-labelledby="h-live"><h2 id="h-live" class="sr-only">Live performance</h2>';
      var counts = (ev.counts && ev.counts.by_status) || {};
      if (!n) {
        html += '<div class="stats"><div class="stat"><div class="stat__label">Forecasts published</div><div class="stat__value">' + esc(ev.counts ? ev.counts.champion_forecasts : hist.total) + '</div></div>' +
          '<div class="stat"><div class="stat__label">Settled</div><div class="stat__value">0</div><div class="stat__note">No results recorded yet</div></div>' +
          '<div class="stat"><div class="stat__label">Awaiting result</div><div class="stat__value">' + esc((counts.pending || 0) + (counts.overdue || 0)) + '</div></div>' +
          '<div class="stat"><div class="stat__label">Validation target</div><div class="stat__value">300</div><div class="stat__note">settled matches</div></div></div>';
        html += '<p class="small muted mt-3">Live performance statistics appear once matches are settled from final results. No numbers are shown before then.</p>';
      } else {
        html += '<div class="stats">' +
          stat('Settled forecasts', n, 'of 300 needed for a firm verdict') +
          stat('Log loss', ch.log_loss.toFixed(3), join(ci(ch.log_loss_ci95, 3), 'lower is better')) +
          stat('Brier score', ch.brier.toFixed(3), join(ci(ch.brier_ci95, 3), 'lower is better')) +
          stat('Most likely outcome right', (ch.accuracy * 100).toFixed(0) + '%', ci(ch.accuracy_ci95, 0, true)) + '</div>';
        if (n < 300) html += '<div class="notice notice--warn mt-3">' + ICON_WARN + '<p><strong>Preliminary.</strong> ' + n + ' settled matches is too few to judge the model.' + (ch.log_loss_ci95 ? ' The 95% intervals show how wide the uncertainty still is.' : ' Intervals appear once forecasts span at least two weeks.') + '</p></div>';
      }
      html += '</section>';

      html += '<section class="section" aria-labelledby="h-bt"><h2 id="h-bt">Historical benchmark</h2><p class="sub">Retrospective test on 1,140 Premier League matches (2023–24 to 2025–26) against bookmakers\u2019 closing odds. Lower log loss is better.</p>' +
        '<div class="panel"><div class="table-wrap"><table><thead><tr><th></th><th class="num">ALEA</th><th class="num">Closing market</th></tr></thead><tbody>' +
        '<tr><td>Log loss</td><td class="num">0.982</td><td class="num">0.960</td></tr>' +
        '<tr><td>Brier score</td><td class="num">0.585</td><td class="num">0.570</td></tr>' +
        '<tr><td>Most likely outcome right</td><td class="num">52.8%</td><td class="num">55.0%</td></tr></tbody></table></div>' +
        '<p class="small mt-3"><strong>The market was more accurate.</strong> ALEA\u2019s log loss was 0.022 worse (95% interval 0.012 to 0.032). ALEA is a transparent research model, not a way to beat the bookmakers.</p></div></section>';

      var items = hist.predictions.slice().sort(function (a, b) { return d(b.kickoff_at_listed) - d(a.kickoff_at_listed); });
      var shown = items.filter(function (f) { return filter === 'all' || (filter === 'settled' ? f.status === 'settled' : f.status !== 'settled'); });
      html += '<section class="section" aria-labelledby="h-all"><h2 id="h-all">All forecasts</h2><div class="filters" role="group" aria-label="Filter forecasts">' +
        ['all', 'settled', 'open'].map(function (k) { return '<button type="button" data-filter="' + k + '" aria-pressed="' + (k === filter) + '">' + { all: 'All', settled: 'Settled', open: 'Awaiting result' }[k] + '</button>'; }).join('') + '</div>';
      if (!shown.length) html += '<p class="muted small">Nothing to show for this filter yet.</p>';
      else {
        html += '<div class="rows">' + shown.map(function (f) {
          var q = pct3(f.probabilities), res;
          if (f.status === 'settled' && f.result) {
            var given = f.probabilities[{ H: 'home', D: 'draw', A: 'away' }[f.result.outcome]];
            res = '<span class="result">' + f.result.home_goals + '\u2013' + f.result.away_goals + '</span> <span class="xs muted">' + esc(outcomeLabel(f.result.outcome, f)) + ', ALEA gave it ' + pct1(given) + '</span>';
          } else {
            res = '<span class="chip' + (f.status === 'pending' ? '' : ' chip--warn') + '">' + esc(STATUS_LABEL[f.status] || f.status) + '</span>';
          }
          return '<a class="hrow" href="#/match/' + encodeURIComponent(f.fixture_key) + '"><div class="hrow__top"><span class="row__teams">' + esc(team(f.home)) + ' v ' + esc(team(f.away)) + '</span>' +
            '<span class="xs muted">' + esc(fmtShort.format(d(f.kickoff_at_listed))) + '</span></div><div class="hrow__bottom"><span class="small"><span class="sr-only">Home, draw, away: </span>' + q.home + ' / ' + q.draw + ' / ' + q.away + '%</span>' + res + '</div></a>';
        }).join('') + '</div>';
      }
      html += '</section>';
      main.innerHTML = html;
      main.querySelectorAll('[data-filter]').forEach(function (b) {
        b.addEventListener('click', function () { viewHistory(b.getAttribute('data-filter')).then(applyWidths).catch(fail); });
      });
    });
    function stat(label, value, note) {
      return '<div class="stat"><div class="stat__label">' + esc(label) + '</div><div class="stat__value">' + esc(value) + '</div><div class="stat__note">' + esc(note || '') + '</div></div>';
    }
    function join(a, b) { return a ? a + ' · ' + b : b; }
    function ci(c, digits, asPct) {
      if (!c) return '';
      return asPct ? '95% interval ' + (c[0] * 100).toFixed(0) + '\u2013' + (c[1] * 100).toFixed(0) + '%' : '95% interval ' + c[0].toFixed(digits) + '\u2013' + c[1].toFixed(digits);
    }
  }

  function viewAbout() {
    setNav('about');
    loading();
    return get('/v1/status').catch(function () { return null; }).then(function (st) {
      var champ = st && st.champion;
      var html = '<div class="page-head"><span class="eyebrow">Method and limits</span><h1>How ALEA works</h1></div><div class="prose">';
      html += '<p>ALEA estimates the chance of a home win, a draw and an away win for English Premier League matches. It is a personal research project that keeps a public, tamper-evident record of every forecast so its accuracy can be judged honestly.</p>';
      html += '<h2>How a forecast is made</h2><ul>' +
        '<li>Twice a week (Tuesday and Friday, 06:00 UTC) a scheduled job collects the latest results and the fixture list.</li>' +
        '<li>It refits the frozen champion model, a Dixon\u2013Coles goals model, on every result available at that moment. Recent matches count more.</li>' +
        '<li>Matches listed 2 to 7 days ahead get a forecast. It is written once to an append-only ledger with a timestamp, the data hash and the code version.</li>' +
        '<li>After the match, the final score is recorded only when the results source is consistent, and the forecast is scored.</li></ul>';
      html += '<h2>What ALEA does not know</h2><p>The model uses final scores only. It does not use injuries, suspensions, line-ups, transfers, managerial changes, weather, travel, betting odds or news. If something important happened since the last results, the forecast does not reflect it.</p>';
      html += '<h2>How accurate is it?</h2><p>On 1,140 past matches (2023\u201324 to 2025\u201326) ALEA was less accurate than bookmakers\u2019 closing odds. Its probabilities are reasonably calibrated: when it says 50%, the event happened close to half the time. Live forecasts are being tracked from November 2026. At least 300 settled matches are needed before its live accuracy can be judged, which will not happen before the 2027\u201328 season.</p>';
      html += '<h2>Not betting advice</h2><p>ALEA does not recommend bets and makes no claim to beat the market. Use the numbers for interest and analysis only.</p>';
      html += '<h2>Model and service</h2><ul>' +
        '<li>Champion model: ' + esc(champ ? champ.model_version : 'alea-dc-v2.4.1') + ' (frozen; file hash verified on every request)</li>' +
        (st ? '<li>Ledger: ' + esc(st.ledger.champion_forecasts) + ' champion forecasts, ' + esc(st.ledger.outcomes) + ' settled results, integrity check ' + esc(st.ledger.sqlite_integrity_check) + '</li>' : '') +
        '<li>Predictions need a connection. The installed app keeps only its layout offline, never forecasts.</li></ul>';
      html += '<h2>Data sources and licences</h2><ul>' +
        '<li>Current-season results: Wikipedia contributors, \u201c<a href="https://en.wikipedia.org/wiki/2026%E2%80%9327_Premier_League" rel="noopener">2026\u201327 Premier League</a>\u201d, licensed <a href="https://creativecommons.org/licenses/by-sa/4.0/" rel="noopener">CC BY-SA 4.0</a>. Each forecast links to the exact revision used.</li>' +
        '<li>Fixtures and historical results: <a href="https://github.com/openfootball/football.json" rel="noopener">OpenFootball football.json</a>, CC0 1.0.</li>' +
        '<li>Typeface: Archivo by Omnibus-Type, SIL Open Font License 1.1.</li>' +
        '<li>Bookmaker odds were used only for the offline benchmark above and are not published here.</li></ul>';
      html += '<h2>Source code</h2><p>The model, the ledger and this site are open source on <a href="https://github.com/gopolang-453/alea" rel="noopener">GitHub</a>.</p>';
      html += '</div>';
      main.innerHTML = html;
    });
  }

  // ------------------------------------------------------------------ router
  function fail(err) { errorView(err, true); }
  /* Widths are set through the CSSOM (allowed by the CSP), never via inline style attributes. */
  function applyWidths() {
    main.querySelectorAll('[data-w]').forEach(function (el) { el.style.width = el.getAttribute('data-w') + '%'; });
  }
  function route() {
    var h = location.hash || '#/';
    document.title = 'ALEA · Premier League forecasts';
    var p;
    if (h.indexOf('#/match/') === 0) p = viewMatch(decodeURIComponent(h.slice(8)));
    else if (h === '#/history') p = viewHistory();
    else if (h === '#/about') p = viewAbout();
    else p = viewMatches();
    p.then(function () { applyWidths(); main.focus({ preventScroll: true }); }).catch(fail);
    window.scrollTo(0, 0);
  }
  function refreshHealth() {
    get('/health', { fresh: true }).then(renderStatus, function (e) {
      if (e && e.kind === 'unavailable') renderStatus({ status: 'unhealthy' });
      else statusbar.innerHTML = '<span class="pill"><span class="dot dot--error" aria-hidden="true"></span>' + (e && e.kind === 'offline' ? 'Offline' : 'Server unreachable') + '</span>';
    });
  }
  window.addEventListener('hashchange', route);
  window.addEventListener('online', function () { cache = {}; refreshHealth(); route(); });
  window.addEventListener('offline', refreshHealth);
  refreshHealth();
  route();

  var local = location.hostname === 'localhost' || location.hostname === '127.0.0.1';
  if ('serviceWorker' in navigator && (location.protocol === 'https:' || local)) {
    navigator.serviceWorker.register('sw.js').catch(function () { /* installability is optional */ });
  }
})();
