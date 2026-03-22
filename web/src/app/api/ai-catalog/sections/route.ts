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
    notice: wantLatest ? "Tùy chọn cập nhật web khả dụng" : undefined,
    permission_notice: wantLatest ? "Một số provider yêu cầu API key hoặc quyền truy cập riêng." : undefined,
    rate_limit_notice: wantLatest ? "Nếu bật web fetch thật, cần tôn trọng rate-limit của từng provider." : undefined,
    update_scope: "cập nhật tới ngày 2026-03-12 (inclusive)",
    last_updated: AI_CATALOG_LAST_UPDATED,
  });
}
