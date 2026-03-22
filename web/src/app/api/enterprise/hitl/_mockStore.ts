export type HitlRisk = "low" | "medium" | "high" | "critical";
export type HitlStatus = "pending" | "approved" | "rejected" | "expired" | "auto_approved";

export interface HitlRequest {
  id: string;
  action_type: string;
  description: string;
  risk_level: HitlRisk;
  requested_by: string;
  session_id: string;
  created_at: string;
  expires_at: string;
  payload: Record<string, unknown>;
  status: HitlStatus;
}

export interface HitlDecision {
  id: string;
  request_id: string;
  action_type: string;
  decided_by: string;
  decision: "approved" | "rejected" | "escalated";
  reason: string;
  duration_seconds: number;
  timestamp: string;
  requested_by: string;
}

const now = Date.now();

const seedPending: HitlRequest[] = [
  {
    id: "HITL-101",
    action_type: "execute_terminal",
    description: "Run privileged DB migration on production shard-2",
    risk_level: "critical",
    requested_by: "agent-architect",
    session_id: "sess_prod_mig_42",
    created_at: new Date(now - 1000 * 20).toISOString(),
    expires_at: new Date(now + 1000 * 95).toISOString(),
    payload: { command: "python migrate.py --target shard-2", env: "prod" },
    status: "pending",
  },
  {
    id: "HITL-102",
    action_type: "delete_file",
    description: "Delete temporary export package older than retention policy",
    risk_level: "medium",
    requested_by: "agent-cleanup",
    session_id: "sess_cleanup_08",
    created_at: new Date(now - 1000 * 70).toISOString(),
    expires_at: new Date(now + 1000 * 210).toISOString(),
    payload: { path: "/tmp/reports/archive.zip", recursive: false },
    status: "pending",
  },
  {
    id: "HITL-103",
    action_type: "external_call",
    description: "Invoke external billing webhook with elevated token",
    risk_level: "high",
    requested_by: "agent-billing",
    session_id: "sess_bill_17",
    created_at: new Date(now - 1000 * 45).toISOString(),
    expires_at: new Date(now + 1000 * 50).toISOString(),
    payload: { endpoint: "https://billing.example.com/v1/reconcile", method: "POST" },
    status: "pending",
  },
];

const seedHistory: HitlDecision[] = [
  {
    id: "DEC-9001",
    request_id: "HITL-090",
    action_type: "execute_terminal",
    decided_by: "operator.alex",
    decision: "approved",
    reason: "Verified maintenance window and rollback plan.",
    duration_seconds: 42,
    timestamp: new Date(now - 1000 * 60 * 21).toISOString(),
    requested_by: "agent-ops",
  },
  {
    id: "DEC-9002",
    request_id: "HITL-091",
    action_type: "external_call",
    decided_by: "operator.kim",
    decision: "rejected",
    reason: "Webhook target not in trusted allowlist.",
    duration_seconds: 65,
    timestamp: new Date(now - 1000 * 60 * 9).toISOString(),
    requested_by: "agent-integrator",
  },
];

const globalStore = globalThis as unknown as {
  __ironcoreHitlPending?: HitlRequest[];
  __ironcoreHitlHistory?: HitlDecision[];
};

if (!globalStore.__ironcoreHitlPending) {
  globalStore.__ironcoreHitlPending = [...seedPending];
}
if (!globalStore.__ironcoreHitlHistory) {
  globalStore.__ironcoreHitlHistory = [...seedHistory];
}

export function listPendingMock(): HitlRequest[] {
  return globalStore.__ironcoreHitlPending ?? [];
}

export function replacePendingMock(items: HitlRequest[]) {
  globalStore.__ironcoreHitlPending = items;
}

export function listHistoryMock(): HitlDecision[] {
  return globalStore.__ironcoreHitlHistory ?? [];
}

export function prependHistoryMock(item: HitlDecision) {
  const current = globalStore.__ironcoreHitlHistory ?? [];
  globalStore.__ironcoreHitlHistory = [item, ...current];
}
