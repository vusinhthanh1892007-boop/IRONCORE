import type { NextConfig } from "next";
import withPWA from "next-pwa";

const withPWAConfig = withPWA({
  dest: "public",
  register: true,
  skipWaiting: true,
  disable: process.env.NODE_ENV === "development",
  buildExcludes: [/middleware-manifest.json$/],
});

const nextConfig: NextConfig = {
  reactStrictMode: true,
};

export default withPWAConfig(nextConfig);
