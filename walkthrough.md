# Chặng Đường Nghiên Cứu & Xây Dựng Bản Thiết Kế "IronCore"

Đây là bản tổng kết toàn diện về quá trình chúng ta phân tích các lỗ hổng của AI Agent hiện tại và xây dựng bản thiết kế cho một hệ thống Agent tương lai mang tên **IronCore** – Vô đối về Bảo mật, Vượt qua mọi hệ thống Anti-Bot và Tiết kiệm Token.

---

## 1. Thành Quả Đạt Được

### Phân tích Lỗ hổng Trí tuệ Nhân tạo (Sự sụp đổ của OpenClaw)
Chúng ta đã bắt đầu bằng việc đọc và phân tích cảnh báo từ cộng đồng mạng (qua 149 links Reddit được tổng hợp) về sự cố bảo mật nghiêm trọng của dự án "OpenClaw".
*   **Soul-Evil Backdoor:** Đã xác nhận bằng cách soi thẳng vào mã nguồn cũ của OpenClaw (`/hooks/soul-evil.ts`). Chúng ta chứng kiến cách lập trình viên cài cắm đoạn code bí mật để lén lút tráo đổi nhân cách (System Prompt) của người dùng thành `SOUL_EVIL.md` dựa trên tỷ lệ ngẫu nhiên.
*   **Hậu quả:** OpenClaw chạy tự do trên máy tính gốc (Bare Metal) mà không có Sandbox, kết hợp cùng hàng tá plugin (Skills) không được kiểm duyệt trên ClawHub, dẫn đến viễn cảnh AI tự động xóa file hoặc tải mã độc.

### Nghiên cứu Tối ưu Cấu trúc (Học hỏi từ SWE-Agent & OpenHands)
Để tránh vết xe đổ của OpenClaw (Monolithic prompt loop), chúng ta đã phân tích các đối thủ mã nguồn mở hàng đầu:
*   **OpenHands (Devin):** Lấy cảm hứng từ vòng lặp `Action/Observation` (Event-driven) và bắt buộc mọi hành động của AI (ví dụ: chạy shell, sửa file) phải diễn ra trong một container Sandbox cách ly hoàn toàn.
*   **SWE-agent:** Khẳng định tầm quan trọng của ACI (Agent-Computer Interface) - giao diện riêng giúp LLM không bị ngợp bởi các terminal log dài dằng dặc.

