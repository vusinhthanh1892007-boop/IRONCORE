import { NextRequest, NextResponse } from "next/server";
import { revokeTokenProfile } from "@/lib/server/token-profiles-store";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function DELETE(
  _req: NextRequest,
  { params }: { params: Promise<{ profileId: string }> }
) {
  const { profileId } = await params;
  if (!profileId) {
    return NextResponse.json({ detail: "Profile ID required" }, { status: 400 });
  }
  revokeTokenProfile(decodeURIComponent(profileId));
  return NextResponse.json({ ok: true });
}
