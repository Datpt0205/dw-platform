# 27 — Dữ liệu tham chiếu Việt Nam: tỉnh sau sáp nhập 2025, ngày lễ và ngày làm việc, tzdata trong image

Type: research
Status: ready-for-agent
Area: studio · Viết: 23/10/2026
FOG: FOG-08 `province-list`, FOG-16 `holidays`, FOG-17 `tzdata`

## Câu hỏi

1. Danh sách tỉnh chính thức sau đợt sắp xếp đơn vị hành chính 2025, cho danh sách chọn và quy tắc phân bổ (FOG-08)?
2. Nguồn ngày lễ của Việt Nam (gồm Tết âm lịch), ai duy trì lịch ngày làm việc mỗi năm, và "+2 ngày làm việc" nghĩa là gì
   khi công ty có ngày nghỉ riêng hay nửa ngày (FOG-16)?
3. `zoneinfo` có nạp được `Asia/Ho_Chi_Minh` trong image worker đã dựng (`infra/docker/worker.Dockerfile:41`,
   `python:3.12-slim-bookworm`) không, khi `tzdata` chỉ được khóa cho dev và Windows (`uv.lock:722`, `uv.lock:1275`)
   (FOG-17)?

## Vì sao

Quy tắc phân bổ theo tỉnh cũ giao lead sai người. Hạn trả lời yêu cầu của chủ thể dữ liệu, hạn phê duyệt và
`time.add_workdays` tính bằng ngày làm việc; lịch cũ làm trễ hạn. Lịch chạy và kỳ tính hạn mức theo múi giờ công ty
(DO-50) sẽ lặng lẽ sai hoặc lỗi ở production nếu image thiếu dữ liệu múi giờ.

## Mở khóa

- Spec: `marketing-pilot` (đối tượng của gói nghiệp vụ, quy tắc phân bổ), `workflow-nodes` (hàm thời gian), `compliance-pdpl` (hạn
  của yêu cầu chủ thể dữ liệu, YC90: 2 ngày làm việc), `workflow-triggers` (lịch chạy, YC98), `usage-and-limits` (03,
  kỳ tính), `studio-skeleton` (YC1: giờ theo `Asia/Ho_Chi_Minh`).
- ADR: 0121, 0113.
- DO: DO-50 (Đạt chốt 23/10/2026: kỳ tính theo múi giờ công ty).

## Đầu ra

- Câu 1-2: văn bản nguồn (số hiệu, ngày, URL, loại) và ai cập nhật dữ liệu mỗi năm; spec chủ quyết nơi giữ dữ liệu.
- Câu 3: kết quả của một lệnh trong image đã dựng. Nếu lỗi, đề xuất thêm `tzdata` vào phụ thuộc runtime cùng một test đỏ
  khi bỏ nó.

## Nguồn

- Brief B7a, B7b, B11, B12.
- [research.md](../research.md) mục 15 (danh sách tỉnh sau sáp nhập 2025 chưa kiểm).

## Việc của agent (phân loại 4/11/2026)

- Câu hỏi: câu 1-3. Nghĩa của "+2 ngày làm việc" khi công ty có ngày nghỉ riêng là quyết định của spec chủ
  (`workflow-nodes`, `compliance-pdpl`); agent chỉ ghi phương án.
- Cách làm: câu 1-2 đọc văn bản gốc (nghị quyết sắp xếp đơn vị hành chính cấp tỉnh năm 2025; Bộ luật Lao động
  2019 về ngày nghỉ lễ và văn bản công bố lịch nghỉ hằng năm), ghi số hiệu, ngày, URL, loại và ngày đọc;
  `vbpl.moj.gov.vn` không phân giải được từ máy này (compliance-pdpl/01), nên dùng Công báo hay cổng Chính phủ.
  Câu 3: dựng ảnh `worker` và `api` của compose, rồi `docker run --rm <ảnh> python -c` in `utcoffset()` của
  `datetime(2026, 1, 1, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))`.
- Đầu ra: `## Answer` ở đây; nếu câu 3 chỉ đúng nhờ gói `tzdata`, đề xuất một test đỏ khi bỏ `tzdata` khỏi phụ
  thuộc chạy.
- Đạt khi: câu 3 in `7:00:00` trong cả hai ảnh; câu 1-2 có văn bản nguồn kèm số hiệu, ngày, URL và loại, điều
  không tìm được ghi "chưa kiểm".

## Comments

- 2026-11-04 (agent, phân loại G12, theo ủy quyền 31/10/2026): `ready-for-agent`. Câu 3 một phần: `tzdata>=2024.1` thành phụ thuộc chạy của `dw-usage` (worker) và `dw-studio` (api) ở `522bd4e` và `73ee226` (khóa 2026.4), nên ảnh có dữ liệu múi giờ, nhưng chưa ai chạy lệnh trong ảnh đã dựng. Câu 1-2 chưa ai đọc nguồn. Không cần người, khóa hay máy riêng.
