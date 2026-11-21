// Video Finder service worker: makes the app installable, opens fast, and shows a friendly
// screen when offline. Searches, videos and thumbnails always come live from the server.
const VERSION = 'vf-2';
const SHELL = '/offline';
const PRECACHE = [SHELL, '/static/theme.css?v=9', '/static/icons/icon-192.png', '/static/logo-light.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(VERSION).then(c => c.addAll(PRECACHE.map(u => new Request(u, { cache: 'reload' })))).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== VERSION).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});

const fromCacheThenRefresh = async req => {
  const cache = await caches.open(VERSION);
  const hit = await cache.match(req);
  const fresh = fetch(req).then(r => { if (r.ok && r.type !== 'opaqueredirect') cache.put(req, r.clone()); return r; }).catch(() => hit);
  return hit || fresh;
};

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (req.mode === 'navigate') {  // pages: always live, offline screen if there is no connection
    e.respondWith(fetch(req).catch(async () => (await caches.match(SHELL)) || Response.error()));
    return;
  }
  if (url.origin === location.origin && url.pathname.startsWith('/static/') && !req.headers.has('range')) {
    e.respondWith(fromCacheThenRefresh(req));  // design files: instant from the phone, refreshed in the background
    return;
  }
  if (url.hostname === 'fonts.googleapis.com' || url.hostname === 'fonts.gstatic.com') {
    e.respondWith(fromCacheThenRefresh(req));
  }
  // everything else (API, videos, thumbnails, voice) goes straight to the network
});
