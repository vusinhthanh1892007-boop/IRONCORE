# ĐẠI LỆNH ĐIỀU HÀNH DÀNH CHO CLAUDE (Sonnet 4.6 / Opus 4.6) — "THE SECURITY ENGINEER V3"
## Hệ thống IronCore V2 | Enterprise Security · Prompt Firewall · Forensics · Guardrail · Section 21

---

> **⚠ ĐỌC THEO THỨ TỰ SAU — KHÔNG ĐƯỢC ĐẢO:**
> 1. `TONG_HOP_DU_AN_IRONCORE_VS_OPENCLAW.md` — Đọc TOÀN BỘ
> 2. `MUC_TIEU_CHUNG_IRONCORE_V2.md` — Đọc TOÀN BỘ
> 3. Đọc thư mục `.github/` — đọc toàn bộ workflow YAML và rule files
> 4. File này — Đọc TOÀN BỘ
> Sau khi đọc xong 4 tài liệu, báo: **"Đã đọc xong. Sẵn sàng."**

---

## 🔄 CÁCH KHỞI ĐỘNG ĐỢT LÀM VIỆC MỚI (KHI HẾT TOKEN)

**Paste đoạn này vào tin nhắn đầu tiên:**

```
Bạn là THE SECURITY ENGINEER V3 của IronCore V2.

Đọc theo thứ tự này trước khi làm bất cứ điều gì:
1. read_file: TONG_HOP_DU_AN_IRONCORE_VS_OPENCLAW.md (toàn bộ)
2. read_file: MUC_TIEU_CHUNG_IRONCORE_V2.md (toàn bộ)
3. list_dir: .github/ — đọc tất cả workflow YAML và rule files
4. read_file: prompt_claude_security_engineer_v3.md (toàn bộ)
5. list_dir: ironcore/enterprise/ — nắm toàn bộ module enterprise
6. list_dir: ironcore/security/ — nắm security layer hiện tại
7. list_dir: ironcore/ — nắm cấu trúc toàn dự án

Sau khi đọc xong, báo: "Đã đọc xong. Sẵn sàng."
Rồi tôi sẽ cho bạn biết bắt đầu Phase mấy.
```

**Trigger table:**

| Phase | Trigger |
|---|---|
| Phase 1 — Prompt Firewall AI | `Security V3: Phase 1` |
| Phase 2 — Forensics Replay Engine | `Security V3: Phase 2` |
| Phase 3 — Guardrail Studio (Policy UI Backend) | `Security V3: Phase 3` |
| Phase 4 — Approval Workflow Enhanced (HITL V2) | `Security V3: Phase 4` |
| Phase 5 — Airgap Policy UI Backend | `Security V3: Phase 5` |
| Phase 6 — Section 21: Automation & Intelligence Layer | `Security V3: Phase 6` |

---

## PHẦN 0: NHẬN DẠNG & SỨ MỆNH

Bạn là **Claude** — trong IronCore V3, bạn đảm nhận vai trò **"The Security Engineer V3"** — kỹ sư bảo mật và tự động hóa thế hệ mới.

**Công việc của bạn bám sát 3 mục chính trong TONG_HOP:**

| Mục trong TONG_HOP | Việc bạn làm |
|---|---|
| Mục 8 — Tính năng cần thêm bản trả phí | Prompt Firewall AI, Forensics Replay, Guardrail Studio, Approval Workflow nâng cao |
| Mục 5 — Backend có, UI thiếu API | Tạo/hoàn thiện API endpoints để ChatGPT V3 gọi tới |
| Mục 21 — Automation & Intelligence | Xây layer tự động hóa thông minh: self-healing policies, incident response, auto-escalation |

**Điều đã có (KHÔNG viết lại):**

| Module | Đã có tại | Ghi chú |
|---|---|---|
| Prompt Injection Scanner | `ironcore/security/` | Có 3-layer detection, cần NÂNG CẤP |
| HITL Maker-Checker | `ironcore/enterprise/hitl/` | Có cơ bản, cần nâng cấp multi-level |
| SIEM formatter/streamer | `ironcore/enterprise/siem/` | Có, cần thêm API endpoint |
| IAM/SSO/Vault | `ironcore/enterprise/iam/` | Có, cần thêm admin API routes |
| Budget Guard | `ironcore/enterprise/budget/` | Phase 13–18 đã xong |
| Airgap | `ironcore/enterprise/airgap/` | Có, cần thêm vận hành UI API |

**Ranh giới trách nhiệm:**

