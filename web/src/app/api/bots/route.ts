import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function headers(req: NextRequest) {
  return {
    "Content-Type": "application/json",
    "X-IronCore-API-Key":
      req.headers.get("X-IronCore-API-Key") ??
      req.headers.get("x-ironcore-api-key") ??
      "",
  };
}

/** GET /api/bots – proxy to GET /v1/channels/status */
export async function GET(req: NextRequest) {
  const res = await fetch(`${BACKEND_URL}/v1/channels/status`, {
    headers: headers(req),
    cache: "no-store",
  }).catch((e) => {
    throw new Error(`Backend unreachable: ${e.message}`);
  });

  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}

/** POST /api/bots – proxy to POST /v1/channels/{name}/{action} */
export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({})) as {
    channel?: string;
    action?: "start" | "stop";
    access_token?: string;
    app_secret?: string;
    refresh_token?: string;
    verify_token?: string;
    phone_number_id?: string;
    allowed_user_ids?: string;
  };

  const { channel, action = "start", ...rest } = body;
  if (!channel) {
    return NextResponse.json({ error: "channel is required" }, { status: 400 });
  }

  const endpointAction = action === "stop" ? "stop" : "start";
  const res = await fetch(
    `${BACKEND_URL}/v1/channels/${channel}/${endpointAction}`,
    {
      method: "POST",
      headers: headers(req),
      body: JSON.stringify(rest),
    }
  ).catch((e) => {
    throw new Error(`Backend unreachable: ${e.message}`);
  });

  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
