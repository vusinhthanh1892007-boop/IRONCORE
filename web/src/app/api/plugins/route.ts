import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
    const apiKey =
        req.headers.get("X-IronCore-API-Key") ??
        req.headers.get("x-ironcore-api-key") ??
        "";

    try {
        const res = await fetch(`${BACKEND_URL}/v1/tools`, {
            headers: {
                "Content-Type": "application/json",
                ...(apiKey ? { "X-IronCore-API-Key": apiKey } : {}),
            },
        });
        if (res.ok) {
            const tools = await res.json();
            // Map IronCore tool format → PluginInfo format for the frontend
            // Each tool treated as its own "plugin" (plugin_id = tool name)
            const plugins = (tools as Array<{
                name: string;
                description?: string;
                risk_level?: string;
            }>).map((t) => ({
                id: t.name,
                name: t.name
                    .split(/[_.]/)
                    .map((w: string) => w.charAt(0).toUpperCase() + w.slice(1))
                    .join(" "),
                version: "1.0.0",
                status: "active",
                tools_count: 1,
                description: t.description ?? "",
                risk_level: t.risk_level ?? "low",
            }));
            return NextResponse.json(plugins);
        }
    } catch {
        // backend offline
    }

    return NextResponse.json([]);
}
