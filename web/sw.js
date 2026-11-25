/* ALEA service worker: caches the app shell only, so the installed app opens
 * and can say it is offline. Forecast data (/v1/*, /health) is never cached:
 * predictions are always fetched live. */
const CACHE = 'alea-shell-v1';
const SHELL = ['./', 'index.html', 'assets/app.css', 'assets/app.js', 'manifest.webmanifest',
  'fonts/archivo-latin-var.woff2', 'icons/icon.svg', 'icons/icon-192.png', 'icons/icon-512.png',
  'icons/apple-touch-icon.png', 'icons/icon-maskable-512.png'];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== self.location.origin) return;
  if (url.pathname.includes('/v1/') || url.pathname.endsWith('/health') || url.pathname.endsWith('/metrics')) return;
  // Network first so a new release is picked up immediately; cache only as an offline fallback.
  event.respondWith(fetch(event.request).then((res) => {
    if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(event.request, copy)); }
    return res;
  }).catch(() => caches.match(event.request).then((hit) => hit || caches.match('index.html'))));
});
