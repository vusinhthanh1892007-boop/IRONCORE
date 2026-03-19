# IronCore V2→V3 — Project Status & Full Documentation
> Last updated: 18/03/2026 · Sau khi chuyển sang đội V3 (ChatGPT UI V3 + Claude Security V3)

---

## Mục lục

1. [Tổng quan dự án](#1-tổng-quan-dự-án)
2. [Tech Stack & Môi trường](#2-tech-stack--môi-trường)
3. [Kiến trúc codebase](#3-kiến-trúc-codebase)
4. [Edition System](#4-edition-system)
5. [Các Phase đã hoàn thành (V1/V2 — Phase 1–10+)](#5-các-phase-đã-hoàn-thành)
6. [Tổng kết test coverage](#6-tổng-kết-test-coverage)
7. [V3 Roadmap — Phase tiếp theo](#7-v3-roadmap)
8. [Conventions & Patterns](#8-conventions--patterns)
9. [Cách chạy tests](#9-cách-chạy-tests)

---

## 1. Tổng quan dự án

IronCore V2→V3 là một AI Agent Platform cấp enterprise với hai tier:

| Tier | Env Var | Mô tả |
|---|---|---|
| **Community Edition (CE)** | `IRONCORE_EDITION=community` | Open-source, chat/plugin/scheduler/webhooks/browser cơ bản |
| **Enterprise Edition (EE)** | `IRONCORE_EDITION=enterprise` | Full features: DLP/IAM/SIEM/Budget/Airgap/HITL/Guardrail |

Dự án V1/V2 đã hoàn thành **Phase 1–10** cộng với các module enterprise nâng cao (Budget Phase 15–18, Optimizer, SIEM/IAM cơ sở, Browser Ghost engine).

**V3** tập trung vào 2 hướng còn thiếu (theo `TONG_HOP_DU_AN_IRONCORE_VS_OPENCLAW.md`):
- **ChatGPT UI V3**: Đưa sức mạnh backend lên Control-Plane UI + tính năng trải nghiệm mới
- **Claude Security V3**: Hoàn thiện Enterprise Security tier + tầng Automation Intelligence

---

## 2. Tech Stack & Môi trường

| Thành phần | Version / Chi tiết |
|---|---|
| **Python** | 3.13.x (miniconda) |
| **PYTHONPATH** | `.` (phải `cd` vào project root trước) |
| **pytest** | 9.x, mode=AUTO |
| **pytest-asyncio** | mode=AUTO |
| **Pydantic** | v2 (`BaseModel`, `model_dump_json()`) |
| **APScheduler** | ≥3.10,<4 |
| **SQLAlchemy** | ≥2.0 |
| **FastAPI** | 0.11x |
| **Next.js** | 15 (App Router) |
| **TypeScript** | 5.x strict |
| **Tailwind CSS** | v4 |
| **shadcn/ui** | Radix UI primitives |
| **Project root** | `/home/vusinhthanh/train ai/` |

**Lệnh chạy test chuẩn:**
```bash
cd "/home/vusinhthanh/train ai" && PYTHONPATH="." python -m pytest tests/<test_file>.py -v --tb=short
```

**Chạy frontend:**
```bash
cd "/home/vusinhthanh/train ai/web" && npm run dev
```

---

## 3. Kiến trúc codebase

```
/home/vusinhthanh/train ai/
├── ironcore/                         ← Core package
│   ├── edition.py                    ← CE/EE edition guard
│   ├── api/                          ← FastAPI routes
│   │   ├── server.py                 ← Main FastAPI app
│   │   ├── auth.py                   ← JWT auth
│   │   ├── ota_routes.py
│   │   ├── scheduler_routes.py
│   │   ├── webhook_routes.py
│   │   ├── channels_routes.py
│   │   ├── stealth_routes.py
│   │   └── lsp_routes.py
│   │   [V3 thêm]: hitl_routes.py, siem_routes.py, iam_routes.py,
│   │              forensics_routes.py, guardrail_routes.py
│   ├── browser/                      ← Browser automation (Ghost agent, stealth)
│   ├── channels/                     ← Telegram, Discord, Zalo, Messenger, WhatsApp
│   ├── core/                         ← Engine, LLMBridge, ContextOptimizer
│   ├── enterprise/
│   │   ├── airgap/                   ← Phase 7 ✅ | [V3] admin_api.py
│   │   ├── dlp/                      ← Phase 8 ✅
│   │   ├── hitl/                     ← Phase 9 ✅ | [V3] escalation.py, audit_chain.py
│   │   ├── iam/                      ← Phase 10 ✅
│   │   ├── siem/                     ← formatter/streamer ✅ | [V3] API endpoints
│   │   ├── budget/                   ← Phase 15–18 ✅
│   │   ├── forensics/                ← [V3 TẠO MỚI] recorder, replayer, exporter
│   │   └── guardrail/                ← [V3 TẠO MỚI] studio, rules_store, evaluator
│   ├── lsp/                          ← LSP bridge
│   ├── memory/                       ← GraphRAG, session store
│   ├── mesh/                         ← Phase 6 ✅ Multi-node mesh
│   ├── monitoring/                   ← [V3 TẠO MỚI] incident_detector, alert_manager, automation_layer
│   ├── optimizer/                    ← Semantic cache, Compression, MCP, Rerank ✅
│   ├── ota/                          ← Phase 2 ✅
│   ├── plugins/                      ← Phase 1 ✅
│   ├── sandbox/
│   ├── scheduler/                    ← Phase 3 ✅
│   ├── security/                     ← RBAC, policy, scanner | [V3] prompt_firewall.py nâng cấp
│   ├── skills/
│   ├── vlm/
│   └── webhooks/                     ← Phase 4 ✅
├── tests/                            ← Test suite
│   ├── [Phase 1–10: đã có] ✅
│   [V3 thêm]:
│   ├── test_phase1_security_firewall.py
│   ├── test_phase2_security_forensics.py
│   ├── test_phase3_security_guardrail.py
│   ├── test_phase4_security_hitlv2.py
│   └── test_phase6_security_automation.py
├── web/                              ← Next.js 15 frontend
│   └── src/
│       ├── app/                      ← Pages (chat ✅ | control-plane/hitl/siem/iam/spatial V3)
│       ├── components/               ← UI components
│       └── lib/                      ← API client, SSE client ✅
├── cli.py                            ← Terminal 14-step wizard + chat ✅
├── pyproject.toml
├── requirements.txt
├── docker-compose.yml
├── Makefile
└── TONG_HOP_DU_AN_IRONCORE_VS_OPENCLAW.md  ← Tài liệu chiến lược
```

---

## 4. Edition System

**File:** `ironcore/edition.py`

```python
class Edition(str, Enum):
    COMMUNITY  = "community"
    ENTERPRISE = "enterprise"

def get_edition() -> Edition              # đọc IRONCORE_EDITION env var
def is_enterprise() -> bool
def is_community() -> bool
def check_enterprise(feature_name: str)   # raise RuntimeError nếu CE
@enterprise_only(feature_name)            # decorator version
def get_feature_list() -> dict
```

**Convention trong test files:**
```python
import os
os.environ["IRONCORE_EDITION"] = "enterprise"  # PHẢI đặt TRƯỚC mọi import
```

---

## 5. Các Phase đã hoàn thành

| Phase | Tên | Module | Test | Tests | Status |
|---|---|---|---|---|---|
| Phase 1 | Plugin System | `ironcore/plugins/` | `test_phase1_architect_plugins.py` | ~40 | ✅ |
| Phase 2 | OTA Update Manager | `ironcore/ota/` | `test_phase2_architect_ota.py` | ~35 | ✅ |
| Phase 3 | Cron Scheduler | `ironcore/scheduler/` | `test_phase3_architect_scheduler.py` | ~30 | ✅ |
| Phase 4 | Webhook Server | `ironcore/webhooks/` | `test_phase4_architect_webhooks.py` | ~45 | ✅ |
| Phase 5 | Channel Connectors | `ironcore/channels/` | `test_phase5_architect_channels.py` | 51 | ✅ |
| Phase 6 | Multi-node Mesh | `ironcore/mesh/` | `test_phase6_architect_mesh.py` | 49 | ✅ |
| Phase 7 | Air-Gapped Enterprise | `ironcore/enterprise/airgap/` | `test_phase7_enterprise_airgap.py` | 41 | ✅ |
| Phase 8 | DLP Engine | `ironcore/enterprise/dlp/` | `test_phase8_enterprise_dlp.py` | 62 | ✅ |
| Phase 9 | Maker-Checker HITL | `ironcore/enterprise/hitl/` | `test_phase9_enterprise_hitl.py` | 56 | ✅ |
| Phase 10 | Enterprise IAM & SSO | `ironcore/enterprise/iam/` | `test_phase10_enterprise_iam.py` | 54 | ✅ |
| Phase 11 | SIEM Integration | `ironcore/enterprise/siem/` | — | — | ✅ Backend có, thiếu API |
| Phase 15–18 | Budget System | `ironcore/enterprise/budget/` | — | — | ✅ |
| Optimizer | Cache/Compress/MCP | `ironcore/optimizer/` | — | — | ✅ |

### Key interfaces đã export (không được thay đổi):

**Plugin System:**
```python
class PluginRegistry:
    async def install_plugin(source_url, requester_id) -> PluginManifest
    async def uninstall_plugin(plugin_id) -> None
    async def list_plugins() -> List[PluginInfo]

class PluginLoader:
    FORBIDDEN_MODULES: frozenset  # subprocess, os, sys ...
    def scan_security(plugin_dir) -> List[str]  # AST-based, không execute code
```

**HITL (Phase 9 — sẽ được nâng cấp bởi Claude Security V3):**
```python
class ApprovalTicket(BaseModel):
    ticket_id: str  # "IRON-{12 hex}"
    status: ApprovalStatus  # PENDING/APPROVED/REJECTED/EXPIRED/CANCELLED
    required_approvals: int
    signatures: Dict[str, str]  # approver_id → HMAC

class MakerCheckerEngine:
    async create_ticket(action, payload, created_by, approvers) -> ApprovalTicket
    async approve(ticket_id, approver_id, session_key) -> ApprovalTicket
    async reject(ticket_id, approver_id, reason) -> ApprovalTicket
    async list_pending() -> List[ApprovalTicket]
```

**IAM/SSO (Phase 10):**
```python
class SSOProvider(str, Enum): AZURE_ENTRA, OKTA, ACTIVE_DIRECTORY, GENERIC_OIDC
class SSOManager:
    def get_authorization_url(state, code_challenge) -> str
    async exchange_code(code, state, code_verifier) -> SSOUserInfo
class VaultSecretsManager:
    async get_secret(path) -> str
    async get_dynamic_credential(role) -> DynamicCredential
```

---

## 6. Tổng kết test coverage

| Phase | Module | Tests | Status |
|---|---|---|---|
| Phase 1–10 | Tất cả | **≥463** | ✅ ALL PASSED |
| V3 Phase 1–6 | Security modules | TBD | 🔄 In Progress |
| Web UI | Next.js | npm build PASS | ✅ skeleton OK |

---

## 7. V3 Roadmap

### 7.1 — Claude Security V3 (Backend)

| Phase | Tên | Module | Trigger |
|---|---|---|---|
| **V3-S1** | Prompt Firewall AI | `ironcore/security/prompt_firewall.py` | `Security V3: Phase 1` |
| **V3-S2** | Forensics Replay Engine | `ironcore/enterprise/forensics/` | `Security V3: Phase 2` |
| **V3-S3** | Guardrail Studio Backend | `ironcore/enterprise/guardrail/` | `Security V3: Phase 3` |
| **V3-S4** | HITL V2 Multi-level | `ironcore/enterprise/hitl/` nâng cấp | `Security V3: Phase 4` |
| **V3-S5** | SIEM/IAM/Airgap API Endpoints | `ironcore/api/*_routes.py` | `Security V3: Phase 5` |
| **V3-S6** | Section 21: Automation Layer | `ironcore/monitoring/` | `Security V3: Phase 6` |

### 7.2 — ChatGPT UI V3 (Frontend)

| Phase | Tên | Route / Component | Trigger |
|---|---|---|---|
| **V3-U1** | Control-Plane UI | `/dashboard/(usage/cron/nodes/logs/config/alerts)` | `UI V3: Phase 1` |
| **V3-U2** | HITL Approval UI | `/hitl/` | `UI V3: Phase 2` |
| **V3-U3** | SIEM & IAM Admin UI | `/siem/` `/iam/` | `UI V3: Phase 3` |
| **V3-U4** | Iron Man (Camera/Voice/Gesture) | `components/ironman/` | `UI V3: Phase 4` |
| **V3-U5** | Spatial Agent 2D Map | `/spatial/` | `UI V3: Phase 5` |
| **V3-U6** | Forensics Replay UI | `/forensics/` | `UI V3: Phase 6` |

### 7.3 — API Endpoints cần có (Claude build, ChatGPT call)

```
GET  /api/enterprise/hitl/pending
POST /api/enterprise/hitl/{id}/approve
POST /api/enterprise/hitl/{id}/reject
GET  /api/enterprise/siem/stream          ← SSE
GET  /api/enterprise/siem/events
GET  /api/enterprise/iam/users
GET  /api/enterprise/iam/roles
GET  /api/forensics/sessions/{id}/timeline
GET  /api/forensics/sessions/{id}/export
GET  /api/guardrail/rules
GET  /api/monitoring/incidents
GET  /api/runtime/agents/stream           ← SSE cho Spatial Map
GET  /api/mesh/nodes
GET  /api/enterprise/budget/stream        ← SSE
```

---

## 8. Conventions & Patterns

### 8.1 Enterprise Guard Pattern
```python
from ironcore.edition import check_enterprise

class MyEnterpriseFeature:
    def __init__(self, ...):
        check_enterprise("feature_name")
        # ... rest of init
```

### 8.2 Stub Pattern (http_client=None)
```python
async def get_secret(self, path: str) -> str:
    if self._http is None:
        h = hashlib.sha256(path.encode()).hexdigest()
        return f"stub-secret-{h[:8]}"
    # ... real implementation
```

### 8.3 Test Pattern
```python
# ĐẦU FILE — TRƯỚC mọi import:
import os
os.environ["IRONCORE_EDITION"] = "enterprise"

from unittest.mock import AsyncMock, MagicMock
mock_http = MagicMock()
mock_http.post = AsyncMock(return_value=MagicMock(json=lambda: {...}))
```

### 8.4 Async Test Convention
```python
# pytest-asyncio mode=AUTO — không cần @pytest.mark.asyncio
async def test_something():
    result = await some_async_func()
    assert result == expected
```

### 8.5 Security Patterns
- **No shell=True** — subprocess dùng list form
- **Constant-time comparison** — `hmac.compare_digest()` cho signature
- **TTL-based deduplication** — replay attack prevention
- **HMAC-SHA256** — digital signatures cho audit trail
- **AST-based scan** — không execute code không tin tưởng
- **CIDR allowlist** — network isolation (airgap)
- **JIT secrets** — secrets không cache, revoke ngay sau dùng
- **Masked output** — không bao giờ log/display raw secret

### 8.6 API Route Registration
```python
# Trong ironcore/api/server.py, include router mới:
from ironcore.api.hitl_routes import router as hitl_router
app.include_router(hitl_router, prefix="/api/enterprise/hitl", tags=["HITL"])
```

---

## 9. Cách chạy tests

### Chạy một phase cụ thể
```bash
cd "/home/vusinhthanh/train ai"
PYTHONPATH="." python -m pytest tests/test_phase10_enterprise_iam.py -v --tb=short
```

### Chạy toàn bộ test suite
```bash
cd "/home/vusinhthanh/train ai"
PYTHONPATH="." python -m pytest tests/ -v --tb=short
```

### Chạy với filter
```bash
PYTHONPATH="." python -m pytest tests/ -v -k "security"
PYTHONPATH="." python -m pytest tests/ -v -k "firewall"
```

### Chạy frontend dev server
```bash
cd "/home/vusinhthanh/train ai/web"
npm run dev
# → http://localhost:3000
```

### Kiểm tra môi trường
```bash
python --version          # 3.13.x
node --version            # ≥ 20.x
npm --version
```
