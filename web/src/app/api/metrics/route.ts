import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
    const apiKey =
        req.headers.get("X-IronCore-API-Key") ??
        req.headers.get("x-ironcore-api-key") ??
        "";

    const headers: Record<string, string> = {
        "Content-Type": "application/json",
        ...(apiKey ? { "X-IronCore-API-Key": apiKey } : {}),
    };

    // Try Enterprise budget snapshot first (most accurate)
    try {
        const budgetRes = await fetch(
            `${BACKEND_URL}/enterprise/budget/snapshot?window=daily`,
            { headers }
        );
        if (budgetRes.ok) {
            const budgetData = (await budgetRes.json()) as {
                snapshot?: {
                    total_cost_usd?: number;
                    total_tokens?: number;
                    total_calls?: number;
                };
            };
            const snap = budgetData.snapshot ?? {};
            return NextResponse.json({
                total_api_calls: snap.total_calls ?? 0,
                cache_hits: 0,
                cache_hit_rate: 0,
                tokens_saved_by_cache: 0,
                tokens_saved_by_compression: 0,
                total_cost_usd: snap.total_cost_usd ?? 0,
                savings_pct: 0,
                time_series: [],
                top_sessions: [],
            });
        }
    } catch {
        // fall through to health check
    }

    // Fallback: /health endpoint
    try {
        const healthRes = await fetch(`${BACKEND_URL}/health`, { headers });
        if (healthRes.ok) {
            const health = (await healthRes.json()) as {
                sessions?: number;
                tools?: number;
            };
            return NextResponse.json({
                total_api_calls: health.sessions ?? 0,
                cache_hits: 0,
                cache_hit_rate: 0,
                tokens_saved_by_cache: 0,
                tokens_saved_by_compression: 0,
                total_cost_usd: 0,
                savings_pct: 0,
                time_series: [],
                top_sessions: [],
            });
        }
    } catch {
        // backend unreachable
    }

    // Backend offline: return empty metrics (no crash)
    return NextResponse.json({
        total_api_calls: 0,
        cache_hits: 0,
        cache_hit_rate: 0,
        tokens_saved_by_cache: 0,
        tokens_saved_by_compression: 0,
        total_cost_usd: 0,
        savings_pct: 0,
        time_series: [],
        top_sessions: [],
    });
}
