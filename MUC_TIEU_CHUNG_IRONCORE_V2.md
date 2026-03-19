# MỤC TIÊU CHUNG — IRONCORE V2 → V3
## Tài liệu Bắt Buộc Đọc Cho TẤT CẢ AI Agents

---

> **⚠ ĐÂY LÀ TÀI LIỆU ĐỌC BẮT BUỘC ĐẦU TIÊN.**
> Trước khi đọc prompt riêng, tất cả AI phải đọc toàn bộ file này + `.github/` workflows/rules.
> Đây là khế ước chung của toàn dự án. Vi phạm = phá vỡ toàn bộ hệ thống.

---

## PHẦN 1: BỐI CẢNH & TRẠNG THÁI DỰ ÁN (tháng 3/2026)

### 1.1 — Những gì V1 & V2 đã xây dựng xong (KHÔNG được viết lại)

IronCore đã hoàn thành 10 phase đầu (Phase 1–10) cộng với nhiều module enterprise:

| Đã hoàn thành | Module | Trạng thái |
|---|---|---|
| Plugin System | `ironcore/plugins/` | ✅ Phase 1 |
| OTA Updates | `ironcore/ota/` | ✅ Phase 2 |
| Cron Scheduler | `ironcore/scheduler/` | ✅ Phase 3 |
| Webhook Server | `ironcore/webhooks/` | ✅ Phase 4 |
| Channel Connectors (Telegram/Discord/Zalo/Messenger/WhatsApp) | `ironcore/channels/` | ✅ Phase 5 |
| Multi-node Mesh | `ironcore/mesh/` | ✅ Phase 6 |
| Air-Gapped Enterprise | `ironcore/enterprise/airgap/` | ✅ Phase 7 |
| DLP Engine | `ironcore/enterprise/dlp/` | ✅ Phase 8 |
| Maker-Checker HITL | `ironcore/enterprise/hitl/` | ✅ Phase 9 (nâng cấp trong V3) |
| Enterprise IAM & SSO | `ironcore/enterprise/iam/` | ✅ Phase 10 |
| SIEM Formatter/Streamer | `ironcore/enterprise/siem/` | ✅ Đã có (cần thêm API & UI) |
| Budget Guard & Ledger | `ironcore/enterprise/budget/` | ✅ Phase 15–18 |
| Optimizer (Cache, Compression, MCP, Rerank) | `ironcore/optimizer/` | ✅ Đã hoàn thành |
| Web UI cơ bản | `web/src/` | ✅ Skeleton (cần nâng cấp) |
| CLI / Terminal | `cli.py` | ✅ 14-step wizard + chat loop |

### 1.2 — Vì sao tiếp tục (những gì còn thiếu theo TONG_HOP_DU_AN)

| Thiếu sót hiện tại | Nguồn gốc | Ai giải quyết |
|---|---|---|
| Control-Plane UI chưa đủ (Usage/Cron/Nodes/Logs) | TONG_HOP mục 5, 11.2 | ChatGPT UI V3 |
| HITL UI chưa có trên web | TONG_HOP mục 5 | ChatGPT UI V3 |
| SIEM & IAM admin UI trống | TONG_HOP mục 5 | ChatGPT UI V3 |
| Iron Man features (Camera/Voice/Gesture) | TONG_HOP mục 11.3 | ChatGPT UI V3 |
| Spatial Agent 2D Map | TONG_HOP mục 12 | ChatGPT UI V3 |
| Prompts Firewall AI chưa đủ mạnh | TONG_HOP mục 8.1 | Claude Security V3 |
| Forensics Replay Engine chưa có | TONG_HOP mục 8.1 & 8.3 | Claude Security V3 |
| Guardrail Studio (policy builder) chưa có | TONG_HOP mục 8.1 | Claude Security V3 |
| HITL multi-level + auto-escalation | TONG_HOP mục 8.1 | Claude Security V3 |
| Automation & Intelligence Layer (Section 21) | TONG_HOP mục 21 | Claude Security V3 |
| API endpoints cho SIEM/IAM/Airgap còn thiếu | TONG_HOP mục 5 | Claude Security V3 |

---

## PHẦN 2: MA TRẬN PHÂN CÔNG V3 — AI NÀO LÀM GÌ

