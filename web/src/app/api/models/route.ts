import { NextRequest, NextResponse } from "next/server";
import {
  AI_CATALOG_LAST_UPDATED,
  queryProviderModels,
} from "@/lib/ai-catalog";
import {
  type LocalProviderId,
  getLocalProviderBaseUrl,
  listLocalProviderModels,
} from "@/lib/server/local-providers";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(req: NextRequest) {
  const provider = req.nextUrl.searchParams.get("provider") ?? "";
  const page = Number(req.nextUrl.searchParams.get("page") ?? "1");
  const filter = req.nextUrl.searchParams.get("filter") ?? "";

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

  const normalizedProvider = provider.trim().toLowerCase();
  const localProviders: LocalProviderId[] = ["ollama", "localai", "vllm", "lmstudio"];

  if (localProviders.includes(normalizedProvider as LocalProviderId)) {
    try {
      const scan = await listLocalProviderModels(normalizedProvider as LocalProviderId);
      return NextResponse.json({
        action: "show_models",
        provider: scan.label,
        provider_id: scan.id,
        base_url: getLocalProviderBaseUrl(scan.id),
        models: scan.models.map((model) => ({
          model_id: model.id,
          model_name: model.name,
          short_description: model.family
            ? `Local ${model.family} model via ${scan.label}`
            : `Local model via ${scan.label}`,
          context_window: null,
          tags: ["local", scan.id],
          example_endpoint_if_known: getLocalProviderBaseUrl(scan.id),
        })),
        pagination: {
          page: 1,
          total_pages: 1,
          total_items: scan.models.length,
        },
        filter,
        last_updated: AI_CATALOG_LAST_UPDATED,
      });
    } catch (error) {
      return NextResponse.json(
        {
          action: "show_models",
          error:
            error instanceof Error ? error.message : "Local provider unavailable",
          provider: normalizedProvider,
          provider_id: normalizedProvider,
          models: [],
          pagination: { page: 1, total_pages: 1, total_items: 0 },
          filter,
          last_updated: AI_CATALOG_LAST_UPDATED,
        },
        { status: 200 }
      );
    }
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
      short_description: model.short_description,
      context_window: model.context_window,
      tags: model.tags,
      example_endpoint_if_known: model.example_endpoint_if_known,
    })),
    pagination: result.pagination,
    filter,
    last_updated: AI_CATALOG_LAST_UPDATED,
  });
}
