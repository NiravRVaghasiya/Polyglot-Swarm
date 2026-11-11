import type { Metadata, Viewport } from "next";
import { Plus_Jakarta_Sans } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";
import { ServiceWorkerRegistrar } from "@/components/ServiceWorkerRegistrar";
import { MotionProvider } from "@/components/ui/MotionProvider";

// Self-hosted by next/font at build time, so the CSP's font-src 'self' holds
// and there is no runtime request to Google.
const sans = Plus_Jakarta_Sans({
  subsets: ["latin", "latin-ext"],
  display: "swap",
  variable: "--font-jakarta",
});

export const metadata: Metadata = {
  title: "Polyglot Swarm",
  description: "Multi-agent AI language tutor",
  manifest: "/manifest.json",
  appleWebApp: {
    capable: true,
    title: "Polyglot Swarm",
    statusBarStyle: "default",
  },
};

// Next.js wants the viewport in its own export (Gate E: mobile). Without
// this the app renders at desktop width on phones.
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#4f46e5" },
    { media: "(prefers-color-scheme: dark)", color: "#0a0c16" },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={sans.variable}>
      <body>
        <ServiceWorkerRegistrar />
        <MotionProvider>
          <AuthProvider>{children}</AuthProvider>
        </MotionProvider>
      </body>
    </html>
  );
}
