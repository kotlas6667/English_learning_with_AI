/* EngLearning PWA service worker — static shell only; /api is network-first. */
const CACHE_NAME = "englearning-shell-v62";
const SHELL_URLS = [
  "/",
  "/static/index.html",
  "/static/app.js?v=62",
  "/static/v2-shell.js?v=62",
  "/static/styles.css?v=62",
  "/static/manifest.webmanifest",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_URLS)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") {
    return;
  }
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) {
    return;
  }

  // API: network-first (fall back to cache only if offline and previously cached).
  if (url.pathname.startsWith("/api")) {
    event.respondWith(
      fetch(req)
        .then((res) => res)
        .catch(() => caches.match(req))
    );
    return;
  }

  // Shell assets: cache-first with network refresh.
  event.respondWith(
    caches.match(req).then((cached) => {
      const network = fetch(req)
        .then((res) => {
          const path = url.pathname + url.search;
          const cacheable =
            SHELL_URLS.includes(url.pathname)
            || SHELL_URLS.includes(path)
            || url.pathname.startsWith("/static/");
          if (res && res.ok && cacheable) {
            const clone = res.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(req, clone));
          }
          return res;
        })
        .catch(() => cached);
      return cached || network;
    })
  );
});
