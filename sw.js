const CACHE = 'garaje-v2';
const SHELL = ['./', './index.html', './manifest.json', './icon-192.png', './icon-512.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  const fuentes = url.hostname.indexOf('fonts.googleapis.com') >= 0 ||
                  url.hostname.indexOf('fonts.gstatic.com') >= 0;

  if (url.origin === location.origin && !fuentes) {
    // la app: red primero para ver los cambios al recargar, cache si no hay conexion
    e.respondWith(
      fetch(req).then(r => {
        const copia = r.clone();
        caches.open(CACHE).then(c => c.put(req, copia));
        return r;
      }).catch(() => caches.match(req).then(r => {
        if (r) return r;
        // solo devolvemos la app para navegaciones; para datos, error limpio
        return req.mode === 'navigate' ? caches.match('./index.html')
                                       : new Response('', { status: 504 });
      }))
    );
    return;
  }

  if (fuentes) {
    // tipografias: cache primero, se descargan una sola vez
    e.respondWith(
      caches.match(req).then(r => r || fetch(req).then(res => {
        const copia = res.clone();
        caches.open(CACHE).then(c => c.put(req, copia));
        return res;
      }).catch(() => new Response('', { status: 504 })))
    );
  }
});
