# 26 — Kho giữ dữ liệu cá nhân ngoài bản ghi: kiểm kê, cách thực thi lưu giữ, telemetry không nội dung

Type: research
Status: needs-triage
Area: studio · Viết: 23/10/2026
FOG: FOG-76 `pd-inventory`, FOG-57 `retention-mechanics`, FOG-71 `otel-genai`

## Câu hỏi

1. Kiểm kê đủ mọi kho giữ dữ liệu cá nhân: nội dung Valkey, Langfuse và ClickHouse, bản sao lưu, file xuất, file tải lên
   đang chờ, log của LiteLLM (FOG-76). Phần bản sao lưu và file xuất hỏi thêm người vận hành.
2. Lưu giữ `inbound_events` và `trigger_deliveries`: DROP PARTITION hay DELETE theo lô (benchmark của đợt nghiên cứu
   hỏng); SeaweedFS có hết hạn object theo tiền tố cho payload bước chạy không; ép lưu giữ trên Langfuse OSS bằng TTL
   của ClickHouse trên bảng v4, hay bằng xoay vòng (FOG-57)?
3. Ghim commit nào của semantic-conventions GenAI, và Langfuse v4 ánh xạ `gen_ai.input.messages` so với `gen_ai.prompt`
   cũ thế nào (FOG-71)?

## Vì sao

Danh sách cổng cho yêu cầu của chủ thể dữ liệu và sổ xử lý chỉ tốt bằng bản kiểm kê này. Lưu giữ không thực thi được là
kiểm soát khai báo mà không ai ép (failure-modes #1). Span phải không có nội dung mà nhân viên vẫn đọc được trên
Langfuse.

## Mở khóa

- Spec: `compliance-pdpl` (06, lớp lưu giữ; yêu cầu của chủ thể dữ liệu ở W2), `telemetry-and-audit` (01, 03),
  `workflow-triggers` (02, lưu giữ sự kiện nhận).
- ADR: 0122, 0106.
- DO: DO-52 (thời hạn lưu cho mọi kho mới), DO-51 (ghi nội dung, xem sử dụng theo người), DO-56.
- Ticket W1: `telemetry-and-audit/01` (ghim commit), `compliance-pdpl/06`.

## Đầu ra

- Bảng kho: tên, có dữ liệu cá nhân gì, ai đọc, thời hạn lưu, cách xóa (DROP PARTITION, DELETE, TTL, hết hạn object),
  đã chạy thử chưa. Dòng nào không có test hay lane thực thi thì ghi là khai báo suông.
- Log và cache của gateway của bên yêu cầu lấy từ ticket 18.
- Commit đã ghim và bảng ánh xạ thuộc tính sang Langfuse, cho `telemetry-and-audit/01`.

## Nguồn

- Brief B7a, B10b, B11; `configs/policies/retention@1.7.0.yaml:120-121` (nhật ký kiểm toán 1095 ngày).
- [research.md](../research.md) mục 5 (benchmark lưu giữ hỏng), mục 11 (commit quy ước GenAI chưa kiểm).

## Comments
