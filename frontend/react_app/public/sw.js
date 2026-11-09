// Minimal app-shell service worker (Gate E: PWA/offline).
//
// Strategy:
// - Next's build assets (/_next/static/) have content-hashed names and never
//   change, so they are served cache-first.
// - Everything else from this origin (pages, manifest, icons) is
//   network-first, falling back to the cache when offline, so a deploy is
//   picked up on the next load.
// - API calls (authenticated, must be fresh), other origins and non-GET
//   requests are never touched.
//
// Bump CACHE when the caching rules change: activation deletes every other
// cache, which also clears assets of earlier releases.

const CACHE = "polyglot-shell-v2";
const SHELL = ["/", "/manifest.json"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.addAll(SHELL))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

function store(request, response) {
  if (response.ok && response.type === "basic") {
    const copy = response.clone();
    caches.open(CACHE).then((cache) => cache.put(request, copy));
  }
  return response;
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);

  if (request.method !== "GET") return;
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) return;

  // Immutable, content-hashed build assets: cache-first.
  if (url.pathname.startsWith("/_next/static/")) {
    event.respondWith(
      caches.match(request).then((cached) => cached || fetch(request).then((res) => store(request, res))),
    );
    return;
  }

  // Pages and other files: network-first; the cache (or the shell, for a
  // page) only when offline.
  event.respondWith(
    fetch(request)
      .then((res) => store(request, res))
      .catch(() =>
        caches
          .match(request)
          .then((cached) => cached || (request.mode === "navigate" ? caches.match("/") : undefined))
          .then((res) => res || Response.error()),
      ),
  );
});