### Đột phá: Vượt Qua "The Bot Check" (CAPTCHA & Datadome)
Với mục tiêu giúp IronCore thao tác web như một con người thực sự:
1.  **Toán học Cơ Sinh học:** Thay vì di chuyển chuột thẳng tắp tịnh tiến, chúng ta đã viết kịch bản `captcha_mouse_bypass.py` áp dụng thuật toán **Đường cong Bezier (Cubic Bezier Curves)** kết hợp với độ nảy vật lý, gia tốc phi tuyến (Easing Functions) và Định luật Fitts (Fitts's Law).
2.  **Khớp Mẫu (OpenCV):** Cấu hình thuật toán dò viền (`cv2.Canny`) và Khớp Mẫu để giải các CAPTCHA mảng trượt (Slider - như GeeTest).
3.  **Thị Giác Máy Tính Máy (VLMs):** Dùng một cục bộ Vision-Language Model (như LLaVA) hoặc YOLO để "nhìn" và phân giải tọa độ điểm click đối với các hình ảnh Captcha yêu cầu chọn đúng vạch kẻ đường, hay xoay hình (ReCaptcha/FunCaptcha).

### Kiến Trúc IronCore MVP (Minimum Viable Product)
Chúng ta đã "đặt móng" mã nguồn thực sự cho dự án mới tại `/home/vusinhthanh/train ai/ironcore/` với các thư mục cốt lõi:
-   `core/engine.py`: Vòng lặp Event-Driven tiên tiến.
-   `sandbox/engine.py`: Cơ chế giam lỏng Skills vào Container mô phỏng.
-   `browser/stealth.py`: Cỗ máy lướt web vô hình tích hợp logic Bezier & VLM CAPTCHA Bypass.
-   `memory/graph_rag.py`: "Trí nhớ tổ ong" (Knowledge Graphs).
-   `lsp/bridge.py`: Cầu nối giao tiếp trực tiếp với Bộ phân tích Cú pháp (AST) sửa code không lo lỗi Syntax.
-   `vlm/bridge.py`: Đường ống truyền ảnh CAPTCHA đến Local GenAI Model.

---

## 2. Kế Hoạch Tiếp Theo (Đã Tự Động Hóa)

Thay vì để hệ thống phình to và một AI phải gánh vác việc Code cả dự án, chúng ta đã chia để trị bằng một **Kế hoạch Phối hợp Đa Đặc Vụ (Multi-Agent Collaboration)** gồm 3 role siêu đặc thù (The Architect, The Ghost, The Brain).

*Toàn bộ Master Prompt Copy-Paste cho 3 AI này đã được biên soạn và lưu trữ tại `ai_collaboration_prompts.md` trong thư mục Artifacts của bạn.*

Chúc Người Điều Phối (Orchestrator) thành công rực rỡ trong việc chỉ huy 3 Agents mã hóa nên tương lai của tự động hóa này!

---

## 3. Bổ Sung Báo Cáo Theo Các Phase Đã Hoàn Tất (The Brain)

*Mốc cập nhật bổ sung: 18/03/2026 — tổng hợp từ các phase đã triển khai/xác thực trong phiên làm việc gần nhất.*

### 3.1. Tổng quan năng lực đã hoàn thiện

Qua các phase đã hoàn thành, lớp "The Brain" của IronCore đã đạt được các năng lực cốt lõi sau:

- **Routing thông minh theo độ phức tạp tác vụ** (Tiered LLM Router).
- **Bộ nhớ lai Graph + Session + Context** giúp ghi nhớ dài hạn nhưng vẫn tối ưu chi phí token.
- **Hệ đăng ký kỹ năng động (Skill Registry)** để mở rộng toolset có kiểm soát.
- **Điều phối đa tác tử (Multi-Agent Coordinator)** để phân rã bài toán, giao việc đúng năng lực, chạy song song, và hợp nhất kết quả.
- **Khung kiểm thử đầy đủ theo phase** để đảm bảo tính đúng đắn trước khi ghép vào engine tổng.

### 3.2. Tổng hợp kỹ năng/kỹ thuật/công nghệ theo phase

#### Phase 3 — Entity/Graph Intelligence Foundation

- **Kỹ năng đạt được:** trích xuất thực thể cơ bản từ ngữ cảnh và chuẩn hóa phục vụ memory graph.
- **Kỹ thuật chính:** chuẩn hóa ID ổn định (case-insensitive), biểu diễn node-edge, tìm láng giềng và đường đi trong graph.
- **Công nghệ áp dụng:** Python typed models, graph traversal logic trong module memory.

#### Phase 5 — Persistent Session Layer

- **Kỹ năng đạt được:** quản lý vòng đời session và lưu vết hội thoại/artifact bền vững.
- **Kỹ thuật chính:** thiết kế schema session/message/artifact, CRUD bất đồng bộ, lọc truy vấn theo trạng thái.
- **Công nghệ áp dụng:** `aiosqlite`, `pydantic`, async I/O, mô hình dữ liệu chuẩn hóa.

#### Phase 6 — Dynamic Skills Registry

- **Kỹ năng đạt được:** tổ chức tập kỹ năng thành registry có metadata, tìm kiếm và chuyển đổi sang tool definitions cho engine.
- **Kỹ thuật chính:** decorator-based skill declaration, auto-discovery module, metadata validation, semver-oriented structure.
- **Công nghệ áp dụng:** Python introspection (`inspect`, `importlib`), `pydantic`, typing contracts.

#### Phase 7 — Context Optimizer & Token Budget

- **Kỹ năng đạt được:** đóng gói context theo ngân sách token, tăng mật độ thông tin, giảm chi phí inference.
- **Kỹ thuật chính:** token counting (exact/approx), phân bổ budget theo slot, summary lịch sử cũ, cắt tỉa RAG nodes theo độ liên quan.
- **Công nghệ áp dụng:** `tiktoken` (khi khả dụng), fallback heuristic tokenizer, async summarization pipeline.

#### Phase 8 — Multi-Agent Coordinator (Mới hoàn thành)

- **Kỹ năng đạt được:** điều phối end-to-end giữa ARCHITECT / BRAIN / GHOST.
- **Kỹ thuật chính:**
	- Phân rã task thành subtask có dependency.
	- Topological scheduling theo wave để chạy song song bằng `asyncio.gather`.
	- Agent routing theo `AgentCapability`.
	- Conflict resolution bằng confidence + LLM adjudication fallback.
	- Phát event chi tiết lên `EventBus` để audit/monitoring.
- **Công nghệ áp dụng:** `asyncio`, Pydantic V2, event-driven orchestration, dependency graph resolution (Kahn-style).

### 3.3. Năng lực kỹ thuật xuyên suốt đã hình thành

- **Async-first architecture:** toàn bộ luồng quan trọng đều ưu tiên bất đồng bộ để sẵn sàng scale.
- **Strong typing & schema discipline:** mô hình hóa dữ liệu bằng Pydantic + type hints giúp giảm lỗi tích hợp giữa module.
- **Event-driven observability:** các mốc xử lý lớn đều có event hook để nối với monitoring/audit.
- **Fail-safe patterns:** fallback decomposition, timeout control, skip dependency khi upstream fail, conflict adjudication.
- **Test-driven stabilization theo phase:** mỗi phase đều có test riêng để cô lập lỗi và xác nhận chất lượng trước khi hợp nhất.

### 3.4. Danh mục công nghệ đã dùng trong các phase đã hoàn tất

- **Ngôn ngữ/lõi runtime:** Python 3, `asyncio`.
- **Data modeling & validation:** `pydantic`.
- **Lưu trữ phiên:** `aiosqlite` / SQLite.
- **Quản lý ngữ cảnh/token:** `tiktoken` (khi có), heuristic token estimator.
- **Cơ chế phối hợp agent:** EventBus + async task orchestration.
- **Tầng kiểm thử:** `pytest` (phase-based test suites).

### 3.5. Giá trị mang lại cho IronCore sau chuỗi phase này

- IronCore đã có nền tảng **"nhớ tốt hơn – nghĩ gọn hơn – phối hợp tốt hơn"**.
- Các module của The Brain giờ đã đủ điều kiện làm **trục reasoning + memory + orchestration** cho hệ đa tác tử.
- Kiến trúc hiện tại sẵn sàng cho bước tiếp theo: gắn bridge runtime thật với các agent handler production và monitoring chain thống nhất.

---

## 4. Bổ Sung Theo Phiên Chat Hiện Tại (Delta Report)

*Mốc cập nhật: 18/03/2026 — chỉ tổng hợp các phần đã thực thi xong trong chính đoạn chat này.*

### 4.1. Phase đã hoàn thành trong phiên này

- **The Brain — Phase 6 (Skills Registry)** đã được triển khai hoàn chỉnh ở mức code + test.
- Đã kiểm thử lại toàn bộ regression liên quan để đảm bảo không làm gãy các phase đã có.

### 4.2. Kỹ năng đã thể hiện trong phase vừa hoàn tất

- **Thiết kế capability registry chuẩn production:** xây dựng registry trung tâm để quản lý skill theo metadata.
- **Xây interface bridge với core engine:** chuyển skill metadata thành `ToolDefinition` để đăng ký trực tiếp vào engine event-driven.
- **Tổ chức mở rộng theo chuẩn module:** hỗ trợ auto-discovery để scale số lượng skill mà không sửa tay từng nơi.
- **Đảm bảo độ tin cậy bằng test theo hành vi:** viết test bao phủ validate, lookup, conflict, discovery, suggestion, bridge conversion.

### 4.3. Kỹ thuật đã dùng trong phiên này

- **Schema-first design:** mô hình hóa `SkillParameterSchema`, `SkillMetadata`, `RegisteredSkill` bằng Pydantic.
- **Validation nghiêm ngặt:** kiểm tra `snake_case`, semver, enum-like fields (`cost_tier`, parameter type).
- **Decorator pattern (`@skill`):** khai báo skill theo hướng declarative và gắn metadata để discover runtime.
- **Dynamic import + introspection:** dùng `importlib` + attribute inspection để nạp skill theo module.
- **Async-safe mutation:** dùng `asyncio.Lock` cho thao tác đăng ký/hủy đăng ký trong registry.
- **Ranking heuristic cho discovery:** search theo weighted score (name/description/long_description/tags).

### 4.4. Công nghệ đã sử dụng trong phiên này

- **Ngôn ngữ & runtime:** Python 3, async/await (`asyncio`).
- **Modeling & validation:** Pydantic.
- **Core integration contract:** `RiskLevel`, `ToolDefinition` từ `ironcore/core/engine.py`.
- **Testing stack:** `pytest` + async tests (`pytest-asyncio`).

### 4.5. Kết quả xác thực kỹ thuật (trong phiên này)

- **`tests/test_brain_phase6.py`: 26/26 test PASSED** (bao phủ đầy đủ chức năng Phase 6 The Brain).
- **Toàn bộ test suite dự án: 61/61 test PASSED** sau khi thêm module mới.
- Kết luận: phần bổ sung không chỉ hoàn thành tính năng mà còn tương thích ổn định với các phase trước.

---

## 5. Bổ Sung Báo Cáo Chuẩn Theo Tiến Độ Thực Tế (18/03/2026)

*Mục này được thêm theo yêu cầu tổng hợp cuối phiên, bám theo trạng thái thực tế đã rà soát trong đoạn chat hiện tại.*

### 5.1. Trạng thái phase đã làm xong

- **Phase 1 (Core MVP):** Hoàn thành.
	- Năng lực cốt lõi đã có: Async ReAct engine, sandbox execution, stealth browser nền tảng, VLM bridge.
- **Phase 2 (GraphRAG Foundation):** Hoàn thành.
	- Đã có graph store, node/edge model, stable ID, truy vấn hàng xóm và tìm path.
- **Phase 3 (Entity Extraction Foundation):** Hoàn thành và đã xác thực test.
	- `test_phase3.py` đã chạy PASS trong phiên trước đó.
- **Phase 4 (Security Core):** Hoàn thành ở mức code.
	- Đã có policy engine và secrets vault mã hóa.

### 5.2. Phase gần hoàn tất (code xong, cần hoàn tất xác thực cuối)

- **Phase 5 (Monitoring & Audit):** Code hoàn thiện, đã có test file, cần chạy xác thực cuối để chốt trạng thái release.
- **Phase 6 (API + LSP Bridge):** Code đã có đầy đủ module chính, cần bổ sung/chạy test tích hợp để đóng phase.

### 5.3. Tổng hợp kỹ năng đã sử dụng qua các phase đã xong

- **Kiến trúc hệ thống:** Thiết kế event-driven, tách lớp rõ ràng (core, security, monitoring, api, lsp, browser, memory).
- **Kỹ năng backend Python nâng cao:** Thiết kế mô-đun theo interface, typed contracts, tổ chức package quy mô vừa/lớn.
- **Kỹ năng bảo mật ứng dụng:** Permission policy theo rule chain, quản lý bí mật mã hóa, tư duy zero-trust.
- **Kỹ năng dữ liệu tri thức:** Mô hình hóa knowledge graph, chuẩn hóa entity, thiết kế memory có thể mở rộng.
- **Kỹ năng kiểm thử theo phase:** Smoke test theo cột mốc, tách test theo module để cô lập lỗi và kiểm chứng hồi quy.

### 5.4. Tổng hợp kỹ thuật đã áp dụng

- **Async-first execution:** ưu tiên `async/await`, event bus, xử lý đồng thời không chặn luồng chính.
- **Schema/contract-first:** dùng model validation để khóa chặt input-output giữa các tầng.
- **Rule Engine pattern:** cho phép mở rộng chính sách an toàn mà không phá vỡ lõi.
- **Tamper-evident audit chain:** xâu chuỗi hash/HMAC để phát hiện sửa đổi log.
- **Safe editing qua LSP bridge:** nền tảng cho chỉnh sửa mã có kiểm tra chẩn đoán và rollback.
- **CAPTCHA/Stealth techniques (nền móng):** mô phỏng chuyển động chuột theo Bezier/easing/Fitts và tích hợp hướng CV/VLM.

### 5.5. Tổng hợp công nghệ đã dùng

- **Ngôn ngữ & runtime:** Python 3, `asyncio`.
- **Validation/modeling:** Pydantic.
- **Storage/session & log persistence:** SQLite/`aiosqlite` (theo thiết kế phase), JSONL append-only cho audit.
- **Security primitives:** Fernet (`cryptography`), HMAC-SHA256 cho chain verify.
- **API layer:** FastAPI + streaming/websocket patterns.
- **LSP integration:** client/bridge/document manager/diagnostic watcher/safe editor.
- **Browser automation foundation:** Playwright/OpenCV/VLM integration orientation trong kiến trúc.

### 5.6. Kết luận điều phối kỹ thuật

Với tiến độ hiện tại, IronCore đã hoàn tất phần nền tảng quan trọng nhất (Phase 1→4) và đã đặt xong khung cho các lớp nâng cao (Phase 5→6). Điều này cho phép chuyển ngay sang bước “đóng phase bằng test tích hợp + hardening”, thay vì phải viết lại kiến trúc.

---

## 6. Bổ Sung Báo Cáo Chuẩn (Theo Các Phase Đã Hoàn Tất Trong Đoạn Chat Này)

*Mốc cập nhật: 18/03/2026 — phần này chỉ tổng hợp đúng các phase đã thực thi xong trong phiên chat hiện tại.*

### 6.1. Phase đã hoàn tất trong phiên này

- **The Brain — Phase 2: GraphRAG Memory Engine (Hybrid Graph + Vector Store)** đã hoàn thành.
- Đã rewrite toàn bộ `ironcore/memory/graph_rag.py` từ stub sang bản production-oriented.
- Đã xác thực lại lỗi file sau chỉnh sửa và kiểm tra import/smoke logic cốt lõi.

### 6.2. Tổng hợp kỹ năng đã sử dụng

- **Kỹ năng kiến trúc module:** tách lớp rõ ràng theo trách nhiệm (`VectorStore`, `GraphStore`, `HybridRetriever`, `GraphRAGMemory`).
- **Kỹ năng thiết kế data contract:** mô hình hóa node/edge/context bằng Pydantic V2, đảm bảo type-safe interface giữa các tầng.
- **Kỹ năng xây memory retrieval thực chiến:** kết hợp semantic search + graph traversal để tăng chất lượng context trả về cho LLM.
- **Kỹ năng xử lý vòng đời tri thức:** thêm interaction, truy vấn ngữ cảnh, xóa dữ liệu theo GDPR (`forget`), dọn dẹp hợp nhất dữ liệu (`consolidate`).

### 6.3. Tổng hợp kỹ thuật đã áp dụng

- **Hybrid retrieval pipeline:** vector top-K → mở rộng graph BFS độ sâu 2 → chấm điểm và giảm trọng số node mở rộng → cắt theo token budget.
- **Deterministic entity dedup:** dùng hash ổn định (case-insensitive) để chống tạo node trùng khi cùng thực thể xuất hiện nhiều lần.
- **Graph intelligence primitives:** neighborhood query, shortest path, community extraction (PageRank-based), edge filtering theo tập node chọn.
- **Async-first I/O:** thiết kế hàm `async` cho thao tác lưu trữ/truy vấn vector để sẵn sàng ghép với core event loop bất đồng bộ.
- **Fail-safe và maintainability:** custom exception hierarchy, logging structured, fallback embedding function khi môi trường thiếu model local.

### 6.4. Tổng hợp công nghệ đã dùng (trong phase đã hoàn tất)

- **Ngôn ngữ/runtime:** Python 3, `asyncio`.
- **Modeling/validation:** `pydantic` V2.
- **Vector memory:** `chromadb` + embedding local qua `sentence-transformers` (`all-MiniLM-L6-v2`, có fallback).
- **Graph memory:** `networkx` (directed graph, traversal, PageRank).
- **Utility nền tảng:** `hashlib`, `uuid`, `logging`, `time`, `re`.

### 6.5. Kết quả xác thực kỹ thuật trong phiên này

- File `graph_rag.py` không còn lỗi diagnostics sau khi rewrite.
- Kiểm tra import module thành công.
- Smoke test logic cốt lõi (graph node/edge/BFS/path, stable ID, entity extraction heuristic) đã được chạy xác nhận.

### 6.6. Giá trị mang lại sau phase này

- IronCore có nền tảng bộ nhớ lai đủ tốt để cấp context chất lượng cho các phase tiếp theo (Entity Extraction nâng cao, Coordinator, Context Optimizer).
- Thiết kế hiện tại giữ cân bằng giữa **chất lượng truy hồi**, **chi phí token**, và **khả năng mở rộng production**.

---

## 7. Bổ Sung Báo Cáo Chuẩn (Theo Phase Đã Làm Xong Trong Chat Này)

*Mốc cập nhật: 18/03/2026 — phần này chỉ ghi nhận các hạng mục đã thực thi và xác thực trong chính phiên chat hiện tại.*

### 7.1. Phase đã hoàn tất

- **The Brain — Phase 1: LLM Tiered Router (LiteLLM Wrapper)**

### 7.2. File đã tạo/cập nhật trong phase này

- `ironcore/core/llm_bridge.py` — triển khai đầy đủ tầng routing theo độ phức tạp.
- `ironcore/__init__.py` — khởi tạo package root.
- `ironcore/core/__init__.py` — export các contract lõi để import nhất quán.
- `ironcore/memory/__init__.py`, `ironcore/vlm/__init__.py`, `ironcore/skills/__init__.py` — chuẩn hóa package layout.

### 7.3. Tổng hợp kỹ năng đã sử dụng

- **Thiết kế kiến trúc LLM gateway:** tạo lớp cầu nối giữa engine và nhà cung cấp model.
- **Routing theo độ phức tạp tác vụ:** tự phân loại SIMPLE/MEDIUM/COMPLEX/CRITICAL trước khi chọn model.
- **Thiết kế fallback an toàn:** model trong tier lỗi thì tự động chuyển model/tier kế tiếp.
- **Chuẩn hóa output thành Action:** parse JSON trả về từ model và kiểm tra hallucinated tool.
- **Kiểm soát chi phí theo session:** tracking token/cost, chặn vượt ngân sách.

### 7.4. Kỹ thuật đã áp dụng

- **Heuristic complexity classifier:** dựa trên keyword + độ dài prompt + độ sâu history.
- **Tiered model config:** cấu hình model theo từng cấp độ và hỗ trợ override.
- **Cost telemetry:** ghi nhận input/output tokens, tổng USD, số lần gọi.
- **Structured error hierarchy:** `LLMRoutingError`, `LLMResponseParseError`, `LLMBudgetExceededError`.
- **Streaming event hooks:** phát `llm.token_stream` và `agent.token_usage` lên `EventBus`.
- **Schema discipline:** sử dụng Pydantic V2 cho `ModelConfig`, `LLMResponse`, `CostRecord`.

### 7.5. Công nghệ đã dùng trong phase này

- **Python 3 + asyncio** (async-first design).
- **LiteLLM** (unified provider API).
- **Pydantic V2** (data validation & typed models).
- **Event-driven integration** với `EventBus`, `Action`, `ToolDefinition` từ `core/engine.py`.

### 7.6. Kết quả xác thực

- Đã cài dependency cần thiết cho phase: `litellm`, `pydantic`.
- `llm_bridge.py` không có lỗi diagnostics sau khi triển khai.
- Các package `ironcore/*` đã có `__init__.py` để import ổn định.

### 7.7. Ghi chú điều phối

- Mục báo cáo này cố ý chỉ phản ánh **đúng phạm vi hoàn thành trong chat hiện tại** để tránh chồng chéo với các mục tổng hợp lịch sử ở trên.

---

## 7. Bổ Sung Báo Cáo Mới (Theo Đúng Các Phase Đã Làm Trong Đoạn Chat Này)

*Mốc cập nhật: 18/03/2026 — phần này được thêm theo yêu cầu “bổ sung xuống dưới file tổng hợp dự án”, chỉ ghi nhận đúng các hạng mục đã thực thi xong trong phiên chat này.*

### 7.1. Phase đã hoàn tất trong phiên này

- **Phase 3 — Entity Extractor (NLP + Triple Extraction): Hoàn thành.**
	- Đã tạo mới `ironcore/core/entity_extractor.py` theo kiến trúc 3 lớp:
		- `FastEntityExtractor` (spaCy NER + regex fallback)
		- `LLMEntityExtractor` (LLM triple extraction + JSON schema validation + retry + batch)
		- `HybridEntityExtractor` (router + content-hash cache)
- **Tích hợp xong vào Phase 2 (GraphRAGMemory integration): Hoàn thành.**
	- Đã cập nhật `ironcore/memory/graph_rag.py` để `GraphRAGMemory` nhận `entity_extractor` tùy chọn.
	- `add_interaction()` đã hỗ trợ:
		- Nhánh Phase 3: entity/triple extraction rồi map sang `KnowledgeNode` + `KnowledgeEdge`.
		- Nhánh fallback Phase 2: heuristic cũ khi extractor unavailable.

### 7.2. Kết quả xác thực kỹ thuật trong phiên này

- Không phát sinh diagnostics lỗi ở 2 file đã sửa/chỉnh.
- Đã chạy smoke test riêng cho Phase 3 (`test_phase3.py`) và đạt:
	- **10/10 tests PASSED**.
- Các kiểm tra bao phủ:
	- Import & schema models (`EntitySpan`, `Triple`, `ExtractionResult`).
	- Fast extraction path.
	- Hybrid routing path + cache behavior.
	- Empty-input guard.
	- Backward compatibility với GraphRAG cũ.
	- Signature/wiring cho `GraphRAGMemory(entity_extractor=...)`.

### 7.3. Tổng hợp kỹ năng đã dùng qua các phase đã hoàn tất trong phiên

- **Kỹ năng thiết kế kiến trúc module:** tách lớp rõ ràng, mỗi lớp một trách nhiệm.
- **Kỹ năng tích hợp liên phase:** nâng cấp Phase 3 nhưng vẫn tương thích Phase 2 (không phá API cũ).
- **Kỹ năng data-contract engineering:** mô hình hóa output chuẩn cho entity/triple, đảm bảo tính nhất quán khi đẩy sang graph memory.
- **Kỹ năng reliability engineering:** có fallback path, retry logic, cache, guard cho input rỗng.
- **Kỹ năng xác thực chất lượng:** viết và chạy smoke test tập trung theo đúng phạm vi phase.

### 7.4. Tổng hợp kỹ thuật đã áp dụng

- **Hybrid extraction strategy:** route theo độ dài/độ phức tạp văn bản.
- **Schema-validated LLM output:** ép JSON structure, parse + validate + lọc item lỗi.
- **Retry with backoff:** tăng độ ổn định khi LLM trả output không chuẩn.
- **Batch extraction:** gom nhiều text ngắn vào một call để giảm overhead.
- **Content-hash caching (SHA-256):** tránh xử lý lặp, tối ưu latency và cost.
- **Graph mapping:** ánh xạ Subject-Predicate-Object thành edge có trọng số confidence.
- **Graceful degradation:** lỗi extractor thì tự rơi về heuristic path, giữ hệ thống chạy liên tục.

### 7.5. Tổng hợp công nghệ đã dùng

- **Ngôn ngữ/runtime:** Python 3, `asyncio`.
- **Modeling/validation:** Pydantic V2.
- **NLP local path:** spaCy (khi khả dụng) + regex fallback.
- **LLM extraction path:** LiteLLM-compatible calling pattern (qua bridge/direct).
- **Memory/graph integration:** GraphRAG (`KnowledgeNode`, `KnowledgeEdge`, `GraphStore`, `HybridRetriever`).
- **Testing/verification:** script smoke test chuyên biệt cho Phase 3.

### 7.6. Kết luận cập nhật

- Phần bổ sung trong phiên này đã hoàn thiện đúng mục tiêu: **xây xong Phase 3 và nối ổn định vào Phase 2**.
- Nền tảng hiện tại sẵn sàng cho các bước kế tiếp như tối ưu context, coordinator nâng cao, và VLM bridge production.
