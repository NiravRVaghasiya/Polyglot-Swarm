/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // The API base URL is read at runtime from NEXT_PUBLIC_API_URL.
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000",
  },
};

export default nextConfig;