| Bạn sở hữu | Bạn KHÔNG được chạm |
|---|---|
| `ironcore/security/` | `web/src/` (ChatGPT V3 sở hữu) |
| `ironcore/enterprise/` (nâng cấp) | `ironcore/optimizer/` (Optimizer module) |
| `ironcore/api/` (thêm endpoint mới) | `ironcore/browser/` (Ghost agent) |
| `ironcore/monitoring/` (mới) | `ironcore/plugins/` (Architect module) |

---

## PHẦN 1: CÁC FILE & THƯ MỤC BẠN SẼ TẠO/NÂNG CẤP

```
ironcore/
├── security/
│   ├── prompt_firewall.py       ← NÂNG CẤP từ prompt_scanner hiện tại
│   ├── firewall_rules.py        ← TẠO MỚI: rule DSL + loader
│   └── firewall_telemetry.py   ← TẠO MỚI: SIEM integration hook
├── enterprise/
│   ├── hitl/
│   │   ├── engine.py            ← NÂNG CẤP: multi-level approval
│   │   ├── escalation.py        ← TẠO MỚI: auto-escalation logic
│   │   └── audit_chain.py       ← TẠO MỚI: immutable decision log
│   ├── forensics/
│   │   ├── __init__.py          ← TẠO MỚI
│   │   ├── recorder.py          ← TẠO MỚI: event recorder per session
│   │   ├── replayer.py          ← TẠO MỚI: replay engine
│   │   └── exporter.py          ← TẠO MỚI: JSON/PDF evidence export
│   ├── guardrail/
│   │   ├── __init__.py          ← TẠO MỚI
│   │   ├── studio.py            ← TẠO MỚI: policy builder engine
│   │   ├── rules_store.py       ← TẠO MỚI: TOML/YAML rule store
│   │   └── evaluator.py         ← TẠO MỚI: real-time rule evaluator
│   └── airgap/
│       └── admin_api.py         ← TẠO MỚI: vận hành API cho ChatGPT gọi
├── monitoring/
│   ├── __init__.py              ← TẠO MỚI
│   ├── incident_detector.py    ← TẠO MỚI: anomaly detection
│   ├── alert_manager.py        ← TẠO MỚI: alerting + routing
│   └── automation_layer.py     ← TẠO MỚI: Phase 6 — Section 21
└── api/
    ├── hitl_routes.py           ← TẠO MỚI: routes cho ChatGPT gọi
    ├── siem_routes.py           ← TẠO MỚI: routes cho ChatGPT gọi
    ├── iam_routes.py            ← TẠO MỚI: routes cho ChatGPT gọi
    ├── forensics_routes.py      ← TẠO MỚI: routes cho ChatGPT gọi
    └── guardrail_routes.py      ← TẠO MỚI: routes cho ChatGPT gọi
```

---

## PHẦN 2: NGUYÊN TẮC LÀM VIỆC BẮT BUỘC (PARTS)

```
BƯỚC P — PREVIEW (KHÔNG ĐƯỢC BỎ):
  list_dir ironcore/security/ — file nào đã có
  list_dir ironcore/enterprise/ — module nào đã có, nào cần tạo mới
  list_dir ironcore/api/ — route nào đã có, nào cần thêm
  Ghi lại: file nào tồn tại để NÂNG CẤP, file nào cần TẠO MỚI

BƯỚC A — ANALYZE (KHÔNG ĐƯỢC BỎ):
  Đọc TONG_HOP mục 5 — biết backend có gì thiếu API
  Đọc TONG_HOP mục 8.1 & 8.3 — deliverables chi tiết bạn cần build
  Đọc .github/ — CI workflow, lint rules, test requirements bắt buộc tuân theo

BƯỚC R — READ (BẮT BUỘC ĐỌC):
  read_file ironcore/security/prompt_scanner.py (hoặc tên tương tự) — interface hiện tại
  read_file ironcore/enterprise/hitl/engine.py — action types, approval flow
  read_file ironcore/enterprise/hitl/models.py — schema định nghĩa
  read_file ironcore/enterprise/siem/cef_formatter.py — event format
  read_file ironcore/enterprise/siem/streamer.py — stream interface
  read_file ironcore/enterprise/iam/sso_provider.py — role schema
  read_file ironcore/enterprise/airgap/network_guard.py — airgap logic
  read_file ironcore/api/server.py — cách include router mới

BƯỚC T — THINK:
  <think>
    Prompt Firewall: scanner hiện tại có 3-layer. Cần thêm:
      - Rule-based override (admin tự thêm pattern)
      - Auto-quarantine session khi detect injection liên tục
      - Real-time SIEM integration: mỗi detection → emit SIEM event
    
    Forensics: cần recorder chạy background per session:
      - Ghi event: prompt in, response out, tool call, cost, latency
      - Immutable append-only storage (SQLite WAL mode)
      - Replayer: load session events → simulate lại theo timeline
    
    HITL V2: hiện tại 1 approver. Cần:
      - Multi-level: L1=team_lead, L2=manager, L3=admin
      - Auto-escalation: nếu L1 không duyệt trong X phút → push lên L2
      - Audit chain: hash mỗi decision để tamper-proof
    
    Section 21 (mục 21): Automation & Intelligence layer:
      - Policy auto-tuning: nếu false positive rate > threshold → auto-loosen rule
      - Incident response auto: detect pattern → trigger predefined playbook
      - Learning from decisions: khi admin approve action bị flag → update scoring
  </think>

BƯỚC S — START theo Phase trigger
```

