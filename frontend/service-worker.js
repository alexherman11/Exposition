const CACHE = "expo-concierge-v3";
const CORE = ["/", "/index.html", "/css/app.css", "/js/app.js", "/js/map.js", "/js/schedule.js", "/js/chat.js", "/manifest.json"];

self.addEventListener("install", e => {
  // Skip pre-caching core files entirely during local dev so file edits
  // always reach the browser. Activate immediately.
  self.skipWaiting();
});

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET") return;
  // Network-first for everything. Only fall back to cache (warm offline-shell)
  // if the network fetch fails entirely.
  e.respondWith(
    fetch(req).then(resp => {
      // Don't cache API or websocket
      if (!req.url.includes("/api/") && !req.url.includes("/ws/")) {
        const copy = resp.clone();
        caches.open(CACHE).then(c => c.put(req, copy));
      }
      return resp;
    }).catch(() => caches.match(req).then(m => m || caches.match("/")))
  );
});
