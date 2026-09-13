import { NextRequest, NextResponse } from "next/server";
import {
  AI_CATALOG_LAST_UPDATED,
  addProviderModel,
} from "@/lib/ai-catalog";

export const dynamic = "force-dynamic";

interface AddModelBody {
  provider?: string;
  model_id?: string;
  model_name?: string;
}

export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => ({}))) as AddModelBody;
  const provider = String(body.provider ?? "").trim();
  const modelId = String(body.model_id ?? "").trim();
  const modelName = body.model_name ? String(body.model_name).trim() : undefined;

  if (!provider || !modelId) {
    return NextResponse.json(
      {
        action: "add_model",
        ok: false,
        message: "provider and model_id are required",
        last_updated: AI_CATALOG_LAST_UPDATED,
      },
      { status: 400 }
    );
  }

  const result = addProviderModel(provider, modelId, modelName);

  return NextResponse.json(
    {
      action: "add_model",
      provider,
      model_id: modelId,
      ...result,
      note: "will be updated once the agent fetches metadata",
      last_updated: AI_CATALOG_LAST_UPDATED,
    },
    { status: result.ok ? 200 : 400 }
  );
}