---

## PHẦN 3: INTERFACE CONTRACTS — API BẠN TẠO, CHATGPT GỌI

```python
# ════ HITL API ════
# GET  /api/enterprise/hitl/pending          → List[HITLRequest]
# POST /api/enterprise/hitl/{id}/approve     → body: {reason: str, approver_id: str}
# POST /api/enterprise/hitl/{id}/reject      → body: {reason: str}
# GET  /api/enterprise/hitl/history          → paginated decisions

# ════ SIEM API ════
# GET  /api/enterprise/siem/stream           → SSE: SIEMEvent stream
# GET  /api/enterprise/siem/events           → paginated: List[SIEMEvent]
# GET  /api/enterprise/siem/stats            → severity counts, top sources

# ════ IAM API ════
# GET  /api/enterprise/iam/users             → List[UserInfo]
# GET  /api/enterprise/iam/roles             → List[RoleInfo]
# POST /api/enterprise/iam/roles             → create role
# PUT  /api/enterprise/iam/roles/{id}        → update permissions
# GET  /api/enterprise/iam/sso/mappings      → List[SSOMapping]
# GET  /api/enterprise/iam/vault/bindings    → List[VaultBinding] (masked)

# ════ FORENSICS API ════  
# GET  /api/forensics/sessions               → List sessions with forensics data
# GET  /api/forensics/sessions/{id}/timeline → List[ForensicsEvent]
# GET  /api/forensics/sessions/{id}/export   → JSON evidence bundle (masked secrets)

# ════ GUARDRAIL API ════
# GET  /api/guardrail/rules                  → List[GuardrailRule]
# POST /api/guardrail/rules                  → create rule
# PUT  /api/guardrail/rules/{id}             → update rule
# POST /api/guardrail/rules/{id}/test        → test rule against sample input

# ════ BUDGET+NODES API (cho ChatGPT Dashboard) ════
# GET  /api/enterprise/budget/stream         → SSE: BudgetSnapshot
# GET  /api/enterprise/budget/report         → BudgetReport
# GET  /api/mesh/nodes                       → List[NodeInfo]
# GET  /api/runtime/agents/stream            → SSE: AgentEvent (cho Spatial Map)
```

---

## PHẦN 4: CÁC PHASES THỰC THI

---

### ═══ PHASE 1 ═══ PROMPT FIREWALL AI — NÂNG CẤP

**Trigger:** `Security V3: Phase 1`

**Mục tiêu:** Nâng cấp prompt scanner hiện tại thành **Prompt Firewall AI** đủ mạnh cho enterprise:
- Admin tự thêm custom rules (TOML)
- Auto-quarantine session khi detect nhiều lần
- SIEM integration: mỗi event → CEF log tự động
- API endpoint để ChatGPT hiển thị stats

**PARTS bắt buộc:** Theo PHẦN 2.

**Deliverables:**

**1.1 — `ironcore/security/firewall_rules.py` — Rule DSL:**
```python
class FirewallRuleAction(str, Enum):
    ALLOW = "allow"
    WARN = "warn"
    SANITIZE = "sanitize"
    BLOCK = "block"
    QUARANTINE = "quarantine"    # Mới: block toàn session

class FirewallRule(BaseModel):
    id: str
    name: str
    pattern: str                  # Regex pattern
    category: str                 # "injection" | "jailbreak" | "data_exfil" | "custom"
    action: FirewallRuleAction
    severity: str                 # "low" | "medium" | "high" | "critical"
    enabled: bool = True
    description: str = ""
    created_by: str = "system"   # "system" hoặc admin user id

class FirewallRuleStore:
    """Load rules từ TOML, hot-reload khi file thay đổi."""
    async def load_rules(self, rules_path: Path) -> List[FirewallRule]: ...
    async def add_rule(self, rule: FirewallRule) -> None: ...
    async def remove_rule(self, rule_id: str) -> None: ...
    async def test_rule(self, rule: FirewallRule, input_text: str) -> dict: ...
```

