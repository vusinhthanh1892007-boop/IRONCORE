import { NextRequest } from "next/server";

import { requestOllamaChat, resolveOllamaModel } from "@/lib/server/ollama";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type FrontendMessage = {
    role: "user" | "assistant" | "system";
    content: string;
};

function encodeSse(payload: Record<string, unknown>) {
    return `data: ${JSON.stringify(payload)}\n\n`;
}

function shouldUseLocal(body: {
    model?: string;
    provider?: string;
}, apiKey: string) {
    if (body.provider?.toLowerCase() === "ollama") return true;
    if (!apiKey) return true;
    if (!BACKEND_URL.trim()) return true;
    return false;
}

async function streamFromOllama(body: {
    message?: string;
    model?: string;
    files?: string[];
    history?: FrontendMessage[];
    session_id?: string;
}) {
    const chosenModel = await resolveOllamaModel(body.model);
    const history = Array.isArray(body.history) ? body.history : [];
    const messages: FrontendMessage[] = history
        .filter((item) => item.role === "user" || item.role === "assistant" || item.role === "system")
        .map((item) => ({ role: item.role, content: item.content }));

    const attachmentSuffix = body.files?.length
        ? `\n\n[Attached files: ${body.files.length} item(s). Binary content omitted in local chat mode.]`
        : "";

    messages.push({
        role: "user",
        content: `${body.message ?? ""}${attachmentSuffix}`.trim(),
    });

    const upstream = await requestOllamaChat(chosenModel, messages, { stream: true });
    if (!upstream.body) {
        return new Response(
            encodeSse({ type: "error", error: "Ollama stream unavailable." }),
            {
                status: 200,
                headers: {
                    "Content-Type": "text/event-stream",
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            }
        );
    }

    const stream = new ReadableStream({
        async start(controller) {
            const decoder = new TextDecoder();
            const encoder = new TextEncoder();
            const reader = upstream.body!.getReader();
            let buffer = "";

            controller.enqueue(
                encoder.encode(encodeSse({ type: "session_start", session_id: body.session_id ?? null, model: chosenModel }))
            );

            while (true) {
                const { value, done } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split("\n");
                buffer = lines.pop() ?? "";

                for (const line of lines) {
                    const trimmed = line.trim();
                    if (!trimmed) continue;
                    try {
                        const parsed = JSON.parse(trimmed) as {
                            message?: { content?: string };
                            done?: boolean;
                        };
                        const token = parsed.message?.content ?? "";
                        if (token) {
                            controller.enqueue(encoder.encode(encodeSse({ type: "token", content: token })));
                        }
                        if (parsed.done) {
                            controller.enqueue(encoder.encode(encodeSse({ type: "done", session_id: body.session_id ?? null })));
                            controller.close();
                            return;
                        }
                    } catch {
                        controller.enqueue(encoder.encode(encodeSse({ type: "error", error: "Malformed Ollama payload." })));
                    }
                }
            }

            controller.enqueue(encoder.encode(encodeSse({ type: "done", session_id: body.session_id ?? null })));
            controller.close();
        },
    });

    return new Response(stream, {
        headers: {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Model": chosenModel,
        },
    });
}

export async function POST(req: NextRequest) {
    const apiKey =
        req.headers.get("X-IronCore-API-Key") ??
        req.headers.get("x-ironcore-api-key") ??
        "";

    // Parse frontend request format: { session_id, message, model, files }
    const body = await req.json().catch(() => ({}));
    const { message, session_id, model, files, provider, history } = body as {
        message?: string;
        session_id?: string;
        model?: string;
        files?: string[];
        provider?: string;
        history?: FrontendMessage[];
    };

    if (shouldUseLocal({ model, provider }, apiKey)) {
        try {
            return await streamFromOllama({ message, session_id, model, files, history });
        } catch (error) {
            return new Response(
                encodeSse({
                    type: "error",
                    error:
                        error instanceof Error ? error.message : "Ollama unavailable.",
                }),
                {
                    status: 200,
                    headers: {
                        "Content-Type": "text/event-stream",
                        "Cache-Control": "no-cache",
                        "X-Accel-Buffering": "no",
                    },
                }
            );
        }
    }

    // Map to backend format: { prompt, max_iterations, system_prompt }
    const backendPayload = {
        prompt: message ?? "",
        max_iterations: 10,
        system_prompt: "You are IronCore, a secure autonomous agent.",
        ...(model ? { model } : {}),
        ...(files?.length ? { files } : {}),
        ...(session_id ? { session_id } : {}),
    };

    const backendRes = await fetch(`${BACKEND_URL}/v1/agent/stream`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "X-IronCore-API-Key": apiKey,
        },
        body: JSON.stringify(backendPayload),
    });

    if (!backendRes.ok || !backendRes.body) {
        const error = await backendRes.text().catch(() => "Backend error");
        try {
            return await streamFromOllama({ message, session_id, model, files, history });
        } catch {
            return new Response(
                encodeSse({ type: "error", error }),
                {
                    status: 200,
                    headers: {
                        "Content-Type": "text/event-stream",
                        "Cache-Control": "no-cache",
                        "X-Accel-Buffering": "no",
                    },
                }
            );
        }
    }

    // Transform backend events → frontend StreamChunk format
    const transformStream = new TransformStream({
        async transform(chunk, controller) {
            const text = new TextDecoder().decode(chunk);
            const lines = text.split("\n");
            for (const line of lines) {
                const trimmed = line.trim();
                if (!trimmed.startsWith("data:")) {
                    controller.enqueue(new TextEncoder().encode(line + "\n"));
                    continue;
                }
                const raw = trimmed.replace(/^data:\s?/, "");
                if (!raw || raw === "[DONE]") {
                            controller.enqueue(
                                new TextEncoder().encode(
                            encodeSse({ type: "done" })
                        )
                    );
                    continue;
                }
                try {
                    const parsed = JSON.parse(raw) as Record<string, unknown>;
                    // Map backend event types to frontend StreamChunk types
                    let mapped: Record<string, unknown>;
                    const evType = parsed.type ?? parsed.event_type;
                    if (evType === "session_start") {
                        mapped = { type: "token", content: "" };
                    } else if (evType === "done") {
                        mapped = { type: "done", session_id: parsed.session_id };
                    } else if (evType === "ping") {
                        mapped = { type: "token", content: "" }; // keepalive
                    } else if (evType === "event") {
                        // IronCore engine event — surface tool calls
                        const innerType = (parsed.event_type as string) ?? "";
                        if (innerType.startsWith("tool.")) {
                            const toolName = (parsed.tool_name as string) ?? "";
                            mapped = {
                                type: innerType === "tool.started" ? "tool_start" : "tool_end",
                                tool_name: toolName,
                            };
                        } else if (innerType === "agent.response") {
                            mapped = {
                                type: "token",
                                content: (parsed.content as string) ?? "",
                            };
                        } else if (innerType === "agent.stopped") {
                            mapped = { type: "done" };
                        } else {
                            mapped = { type: "token", content: "" };
                        }
                    } else {
                        mapped = parsed;
                    }
                    controller.enqueue(
                        new TextEncoder().encode(encodeSse(mapped))
                    );
                } catch {
                    controller.enqueue(new TextEncoder().encode(trimmed + "\n"));
                }
            }
        },
    });

    const outStream = backendRes.body.pipeThrough(transformStream);

    return new Response(outStream, {
        headers: {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    });
}
