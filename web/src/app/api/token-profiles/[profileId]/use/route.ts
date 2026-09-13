import { NextRequest, NextResponse } from "next/server";
import { activateTokenProfile } from "@/lib/server/token-profiles-store";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(
  _req: NextRequest,
  { params }: { params: Promise<{ profileId: string }> }
) {
  const { profileId } = await params;
  if (!profileId) {
    return NextResponse.json({ detail: "Profile ID required" }, { status: 400 });
  }
  const token = activateTokenProfile(decodeURIComponent(profileId));
  if (!token) {
    return NextResponse.json({ detail: "Profile not found or revoked." }, { status: 404 });
  }
  return NextResponse.json({ ok: true, token });
}