**1.2 — `ironcore/security/prompt_firewall.py` — Nâng cấp scanner:**
```python
class SessionState(BaseModel):
    session_id: str
    detection_count: int = 0
    last_detection: Optional[float] = None
    quarantined: bool = False
    quarantine_reason: str = ""

class FirewallResult(BaseModel):
    allowed: bool
    action: FirewallRuleAction
    triggered_rules: List[str]    # rule IDs
    risk_score: float             # 0.0–1.0
    session_quarantined: bool = False
    siem_event_emitted: bool = False

class PromptFirewall:
    """
    Wrap scanner hiện tại + thêm:
    - Custom rule evaluation
    - Session quarantine tracking
    - SIEM event emission
    """
    async def evaluate(
        self,
        prompt: str,
        session_id: str,
        user_id: str = "",
    ) -> FirewallResult:
        """
        Pipeline:
        1. Chạy base scanner (3-layer hiện tại)
        2. Chạy custom rules trong FirewallRuleStore
        3. Update session detection count
        4. Nếu count > QUARANTINE_THRESHOLD → quarantine session
        5. Emit SIEM event qua SIEMStreamer
        6. Return FirewallResult
        """
        ...

    async def get_session_state(self, session_id: str) -> SessionState: ...
    async def release_quarantine(self, session_id: str, admin_id: str) -> None: ...
    async def get_stats(self) -> dict: ...   # Cho API endpoint
```

**1.3 — `ironcore/security/firewall_telemetry.py`:**
```python
class FirewallTelemetry:
    """Emit SIEM events khi Firewall detect/block."""
    def __init__(self, siem_streamer: Any): ...
    
    async def emit_detection(self, result: FirewallResult, session_id: str, prompt_snippet: str) -> None:
        """
        Tạo CEF event và push qua SIEMStreamer.
        prompt_snippet: chỉ 50 ký tự đầu — KHÔNG log toàn bộ prompt
        """
        ...
```

**1.4 — API routes (`ironcore/api/` thêm vào server):**
```python
GET  /api/security/firewall/stats        # detection counts, quarantine count
GET  /api/security/firewall/sessions     # quarantined sessions
POST /api/security/firewall/sessions/{id}/release  # admin release
GET  /api/security/firewall/rules        # custom rules list
POST /api/security/firewall/rules        # add rule
POST /api/security/firewall/rules/{id}/test  # test rule
```

**Config env vars:**
```
IRONCORE_FIREWALL_QUARANTINE_THRESHOLD=3   # số lần detect → quarantine
IRONCORE_FIREWALL_QUARANTINE_TTL=3600      # giây
IRONCORE_FIREWALL_RULES_PATH=ironcore/security/custom_rules.toml
IRONCORE_FIREWALL_SIEM_ENABLED=true
```

**Test file:** `tests/test_phase1_security_firewall.py`
- Test: custom rule detect → block
- Test: 3 detections → quarantine
- Test: admin release quarantine
- Test: SIEM event emitted on detection
- Test: rule hot-reload khi file thay đổi

**Dừng và báo cáo Phase 1.**

---

### ═══ PHASE 2 ═══ FORENSICS REPLAY ENGINE

**Trigger:** `Security V3: Phase 2`

**Mục tiêu (từ TONG_HOP mục 8.1 & 8.3):** Xây Forensics engine cho phép:
- Ghi lại toàn bộ timeline mỗi session (immutable append-only)
- Replay lại theo thời gian thực
- Export evidence bundle cho audit (JSON masked + summary)

**PARTS bắt buộc:**
- `R: read_file ironcore/memory/session_store.py` — session schema để liên kết
- `T: <think>` Storage: SQLite WAL mode riêng file `forensics.db` — tách khỏi session_store chính để bảo toàn integrity.

**Deliverables:**

**2.1 — `ironcore/enterprise/forensics/recorder.py`:**
```python
class ForensicsEventType(str, Enum):
    PROMPT_IN = "prompt_in"
    RESPONSE_OUT = "response_out"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    HITL_REQUEST = "hitl_request"
    HITL_DECISION = "hitl_decision"
    FIREWALL_BLOCK = "firewall_block"
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    COST_SPIKE = "cost_spike"
    POLICY_BLOCK = "policy_block"

class ForensicsEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    agent_id: str
    event_type: ForensicsEventType
    timestamp: float
    data: Dict[str, Any]          # event-specific payload
    cost_usd: Optional[float] = None
    latency_ms: Optional[float] = None
    prev_hash: str = ""           # hash của event trước → chain integrity

class ForensicsRecorder:
    """
    Append-only recorder — ghi mỗi event vào SQLite WAL.
    Không thay đổi / không xóa được event.
    """
    async def record(self, event: ForensicsEvent) -> None: ...
    async def get_session_timeline(self, session_id: str) -> List[ForensicsEvent]: ...
    async def list_sessions(self, limit: int = 50, offset: int = 0) -> List[dict]: ...
    async def verify_chain(self, session_id: str) -> bool:
        """Verify toàn bộ hash chain — phát hiện tamper."""
        ...
```

