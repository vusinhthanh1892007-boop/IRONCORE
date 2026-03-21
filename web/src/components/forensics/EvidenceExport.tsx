"use client";

import * as React from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

interface EvidenceExportProps {
  sessionId: string;
  sessionMeta: Record<string, unknown> | null;
  verifyMeta: Record<string, unknown> | null;
  timeline: Array<Record<string, unknown>>;
}

function shouldMask(key: string) {
  const needle = key.toLowerCase();
  return ["secret", "token", "password", "api_key", "apikey", "auth", "credential"].some((term) =>
    needle.includes(term)
  );
}

function sanitize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sanitize);
  if (value && typeof value === "object") {
    const obj = value as Record<string, unknown>;
    const next: Record<string, unknown> = {};
    Object.entries(obj).forEach(([key, item]) => {
      next[key] = shouldMask(key) ? "***masked***" : sanitize(item);
    });
    return next;
  }
  return value;
}

function escapeCsv(value: unknown): string {
  const text = value == null ? "" : String(value);
  return `"${text.replaceAll('"', '""')}"`;
}

export function EvidenceExport({ sessionId, sessionMeta, verifyMeta, timeline }: EvidenceExportProps) {
  const buildBundle = React.useCallback(() => {
    const payload = {
      session_id: sessionId,
      exported_at: new Date().toISOString(),
      compliance_notice: "This report is for authorized use only",
      session: sanitize(sessionMeta ?? {}),
      verify: sanitize(verifyMeta ?? {}),
      timeline: sanitize(timeline),
    };
    return payload;
  }, [sessionId, sessionMeta, verifyMeta, timeline]);

  const exportJson = React.useCallback(() => {
    const bundle = buildBundle();
    const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `forensics-${sessionId}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }, [buildBundle, sessionId]);

  const exportCsv = React.useCallback(() => {
    const rows = timeline.map((event) => {
      const metadata = (event.metadata ?? {}) as Record<string, unknown>;
      return [
        event.seq,
        event.event_id,
        event.event_type,
        event.timestamp,
        event.chain_hash_prefix,
        metadata.agent_id,
        metadata.tool_name,
        metadata.severity,
      ];
    });

    const csv = [
      "seq,event_id,event_type,timestamp,chain_hash_prefix,agent_id,tool_name,severity",
      ...rows.map((row) => row.map((cell) => escapeCsv(cell)).join(",")),
    ].join("\n");

    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `forensics-${sessionId}.csv`;
    anchor.click();
    URL.revokeObjectURL(url);
  }, [sessionId, timeline]);

  const exportPdf = React.useCallback(() => {
    const bundle = buildBundle();
    const reportWindow = window.open("", "_blank", "width=1080,height=900");
    if (!reportWindow) return;

    const html = `
      <html>
        <head>
          <title>Forensics Report ${sessionId}</title>
          <style>
            body { font-family: ui-sans-serif, system-ui, sans-serif; margin: 24px; color: #0f172a; }
            h1, h2 { margin: 0 0 12px 0; }
            pre { white-space: pre-wrap; word-break: break-word; background: #f8fafc; padding: 12px; border-radius: 8px; }
            .notice { margin: 12px 0 20px; color: #b45309; font-size: 12px; }
          </style>
        </head>
        <body>
          <h1>Forensics Evidence Report</h1>
          <div><strong>Session:</strong> ${sessionId}</div>
          <div><strong>Exported:</strong> ${new Date().toISOString()}</div>
          <div class="notice">This report is for authorized use only.</div>
          <h2>Session Summary</h2>
          <pre>${JSON.stringify(bundle.session, null, 2)}</pre>
          <h2>Verification</h2>
          <pre>${JSON.stringify(bundle.verify, null, 2)}</pre>
          <h2>Timeline</h2>
          <pre>${JSON.stringify(bundle.timeline, null, 2)}</pre>
        </body>
      </html>
    `;

    reportWindow.document.open();
    reportWindow.document.write(html);
    reportWindow.document.close();
    reportWindow.focus();
    reportWindow.print();
  }, [buildBundle, sessionId]);

  return (
    <Card className="border border-border bg-card p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-sm font-semibold">Evidence Export</div>
          <div className="text-xs text-amber-600">This report is for authorized use only</div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" onClick={exportJson}>Full JSON</Button>
          <Button variant="outline" size="sm" onClick={exportPdf}>PDF Report</Button>
          <Button variant="outline" size="sm" onClick={exportCsv}>CSV Events</Button>
        </div>
      </div>
    </Card>
  );
}
