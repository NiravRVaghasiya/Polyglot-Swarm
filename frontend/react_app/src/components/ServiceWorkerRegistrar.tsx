"use client";

// Registers the service worker so the app is installable and shells load
// offline (Gate E: PWA/mobile). No-op when the browser has no service-worker
// support or in a non-secure context; failures are swallowed so a registration
// problem never breaks the app.

import { useEffect } from "react";

export function ServiceWorkerRegistrar() {
  useEffect(() => {
    if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) return;
    const register = () => {
      navigator.serviceWorker.register("/sw.js").catch(() => {
        // Registration is best-effort; the app works without it.
      });
    };
    if (document.readyState === "complete") register();
    else window.addEventListener("load", register, { once: true });
  }, []);

  return null;
}
