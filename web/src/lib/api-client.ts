export interface CostMetrics {
  total_api_calls: number;
  cache_hits: number;
  cache_hit_rate: number;
  tokens_saved_by_cache: number;
  tokens_saved_by_compression: number;
  total_cost_usd: number;
  estimated_cost_without_optimizer?: number;
  savings_pct: number;
  time_series: Array<{ timestamp: number; value: number; label: string }>;
  top_sessions?: Array<{
    session_id: string;
    cost_usd: number;
    cache_hits: number;
    messages?: number;
    started_at?: number;
  }>;
}

export interface PluginInfo {
  id: string;
  name: string;
  version: string;
  status: "active" | "disabled" | "error";
  tools_count: number;
}

export interface SessionInfo {
  session_id: string;
  status: string;
  created_at: number;
  stopped_at?: number | null;
}

export interface HitlRequest {
  id: string;
  action_type: string;
  description: string;
  risk_level: "low" | "medium" | "high" | "critical";
  requested_by: string;
  session_id: string;
  created_at: string;
  expires_at: string;
  payload: Record<string, unknown>;
  status: "pending" | "approved" | "rejected" | "expired" | "auto_approved";
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

class IronCoreClient {
  private baseUrl: string;
  private apiKey: string | null = null;

  constructor(baseUrl = "") {
    this.baseUrl = baseUrl;
  }

  setApiKey(key: string) {
    this.apiKey = key;
  }

  private async fetchJson<T>(path: string, options?: RequestInit): Promise<T> {
    const res = await fetch(`${this.baseUrl}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(this.apiKey ? { "X-API-Key": this.apiKey } : {}),
        ...(this.apiKey ? { "X-IronCore-API-Key": this.apiKey } : {}),
        ...options?.headers,
      },
    });

    if (!res.ok) {
      const error = await res.json().catch(() => ({ message: "Unknown error" }));
      throw new Error(error.message || `HTTP ${res.status}`);
    }

    return (await res.json()) as T;
  }

  async getMetrics(range?: string): Promise<CostMetrics> {
    const query = range ? `?range=${encodeURIComponent(range)}` : "";
    return this.fetchJson<CostMetrics>(`/api/metrics${query}`);
  }

  async getPlugins(): Promise<PluginInfo[]> {
    return this.fetchJson<PluginInfo[]>("/api/plugins");
  }

  async listSessions(): Promise<SessionInfo[]> {
    return this.fetchJson<SessionInfo[]>("/api/sessions");
  }

  async getHitlPending(): Promise<HitlRequest[]> {
    return this.fetchJson<HitlRequest[]>("/api/enterprise/hitl/pending");
  }

  async decideHitlRequest(requestId: string, decision: "approve" | "reject" | "escalate", reason = ""): Promise<unknown> {
    return this.fetchJson<unknown>(`/api/enterprise/hitl/${requestId}/${decision}`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    });
  }

  async getHitlHistory(): Promise<HitlDecision[]> {
    return this.fetchJson<HitlDecision[]>("/api/enterprise/hitl/history");
  }
}

export const ironCoreClient = new IronCoreClient();
