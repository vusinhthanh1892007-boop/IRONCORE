import { NextResponse } from "next/server";

import { listOllamaModels } from "@/lib/server/ollama";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET() {
  try {
    const models = await listOllamaModels();
    return NextResponse.json([
      {
        id: "local-ollama",
        host: "127.0.0.1",
        status: models.length ? "healthy" : "offline",
        cpu_pct: 0,
        mem_pct: 0,
        active_sessions: 0,
        last_heartbeat: new Date().toISOString(),
        models: models.map((model) => model.name),
      },
    ]);
  } catch {
    return NextResponse.json([], { status: 200 });
  }
}
