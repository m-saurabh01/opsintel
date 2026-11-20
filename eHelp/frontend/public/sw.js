/**
 * Service Worker for eHelp offline support and caching
 * Installed at http://localhost:8123/sw.js
 */

const CACHE_VERSION = 'ehelp-v1';
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const API_CACHE = `${CACHE_VERSION}-api`;
const FILE_CACHE = `${CACHE_VERSION}-files`;

const STATIC_ASSETS = [
  '/',
  '/index.html',
  '/manifest.json',
];

// Install: pre-cache static assets
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) => {
      return cache.addAll(STATIC_ASSETS).catch(() => {
        // Fail gracefully if offline during install
        console.warn('Could not pre-cache assets (possibly offline)');
      });
    }).then(() => self.skipWaiting())
  );
});

// Activate: clean up old cache versions
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((names) => {
      return Promise.all(
        names
          .filter((name) => name.startsWith('ehelp-') && name !== STATIC_CACHE && name !== API_CACHE && name !== FILE_CACHE)
          .map((name) => caches.delete(name))
      );
    }).then(() => self.clients.claim())
  );
});

// Fetch: network-first for API, cache-first for static
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Skip non-GET, non-HTTP(S)
  if (request.method !== 'GET' || !url.protocol.startsWith('http')) {
    return;
  }

  // Static assets: cache-first
  if (url.pathname.match(/\.(css|js|png|jpg|jpeg|gif|webp|woff|woff2|ttf|svg)$/i)) {
    event.respondWith(
      caches.match(request).then((response) => {
        if (response) return response;
        return fetch(request).then((res) => {
          if (res.ok && url.hostname === 'localhost') {
            caches.open(STATIC_CACHE).then((cache) => cache.put(request, res.clone()));
          }
          return res;
        });
      }).catch(() => new Response('Not cached', { status: 503 }))
    );
    return;
  }

  // API calls: network-first with fallback
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok && request.method === 'GET') {
            caches.open(API_CACHE).then((cache) => cache.put(request, response.clone()));
          }
          return response;
        })
        .catch(() => {
          return caches.match(request).then((cached) => {
            return cached || new Response(
              JSON.stringify({ error: 'Offline: cached data unavailable' }),
              { status: 503, headers: { 'Content-Type': 'application/json' } }
            );
          });
        })
    );
    return;
  }

  // File downloads/previews: cache-first with long TTL
  if (url.pathname.startsWith('/uploads/') || url.pathname.startsWith('/api/file/')) {
    event.respondWith(
      caches.match(request).then((cached) => {
        if (cached) return cached;
        return fetch(request).then((response) => {
          if (response.ok && response.status === 200) {
            caches.open(FILE_CACHE).then((cache) => {
              cache.put(request, response.clone());
              // Cleanup: keep max 50 file entries
              cache.keys().then((keys) => {
                if (keys.length > 50) {
                  keys.slice(0, keys.length - 50).forEach((key) => cache.delete(key));
                }
              });
            });
          }
          return response;
        });
      }).catch(() => new Response('File unavailable', { status: 503 }))
    );
    return;
  }

  // Everything else: network-first
  event.respondWith(
    fetch(request)
      .then((response) => response)
      .catch(() => caches.match(request))
  );
});

// Background sync for offline document uploads (future feature)
self.addEventListener('sync', (event) => {
  if (event.tag === 'sync-uploads') {
    event.waitUntil(syncPendingUploads());
  }
});

async function syncPendingUploads() {
  const db = await openIndexedDB();
  const uploads = await db.getAll('pending-uploads');
  for (const upload of uploads) {
    try {
      await fetch('/api/upload', {
        method: 'POST',
        body: upload.formData,
      });
      await db.delete('pending-uploads', upload.id);
    } catch (err) {
      console.error('Upload sync failed:', err);
    }
  }
}

function openIndexedDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open('ehelp', 1);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
    req.onupgradeneeded = (event) => {
      const db = event.target.result;
      if (!db.objectStoreNames.contains('pending-uploads')) {
        db.createObjectStore('pending-uploads', { keyPath: 'id' });
      }
    };
  });
}
