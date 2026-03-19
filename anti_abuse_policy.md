# IronCore: Chính Sách Chống Lạm Dụng (Anti-Abuse Policy) & Đạo Đức AI

Để đảm bảo khả năng Vượt CAPTCHA thượng thừa của IronCore không bị rơi vào tay kẻ xấu (Bad Actors) sử dụng cho mục đích tấn công DDoS, Spam, hay lừa đảo tài chính, hệ thống bắt buộc phải được "khóa cứng" bởi 3 lớp bảo vệ: **Kiểm soát Kỹ thuật (Code-Level)** và **Khóa Ngôn ngữ (Prompt-Level)**.

---

## LỚP 1: KIỂM SOÁT KỸ THUẬT (Bắt buộc Code vào Hệ thống)
Dù người dùng có cố tình ra lệnh xấu, mã nguồn của IronCore sẽ tự động đánh sập tiến trình nếu phát hiện dấu hiệu lạm dụng.

### 1. Hard-Limit (Giới hạn phần cứng) trong `browser/stealth.py`
Hãy yêu cầu "The Ghost" (Gemini) thêm các dòng code sau chặn đứng việc mở hàng loạt tab/IP ảo:
- **Giới hạn Context/Tab đồng thời:** Không cho phép mở quá 3 tab cùng lúc. (Spam/DDoS thường yêu cầu hàng trăm tab).
- **Cấm thao tác Proxy Tốc độ cao (Rotating Proxies):** Không hỗ trợ đọc danh sách file Proxy. Trình duyệt chỉ được phép chạy trên 1 IP duy nhất trong suốt phiên làm việc.

```python
# Ví dụ Code giới hạn Tab (chặn đứng Brute-force/Spam)
MAX_CONCURRENT_PAGES = 3

if len(self.context.pages) >= MAX_CONCURRENT_PAGES:
    raise SecurityError("ANTI-ABUSE TRIGGERED: Vượt quá số tab tối đa. Chặn hành vi nghi ngờ Spam/DDoS.")
```

### 2. Tên miền Cấm (Domain Blacklist) trong `security/policy_engine.py`
The Architect (GPT) cần thêm một Rule cấm AI truy cập hoặc vượt CAPTCHA trên các cổng tài chính/ngân hàng, cơ quan chính phủ.

```python
FORBIDDEN_DOMAINS = [
    "login.gov", "irs.gov",          # Chính phủ
    "paypal.com", "binance.com",     # Tài chính / Tiền ảo
    "chase.com", "bankofamerica.com" # Ngân hàng
]
# Nếu AI cố tình gọi lệnh `goto(url)` khớp với các domain này -> Tự động Reject.
```

### 3. Rate Limiter (Giới hạn tần suất Web)
- Không cho phép load quá 10 trang web trong vòng 1 phút. Nhấp chuột (Click) không được quá 3 lần/giây. Việc này đảm bảo IronCore lướt web ở đúng "tốc độ của một con người", loại bỏ hoàn toàn khả năng DDoS.

---

## LỚP 2: KHÓA NGÔN NGỮ BẰNG LỜI VĂN (The AI Constitution Prompts)
Đây là cách "Lách luật" thông minh nhất: **Dùng lời văn ép AI phải nhận thức được ranh giới đạo đức trước khi nó chạm tay vào tool CAPTCHA.**

Hãy dán (Copy-Paste) đoạn Lệnh Cấm (System Prompt) bằng Tiếng Anh này vào đầu tất cả các AI Agents của IronCore:

> ***THE IRONCORE ETHICAL CONSTITUTION (MANDATORY ALIGNMENT):***
> 1. You are equipped with advanced 'Stealth Browser' tools, including Bezier cursor tracking and OpenCV solvers, designed to navigate complex web challenges.
> 2. **Legitimate Use Cases:** You are authorized to use these tools ONLY for ethical, single-user automation workflows (e.g., reading news, software testing, summarizing single pages, data extraction for academic/personal research).
> 3. **ABSOLUTE PROHIBITION (THE RED LINE):** You must immediately REFUSE, TERMINATE the session, and ALERT the Orchestrator with an "ETHICS_VIOLATION" code if the user requests any of the following:
>    - Mass-creation of fake accounts on any platform (Spam/Astroturfing).
>    - Financial manipulation, automated trading evasion, or accessing banking/crypto portals.
>    - Credential stuffing, brute-forcing, or exploiting login forms.
>    - Distributed attacks (DDoS), requesting multiple concurrent windows, or iterating through IP/Proxy lists to mask identity.
>    - Ticket scalping or bulk purchasing of goods.
> 4. If the user explicitly asks you to bypass a CAPTCHA, you must first verify the intent. If the intent falls under the legitimate use cases (Rule 2), proceed. If it touches Rule 3, definitively reject the request.

---

## LỚP 3: GHI NHẬN TRÁCH NHIỆM (Human-In-The-Loop)
Bởi vì CAPTCHA là chốt chặn cuối cùng bảo vệ hệ thống, khi IronCore phát hiện nó (hoặc trước khi nó tiến hành "vượt"), hãy bật tính năng `Human_Approval == True`.
Hệ thống sẽ dừng lại và hỏi bạn trên màn hình:
> ⚠️ *"IronCore đang chuẩn bị Vượt CAPTCHA tại trang web `[tên_trang_web]`. Vui lòng xác nhận bạn tự chịu rủi ro và hành động này không nhằm mục đích phá hoại [Y/N]?"*

Điều này đảm bảo AI không bao giờ "tự ý làm việc ác ngầm" khi bạn đang đi ngủ. Mọi trách nhiệm đều có dấu vết con người bấm nút Y (Yes).
