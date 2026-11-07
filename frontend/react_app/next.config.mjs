/** @type {import('next').NextConfig} */

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Security headers (ADR-0035, R8). The bearer token lives in localStorage,
// so the policy that matters most is connect-src: even if a script were
// injected, the browser may only talk to this origin and the API, which
// blocks sending a stolen token elsewhere. Next's hydration needs inline
// scripts, hence 'unsafe-inline' for script-src (no nonce pipeline yet).
const csp = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  `connect-src 'self' ${API_URL}`,
  "img-src 'self' data: blob:",
  "media-src 'self' data: blob:",
  "font-src 'self' data:",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "no-referrer" },
  // The microphone is used by voice practice on this origin only.
  { key: "Permissions-Policy", value: "camera=(), geolocation=(), microphone=(self)" },
];

const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // The API base URL is read at runtime from NEXT_PUBLIC_API_URL.
  env: {
    NEXT_PUBLIC_API_URL: API_URL,
  },
  async headers() {
    // Dev mode needs eval for fast refresh, so the policy applies to builds only.
    if (process.env.NODE_ENV !== "production") return [];
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
