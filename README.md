# IronCore

IronCore la mot bo khung AI agent huong bao mat, duoc thiet ke de chay theo kieu `Action/Observation`, co sandbox, policy engine, memory, LSP safe editing, monitoring, va deployment scaffold.

Du an nay duoc xay theo mo hinh 3 agent phoi hop:
- `The Architect`: phu trach `core/`, `sandbox/`, `security/`, `lsp/`, `api/`, `monitoring/`, `tests/`, `deployment/`
- `The Brain`: phu trach memory, skill registry, entity extraction, llm orchestration
- `The Ghost`: phu trach browser stealth, fingerprint, session manager, anti-bot stack

## Muc tieu

- Bao mat mac dinh: policy engine, RBAC, encrypted secrets, audit chain
- Tach biet thuc thi: sandbox Docker/gVisor cho cac tac vu rui ro cao
- Sua code an toan: LSP bridge + rollback khi diagnostics loi
- Quan sat duoc: event bus, audit log, verify chain
- San sang mo rong: memory, browser, VLM, skills, API, worker, CI/CD

## Cau truc chinh

```text
ironcore/
├── api/          # FastAPI server, auth, health check
├── browser/      # Stealth browser, session manager, anti-bot components
├── core/         # Engine, LLM bridge, coordinator, context optimizer
├── lsp/          # Safe code editing qua Language Server Protocol
├── memory/       # GraphRAG, session store
├── monitoring/   # Audit logger, hash chain verification
├── sandbox/      # Docker/gVisor isolation engine
├── security/     # Policy engine, vault, RBAC, rule loader
├── skills/       # Skill registry
├── tests/        # Test suite cho phan Architect
└── vlm/          # Vision-Language bridge
```

## Thanh phan noi bat

- `ironcore/core/engine.py`: vong lap agent async trung tam
- `ironcore/security/policy_engine.py`: deny/allow/rate-limit/sandbox escalation
- `ironcore/security/rbac.py`: role + permission + token
- `ironcore/sandbox/engine.py`: thuc thi container co gioi han tai nguyen
- `ironcore/lsp/safe_editor.py`: sua file va tu rollback neu sinh diagnostics loi
- `ironcore/api/server.py`: HTTP API + `/health`
- `deployment/worker.py`: worker process cho `docker-compose`

## Tính năng mới cập nhật (Tháng 3/2026)

- **Setup Wizard Đa Ngôn Ngữ:** Trình cài đặt tương tác qua Terminal hỗ trợ hơn 100+ ngôn ngữ, tự động dịch các prompt setup sang ngôn ngữ bản địa của người dùng.
- **Tùy biến Kỹ năng (Skills Selection):** Cho phép người dùng tùy chọn chỉ cài đặt các kỹ năng AI cần thiết (Web Browsing, Code Execution, Vision...) ngay trong lúc chạy setup.
- **Hỗ trợ Danh sách Model 2026 Đồ Sộ:** Tích hợp tất cả model mạnh nhất tính đến thời điểm hiện tại:
  - **OpenAI:** GPT-5.4, o1, GPT-5.3-Codex...
  - **Anthropic:** Claude 4.6 (Opus, Sonnet, Haiku)
  - **Google:** Gemini 3.1 Pro, Gemini 3.1 Flash-Lite
  - **China LLMs:** Qwen 3.5 397B, GLM-5, Kimi K2.5, Hunyuan Turbo S
  - **Others:** DeepSeek V4, Grok 4.20, Mistral Large 3, Command R+
- **Giao diện Cài đặt (Settings UI) Thông Minh:** Chọn AI Provider tự động load danh sách Model tương ứng. Hỗ trợ kết nối qua hơn 40 API Gateways phổ biến (OpenRouter, Together AI, AWS Bedrock, Replicate...).
- **Chế độ chạy linh hoạt:** Lựa chọn chạy IronCore thông qua Web UI hiện đại hoặc CLI Terminal siêu nhẹ.
- **Tích hợp Workflow Sidebars:** Click "Deploy Staging" hoặc các script lưu sẵn trên Sidebar Web UI sẽ tự động kích hoạt Agent thực thi lệnh trong Chat.

## Chay nhanh

### Cach 1: Local Python

```bash
python -m pip install -r requirements.txt
python -m pip install -e .[dev]
uvicorn ironcore.api.server:app --host 0.0.0.0 --port 8000 --reload
```

### Cach 2: Dung Makefile

```bash
make install
make run-api
```

### Cach 3: Dung Docker Compose

```bash
docker compose up --build
```

API health check:

```bash
curl http://127.0.0.1:8000/health
```

## Test va lint

```bash
make test
make test-cov
make lint
make format
```

Neu moi truong cua ban chua co `pytest`, `ruff`, `mypy` hoac `docker`, hay chay `make install` truoc.

## Tai lieu lien quan

- `implementation_plan.md`: ke hoach tong the cua IronCore
- `walkthrough.md`: tom tat qua trinh nghien cuu va xay dung
- `prompt_gpt5_4_architect.md`: prompt chi huy cho The Architect
- `prompt_claude4_6_brain.md`: prompt chi huy cho The Brain
- `prompt_gemini3_1_ghost.md`: prompt chi huy cho The Ghost

## Trang thai

Du an dang o giai doan scaffold + implementation theo phase. Kien truc da du phan he chinh, nhung van can tiep tuc hardening, integration test, va dong bo giua 3 nhom module.
