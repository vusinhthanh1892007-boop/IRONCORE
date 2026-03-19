---
description: "Run a safe code-change workflow on this repository with anti-hallucination checks and strict validation."
mode: ask
---

# Safe Change Workflow

Mục tiêu: thực hiện thay đổi code an toàn, không làm hỏng cấu trúc hiện tại.

## Input
- Yêu cầu thay đổi:
- File/Module ưu tiên:
- Mức rủi ro chấp nhận: low / medium / high

## Instructions for agent

Thực hiện theo PARTS:
1. Preview phạm vi ảnh hưởng.
2. Analyze yêu cầu và ràng buộc.
3. Read file liên quan trước khi sửa.
4. Think ngắn gọn về root-cause và rủi ro.
5. Start với minimal patch.

## Hard constraints
- Chỉ sửa file cần thiết.
- Không thay đổi public contract trừ khi yêu cầu explicit.
- Không thêm dependency nếu không bắt buộc.

## Validation requirements
- Kiểm tra lỗi file đã sửa.
- Chạy test liên quan gần nhất.
- Báo cáo theo format:
  - What changed
  - Validation result
  - Remaining risk
  - Next suggested step
