# 🧪 Báo cáo Kiểm thử Giao diện Terminal TUI V3 (QA Report)
**Ngày thực hiện:** 2026-03-19
**Mục tiêu:** Kiểm thử "đâm đụng" (Monkey Testing/Smoke Testing) toàn bộ luồng TUI, mô phỏng các thao tác bấm chọn, gõ bậy bạ, và bỏ trống field để tìm ra lỗi crash/logic.

---

## 🛠️ Trình tự Thử nghiệm Hành vi Thực tế

### Bước 1 & 2: Chọn Ngôn Ngữ + Preflight
- **Thao tác:** Bấm phím Xuống (hiển thị outline chọn ngôn ngữ) -> Bấm `Enter`. Tiếp tục bấm `Next` ở màn hình Preflight.
- **Kết quả:** `[Pass]` Chuyển cảnh mượt mà. Không crash. Dịch thuật đổi tức thì.

### Bước 3: Xác thực (AuthScreen)
- **Thao tác 1:** Đổi sang chế độ `Cloud Token`.
- **Thao tác 2:** Nhập vào `auth-token` một chuỗi linh tinh `&*(&*20392`. Không điền gì và bấm Next.
- **Kết quả:** `[Pass]` Màn hình ẩn hiện Input rất tốt. Lưu token rác vào bộ nhớ an toàn.

### Bước 4: Search Provider
- **Thao tác:** Chọn `Skip for now`, Input API bị ẩn đi. Cố tình nhấn Tab để focus vào đoạn bị ẩn -> Bấm `Next`.
- **Kết quả:** `[Pass]` Focus mất tác dụng, UI không cho nhập API khi chọn Skip. Chạy ổn.

### Bước 5: Cấu hình Model Providers
- **Thao tác:** Bỏ chọn SẠCH SẼ toàn bộ các Provider trong `SelectionList`. Để trống cấu hình Global API, bấm `Next`.
- **Lỗ hổng 1 (Logic Bug):** `[Fail]` UI cho phép đi tiếp! Nó lưu mảng rỗng `providers: []` vào config. Khi TUI kết thúc xuất ra file JSON, nếu thiếu provider thì core engine backend sẽ báo lỗi *No Provider Registered*.
- **Mức độ:** Cực kỳ nghiêm trọng (Core Panic). Cần thêm Validation báo lỗi màu đỏ không cho Next.

### Bước 6: Chọn Model Chính (ModelPickerScreen)
- **Thao tác 1:** Trong lúc app đang cắm GET API OpenRouter (chạy multi-thread), bấm liên tục chữ `a` vào ô Search.
- **Thao tác 2:** Chưa đợi tải xong (hoặc lúc chưa chịu bấm chuột vào List), bấm nút `Next` luôn!
- **Lỗ hổng 2 (Null Pointer / Key Error):** `[Fail]` 
  - Mã hiện tại: `if lst.index is not None:` ... nếu chưa focus hoặc list chưa load, nó rơi vào block `else` và `dismiss("channels")` luôn MÀ KHÔNG GÁN `self.app.cfg["primary_model"]`.
  - Hậu quả: Xảy ra lỗi Missing Key `primary_model` ở giai đoạn Export JSON cuối luồng. Cần khoá nút Next hoặc hiện cảnh báo *"Bạn phải chọn ít nhất 1 model!"*!

### Bước 7 -> 9: Channels, Skills, Hooks
- **Thao tác:** Đánh dấu Check 1 cái, xong gỡ ra đánh dấu 2 cái cực nhanh. Gõ text bậy bạ vào URL Webhook `"not-a-url"`. Bấm `Next` phi mã.
- **Lỗ hổng 3 (Validation URL Webhook):** `[Fail]` Input Webhook URL không có validator (Regex hoặc Textual Validator). Nhập chữ cũng cho qua. Nó có thể khiến Service bị lỗi khi khởi động.
- **Mức độ:** Trung bình.