```
╔══════════════════════════════════════╦══════════════════════════════════════╗
║  CHATGPT (GPT-4o / o3 / GPT-next)   ║  CLAUDE (Sonnet 4.6 / Opus 4.6)     ║
║  "THE UI DESIGNER V3"                ║  "THE SECURITY ENGINEER V3"          ║
╠══════════════════════════════════════╬══════════════════════════════════════╣
║ Control-Plane UI (Usage/Cron/Nodes)  ║ Prompt Firewall AI (nâng cấp)        ║
║ HITL Approval Dashboard              ║ Forensics Replay Engine              ║
║ SIEM Log Viewer UI                   ║ Guardrail Studio Backend             ║
║ IAM Admin UI                         ║ HITL V2 (multi-level, escalation)    ║
║ Iron Man: Camera + Voice + Gesture   ║ SIEM/IAM/Airgap API Endpoints        ║
║ Spatial Agent 2D Map                 ║ Section 21: Automation Intelligence  ║
║ Forensics Replay UI                  ║ Incident Detector + Alert Manager    ║
╚══════════════════════════════════════╩══════════════════════════════════════╝
```

**Ranh giới tuyệt đối:**

| ChatGPT sở hữu | Claude sở hữu |
|---|---|
| `web/src/` (toàn bộ Next.js) | `ironcore/security/` |
| API calls → routes backend | `ironcore/enterprise/` (nâng cấp) |
| Mock data khi API chưa có | `ironcore/monitoring/` (mới) |
| **KHÔNG** sửa Python code | `ironcore/api/` (thêm routes mới) |
| **KHÔNG** tạo route mới | **KHÔNG** sửa `web/src/` |

---

## PHẦN 3: NGUYÊN TẮC VÀNG — 7 ĐIỀU BẮT BUỘC CHO MỌI AI

### Nguyên tắc 1 — ĐỌC TRƯỚC KHI LÀM (PARTS Protocol)

```
P — PREVIEW:  list_dir để biết trạng thái hiện tại
A — ANALYZE:  đọc TONG_HOP_DU_AN + file này + .github/ workflows + rules
R — READ:     đọc code hiện tại — KHÔNG bao giờ giả định trạng thái
T — THINK:    <think>...</think> rõ ràng về design quyết định
S — START:    chỉ code sau khi P-A-R-T hoàn tất
```

> **Nếu bỏ qua PARTS → code sẽ conflict, interface sẽ không match, tests sẽ fail.**

### Nguyên tắc 2 — KHÔNG ĐƯỢC VƯỢT RANH GIỚI SỞ HỮU

Mỗi AI có domain riêng. **Tuyệt đối không sửa code của bên kia.**
- Interface thay đổi → báo cáo trước, chờ confirm.
- Cần dùng code bên kia → import, không copy-paste.

### Nguyên tắc 3 — INTERFACE CONTRACT LÀ LUẬT

Khi export class/function cho bên kia dùng → signature đó là **bất biến**.
Thay đổi signature = breaking change = phải thông báo rõ ràng trước.

### Nguyên tắc 4 — PRODUCTION CODE STANDARDS

**Backend (Claude — Python):**
```python
# ✅ Đúng
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import logging
logger = logging.getLogger(__name__)

async def process(data: InputModel) -> OutputModel:
    logger.info("[Module] Action | key=%s", key)
    ...

# ❌ Sai
print("debug")          # Dùng logger
def sync_call(): ...    # Phải async nếu có I/O
# Không hard-code secret, không log raw prompt/token
```

**Frontend (ChatGPT — TypeScript):**
```typescript
// ✅ Đúng
// TypeScript strict mode — no `any`
// Mock data fallback khi API chưa có
// Confirm dialog trước destructive actions
// Không store JWT trong localStorage — chỉ httpOnly cookies

// ❌ Sai
const data: any = ...       // explicit type hoặc unknown
console.log(rawApiKey)      // không log secret
```

### Nguyên tắc 5 — MỖI PHASE PHẢI CÓ TEST/VERIFY

**Backend phases (Claude):**
```
tests/test_phase[N]_security_[name].py
→ pytest phải PASS trước khi báo cáo hoàn thành
```

**Frontend phases (ChatGPT):**
```
npm run lint   → 0 errors
npm run build  → 0 type errors
Route render được trong browser mà không crash
Có mock data fallback khi API unavailable
```

### Nguyên tắc 6 — BÁO CÁO CHUẨN SAU MỖI PHASE

