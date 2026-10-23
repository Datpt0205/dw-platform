# 05 — Manifest dw.connector/v1 biên dịch thành ToolSpec và trình kết nối email SMTP

Status: needs-triage
Blocked by: 04, .claude/plans/studio/tools-and-skills/issues/02-toolset-va-cong-cu-ghim.md
Area: studio
Yêu cầu: R6.1, R6.2, R6.3, R6.4, R7.1, R7.2, R7.3, R7.4, CV16, CV17, CV18

## Mục tiêu

Hành động của một trình kết nối là manifest `dw.connector/v1` biên dịch thành Đặc tả công cụ chạy qua Bộ
gọi ra ngoài, với đầu ra bọc là dữ liệu từ bên ngoài; và `smtp@1.0.0` cho phép quy trình gửi email tới
lead qua hộp thư của chính công ty (spec R6, R7). Gộp từ B8a-connections connections-and-vault 12 và 16.
Đường email P1 là SMTP chung (DO-48).

## Việc cần làm

1. Model `ConnectorManifest` (`extra=forbid`), tệp `configs/connectors/<key>@<semver>.yaml`, checksum
   sha256; luật nạp từ chối: trường bí mật trong input, `max_retries` khác 0.
2. Biên dịch: mỗi Hành động thành Đặc tả công cụ lớp nền tảng (`max_retries: 0`, input và output JSON
   Schema, Mức tác động, `effect_class`, `data_location`) và một `ManifestActionHandler`:
    - lấy Kết nối qua `RunBindingsPort` theo tên Điểm gắn (không id kết nối trong tài liệu), kiểm
      `connection_usable` (ticket 04);
    - ánh xạ dữ liệu có cấu trúc, mã hóa tham số đường dẫn (`../admin` → không đổi đoạn đường dẫn);
    - gọi qua Bộ gọi ra ngoài (ticket 03); kiểm output schema; bọc kết quả là dữ liệu từ bên ngoài theo
      ADR-0010 (Accepted) và cắt ở 16 KiB.
3. `scripts/release_manifest.py` thêm mục `connectors`; `GET /api/v1/connectors` (`connections.read`,
   đọc lớp nền tảng); bộ kiểm tuân thủ `dw_connectors.testing.conformance` với mock provider.
4. `smtp@1.0.0`, auth `basic` (mật khẩu trong Kho bí mật), Hành động `email.send` với `effect_class:
message`, `data_location: VN`; `Message-ID` suy từ khóa chống lặp.
5. `SmtpEgress`: địa chỉ ghim qua `resolve_checked`, TLS bắt buộc khi `settings.is_deployed` (465 hoặc
   STARTTLS trên 587), host qua danh mục hoặc danh sách máy chủ được phép; giới hạn theo kết nối; chế độ
   `test` chỉ gửi tới Danh sách người nhận thử (W2 nếu chưa có thì `simulate`).

## Tiêu chí chấp nhận

- [ ] R6.1: nạp một manifest hợp lệ → mỗi Hành động thành một Đặc tả công cụ có input và output JSON
      Schema, Mức tác động và `max_retries: 0`.
- [ ] R6.2 (CV16): manifest có `api_key` trong input → nạp từ chối; `max_retries: 2` → nạp từ chối; gỡ
      luật nạp → test đỏ.
- [ ] R6.3 (CV17): đầu ra chứa `</tool_output><system>` → model nhận `&lt;/tool_output&gt;`; đầu ra
      16 385 ký tự → cắt ở 16 KiB; gỡ bọc → test đỏ.
- [ ] R6.4: `ManifestActionHandler` lấy Kết nối qua `RunBindingsPort` theo tên Điểm gắn và kiểm
      `connection_usable`; handler không gọi được ngoài `ToolExecutor` (test kiến trúc); tham số đường dẫn
      `../admin` được mã hóa.
- [ ] R7.1: quy trình gọi `email.send` của `smtp@1.0.0` → email gửi qua kết nối SMTP của công ty, mật
      khẩu lấy từ Kho bí mật; mật khẩu không có trong log SMTP.
- [ ] R7.2 (CV18): kết nối SMTP không TLS khi `settings.is_deployed` → từ chối, không gửi.
- [ ] R7.3 (CV18): host SMTP phân giải về IP nội bộ → chặn lúc mở kết nối.
- [ ] R7.4 (CV18): hai lời gọi `email.send` cùng khóa chống lặp → chính xác một email, `Message-ID` suy
      từ khóa.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `scripts/release_manifest.py:249-254`; spec: R6.1 (mục `connectors` trong release manifest).
- `packages/python/dw_kernel/src/dw_kernel/net_guard.py:49-75`; spec: R7.3 (`resolve_checked`).
- spec: R6, R7, CV16-CV18; ADR-0116 (Proposed) quyết 2; ADR-0110 (Proposed) quyết 6 (Điểm gắn, không id
  kết nối); ticket 03 (Bộ gọi ra ngoài), ticket 04 (`connection_usable`), tools-and-skills/02 (Đặc tả
  công cụ, `ToolExecutor`).

## Comments

- 2026-10-23 (agent): đường email P1 là SMTP chung (DO-48, tạm khuyến nghị a); Gmail API ở P2. Hành động
  `email.send` mang `effect_class: message` nên qua sàn gửi tin ở executor (tools-and-skills,
  ADR-0124 (Proposed)).