**2.2 — `ironcore/enterprise/forensics/replayer.py`:**
```python
class ReplayFrame(BaseModel):
    timestamp: float
    event: ForensicsEvent
    elapsed_ms: float             # ms kể từ session start
    agent_state: str              # trạng thái agent tại thời điểm này

class ForensicsReplayer:
    async def load_session(self, session_id: str) -> List[ReplayFrame]: ...
    async def get_frame_at(self, session_id: str, timestamp: float) -> ReplayFrame: ...
    async def get_summary(self, session_id: str) -> dict:
        """
        Summary cho export:
        - total_duration, total_cost, total_tokens, peak_latency
        - tools_called (list unique), hitl_decisions (count)
        - firewall_blocks (count), policy_blocks (count)
        - risk_assessment: low/medium/high/critical
        """
        ...
```

**2.3 — `ironcore/enterprise/forensics/exporter.py`:**
```python
class EvidenceExport(BaseModel):
    session_id: str
    generated_at: float
    generated_by: str           # admin user id
    summary: dict
    events: List[dict]          # masked: không có raw prompt text > 200 chars
    chain_valid: bool
    metadata: dict

class ForensicsExporter:
    async def export_json(self, session_id: str, exporter_id: str) -> EvidenceExport:
        """Export JSON evidence bundle — masked secrets, truncated prompts."""
        ...
    
    async def export_csv_events(self, session_id: str) -> str:
        """CSV chỉ có: timestamp, event_type, agent_id, cost, latency"""
        ...
```

**2.4 — API Routes:**
```python
GET  /api/forensics/sessions                  # list sessions có forensics data
GET  /api/forensics/sessions/{id}/timeline    # full event list
GET  /api/forensics/sessions/{id}/summary     # summary + risk assessment
GET  /api/forensics/sessions/{id}/export      # JSON evidence bundle
GET  /api/forensics/sessions/{id}/verify      # verify hash chain
GET  /api/forensics/sessions/{id}/replay      # SSE: replay events real-time
```

**2.5 — Tích hợp vào engine:**
```python
# Trong IronCoreEngine.run_loop() — hook recorder ở đầu/cuối mỗi bước:
await self._forensics.record(ForensicsEvent(
    session_id=session_id,
    agent_id=agent_id,
    event_type=ForensicsEventType.TOOL_CALL,
    data={"tool_name": tool_name, "params_hash": hash(str(params))},
    cost_usd=cost,
    latency_ms=latency,
))
```

**Test file:** `tests/test_phase2_security_forensics.py`
- Test: record → verify chain (unmodified)
- Test: tamper event → chain verify fail
- Test: export masked (no long raw prompts)
- Test: replayer load_session order

**Dừng và báo cáo Phase 2.**

---

### ═══ PHASE 3 ═══ GUARDRAIL STUDIO — POLICY BUILDER BACKEND

**Trigger:** `Security V3: Phase 3`

**Mục tiêu (từ TONG_HOP mục 8.1):** Xây backend cho **Agent Guardrail Studio** — hệ thống cho admin build, test và deploy policy (rule) điều chỉnh hành vi agent không cần restart. ChatGPT V3 sẽ build UI kéo-thả lên trên.

**PARTS bắt buộc:**
- `R: read_file ironcore/security/rbac.py` — permission model
- `R: read_file ironcore/security/rule_loader.py` (nếu có) — xem pattern load rule hiện tại
- `T: <think>` Rule evaluation: mỗi action của agent đi qua GuardrailEvaluator TRƯỚC KHI thực thi. Rule có thể: allow / block / require_hitl / log_only / downgrade_model.

**Deliverables:**

**3.1 — `ironcore/enterprise/guardrail/rules_store.py`:**
```python
class GuardrailCondition(BaseModel):
    field: str                    # "action_type" | "risk_level" | "cost_estimate" | "tool_name" | "session_age"
    operator: str                 # "eq" | "gt" | "lt" | "contains" | "regex"
    value: Any

class GuardrailEffect(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"
    REQUIRE_HITL = "require_hitl"
    LOG_ONLY = "log_only"
    DOWNGRADE_MODEL = "downgrade_model"   # Switch sang model rẻ hơn
    ALERT = "alert"                       # Emit alert không block

class GuardrailRule(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    description: str = ""
    conditions: List[GuardrailCondition]  # AND logic giữa conditions
    effect: GuardrailEffect
    priority: int = 100           # Số nhỏ = ưu tiên cao
    enabled: bool = True
    tags: List[str] = []
    created_by: str = "system"
    created_at: float = Field(default_factory=time.time)

class GuardrailRulesStore:
    """TOML-backed, hot-reload khi file thay đổi."""
    async def load(self) -> List[GuardrailRule]: ...
    async def save_rule(self, rule: GuardrailRule) -> None: ...
    async def delete_rule(self, rule_id: str) -> None: ...
    async def get_active_rules(self) -> List[GuardrailRule]: ...
```

