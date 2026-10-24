# 06 — Chủ thể qua chuỗi lồng nhau, mức truy cập trên định nghĩa, khóa vai của gói nghiệp vụ và sản phẩm hạ nguồn

Type: grilling
Status: needs-triage
Area: studio · Viết: 23/10/2026
FOG: FOG-45 `nested-actors`, FOG-46 `definition-depth`, FOG-49 `pack-roles`

## Câu hỏi

Hỏi Đạt; câu 4 hỏi thêm chủ của dw-proterial:

1. Chủ thể lồng nhau: bước agent trong quy trình, agent gọi một quy trình đã phát hành như công cụ, quy trình gọi agent.
   Ở mỗi chặng chủ thể nào và giới hạn dữ liệu nào áp dụng, và chúng giao nhau thế nào dọc chuỗi (FOG-45)?
2. Mỗi nhóm có thuộc đúng một workspace không, như thứ tự mức truy cập toàn phần đòi hỏi; quan hệ quản lý trực tiếp dùng
   cho chuyển cấp việc lấy từ đâu, và có theo từng workspace không (FOG-45)?
3. Quyền trên định nghĩa (công cụ, kỹ năng, máy chủ MCP, kết nối) có mức truy cập (của tôi, workspace, workspace và cấp
   dưới, toàn công ty) như bản ghi theo D1 không (FOG-46)?
4. Vai trò mẫu của gói nghiệp vụ gọi khóa đối tượng của chính gói nghiệp vụ đó thế nào; ai chuyển `memberships.role_keys` và các vai
   `sales_*` của dw-proterial sang vai trò dạng dữ liệu, và khi nào (FOG-49)?

## Vì sao

Một chuỗi nới tầm ở bất kỳ chặng nào là đường leo thang quyền. Nếu định nghĩa có mức truy cập thì bảng định nghĩa cần
thêm policy theo mức truy cập như bảng bản ghi, ngoài RLS chỉ theo tenant mà ADR 0100 đặt cho định nghĩa toàn công ty
(DO-01). Đổi khóa vai mà không có kế hoạch làm gãy gói nghiệp vụ và sản phẩm đang chạy: một sản phẩm còn ghi `memberships.role_keys` sẽ lỗi
(ADR 0104).

## Mở khóa

- Spec: `record-access` (04, giới hạn dữ liệu), `org-and-principals` (03), `workflow-engine`, `agent-builder`,
  `tools-and-skills`, `connections-and-vault` (phạm vi dùng chung), `tenant-rbac` (02), `domain-packs`.
- ADR: 0103 (đang viết), 0102 (Open 3), 0104 (Open 5), 0105, 0116.
- DO: DO-12 (chủ thể của lượt chạy không người, trước W1), DO-10 (Đạt chốt 23/10/2026: mức "Của nhóm tôi" là tôi
  và nhóm tôi), DO-09, DO-25.

## Đầu ra

- Một bảng chuỗi: chặng, chủ thể, giới hạn dữ liệu, phép giao, test âm sẽ có; ghi vào ADR 0103.
- Câu 2 trái giả định ở điểm 4 của ADR 0102 thì quyền trên bản ghi thêm nhánh và ticket 05 đo lại.
- Câu 3 ghi bảng định nghĩa nào cần policy theo mức truy cập, nếu có.
- Câu 4 ghi người chịu trách nhiệm và hạn chuyển đổi của dw-proterial.

## Nguồn

- Brief B3 (F5, F8, F9), B4, B7b, B8b.
- `docs/adr/0102-workspace-is-a-nested-data-owning-unit.md` và
  `docs/adr/0104-tenant-roles-with-depth-and-one-effective-grants-owner.md`, mục Open.

## Comments
