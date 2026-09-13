import { NextRequest, NextResponse } from "next/server";
import { getAllTokenProfiles, saveTokenProfile } from "@/lib/server/token-profiles-store";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET() {
  const profiles = getAllTokenProfiles();
  return NextResponse.json({ profiles });
}

export async function POST(req: NextRequest) {
  try {
    const body = (await req.json().catch(() => ({}))) as {
      profile_id?: string;
      token?: string;
      environment?: string;
      scopes?: string[];
      expires_in_days?: number;
    };

    if (!body.profile_id?.trim() || !body.token?.trim()) {
      return NextResponse.json({ detail: "profile_id and token are required." }, { status: 400 });
    }

    saveTokenProfile({
      profile_id: body.profile_id.trim(),
      token: body.token.trim(),
      environment: body.environment,
      scopes: body.scopes,
      expires_in_days: body.expires_in_days,
    });

    return NextResponse.json({ ok: true });
  } catch (error) {
    return NextResponse.json(
      { detail: error instanceof Error ? error.message : "Failed to save profile." },
      { status: 500 }
    );
  }
}