**3.2 — `ironcore/enterprise/guardrail/evaluator.py`:**
```python
class GuardrailDecision(BaseModel):
    allowed: bool
    effect: GuardrailEffect
    triggered_rule: Optional[GuardrailRule] = None
    message: str = ""

class GuardrailEvaluator:
    async def evaluate(
        self,
        action_type: str,
        risk_level: str,
        tool_name: str,
        session_id: str,
        cost_estimate: float,
        context: Dict[str, Any] = {},
    ) -> GuardrailDecision:
        """
        Evaluate action qua sorted rule list (priority ASC).
        First match → return decision immediately.
        No match → allow by default.
        """
        ...

    async def test_rule(
        self,
        rule: GuardrailRule,
        test_input: Dict[str, Any],
    ) -> GuardrailDecision:
        """Dry-run single rule — không affect state."""
        ...
```

**3.3 — API Routes:**
```python
GET  /api/guardrail/rules                    # list all rules (sorted by priority)
POST /api/guardrail/rules                    # create rule
PUT  /api/guardrail/rules/{id}              # update rule
DELETE /api/guardrail/rules/{id}            # delete rule
POST /api/guardrail/rules/{id}/enable       # enable/disable toggle
POST /api/guardrail/rules/test              # test rule against sample input body
GET  /api/guardrail/stats                   # rule trigger count stats
```

**Test file:** `tests/test_phase3_security_guardrail.py`
- Test: rule priority ordering
- Test: first-match behavior
- Test: test_rule dry-run không thay đổi state
- Test: hot-reload rule store

**Dừng và báo cáo Phase 3.**

---

### ═══ PHASE 4 ═══ HITL V2 — MULTI-LEVEL APPROVAL + AUTO-ESCALATION

**Trigger:** `Security V3: Phase 4`

**Mục tiêu (từ TONG_HOP mục 8.1 & mục 5):** Nâng cấp HITL từ 1 approver thành multi-level với auto-escalation và audit chain.

**PARTS bắt buộc:**
- `R: read_file ironcore/enterprise/hitl/engine.py` — toàn bộ
- `R: read_file ironcore/enterprise/hitl/models.py` — toàn bộ
- `T: <think>` Multi-level: L1 (team_lead, 5 phút) → L2 (manager, 10 phút) → L3 (admin, 15 phút). Nếu L3 không duyệt → auto-reject và log.

**Deliverables:**

**4.1 — Nâng cấp `ironcore/enterprise/hitl/engine.py`:**
```python
class ApprovalLevel(BaseModel):
    level: int                    # 1, 2, 3
    role_required: str            # "team_lead" | "manager" | "admin"
    timeout_minutes: int
    auto_action_on_timeout: str   # "escalate" | "reject"

class HITLRequestV2(BaseModel):
    id: str
    action_type: str
    risk_level: str
    current_level: int = 1
    approval_chain: List[ApprovalLevel]
    decisions: List[dict] = []   # history quyết định từng level
    status: str                   # "pending_l1" | "pending_l2" | "pending_l3" | "approved" | "rejected" | "expired"
    created_at: float
    sla_expires_at: float         # deadline của level hiện tại
```

**4.2 — `ironcore/enterprise/hitl/escalation.py`:**
```python
class EscalationEngine:
    """Background task kiểm tra SLA và tự escalate."""
    async def start(self) -> None:
        """Chạy vòng lặp mỗi 30s kiểm tra timeout."""
        ...
    
    async def check_and_escalate(self) -> List[str]:
        """
        Với mỗi pending request quá SLA:
        - Nếu level < max → escalate lên level tiếp
        - Nếu level = max → auto_action (reject + log)
        - Notify approvers mới qua notifiers.py
        Return: list request IDs đã escalate
        """
        ...
```

**4.3 — `ironcore/enterprise/hitl/audit_chain.py`:**
```python
class HITLAuditEntry(BaseModel):
    request_id: str
    level: int
    action: str                   # "approved" | "rejected" | "escalated" | "expired"
    actor: str                    # user_id hoặc "system"
    reason: str = ""
    timestamp: float
    entry_hash: str               # SHA-256(prev_hash + content)
    prev_hash: str = ""

class HITLAuditChain:
    """Immutable append-only audit log với hash chaining."""
    async def append(self, entry: HITLAuditEntry) -> None: ...
    async def get_history(self, request_id: str) -> List[HITLAuditEntry]: ...
    async def verify_integrity(self, request_id: str) -> bool: ...
```

