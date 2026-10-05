const CACHE_NAME = "libim-v1";

self.addEventListener("install", (event) => {
    console.log("Service Worker LIBIM instalado");
    self.skipWaiting();
});

self.addEventListener("activate", (event) => {
    console.log("Service Worker LIBIM activado");
    event.waitUntil(self.clients.claim());
});