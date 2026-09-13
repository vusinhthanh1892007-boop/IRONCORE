import { NextRequest, NextResponse } from "next/server";
import { AI_CATALOG_LAST_UPDATED, listSectionsSummary } from "@/lib/ai-catalog";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const wantLatest = req.nextUrl.searchParams.get("latest") === "true";

  return NextResponse.json({
    action: "show_sections",
    sections: listSectionsSummary(),
    can_web_update: false,
    update_mode: wantLatest ? "local-fallback" : "local",
    notice: wantLatest ? "Web update option available" : undefined,
    permission_notice: wantLatest ? "Some providers require API keys or private access." : undefined,
    rate_limit_notice: wantLatest ? "If live web fetch is enabled, respect provider-specific rate limits." : undefined,
    update_scope: "updated through 2026-03-12 (inclusive)",
    last_updated: AI_CATALOG_LAST_UPDATED,
  });
}
