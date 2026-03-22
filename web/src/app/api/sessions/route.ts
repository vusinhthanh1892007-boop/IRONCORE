import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
    const apiKey =
        req.headers.get("X-IronCore-API-Key") ??
        req.headers.get("x-ironcore-api-key") ??
        "";

    try {
        const res = await fetch(`${BACKEND_URL}/v1/agent/sessions`, {
            headers: {
                "Content-Type": "application/json",
                ...(apiKey ? { "X-IronCore-API-Key": apiKey } : {}),
            },
        });
        if (res.ok) {
            const data = await res.json();
            return NextResponse.json(data);
        }
    } catch {
        // backend offline
    }

    // Return empty list if backend down — frontend handles gracefully
    return NextResponse.json([]);
}
