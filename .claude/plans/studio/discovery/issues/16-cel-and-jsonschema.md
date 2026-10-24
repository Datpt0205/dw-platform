# 16 — Runtime CEL và chi phí kiểm JSON Schema trên đường nóng

Type: prototype
Status: needs-triage
Area: studio · Viết: 23/10/2026
FOG: FOG-50 `cel-runtime`, FOG-58 `jsonschema-cost`

## Câu hỏi

1. Runtime CEL Python nào (`cel-expr-python` 0.1.3, `common-expression-language` 0.10.0, `cel-python` 0.5.0) đăng ký
   được hàm Python và đối tượng có kiểu, ép được giới hạn chi phí, qua bộ conformance, có wheel manylinux cho image
   Python 3.12, và chấm tiêu chí chia sẻ trong giới hạn chi phí theo lô 1.000 bản ghi (FOG-50)?
2. Bản Rust dự phòng có bị chặn chi phí chỉ bằng kiểm AST trước khi chạy không, khi một lời gọi native không ngắt được
   từ Python (FOG-50)?
3. Kiểm `jsonschema` mỗi lời gọi tốn bao nhiêu (p95, lược đồ 30 thuộc tính); thu hẹp lược đồ theo bảo mật trường cho mỗi
   lượt chạy tốn bao nhiêu; `jsonschema-rs` (giấy phép, wheel, tương đương) có nên thay ở ingress và đầu ra của bước
   không (FOG-58)?

## Vì sao

Một ngôn ngữ biểu thức cho điều kiện, chuỗi có biến, điều kiện để lưu được, trường công thức và quy tắc chia sẻ dựa cả
vào runtime này. Kiểm lược đồ chạy ở mọi lời gọi công cụ và mọi sự kiện nhận.

## Mở khóa

- Spec: `workflow-nodes` (01, `ExpressionEngine`), `custom-objects` (điều kiện để lưu được), `record-access` (quy tắc
  chia sẻ, W2), `tools-and-skills` (01, executor tự kiểm JSON Schema), `workflow-triggers` (02, ingress).
- ADR: 0114 (Open 5), 0116.
- DO: DO-38 (bản C++ 0.1.x ghim chính xác làm mặc định, bản Rust dự phòng qua cùng bộ test hợp đồng), DO-37 (Đạt
  chốt 23/10/2026: "phải đúng", CEL với vector thử port từ si-platform).
- Ticket W1: `workflow-nodes/01`, `tools-and-skills/01` (P0).

## Dựng tối thiểu

Ba adapter `ExpressionEngine` mỏng qua cùng một bộ test hợp đồng: một hàm Python tùy biến, một đối tượng JSON có kiểu,
một biểu thức vượt chi phí, 1.000 bản ghi giả lập cho tiêu chí chia sẻ; cài wheel trong image `python:3.12-slim-bookworm`
(`infra/docker/worker.Dockerfile:41`). Phần JSON Schema: một lược đồ 30 thuộc tính, `jsonschema` 4.26.0
(`uv.lock:1947`) so với `jsonschema-rs` trên cùng bộ vector.

## Phép đo quyết định

| Đo                                                            | Ngưỡng hay so sánh                         | Quyết định                                       |
| ------------------------------------------------------------- | ------------------------------------------ | ------------------------------------------------ |
| Hàm Python, kiểu, conformance, wheel                          | Có hay không, theo từng runtime            | Runtime mặc định và dự phòng (ADR 0114, DO-38)   |
| Biểu thức vượt chi phí trên mỗi runtime                       | Dừng trong giới hạn, không treo tiến trình | Bản Rust có cần ranh giới tiến trình không       |
| Lô 1.000 bản ghi                                              | Chưa có ngưỡng; ghi p95                    | Quy tắc chia sẻ (W2) dùng được runtime này không |
| `jsonschema` p95 mỗi lời gọi; tương đương với `jsonschema-rs` | Ghi số; mọi vector cho cùng kết quả        | Giữ `jsonschema` hay đổi                         |

## Nguồn

- Brief B4, B5, B7a, B7b, B8b; `docs/adr/0114-cel-is-the-one-expression-language.md:110` (đo trước) và Open 5.
- [research.md](../research.md) mục 3 và 15 (runtime CEL chưa chọn; giới hạn chi phí có thật sự được ép không chưa
  kiểm).

## Comments
