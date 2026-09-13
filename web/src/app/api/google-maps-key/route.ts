import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

let storedKey: string = process.env.GOOGLE_MAPS_API_KEY ?? process.env.NEXT_PUBLIC_GOOGLE_MAPS_KEY ?? "";

function maskKey(key: string): string {
  if (!key) return "";
  if (key.length <= 8) return "********";
  return `${key.slice(0, 4)}...${key.slice(-4)}`;
}

export async function GET() {
  return NextResponse.json({
    has_key: Boolean(storedKey.trim()),
    masked_key: maskKey(storedKey.trim()),
  });
}

export async function PUT(req: NextRequest) {
  try {
    const body = (await req.json().catch(() => ({}))) as { api_key?: string };
    const key = String(body.api_key ?? "").trim();
    if (!key) {
      return NextResponse.json({ detail: "API key is required" }, { status: 400 });
    }
    storedKey = key;
    return NextResponse.json({
      has_key: true,
      masked_key: maskKey(storedKey),
    });
  } catch (error) {
    return NextResponse.json(
      { detail: error instanceof Error ? error.message : "Failed to save Google Maps key" },
      { status: 500 }
    );
  }
}

export async function DELETE() {
  storedKey = "";
  return NextResponse.json({
    has_key: false,
    masked_key: "",
  });
}
