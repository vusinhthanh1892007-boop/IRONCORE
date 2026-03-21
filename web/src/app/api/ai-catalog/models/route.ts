import { NextRequest, NextResponse } from "next/server";
import {
  AI_CATALOG_LAST_UPDATED,
  queryProviderModels,
} from "@/lib/ai-catalog";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const provider = req.nextUrl.searchParams.get("provider") ?? "";
  const page = Number(req.nextUrl.searchParams.get("page") ?? "1");
  const filter = req.nextUrl.searchParams.get("filter") ?? "";
  const wantLatest = req.nextUrl.searchParams.get("latest") === "true";

  if (!provider.trim()) {
    return NextResponse.json(
      {
        action: "show_models",
        error: "Missing provider query param",
        last_updated: AI_CATALOG_LAST_UPDATED,
      },
      { status: 400 }
    );
  }

  const result = queryProviderModels(provider, page, filter);
  if (!result) {
    return NextResponse.json(
      {
        action: "show_models",
        error: "Provider not found",
        provider,
        last_updated: AI_CATALOG_LAST_UPDATED,
      },
      { status: 404 }
    );
  }

  return NextResponse.json({
    action: "show_models",
    provider: result.provider.name,
    provider_id: result.provider.id,
    models: result.models.map((model) => ({
      model_id: model.model_id,
      model_name: model.model_name,
      name: model.model_name,
      short_description: model.short_description,
      desc: model.short_description,
      context_window: model.context_window,
      ctx: model.context_window,
      tags: model.tags,
      example_endpoint_if_known: model.example_endpoint_if_known,
    })),
    pagination: result.pagination,
    filter,
    can_web_update: false,
    notice: wantLatest ? "Tùy chọn cập nhật web khả dụng" : undefined,
    permission_notice: wantLatest ? "Một số provider yêu cầu API key hoặc quyền truy cập riêng." : undefined,
    rate_limit_notice: wantLatest ? "Nếu bật web fetch thật, cần tôn trọng rate-limit của từng provider." : undefined,
    update_scope: "cập nhật tới ngày 2026-03-12 (inclusive)",
    last_updated: AI_CATALOG_LAST_UPDATED,
  });
}
