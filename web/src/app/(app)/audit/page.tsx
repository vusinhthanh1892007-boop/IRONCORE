"use client";

import { Lock, ShieldWarning as ShieldAlert, ShieldCheck, Pulse } from "@phosphor-icons/react";

export default function AuditPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Security Audit</h1>
        <p className="text-sm text-muted-foreground">System-wide security posture and event log.</p>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        {[
          { icon: ShieldCheck, label: "Passed checks", value: "142", color: "text-emerald-500" },
          { icon: ShieldAlert, label: "Warnings", value: "3", color: "text-amber-500" },
          { icon: Lock, label: "Blocked attempts", value: "17", color: "text-red-500" },
        ].map(({ icon: Icon, label, value, color }) => (
          <div key={label} className="rounded-xl border border-border bg-card p-4">
            <div className="flex items-center gap-3">
              <Icon className={`h-5 w-5 ${color}`} />
              <div>
                <div className="text-xs text-muted-foreground">{label}</div>
                <div className="text-2xl font-bold">{value}</div>
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="rounded-xl border border-border bg-card p-6">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <Pulse className="h-4 w-4" />
          Recent Events
        </div>
        <div className="mt-4 space-y-2 text-xs text-muted-foreground">
          {[
            { time: "09:48", msg: "Auth token validated — session #c8cc83" },
            { time: "09:46", msg: "System boot — all services reachable" },
            { time: "09:44", msg: "Rate limit enforced — 429 on /api/chat" },
          ].map((e) => (
            <div key={e.time} className="flex gap-3 rounded-lg border border-border px-3 py-2">
              <span className="font-mono text-muted-foreground/60">{e.time}</span>
              <span>{e.msg}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
