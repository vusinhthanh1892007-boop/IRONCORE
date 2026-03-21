import { NextRequest, NextResponse } from "next/server";
import {
  AI_CATALOG_LAST_UPDATED,
  queryProviderModels,
} from "@/lib/ai-catalog";
import { listOllamaModels } from "@/lib/server/ollama";

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

  if (provider.trim().toLowerCase() === "ollama") {
    try {
      const models = await listOllamaModels();
      return NextResponse.json({
        action: "show_models",
        provider: "Ollama",
        provider_id: "ollama",
        models: models.map((model) => ({
          model_id: model.name,
          model_name: model.name,
          short_description: model.family
            ? `Local ${model.family} model via Ollama`
            : "Local model via Ollama",
          context_window: null,
          tags: ["local", "ollama"],
          example_endpoint_if_known: "http://127.0.0.1:11434",
        })),
        pagination: {
          page: 1,
          total_pages: 1,
          total_items: models.length,
        },
        filter,
        last_updated: AI_CATALOG_LAST_UPDATED,
      });
    } catch (error) {
      return NextResponse.json(
        {
          action: "show_models",
          error:
            error instanceof Error ? error.message : "Ollama unavailable",
          provider: "Ollama",
          provider_id: "ollama",
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
