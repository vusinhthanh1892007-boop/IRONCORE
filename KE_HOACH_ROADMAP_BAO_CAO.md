# Kế hoạch / Roadmap / Báo cáo thống kê (IronCore)

**Thời điểm lập báo cáo:** 2026-03-23  
**Phạm vi:** Toàn bộ repository `IRONCORE`

## 1) Tóm tắt mục tiêu
- Xây dựng và duy trì một framework AI agent an toàn, có khả năng mở rộng.
- Cân bằng 3 trục chính: **bảo mật**, **độ ổn định**, **tốc độ phát triển tính năng**.

## 2) Số liệu hiện trạng (snapshot)

| Hạng mục | Giá trị |
|---|---:|
| Số entry cấp cao nhất ở root | 31 |
| Số file Python toàn repo | 165 |
| Số file test (`tests/test_*.py`) | 21 |
| Số file web (`.ts/.tsx/.js` trong `web/`) | 146 |
| Số thư mục con trực tiếp trong `ironcore/` | 21 |

> Ghi chú: Đây là số liệu snapshot tại thời điểm lập báo cáo, có thể thay đổi khi codebase tiếp tục phát triển.

## 3) Roadmap đề xuất

### Giai đoạn 1 (0-30 ngày): Ổn định nền tảng
- Chuẩn hóa môi trường local/CI để chạy lint + test ổn định.
- Ưu tiên xử lý các lỗi ảnh hưởng trực tiếp tới luồng phát triển (lint, unit test cốt lõi).
- Rà soát cấu hình triển khai cơ bản (API healthcheck, compose, chart cấu hình chính).

### Giai đoạn 2 (31-60 ngày): Nâng cao chất lượng & observability
- Cải thiện độ phủ test cho các module trọng yếu (core, security, memory).
- Chuẩn hóa chỉ số vận hành cơ bản: pass rate test, lỗi runtime, độ trễ endpoint chính.
- Tăng cường tài liệu vận hành cho web + API + CLI.

### Giai đoạn 3 (61-90 ngày): Tối ưu hiệu năng & mở rộng
- Tối ưu chi phí và tốc độ xử lý các pipeline AI/LLM.
- Củng cố guardrail bảo mật và quy trình scan định kỳ.
- Hoàn thiện roadmap phát hành theo mốc version hóa rõ ràng.

## 4) Định dạng báo cáo định kỳ khuyến nghị
- **Báo cáo tuần:** tiến độ checklist, blocker, rủi ro.
- **Báo cáo tháng:** so sánh KPI theo xu hướng (quality, security, delivery).
- **Báo cáo quý:** tổng kết roadmap, điều chỉnh ưu tiên, kế hoạch quý tiếp theo.

## 5) KPI gợi ý theo dõi
- Tỷ lệ test pass (CI).
- Tỷ lệ lint pass.
- Số lỗi nghiêm trọng theo tuần/tháng.
- Thời gian phản hồi trung bình của API chính.
- Tỷ lệ issue hoàn thành đúng hạn theo roadmap.
