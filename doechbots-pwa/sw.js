/* DoechBots Panel hizmet betiği (service worker).
   Panel sayfaları ve bot verisi hiçbir zaman önbelleğe alınmaz: her istek ağa gider, böylece
   bot durumu hep günceldir ve oturum bilgisi telefonda saklanmaz.
   Tek işi: bağlantı yokken bir sayfa açılmak istenirse çevrimdışı sayfasını göstermek.
   Bu dosya sitenin KÖKÜNDEN (/sw.js) sunulmalı, yoksa tüm paneli kapsayamaz. */
const VERSION = '1';                       /* offline.html değişince artır */
const CACHE = 'doechbots-' + VERSION;
const OFFLINE = '/offline.html';

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.addAll([
        new Request(OFFLINE, { cache: 'reload' }),
        new Request('/icons/icon-192.png', { cache: 'reload' }),
      ]))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter((k) => k.startsWith('doechbots-') && k !== CACHE).map((k) => caches.delete(k)));
    if (self.registration.navigationPreload) await self.registration.navigationPreload.enable();
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  /* Çevrimdışı sayfasının kendi ikonu */
  if (request.method === 'GET' && new URL(request.url).pathname === '/icons/icon-192.png') {
    event.respondWith(fetch(request).catch(() => caches.match(request)));
    return;
  }
  /* Form gönderimi, API çağrıları, dosyalar: tarayıcıya kalır, betik karışmaz */
  if (request.mode !== 'navigate' || request.method !== 'GET') return;
  event.respondWith((async () => {
    try {
      return (await event.preloadResponse) || (await fetch(request));
    } catch (error) {
      return (await caches.match(OFFLINE)) || Response.error();
    }
  })());
});
