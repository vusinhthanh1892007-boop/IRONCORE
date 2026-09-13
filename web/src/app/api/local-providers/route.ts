import { NextResponse } from "next/server";
import { listAllLocalProviderModels } from "@/lib/server/local-providers";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  const providers = await listAllLocalProviderModels();
  return NextResponse.json({ providers }, { status: 200 });
}