```
╔══════════════════════════════════════════════════════════════╗
║        PHASE [N] — [AI NAME] — HOÀN THÀNH & BÁO CÁO        ║
╠══════════════════════════════════════════════════════════════╣
║ Files đã tạo/sửa:                                           ║
║   [✓] /path/file — [mô tả 1 dòng]                          ║
║                                                              ║
║ Interface export (Claude) hoặc API calls (ChatGPT):         ║
║   [✓] ClassName.method(params) → ReturnType                 ║
║   [✓] GET /api/endpoint → ResponseType                      ║
║                                                              ║
║ Test/Verify kết quả:                                        ║
║   [✓] Backend: pytest X tests PASSED                        ║
║   [✓] Frontend: npm run build OK, route render OK           ║
║                                                              ║
║ Env vars mới (nếu có):                                      ║
║   [✓] IRONCORE_VAR=default  (# Mô tả)                      ║
║                                                              ║
║ ⛔ DỪNG — CHỜ XÁC NHẬN TRƯỚC KHI TIẾP TỤC PHASE TIẾP THEO ║
╚══════════════════════════════════════════════════════════════╝
```

### Nguyên tắc 7 — BẢO MẬT KHÔNG ĐƯỢC COMPROMISE

- Không hard-code API key, secret, password bất kỳ đâu
- Không log sensitive data (tokens, raw prompts, credentials)
- Không disable security middleware để chạy nhanh hơn
- Không expose endpoint nội bộ ra ngoài không có auth
- Secrets: chỉ hiển thị dưới dạng masked hoặc "present: true"

---

## PHẦN 4: KIẾN TRÚC HỆ THỐNG V3 — TOÀN CẢNH

```
                ┌─────────────────────────────────────────────┐
                │              NGƯỜI DÙNG                      │
                │  Browser / Telegram / Discord / CLI / API    │
                └─────────────────┬───────────────────────────┘
                                  │ HTTPS / WebSocket / Bot API
                ┌─────────────────▼───────────────────────────┐
                │         WEB UI LAYER (ChatGPT)               │
                │  Next.js 15 — Chat / Dashboard / HITL UI     │
                │  Control-Plane / Spatial Map / Iron Man      │
                └─────────────────┬───────────────────────────┘
                                  │ REST / SSE / WebSocket
        ┌─────────────────────────▼───────────────────────────┐
        │                 IRONCORE API (FastAPI)               │
        │   /chat  /enterprise/*  /guardrail  /forensics       │
        │   /monitoring  /mesh  /scheduler  /plugins           │
        └────────────┬────────────────────────┬───────────────┘
                     │                        │
        ┌────────────▼────────────┐  ┌────────▼────────────────────┐
        │  SECURITY & AUTOMATION  │  │  CORE INFRA (đã có từ V1/V2)|
        │  (Claude Security V3)   │  │                             │
        │                         │  │  • Plugin System            │
        │  • Prompt Firewall AI   │  │  • Cron Scheduler           │
        │  • Forensics Engine     │  │  • Webhook Server           │
        │  • Guardrail Studio     │  │  • Channel Connectors       │
        │  • HITL V2 Multi-level  │  │  • Multi-node Mesh          │
        │  • Incident Detector    │  │  • OTA Updates              │
        │  • Alert Manager        │  │  • Optimizer Layer          │
        │  • Automation Layer     │  │  • DLP / IAM / SIEM / Budget|
        └────────────┬────────────┘  └────────┬────────────────────┘
                     │                        │
        ┌────────────▼────────────────────────▼────────────────┐
        │              IRONCORE CORE ENGINE                     │
        │    Engine + Memory (GraphRAG) + VLM + Browser        │
        └───────────────────────────────────────────────────────┘
                                  │
        ┌─────────────────────────▼───────────────────────────┐
        │                 DATA LAYER                           │
        │  Redis (cache) + SQLite (sessions/scheduler/forensics│
        │  ChromaDB (RAG) + SQLite WAL (forensics audit chain) │
        └─────────────────────────────────────────────────────┘
```

---

## PHẦN 5: INTERFACE CONTRACTS — AI NÀO CUNG CẤP CHO AI NÀO

### Claude Security V3 cung cấp cho ChatGPT UI V3 (API endpoints):

