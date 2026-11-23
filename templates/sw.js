/* Hizmet betiği. Sayfalar ve randevu verisi hiçbir zaman saklanmaz: her istek ağa gider.
   Tek işi, bağlantı yokken sayfa açılmak istendiğinde çevrimdışı sayfasını göstermektir. */
const CACHE = 'kr-{{ version }}';
const OFFLINE = '{% url "offline" %}';

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.add(new Request(OFFLINE, { cache: 'reload' }))).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter((key) => key.startsWith('kr-') && key !== CACHE).map((key) => caches.delete(key)));
    if (self.registration.navigationPreload) await self.registration.navigationPreload.enable();   /* betik uyanırken istek yola çıkmış olur */
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.mode !== 'navigate' || request.method !== 'GET') return;   /* form gönderimi ve dosyalar tarayıcıya kalır */
  event.respondWith((async () => {
    try {
      return (await event.preloadResponse) || (await fetch(request));
    } catch (error) {
      return (await caches.match(OFFLINE)) || Response.error();
    }
  })());
});
