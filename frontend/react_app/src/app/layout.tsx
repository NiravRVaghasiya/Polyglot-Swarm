import type { Metadata, Viewport } from "next";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";
import { ServiceWorkerRegistrar } from "@/components/ServiceWorkerRegistrar";

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

// Next.js 14 wants the viewport in its own export (Gate E: mobile). Without
// this the app renders at desktop width on phones.
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#4f46e5",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <ServiceWorkerRegistrar />
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