```python
# ════ HITL (ChatGPT hiển thị + điều khiển) ════
GET  /api/enterprise/hitl/pending          → List[HITLRequest]
POST /api/enterprise/hitl/{id}/approve     → ApprovalResult
POST /api/enterprise/hitl/{id}/reject      → ApprovalResult
GET  /api/enterprise/hitl/history          → paginated

# ════ SIEM (ChatGPT stream + hiển thị) ════
GET  /api/enterprise/siem/stream           → SSE: SIEMEvent
GET  /api/enterprise/siem/events           → paginated List[SIEMEvent]
GET  /api/enterprise/siem/stats            → severity counts

# ════ IAM (ChatGPT quản lý) ════
GET  /api/enterprise/iam/users             → List[UserInfo] (masked)
GET  /api/enterprise/iam/roles             → List[RoleInfo]
GET  /api/enterprise/iam/sso/mappings      → List[SSOMapping]
GET  /api/enterprise/iam/vault/bindings    → List[VaultBinding] (no values)

# ════ Forensics (ChatGPT replay UI) ════
GET  /api/forensics/sessions               → List sessions
GET  /api/forensics/sessions/{id}/timeline → List[ForensicsEvent]
GET  /api/forensics/sessions/{id}/export   → EvidenceExport (masked)
GET  /api/forensics/sessions/{id}/replay   → SSE: replay stream

# ════ Guardrail (ChatGPT policy UI) ════
GET  /api/guardrail/rules                  → List[GuardrailRule]
POST /api/guardrail/rules                  → create rule
POST /api/guardrail/rules/{id}/test        → test result

# ════ Monitoring (ChatGPT dashboard) ════
GET  /api/monitoring/incidents             → List[Incident]
GET  /api/monitoring/suggestions           → List PolicyLearner suggestions
GET  /api/enterprise/budget/stream         → SSE: BudgetSnapshot
GET  /api/mesh/nodes                       → List[NodeInfo]
GET  /api/runtime/agents/stream            → SSE: AgentEvent (Spatial Map)
```

### ChatGPT UI V3 cung cấp cho Claude Security V3:

```
- Khi tạo route mới, ChatGPT cần thông báo format request body để Claude validate đúng
- Khi Iron Man gesture trigger HITL approve → gọi POST /api/enterprise/hitl/{id}/approve
- Khi Spatial Map detect agent vào HITL zone → call GET /api/enterprise/hitl/pending
```

---

## PHẦN 6: ĐỌC BẮT BUỘC THEO THỨ TỰ

**Gợi ý thứ tự đọc cho mỗi AI (phải đọc đủ 5 bước):**

```
1. TONG_HOP_DU_AN_IRONCORE_VS_OPENCLAW.md  ← Bức tranh tổng thể, ưu tiên
2. MUC_TIEU_CHUNG_IRONCORE_V2.md           ← File này — phân công + contracts
3. .github/ (toàn bộ)                       ← Workflow CI, lint rules, conventions
4. Prompt riêng của mình                    ← Phase chi tiết
5. list_dir + read_file code liên quan      ← Bước R trong PARTS
```

---

## PHẦN 7: THỨ TỰ TRIỂN KHAI KHUYẾN NGHỊ (V3)

```
Tuần 1 (P0 — song song):
  Claude:   Phase 1 (Prompt Firewall) + Phase 2 (Forensics Engine)
  ChatGPT:  Phase 1 (Control-Plane UI: Usage/Cron/Nodes/Logs)

Tuần 2:
  Claude:   Phase 3 (Guardrail Studio) + Phase 4 (HITL V2)
  ChatGPT:  Phase 2 (HITL Approval UI) + Phase 3 (SIEM/IAM UI)

Tuần 3:
  Claude:   Phase 5 (API endpoints: SIEM/IAM/Airgap/Budget/Nodes)
  ChatGPT:  Phase 4 (Iron Man: Camera/Voice/Gesture)

Tuần 4:
  Claude:   Phase 6 (Section 21: Automation Intelligence Layer)
  ChatGPT:  Phase 5 (Spatial Agent 2D Map)

Integration:
  ChatGPT:  Phase 6 (Forensics Replay UI — dùng APIs từ Claude Phase 2)
  Full end-to-end test: tất cả modules
  Security audit: tất cả new endpoints
```

---

*Phiên bản: IronCore V3 — 18/03/2026*
*Đội: ChatGPT (UI Designer V3) + Claude (Security Engineer V3)*
*Tài liệu tham khảo gốc: `TONG_HOP_DU_AN_IRONCORE_VS_OPENCLAW.md`*
