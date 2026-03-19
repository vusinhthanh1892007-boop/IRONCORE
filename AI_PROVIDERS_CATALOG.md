# AI Providers & Models Catalog
**Last Updated:** 2026-03-12

*Tài liệu này tổng hợp danh mục các nhà cung cấp AI, các nền tảng inference, gateway và framework mã nguồn mở. Được thiết kế để Front-end và AI Agent dùng làm dữ liệu gốc cho UI chọn Model.*

## Table of Contents
- [2️⃣ Open-source LLM có API](#2️⃣-open-source-llm-có-api)
- [3️⃣ Chinese LLM API](#3️⃣-chinese-llm-api)
- [4️⃣ Multimodal / video / image API](#4️⃣-multimodal--video--image-api)
- [5️⃣ AI Search API (RAG / agent)](#5️⃣-ai-search-api-rag--agent)
- [6️⃣ AI Gateway / inference platform](#6️⃣-ai-gateway--inference-platform)
- [7️⃣ Open-source “universal AI API”](#7️⃣-open-source-universal-ai-api)
- [API Guidelines & Example](#api-guidelines--example)

---

## 2️⃣ Open-source LLM có API
*Các nhà cung cấp cấp API cho các mô hình ngôn ngữ mở (hoặc tự chủ).*

### Provider: Meta
> Mô hình mã nguồn mở hàng đầu thế giới (Llama series), mạnh mẽ về suy luận và tiết kiệm tài nguyên.
[👉 Xem models của Meta]

### Provider: Mistral
> Mô hình AI Châu Âu tối ưu hóa hiệu suất cao, nổi bật với kiến trúc MoE (Mixtral).
[👉 Xem models của Mistral]

### Provider: Cohere
> Cung cấp các mô hình Command chuyên dùng cho doanh nghiệp và RAG.
[👉 Xem models của Cohere]

### Provider: AI21
> Các mô hình Jurassic và Jamba ứng dụng kiến trúc kết hợp SSM-Transformer giải quyết luồng văn bản dài.
[👉 Xem models của AI21]

---

## 3️⃣ Chinese LLM API
*Các nền tảng LLM lớn đến từ thị trường Trung Quốc.*

### Provider: DeepSeek
> Trí tuệ nhân tạo nguồn mở siêu việt, nổi tiếng với các bản DeepSeek-V3 và DeepSeek-R1 suy luận cực mạnh.
[👉 Xem models của DeepSeek]

### Provider: Alibaba
> Cung cấp họ mô hình Qwen cực kỳ ấn tượng trong các bài benchmark đa ngôn ngữ và lập trình.
[👉 Xem models của Alibaba]

### Provider: Zhipu
> Nổi bật với họ mô hình GLM (ChatGLM), tối ưu cho ngữ cảnh tiếng Trung và đa nhiệm.
[👉 Xem models của Zhipu]

### Provider: Moonshot
> Tối ưu hóa xử lý văn bản siêu dài (Kimi) với cửa sổ ngữ cảnh lên đến hàng triệu token.
[👉 Xem models của Moonshot]

### Provider: MiniMax
> Mô hình AI tổng hợp cả văn bản, giọng nói và video thế hệ thứ hạng cao.
[👉 Xem models của MiniMax]

### Provider: Tencent
> Nhóm mô hình Hunyuan mạnh mẽ tích hợp sâu vào hệ sinh thái của Tencent.
[👉 Xem models của Tencent]

### Provider: ByteDance
> Hệ thống mô hình Doubao, đáp ứng lượng request khổng lồ và ứng dụng trên thiết bị di động.
[👉 Xem models của ByteDance]

---

## 4️⃣ Multimodal / video / image API
*Các nhà cung cấp chuyên cho Đa phương thức, Xử lý hình ảnh và Video.*

### Provider: OpenAI
> Hệ sinh thái đa phương thức tiên tiến (GPT-4o, Sora, DALL-E) dẫn đầu thị trường AI.
[👉 Xem models của OpenAI]

### Provider: Google
> Mô hình Gemini (Pro/Flash/Ultra) xử lý đa phương thức nguyên bản (video, âm thanh, text).
[👉 Xem models của Google]

### Provider: Stability AI
> Nổi tiếng với Stable Diffusion (SDXL, SD3) và công nghệ gen hình ảnh nguồn mở.
[👉 Xem models của Stability AI]

### Provider: Black Forest Labs
> Đào tạo mô hình FLUX xuất sắc trong việc tạo hình ảnh chân thực và render văn bản.
[👉 Xem models của Black Forest Labs]

### Provider: Runway
> Hệ thống AI mạnh nhất cho Video Generation (Gen-2, Gen-3 Alpha).
[👉 Xem models của Runway]

### Provider: Luma AI
> Chuyên Video generation với Dream Machine, chất lượng cao và tốc độ render nhanh.
[👉 Xem models của Luma AI]

### Provider: Galileo AI
> Tạo giao diện UI/UX trực tiếp từ prompt ngôn ngữ tự nhiên.
[👉 Xem models của Galileo AI]

---

## 5️⃣ AI Search API (RAG / agent)
*Các công cụ tìm kiếm được nhúng AI (Real-time Web Search).*

### Platform: Brave
> Cung cấp Search API nhanh gọn, không theo dõi, làm nguồn cấp dữ liệu web cho RAG.
[👉 Xem API của Brave]

### Platform: Perplexity
> Công cụ tìm kiếm đàm thoại top đầu, cung cấp API hỏi đáp thời gian thực.
[👉 Xem API của Perplexity]

### Platform: You.com
> Search API tối ưu cho LLM, cung cấp trích dẫn và scraping web hiệu quả.
[👉 Xem API của You.com]

### Platform: Exa
> Neural search framework được thiết kế riêng cho AI thấu hiểu text và mã nguồn.
[👉 Xem API của Exa]

### Platform: Tavily
> Search Engine chuyên biệt dành cho Autonomous AI Agents, tổng hợp thông tin sâu.
[👉 Xem API của Tavily]

### Platform: Jina AI
> Dịch vụ RAG cơ sở, Reader API và reranker API tối ưu cho tìm kiếm vector.
[👉 Xem API của Jina AI]

---

## 6️⃣ AI Gateway / inference platform
*Nền tảng host, điều phối và tăng tốc Inference cho LLM.*

**Danh sách Providers:**
- **OpenRouter:** Gateway AI đa mô hình chuẩn mực nhất. [👉 Xem models]
- **Together AI:** Cung cấp hạ tầng inference siêu nhanh cho open-source. [👉 Xem models]
- **Replicate:** Chạy custom models, images/video models dễ dàng. [👉 Xem models]
- **Fireworks AI:** Tối ưu hóa độ trễ (latency), suy luận siêu tốc. [👉 Xem models]
- **HuggingFace:** Hub khổng lồ cho mọi mô hình học máy. [👉 Xem models]
- **Azure AI Foundry:** Dịch vụ AI tổng hợp chuẩn doanh nghiệp của Microsoft. [👉 Xem models]
- **AWS Bedrock:** Managed AI models của Amazon. [👉 Xem models]
- **Google Vertex AI:** Nền tảng phát triển AI chuyên nghiệp của Google Cloud. [👉 Xem models]
- **NVIDIA NIM:** Microservices inference tối ưu phần cứng từ NVIDIA. [👉 Xem models]
- **GroqCloud:** Chạy LLM trên LPU nội bộ với tốc độ kỷ lục. [👉 Xem models]
- **Baseten, Modal, RunPod, OctoAI, Banana.dev:** Nhóm Serverless GPU chuyên dụng scale LLM.
- **Portkey, Helicone, Langdock, Langfuse, Humanloop, LiteLLM:** Nhóm Observability / Analytics & Gateway Management.
- **Eden AI, AIProxy, Vercel (AI SDK):** AI API Hubs cho lập trình viên.
- **DeepInfra, Anyscale, Inference.net:** Chạy Open-source model với chi phí thấp và scale auto.

---

## 7️⃣ Open-source “universal AI API”
*Nhóm dự án mã nguồn mở, Agents Framework và Orchestration tools.*

**SDK & Agent Frameworks:**
- **LangChain / LlamaIndex:** Các thư viện nền tảng hàng đầu xây dựng RAG & LLM Apps.
- **AutoGen / CrewAI:** Framework hỗ trợ mô hình Multi-agent tự trị và tương tác chéo.
- **LangGraph:** Xây dựng stateful, multi-actor agents với đồ thị (graph).
- **SuperAGI / Semantic Kernel:** Enterprise-grade Agent Frameworks (dùng Python/C#).
- **ModelScope Agent:** Framework tạo AI Agent của hệ sinh thái Alibaba.

**Inference Engines / Routing:**
- **vLLM / SGLang:** Động cơ suy luận (Inference Engine) nhanh nhất dành cho LLM.
- **Ollama / LocalAI:** Chạy LLM cục bộ trên máy tính không cần GPU cực khủng.
- **Haystack:** NLP framework xây dựng end-to-end search pipelines.
- **RouteLLM:** Bộ định tuyến tiết kiệm chi phí, điều phối prompts tới các model mạnh nhẹ khác nhau.

---

## API Guidelines & Example

### Tính Năng Pagination & Filtering
- **Không load toàn bộ in 1 lần:** Chỉ load dữ liệu chi tiết của model khi người dùng thao tác *"👉 Xem models"*.
- **Phân trang (Pagination):** Request sử dụng page size mặc định là `20`. Tham số `page=1`.
- **Tìm kiếm (Filter & Search):** Truy vấn danh sách hỗ trợ tham số `query/filter` (vd: theo tên, context, tag).
- **Thêm Model Tùy Chỉnh:** User có thể nhập `model_id` mới. Backend sẽ bắt `model_id` này đưa vào db tạm và hiển thị nhãn: *"sẽ được cập nhật khi agent fetch được metadata"*. 
- **Fetch Internet / Rate Limit:** Nếu tính năng "Cập nhật mới nhất" được bật, Agent sẽ kết nối ra API nguồn để kiểm tra phiên bản model mới (Cập nhật tới ngày `2026-03-12` inclusive). Agent tôn trọng rate-limit / TOS của provider. Nếu provider có yêu cầu kiểm tra auth key thì sẽ hiển thị *"Yêu cầu cấu hình API Key để cấp quyền"*.

### JSON Example Payload
Một ví dụ cấu trúc dữ liệu trả về cho Front-end khi click `[👉 Xem models của Meta]`:

```json
{
  "action": "show_models",
  "provider": "Meta",
  "models": [
    {
      "model_id": "meta/llama4-maverick",
      "name": "Llama 4 Maverick",
      "ctx": 128000,
      "tags": ["open-weight", "inference"],
      "desc": "Large open-weight model optimized for reasoning",
      "example_endpoint_if_known": "https://api.deepinfra.com/v1/openai/chat/completions"
    },
    {
      "model_id": "meta/llama4-scout",
      "name": "Llama 4 Scout",
      "ctx": 32768,
      "tags": ["efficient", "edge"],
      "desc": "Smaller footprint variant for edge devices and fast generation"
    }
  ],
  "last_updated": "2026-03-12"
}
```

### 👉 Hướng dẫn tích hợp cho Dev
> Cách tích hợp: expose endpoint `/models?provider=Meta&page=1&filter=reasoning` returning JSON above. Endpoint này có nhiệm vụ phân trang, lọc model theo tag hoặc mô tả. Front-end gọi API này lúc bấm nút "Xem models" để bind danh sách vô UI chọn Model.
