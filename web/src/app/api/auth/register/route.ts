import { NextRequest, NextResponse } from "next/server";

import { registerDevUser } from "@/lib/server/dev-auth-store";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => ({}))) as {
    name?: string;
    email?: string;
    password?: string;
  };

  const name = String(body.name ?? "").trim();
  const email = String(body.email ?? "").trim().toLowerCase();
  const password = String(body.password ?? "");

  if (!name || !email || !password) {
    return NextResponse.json(
      { message: "Missing required fields." },
      { status: 400 }
    );
  }

  try {
    const user = await registerDevUser({ name, email, password });
    return NextResponse.json({ ok: true, user }, { status: 201 });
  } catch (error) {
    return NextResponse.json(
      {
        message:
          error instanceof Error ? error.message : "Registration failed.",
      },
      { status: 409 }
    );
  }
}
