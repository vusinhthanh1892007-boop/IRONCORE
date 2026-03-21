// Type shim for next-pwa (no @types package available)
declare module "next-pwa" {
    import type { NextConfig } from "next";
    interface PWAConfig {
        dest?: string;
        register?: boolean;
        skipWaiting?: boolean;
        disable?: boolean;
        buildExcludes?: RegExp[];
        fallbacks?: Record<string, string>;
        [key: string]: unknown;
    }
    function withPWA(config: PWAConfig): (nextConfig: NextConfig) => NextConfig;
    export default withPWA;
}
