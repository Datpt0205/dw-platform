# Gói miền: định dạng dw.package/v1, cài vào tenant thành bản sao có nguồn gốc

Status: needs-info (DO-25)
Area: studio · Nhánh: `docs/studio-planning` · Viết: 23/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Nền tảng giao nội dung nghiệp vụ dưới dạng dữ liệu, không thành context hay gói Python: một Gói nghiệp vụ (Marketing
trước tiên, D4) là thư mục `dw.package/v1` trong `configs/packs/<key>@<semver>/`, cài vào công ty chỉ qua API công
khai thành Bản sao từ gói, và phiên bản mới của gói chỉ đến như Đề xuất cập nhật gói vào bản nháp (ADR-0100 (Proposed)
(Proposed) quyết định 2). Spec này không có ticket W1: lát W1 gieo Lead và Campaign bằng một script gọi API công khai
(marketing-pilot/02), và chính script đó là nguồn của gói Marketing 1.0 ở W2. Mọi yêu cầu dưới đây là phạm vi W2;
hàng W3 nằm ở Ngoài phạm vi.

## Hiện trạng (đã kiểm ở `ab33703` ngày 23/10/2026)

- Lối cài mẫu báo cáo có sẵn nuốt mọi lỗi và không gốc ghép nào cung cấp hook của nó
  (`apps/api/src/dw_api/routes/v1/admin_console.py:179-199`, `apps/api/src/dw_api/routes/v1/platform.py:131-151`).
  Ràng buộc: trình cài gói không chép dạng cài lặng lẽ này (failure-modes #1).
- Release manifest dựng từ `configs/` và không có mục gói (`scripts/release_manifest.py:205-232`). Thiếu: chưa có
  `configs/packs/` và chưa có mục `packs` ghim gói.
- Mọi thứ có phiên bản được release manifest ghim (`CLAUDE.md:63-64`). Ràng buộc: mỗi gói nền tảng vào release
  manifest bằng phiên bản và hash.
- Câu trả lời kiểm kê chỉ đọc lớp nền tảng (`CLAUDE.md:195-196`). Ràng buộc: danh mục gói không phụ thuộc người hỏi.
- `TenantOverlay` là lớp nền tảng cộng lớp công ty, không bao giờ lấy ngang sang công ty khác
  (`packages/python/dw_kernel/src/dw_kernel/overlay.py:29-34`,
  `packages/python/dw_agent_runtime/tests/unit/test_tenant_overlay.py:72`). Ràng buộc: gói không là một lớp overlay;
  Bản sao từ gói là dữ liệu của công ty.
- Entitlement tách khỏi phân quyền (`CLAUDE.md:169`); gói dịch vụ nằm trong mã ở `DEFAULT_PLANS`
  (`packages/python/dw_platform/src/dw_platform/application/entitlement.py:17-36`) và được hỏi qua `has_feature`
  (`packages/python/dw_platform/src/dw_platform/application/entitlement.py:45-49`). Ràng buộc: quyền cài và
  entitlement `studio.pack.<key>` là hai lần kiểm riêng.
- Chỉ có ba schema `knowledge`, `memory`, `platform` (`db/migrations/sql/0001_platform_baseline.sql:1-7`). Thiếu:
  vỏ thành phần `studio.artifacts` có cột `origin` do tenant-config/02 tạo (ADR-0109 (Proposed)).

## Mục tiêu

### R1 — Định dạng gói `dw.package/v1` và gói nền tảng

Nền tảng giao gói nghiệp vụ dưới dạng thư mục có phiên bản, kiểm được ở CI (ADR-0100 (Proposed)).

- R1.1 Bộ nạp gói PHẢI chỉ nhận thư mục `configs/packs/<key>@<semver>/` có `package.json` hợp lệ theo JSON Schema
  `dw.package/v1`, schema không cho khóa nào ngoài định nghĩa.
- R1.2 NẾU một gói có thành phần ngoài các loại đã đăng ký, hay chứa bản ghi hoặc thông tin bí mật, THÌ bộ nạp gói
  PHẢI từ chối gói đó ở CI và khi cài, và không cài gì.
- R1.3 NẾU một tệp thành phần đổi mà phiên bản của gói không đổi, THÌ kiểm release manifest trong CI PHẢI đỏ.
- R1.4 NẾU hash tính lại của một gói khác hash khai báo, THÌ trình cài PHẢI từ chối cài và không tạo gì.
- R1.5 Release manifest PHẢI ghim mỗi gói nền tảng bằng `key`, `version` và `hash` trong mục `packs`.
- R1.6 NẾU một gói đặt `api_name` ngoài Tiền tố dành riêng nó khai báo, THÌ bộ nạp gói PHẢI từ chối gói đó.

### R2 — Cài gói thành Bản sao từ gói

Quản trị viên công ty cài một gói nghiệp vụ rồi tự sửa, không chạm phần của công ty khác (YC38).

- R2.1 KHI một yêu cầu cài qua được kiểm quyền và kiểm entitlement, trình cài PHẢI tạo mọi thành phần của gói thành
  Bản sao từ gói với `origin` (`pack_key`, `pack_version`, `component_key`, `base_content_hash`) trong một giao dịch.
- R2.2 Trình cài PHẢI tạo thành phần chỉ qua route công khai và trình kiểm của từng loại, như khi người dùng tạo,
  không ghi thẳng bảng nào.
- R2.3 NẾU một thành phần của gói không hợp lệ, THÌ trình cài PHẢI trả 422 liệt kê mọi lỗi và không tạo thành phần
  nào.
- R2.4 KHI cài xong, trình cài PHẢI để mọi thành phần của gói ở Nháp, không thành phần nào ở Đang dùng, và không tạo
  lượt chạy nào.
- R2.5 NẾU gói dịch vụ của công ty không gồm gói đó, THÌ route cài PHẢI trả 403 `entitlement_denied` và không cài
  gì.
- R2.6 NẾU người gọi thiếu quyền cài gói [CAN LAM RO: Q1], THÌ route cài PHẢI trả 403 `permission_denied` và không
  cài gì.
- R2.7 KHI cùng `Idempotency-Key` của cùng người gọi được gửi lại, route cài PHẢI trả cùng kết quả và chỉ cài một
  lần.
- R2.8 NẾU gói đã được cài ở công ty, THÌ route cài PHẢI trả 409 `pack_already_installed` và không cài gì.
- R2.9 NẾU người của công ty B đọc bản cài của công ty A, THÌ API gói PHẢI trả 404.

### R3 — Tiền tố dành riêng

Tên mà gói nền tảng dùng không bị công ty chiếm trước.

- R3.1 NẾU người dùng tạo thành phần có `api_name` bắt đầu bằng Tiền tố dành riêng của một gói nền tảng (`mkt_`),
  THÌ API thành phần PHẢI trả 422 và không tạo gì.

### R4 — Gói Marketing 1.0.0 và "Bắt đầu với Marketing"

Một công ty mới có ngay bộ đối tượng, vai trò mẫu, quy trình và trợ lý của lát Marketing (D4).

- R4.1 KHI gói `marketing@1.0.0` được cài vào một công ty trắng, trình cài PHẢI tạo mọi thành phần của gói hợp lệ
  và liệt kê mọi Điểm gắn còn thiếu (`zalo_oa`, `email_sender`, `score_threshold`).
- R4.2 Gói `marketing@1.0.0` PHẢI cho cùng đối tượng, trường và vai trò mẫu như script gieo của marketing-pilot/02.
- R4.3 Gói `marketing@1.0.0` PHẢI mang bộ eval tổng hợp có prompt injection, tấn công chéo công ty và thiếu bằng
  chứng, chạy ở chế độ `simulate`.
- R4.4 KHI quản trị viên công ty mở "Bắt đầu với Marketing", trang PHẢI hiện thành phần sẽ tạo và Điểm gắn cần đặt
  sau khi cài, trước khi cài.

### R5 — Xuất và nhập Gói cài đặt của công ty

Công ty mang thành phần của mình giữa các công ty của nó mà không mất gì.

- R5.1 KHI một yêu cầu xuất qua được kiểm quyền, API gói PHẢI trả một Gói cài đặt `dw.package/v1` chứa bao đóng của
  các thành phần được chọn theo chỉ mục phụ thuộc.
- R5.2 KHI một Gói cài đặt vừa xuất được nhập vào một công ty trắng, API gói PHẢI tạo thành phần có cùng
  `content_hash` với bản đã xuất.
- R5.3 NẾU gói nhập có đường dẫn chứa `../`, nặng hơn 20 MiB, có hơn 2.000 tệp hay hash sai (đúng bằng giới hạn thì
  nhận), THÌ API gói PHẢI từ chối và không giải nén tệp nào ra ngoài thư mục tạm.
- R5.4 NẾU người gọi thiếu quyền nhập gói [CAN LAM RO: Q1], THÌ API gói PHẢI trả 403 và không nhập gì.

### R6 — Cập nhật bằng Đề xuất cập nhật gói

Phiên bản mới của gói đến như đề xuất vào bản nháp, không đè phần công ty đã sửa (ADR-0100 (Proposed)).

- R6.1 KHI một phiên bản mới của gói đã cài có trong release, trình cập nhật PHẢI tạo một Đề xuất cập nhật gói cho mỗi
  thành phần đã đổi, xếp loại `fast_forward`, `conflict`, `add` hay `deprecate`, và không đổi thành phần nào.
- R6.2 NẾU thành phần đã bị công ty sửa khác `base_content_hash`, THÌ trình cập nhật PHẢI xếp đề xuất loại
  `conflict` và giữ cả ba bản: gốc, của công ty và mới.
- R6.3 KHI một người có quyền cập nhật gói [CAN LAM RO: Q1] áp một đề xuất, trình cập nhật PHẢI chỉ ghi vào bản Nháp
  của thành phần, phiên bản Đang dùng giữ nguyên.
- R6.4 Trình cập nhật PHẢI không áp đề xuất nào khi không có người áp.

## Trong phạm vi

- JSON Schema và model `dw.package/v1` (`contracts/jsonschema/dw.package.v1.json`); thư mục
  `configs/packs/<key>@<semver>/`; mục `packs` của release manifest; registry Tiền tố dành riêng.
- Bảng `studio.pack_installs`, `studio.pack_install_components`, `studio.pack_update_proposals`.
- Route `GET /api/v1/studio/packs`, `POST /api/v1/studio/packs/{key}/install`, `GET /api/v1/studio/packs/installs/{id}`;
  xuất, nhập Gói cài đặt của công ty; áp Đề xuất cập nhật gói; audit và outbox `studio.pack.installed`.
- Gói `configs/packs/marketing@1.0.0/`; màn "Gói nghiệp vụ" và trình "Bắt đầu với Marketing".

## Ngoài phạm vi

| Việc                                                                | Vì sao                                                                   | Chủ                             |
| ------------------------------------------------------------------- | ------------------------------------------------------------------------ | ------------------------------- |
| Định dạng gói `dw.package/v1` và gói nền tảng trong `configs/packs` | Không có ticket W1; R1 cắt ticket khi W2 bắt đầu                         | domain-packs, đợt sau (W2)      |
| Cài gói nền tảng vào tenant thành bản sao có nguồn gốc              | R2, R3; cần vỏ thành phần và loại `object`, quy trình, trợ lý đã có      | domain-packs, đợt sau (W2)      |
| Gói Marketing 1.0.0 và trình "Bắt đầu với Marketing"                | R4; nguồn là script gieo W1 của marketing-pilot/02                       | domain-packs, đợt sau (W2)      |
| Xuất và nhập gói của tenant; cập nhật bằng đề xuất ba bên           | R5, R6; cần chỉ mục phụ thuộc và nguyên mẫu đề xuất ba bên               | domain-packs, đợt sau (W2)      |
| Đưa gói từ Công ty thử nghiệm lên; ký gói cho data plane tự host    | Cần Công ty thử nghiệm (DO-62) và data plane do khách tự host            | domain-packs, đợt sau (W3)      |
| Lát gieo Lead và Campaign bằng script gọi API công khai             | W1 dựng bằng script, chưa cần định dạng gói                              | marketing-pilot (W1, ticket 02) |
| Nội dung đối tượng, quy trình, trợ lý của gói Marketing             | marketing-pilot định nghĩa; spec này đóng gói                            | marketing-pilot                 |
| Chợ gói của bên thứ ba; công ty bán gói cho công ty khác            | Không có nhu cầu ở v1                                                    | không làm                       |
| Tự cập nhật phiên bản Đang dùng                                     | Cập nhật luôn là đề xuất vào bản nháp (ADR-0100 (Proposed) quyết định 2) | không làm                       |
| Dữ liệu mẫu cài vào công ty chính                                   | Chỉ dữ liệu tổng hợp, chỉ ở Công ty thử nghiệm                           | không làm                       |

## Kiểm soát

| #    | Kiểm soát                            | Yêu cầu    | Test âm                                                                                                                   |
| ---- | ------------------------------------ | ---------- | ------------------------------------------------------------------------------------------------------------------------- |
| DP1  | Gói không chứa dữ liệu cấm           | R1.2       | `package.json` có khóa ngoài schema, thành phần bản ghi hay bí mật → bị từ chối khi nạp ở CI và khi nhập                  |
| DP2  | Hash gói đúng                        | R1.3, R1.4 | Sửa một tệp thành phần mà không đổi phiên bản → kiểm release manifest đỏ; hash tính lại khác khai báo → cài bị từ chối    |
| DP3  | Cài là một giao dịch                 | R2.3       | Một thành phần không hợp lệ → không thành phần nào được tạo, 422 liệt kê đủ lỗi; bỏ giao dịch → test đỏ                   |
| DP4  | Cài đi qua cùng đường như người dùng | R2.2       | Thành phần vi phạm trình kiểm của loại → bị từ chối như khi người dùng tạo; mô-đun cài ghi thẳng bảng → test kiến trúc đỏ |
| DP5  | Không tự kích hoạt                   | R2.4       | Sau cài, không thành phần nào ở Đang dùng; gửi sự kiện tới quy trình của gói → không lượt chạy nào                        |
| DP6  | Tiền tố dành riêng                   | R1.6, R3.1 | Công ty tạo `api_name` `mkt_x` → 422; gói dùng tiền tố khác tiền tố khai báo → nạp lỗi                                    |
| DP7  | Quyền và entitlement tách rời        | R2.5, R2.6 | Có quyền, gói dịch vụ không gồm gói → 403 `entitlement_denied`; có entitlement, thiếu quyền → 403 `permission_denied`     |
| DP8  | Cài đúng một lần                     | R2.7, R2.8 | Gửi lại cùng `Idempotency-Key` → cùng kết quả, một lần cài; khóa khác khi đã cài → 409 `pack_already_installed`           |
| DP9  | Cô lập công ty                       | R2.9       | Cài ở A không tạo và không lộ gì ở B; `GET` bản cài của A từ B → 404                                                      |
| DP10 | Cập nhật không bao giờ tự phát hành  | R6.3, R6.4 | Áp đề xuất → chỉ bản nháp đổi, phiên bản Đang dùng giữ nguyên; thêm một lane tự áp → test đỏ                              |
| DP11 | Gói nhập bị coi là dữ liệu lạ        | R5.3       | Zip có `../`, 20 MiB cộng một byte, 2.001 tệp, hash sai → từ chối; không tệp nào ra ngoài thư mục tạm                     |
| DP12 | Chỉ người có quyền nhập              | R5.4       | Người thiếu quyền nhập gửi gói hợp lệ → 403, không thành phần nào được tạo                                                |

## Tiêu chí xong

- Mọi tiêu chí R có test; mọi kiểm soát có test âm đã thấy đỏ khi gỡ kiểm soát, ghi ở Comments của ticket W2.
- `make ci` và `make test-integration` xanh, gồm một test integration cài `marketing@1.0.0` vào một công ty trắng.

## Phụ thuộc

- Vỏ thành phần với `origin`, dịch vụ phát hành và `studio.dependencies` (tenant-config/02, ADR-0109 (Proposed));
  Điểm gắn và phiên bản cấu hình (tenant-config, ADR-0110 (Proposed)).
- Máy giai đoạn và cổng phát hành (ADR-0120 (Proposed)): gói không đưa thành phần nào lên Đang dùng.
- Loại `object` và đường phát hành của nó (`custom-objects:R1.1`, `custom-objects:R1.2`); vai trò mẫu của
  tenant-rbac; loại quy trình của workflow-engine; loại trợ lý của agent-builder.
- `Idempotency-Key` gắn người gọi (app-standards/02); entitlement theo gói dịch vụ (usage-and-limits).
- Kiểm lại khi: trả lời Q1 (DO-25) → toàn spec; trả lời Q1 của custom-objects về phát hành đối tượng → R2.4;
  ADR-0109 (Proposed) đổi `origin` → R2.1; ADR-0110 (Proposed) đổi Điểm gắn → R4.1.

## Câu hỏi còn mở

- Q1. DO-25: Gói nghiệp vụ sống trong repo này dưới dạng cấu hình, mỗi công ty cài một gói một lần, entitlement
  `studio.pack.<key>` theo gói dịch vụ, và ai được cài, cập nhật, xuất, nhập gói (đề xuất các khóa
  `studio.packs.install`, `studio.packs.update`, `studio.packages.export`, `studio.packages.import`)? Chủ: người đặt
  yêu cầu và Đạt. Chặn: R2.6, R5.4, R6.3, toàn spec.
- Q2. Công ty thí điểm đã có `mkt_lead`, `mkt_campaign` do script W1 của marketing-pilot/02 gieo: khi gói Marketing
  1.0 ra ở W2, cài gói vào công ty đó thì gắn nguồn gốc cho thành phần đang có, hay chỉ cài vào công ty mới? Chủ:
  Đạt. Chặn: R3.1, R4.1.
- Q3. DO-62: Công ty thử nghiệm ở v2 do ai tạo, tính phí ra sao và được giữ dữ liệu gì? Chủ: người đặt yêu cầu và
  luật sư. Không đổi: phạm vi W2 của spec này; chỉ hàng W3 Đưa lên phụ thuộc câu trả lời.

## Quyết định

- 22/10/2026 (người đặt yêu cầu): D2 người dựng làm việc với mẫu theo nghiệp vụ; D4 Marketing là lát đầu và là gói
  nghiệp vụ đầu tiên. Sửa: R4.
- 23/10/2026 (người đặt yêu cầu): D11 mọi phát hành quy trình, trợ lý cần người thứ hai, nên cài gói không đưa gì lên
  Đang dùng. Sửa: R2.4.
- 23/10/2026 (agent, tạm): Mâu thuẫn nguồn: brief B6 (domain-packs 02) nói cài gói thì kích hoạt đối tượng, YC38 nói
  không kích hoạt gì; theo YC38.
- 23/10/2026 (agent, tạm): Mâu thuẫn nguồn: roadmap viết hàng W3 là "tổ chức thử nghiệm", glossary dùng "Công ty thử
  nghiệm" và tránh "tổ chức"; theo glossary.

## Danh sách ticket

Chưa có ticket: spec này không có ticket W1, và ticket được cắt khi W2 bắt đầu.
