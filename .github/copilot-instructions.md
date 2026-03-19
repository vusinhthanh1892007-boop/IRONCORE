# IronCore Safe Coding Workflow (Anti-Hallucination)

Mục tiêu: AI sửa code nhanh nhưng không làm hỏng dự án.

## Quy trình bắt buộc: PARTS

Mọi task code phải đi theo thứ tự này:

1) Preview
- Xác định file/feature bị ảnh hưởng.
- Không đọc cả repo nếu không cần.

2) Analyze
- Đọc đúng file kế hoạch liên quan (`implementation_plan.md`, module docs nếu có).
- Xác định ràng buộc API hiện hữu trước khi sửa.

3) Read
- Đọc file mục tiêu và file interface liên quan trước khi đề xuất patch.
- Không đoán tên class/function chưa đọc thấy.

4) Think
- Viết ngắn gọn: nguyên nhân gốc + phạm vi sửa + rủi ro.
- Ưu tiên sửa nhỏ, đúng chỗ, giữ nguyên public contract.

5) Start
- Chỉ sửa sau khi 4 bước trên hoàn tất.
- Mỗi lần sửa tập trung 1 mục tiêu kỹ thuật rõ ràng.

## Luật chỉnh sửa an toàn

- Không đổi kiến trúc/đổi API công khai nếu chưa được yêu cầu.
- Không sửa file ngoài phạm vi task.
- Không chạm phần bảo mật, sandbox, policy nếu task không yêu cầu.
- Không thêm dependency mới nếu chưa cần thiết.
- Không tạo file tài liệu mới trừ khi được yêu cầu.

## Luật chống ảo giác

- Mọi kết luận phải dựa trên file đã đọc trong workspace.
- Nếu thiếu thông tin: hỏi 1-3 câu làm rõ hoặc nêu rõ giả định.
- Nếu cùng một lỗi lặp lại 2-3 lần: dừng, báo blocker, đề xuất phương án thay thế.

## Luật kiểm chứng trước khi kết thúc

- Chạy kiểm tra lỗi cho file đã sửa.
- Nếu có test liên quan, chạy test gần nhất trước (targeted tests), sau đó mới mở rộng.
- Báo cáo kết quả ngắn gọn theo format:
  - What changed
  - Why
  - Validation
  - Risks/Notes

## Luật output khi làm việc

- Trả lời ngắn, rõ, có bước tiếp theo.
- Không khoe nội dung file dài dòng nếu không được hỏi.
- Khi cập nhật tiến độ, nêu: đang làm gì + tiếp theo làm gì.
