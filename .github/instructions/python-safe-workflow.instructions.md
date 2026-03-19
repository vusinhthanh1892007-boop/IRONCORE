---
applyTo: "ironcore/**/*.py"
description: "Use when editing Python files in IronCore: enforce PARTS workflow, small safe diffs, and mandatory validation before finishing."
---

# Python Safe Workflow (IronCore)

## Scope
Áp dụng cho mọi file Python trong `ironcore/`.

## Mandatory execution order

1. Read related interfaces first
- Đọc class/type contract liên quan trước khi sửa.
- Nếu module có event/schema, đọc producer + consumer.

2. Plan minimal diff
- Giữ thay đổi nhỏ và cô lập.
- Tránh đổi tên symbol hàng loạt nếu không bắt buộc.

3. Implement
- Ưu tiên root-cause fix.
- Giữ style nhất quán với file hiện tại.

4. Validate
- Chạy kiểm tra lỗi file đã sửa.
- Chạy test nhỏ nhất liên quan trước.

5. Report
- Tóm tắt chính xác file đã đổi, lý do, và kết quả kiểm chứng.

## Safety constraints

- Không tự ý xóa code lớn hoặc xóa file.
- Không sửa test unrelated để “ép xanh”.
- Không thêm TODO mơ hồ thay cho fix thật.
- Không dùng mock answer cho logic production trừ khi được yêu cầu rõ.

## Anti-hallucination guardrails

- Không viện dẫn API/thư viện chưa tồn tại trong repo mà không kiểm tra.
- Không khẳng định “đã chạy test” nếu chưa chạy.
- Nếu có bất định kỹ thuật, ghi rõ giả định rồi mới triển khai.