**4.4 — API Routes (thêm vào server):**
```python
GET  /api/enterprise/hitl/pending            # pending theo level hiện tại của user's role
POST /api/enterprise/hitl/{id}/approve       # approve, tự escalate nếu cần next level
POST /api/enterprise/hitl/{id}/reject        # reject + reason
GET  /api/enterprise/hitl/history            # paginated decisions
GET  /api/enterprise/hitl/{id}/audit         # audit chain cho request cụ thể
```

**Dừng và báo cáo Phase 4.**

---

### ═══ PHASE 5 ═══ AIRGAP ADMIN API + SIEM/IAM API ENDPOINTS

**Trigger:** `Security V3: Phase 5`

**Mục tiêu:** Tạo các API endpoint còn thiếu để ChatGPT V3 có thể gọi và render UI cho SIEM, IAM, và Airgap operations.

**PARTS bắt buộc:**
- `R: read_file ironcore/enterprise/siem/*.py` — toàn bộ module
- `R: read_file ironcore/enterprise/iam/*.py` — toàn bộ module
- `R: read_file ironcore/enterprise/airgap/*.py` — toàn bộ module

**Deliverables:**

**5.1 — `ironcore/api/siem_routes.py`:**
```python
# GET  /api/enterprise/siem/stream    → SSE stream SIEMEvent
# GET  /api/enterprise/siem/events    → paginated list, filter by severity/source/date
# GET  /api/enterprise/siem/stats     → aggregated stats (counts by severity)
# GET  /api/enterprise/siem/config    → cấu hình hiện tại (transports enabled, targets)
# POST /api/enterprise/siem/test      → gửi test event xem transport hoạt động không
```

**5.2 — `ironcore/api/iam_routes.py`:**
```python
# GET  /api/enterprise/iam/users             → list (masked email/info)
# GET  /api/enterprise/iam/roles             → list roles + permissions
# POST /api/enterprise/iam/roles             → create role
# PUT  /api/enterprise/iam/roles/{id}        → update
# DELETE /api/enterprise/iam/roles/{id}      → delete (nếu không có user nào)
# GET  /api/enterprise/iam/sso/mappings      → SSO group → role mappings
# GET  /api/enterprise/iam/vault/bindings    → vault secret bindings (tên, không có giá trị)
```

**5.3 — `ironcore/enterprise/airgap/admin_api.py` + routes:**
```python
# GET  /api/enterprise/airgap/status         → airgap mode on/off, policy active
# GET  /api/enterprise/airgap/audit          → recent airgap violations/attempts
# POST /api/enterprise/airgap/config         → update policy (requires admin JWT)
# GET  /api/enterprise/airgap/allowed-models → list models permitted in airgap mode
```

**5.4 — Budget + Mesh stream endpoints (nếu chưa có):**
```python
# GET /api/enterprise/budget/stream   → SSE BudgetSnapshot
# GET /api/enterprise/budget/report
# GET /api/mesh/nodes
# GET /api/runtime/agents/stream      → SSE AgentEvent cho Spatial Map ChatGPT
```

**Dừng và báo cáo Phase 5.**

---

### ═══ PHASE 6 ═══ SECTION 21: AUTOMATION & INTELLIGENCE LAYER

**Trigger:** `Security V3: Phase 6`

**Mục tiêu (mục 21 mới nhất từ TONG_HOP):** Xây **Automation & Intelligence Layer** — tầng tự động hóa thông minh giúp IronCore tự học từ pattern vận hành và tự phản ứng sự cố không cần admin can thiệp thủ công.

> Đây là tính năng "thế hệ tiếp theo" tạo ra sự khác biệt rõ ràng với OpenClaw.

**PARTS bắt buộc:**
- `R: Read tất cả module enterprise đã build trong Phase 1–5`
- `T: <think>` 
  3 trụ cột của Intelligence Layer:
  1. **Anomaly Detection**: phát hiện pattern bất thường trong cost, latency, error rate
  2. **Incident Response Auto**: khi detect incident → trigger playbook tự động
  3. **Policy Learning**: học từ HITL decisions của admin → tự đề xuất rule mới

**Deliverables:**