### Bước 10: Gateway Server
- **Thao tác:** Xóa sạch (Backspace) cái text "8000" ở Gateway Port. Đế trống bốc.
- **Lỗ hổng 4 (Empty Port Crash):** `[Fail]` Nếu để trống Port, khi backend đọc biến môi trường để cấp phát port cho Docker/Uvicorn, nó sẽ nhận một `String` rỗng `""` thay vì số nguyên, đẫn tới Crash toàn bộ IronCore Engine Start-up.
- **Mức độ:** Cao. Cần force Input chỉ nhận `[0-9]{2,5}` và không được bỏ trống.

### Bước 11 -> 14: System, Persona, Monitoring
- **Thao tác:** Bật/Tắt các Toggle (Công tắc gạt) cho Telemetry và Backup. Gõ rất nhiều chữ vào System Prompt.
- **Kết quả:** `[Pass]` Rất ổn định, không có lỗi. Các chuỗi input đều lưu dict bình thường.

### Bước 15: Màn hình Cảnh báo nguy hiểm (Summary & Deploy)
- **Thao tác:** Không thèm gạt công tắc `ack-destructive` (Chấp nhận rủi ro ghi đè hệ thống), bấm thẳng `[Next]`.
- **Kết quả:** `[Pass]` Hệ thống từ chối cho qua, bật chuông `bell()` và bắn thông báo chữ đỏ: *"You MUST acknowledge destructive actions!"*. Chắn rủi ro thành công!

---

## ⛔ Tổng hợp 4 Lỗ hổng / Bug Ngầm cực gắt phát hiện được (Phần 1):
1. **Model Providers:** Cho phép chọn `0` provider.
2. **Model Picker:** Nút Next vẫn hoạt động khi user Cố Tình không tick hoặc bấm vào Model nào trong cái list Fetch từ internet.
3. **Webhook URL:** Ô input nhận bậy cả những chữ không phải là web link (`http/...`).
4. **Gateway Port:** Cho phép để rỗng (`""`) dẫn tới sụp đổ hệ thống lúc engine boot.

---

## 🛠️ Đợt Test Vòng 2: Automation Integration (End-to-End Test)
Tôi vừa viết kịch bản Tự động hóa `qa_test.py` thứ hai. Kịch bản này không bấm lung tung nữa mà đi tuần tự và tốc độ cao qua đúng 15 màn hình (Nhập cấu hình mẫu, gạt công tắc chuẩn và pass). 

**Kết quả:**
- **Mạch luồng App:** Chạy mượt mà, chuyển cảnh 15 vòng thu về trọn vẹn JSON Config cuối cùng:
  `{'auth': ... 'providers': ['openai'], 'primary_model': 'gpt-4o', 'channel': 'telegram', 'gateway': {'port': '8000', 'bind': 'bind-local'}...}` -> Dữ liệu đầu ra TUI cực chuẩn!
- **Lỗ hổng 5 (Race Condition / Bất đồng bộ Threading):** `[Fail]` 
  - Kịch bản Automation bấm `Next` ở màn hình Model Picker quá nhanh (Chỉ 0.2s sau khi hiện).
  - Kết quả là Thread chạy ngầm tải Model từ OpenRouter báo lỗi sập: `textual._context.NoActiveAppError` (Lỗi mất App Context).
  - Nguyên nhân: Thread tải xong model muốn update UI nhưng UI Model Picker đã bị tắt (người dùng bấm Next quá nhanh trước khi tải xong). 
  - **Mức độ:** Cực kỳ khó chịu vì user "tay nhanh hơn não" sẽ thấy luồng console in ra Exception đỏ chóe phá hỏng giao diện terminal. Cần bọc `try-except` quanh hàm `call_from_thread`!

🔥 **Tổng cộng 5 BUGS (4 Logic + 1 Threading) ! Anh đã sẵn sàng để tôi vá toàn bộ chưa?**
