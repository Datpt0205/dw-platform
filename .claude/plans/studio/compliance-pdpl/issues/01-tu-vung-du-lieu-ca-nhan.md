# 01 — Từ vựng loại dữ liệu cá nhân một chủ

Status: needs-triage
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.4, CP1

## Mục tiêu

Một module kernel sở hữu từ vựng `pd_category`, `sensitive_type` và Trường định danh chủ thể; mọi bảng
định nghĩa trường đọc từ đó, và tạo trường thiếu loại bị từ chối (spec R1).

## Việc cần làm

1. `dw_kernel.personal_data` (thuần stdlib): `PdCategory` (`none`, `basic`, `sensitive`); `SensitiveType`
   theo Nghị định 356 Điều 4.1 (danh sách giữ một chỗ); `SubjectIdentifierKind` (email, phone,
   national_id, zalo_user_id, facebook_psid, tax_code, bank_account); `requires_explicit_grant(category)`.
2. JSON Schema `contracts/jsonschema/pd_classification.json` sinh ra từ module và `--check` trong CI.
3. Bảng nhãn tiếng Việt `apps/web/lib/pd-labels.ts`; test đỏ khi một giá trị `pd_category` hay
   `sensitive_type` thiếu nhãn.
4. Helper test catalog `assert_field_tables_classified(...)` để custom-objects, workflow-triggers và
   tools-and-skills dùng: mỗi bảng định nghĩa trường có cột `pd_category`, `sensitive_type`,
   `subject_identifier`, và ràng buộc CHECK bằng đúng enum của `dw_kernel.personal_data`.
5. Mã lỗi `pd_category_required` và helper validate cho các spec chủ bảng; thiếu `pd_category` khi tạo
   trường → 422 (spec chủ bảng thực thi điểm chèn, lát này cấp mã và helper).

## Tiêu chí chấp nhận

- [ ] R1.1 (CP1): POST một trường không có `pd_category` → 422 `pd_category_required`, không tạo trường.
- [ ] R1.2 (CP1): ràng buộc CHECK `pd_category` của một bảng định nghĩa trường bằng đúng enum của
      `dw_kernel.personal_data`.
- [ ] R1.3 (CP1): thêm một giá trị CHECK ngoài enum kernel → test drift đỏ; một giá trị thiếu nhãn tiếng
      Việt → test nhãn đỏ.
- [ ] R1.4: một trường `Nhạy cảm` thiếu `sensitive_type` → từ chối; một trường `Cơ bản` mang
      `sensitive_type` → từ chối.
- [ ] Xong: `make ci` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/contracts.py:167`; spec: R1.1 (`data_classification`
  khai mà không đọc, thay bằng `pd_category` theo thuộc tính).
- ADR-0106 (Proposed) quyết 1.

## Comments

- 2026-10-23 (agent): B11-security compliance-pdpl 01. field-security, custom-objects và Data Hub đọc từ
  đây; field-security sở hữu chế độ `Mở`/`Bảo vệ` và mặc định bảo vệ.