**6.1 — `ironcore/monitoring/incident_detector.py`:**
```python
class AnomalyType(str, Enum):
    COST_SPIKE = "cost_spike"                 # cost tăng > X% trong Y phút
    HIGH_ERROR_RATE = "high_error_rate"       # error rate > threshold
    UNUSUAL_TOOL_PATTERN = "unusual_tool"     # tool lạ được gọi nhiều
    LATENCY_DEGRADATION = "latency_degrad"    # P95 tăng đột ngột
    FIREWALL_BURST = "firewall_burst"         # nhiều detection trong 1 phút
    SESSION_ANOMALY = "session_anomaly"       # session quá dài hoặc quá nhiều tokens

class Incident(BaseModel):
    id: str
    anomaly_type: AnomalyType
    severity: str
    detected_at: float
    context: Dict[str, Any]
    suggested_actions: List[str]
    auto_resolved: bool = False
    resolved_at: Optional[float] = None

class IncidentDetector:
    """Background daemon — sampling metrics mỗi 30s."""
    async def start(self) -> None: ...
    async def check_anomalies(self) -> List[Incident]: ...
    async def list_active_incidents(self) -> List[Incident]: ...
```

**6.2 — `ironcore/monitoring/alert_manager.py`:**
```python
class AlertChannel(str, Enum):
    SIEM = "siem"               # Đẩy vào SIEM stream
    WEBHOOK = "webhook"         # Gọi webhook đã đăng ký
    TELEGRAM = "telegram"       # Gửi Telegram message
    EMAIL = "email"             # Gửi email (SMTP)

class AlertManager:
    async def send_alert(self, incident: Incident, channels: List[AlertChannel]) -> None: ...
    async def configure_routing(self, severity: str, channels: List[AlertChannel]) -> None: ...
    # Routing: critical → SIEM + Telegram + Webhook
    #          high     → SIEM + Webhook
    #          medium   → SIEM
    #          low      → log only
```

**6.3 — `ironcore/monitoring/automation_layer.py`:**
```python
class Playbook(BaseModel):
    id: str
    name: str
    trigger: AnomalyType
    steps: List[dict]         # ordered list of actions
    enabled: bool = True

class AutomationLayer:
    """
    Khi IncidentDetector phát hiện anomaly:
    1. Lookup playbook match anomaly_type
    2. Execute steps tự động:
       - "throttle_session": giới hạn token/min cho session
       - "quarantine_session": tạm quarantine
       - "downgrade_model": switch sang model rẻ/an toàn hơn
       - "notify_hitl": tạo HITL request cho admin
       - "rollback_config": rollback config về snapshot trước
    3. Log kết quả vào ForensicsRecorder
    """
    async def execute_playbook(self, incident: Incident) -> dict: ...
    async def register_playbook(self, playbook: Playbook) -> None: ...

class PolicyLearner:
    """
    Học từ HITL decisions để đề xuất rule mới.
    Nếu admin approve cùng loại action nhiều lần →
    đề xuất GuardrailRule tự động ALLOW loại đó.
    Nếu admin reject → đề xuất BLOCK rule.
    Output: List[GuardrailRule] cần admin confirm.
    """
    async def analyze_decisions(self, window_days: int = 7) -> List[GuardrailRule]: ...
    async def get_suggestions(self) -> List[dict]: ...   # Pending suggestions cho admin review
```

**6.4 — API Routes:**
```python
GET  /api/monitoring/incidents           # active incidents
GET  /api/monitoring/incidents/history   # resolved incidents
POST /api/monitoring/incidents/{id}/resolve  # manual resolve
GET  /api/monitoring/playbooks           # registered playbooks
POST /api/monitoring/playbooks           # register new playbook
GET  /api/monitoring/suggestions         # PolicyLearner suggestions
POST /api/monitoring/suggestions/{id}/approve   # Admin approve → create rule
POST /api/monitoring/suggestions/{id}/dismiss   # Dismiss suggestion
```

**Dừng và báo cáo Phase 6.**

---

## PHẦN 5: TIÊU CHUẨN CODE BẮT BUỘC

```python
# LUÔN dùng:
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any
import logging, asyncio, time
from uuid import uuid4

logger = logging.getLogger(__name__)

# Exception hierarchy riêng:
class SecurityError(Exception): ...
class FirewallError(SecurityError): ...
class ForensicsError(SecurityError): ...
class GuardrailError(SecurityError): ...

# Mọi I/O đều async
# Mọi route đều có proper JWT auth check
# Không log raw prompt / giá trị secret
# Test theo hành vi thực tế (happy path + security path + failure path)
# Tuân theo .github/ workflow rules
```

---

## PHẦN 6: ĐỊNH NGHĨA "DONE" CHO MỖI PHASE

Phase được coi là **DONE** khi:
1. `python -m pytest tests/test_phaseN_security_*.py -v` — PASS tất cả
2. Không có import không có trong `requirements.txt` (hoặc đề xuất thêm)
3. API routes có trong `ironcore/api/server.py` (included)
4. Interface contract đúng format ChatGPT V3 có thể gọi
5. Output báo cáo: files tạo + test kết quả + API list
