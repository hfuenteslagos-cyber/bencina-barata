const CACHE_NAME = 'bencina-barata-v1';
const STATIC_ASSETS = ['/', '/manifest.json'];

self.addEventListener('install', e => {
    e.waitUntil(caches.open(CACHE_NAME).then(c => c.addAll(STATIC_ASSETS)));
    self.skipWaiting();
});

self.addEventListener('activate', e => {
    e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))));
    self.clients.claim();
});

self.addEventListener('fetch', e => {
    if (e.request.url.includes('/api/')) return; // Never cache API calls
    e.respondWith(
        caches.match(e.request).then(r => r || fetch(e.request).then(res => {
            if (res.status === 200) {
                const clone = res.clone();
                caches.open(CACHE_NAME).then(c => c.put(e.request, clone));
            }
            return res;
        }))
    );
});
