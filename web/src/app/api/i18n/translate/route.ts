import { NextRequest, NextResponse } from "next/server";
import staticLocales from "@/lib/static-locales.json";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

interface TranslateRequest {
  texts?: string[];
  target?: string;
  source?: string;
}

interface TranslateResponse {
  translations: string[];
}

export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => ({}))) as TranslateRequest;
  const texts = Array.isArray(body.texts) ? body.texts : [];
  const target = (body.target || "en").slice(0, 5);

  if (!texts.length) {
    return NextResponse.json({ translations: [] } as TranslateResponse, { status: 200 });
  }

  // Load purely offline dictionary mapping
  const dict = (staticLocales as Record<string, Record<string, string>>)[target] || {};

  const translations = texts.map((text) => {
    const raw = String(text ?? "").trim();
    if (!raw) return text;
    // Fast dictionary mapping, preserves English if key is completely unknown.
    return dict[raw] || raw;
  });

  return NextResponse.json({ translations } as TranslateResponse, { status: 200 });
}
