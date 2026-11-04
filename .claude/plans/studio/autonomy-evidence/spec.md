# Tự chủ kiếm bằng bằng chứng: scorecard theo loại quyết định, đề nghị nâng, tự hạ, duyệt theo ngoại lệ có lấy mẫu

Status: needs-info
Area: studio · Nhánh: `main` · Viết: 4/11/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Business Owner muốn Digital Worker (DW) bớt hỏi người ở một loại quyết định khi chính loại đó đã chứng tỏ được, và lấy lại người ngay khi nó bắt đầu sai, mà không hạ chốt nào (D19, 4/11/2026). Spec này dựng bốn việc của ADR-0129 (Proposed) trên lõi DW của spec `digital-worker`: scorecard theo từng loại quyết định, hệ thống đề nghị nâng khi đủ N lần duyệt nguyên văn mà vẫn cần hai người, tự hạ khi có tín hiệu xấu, và duyệt theo ngoại lệ có lấy mẫu ở A3, A4. Các con số để trống, đo trên DW chăm sóc lead với 200 lead giả lập.

## Hiện trạng (đã kiểm ở `9d5f06f` ngày 4/11/2026)

- Cổng ghi một dòng audit `dw.decision.auto` có `decision_class` cho mỗi quyết định DW tự làm, và mở approval `dw.decision` cho mỗi quyết định cần người (`packages/python/dw_platform/src/dw_platform/application/decision_gate.py:85-143`). Ràng buộc: hai nguồn này đã giữ mọi sự kiện bằng chứng cần; không đếm lại ở bảng thứ hai.
- Mỗi quyết định ghi người duyệt có sửa đề xuất hay không (`packages/python/dw_platform/src/dw_platform/adapters/persistence/tables.py:411-415`). Ràng buộc: "duyệt nguyên văn" là `outcome = 'approved'` và `edited = false`.
- Scorecard đếm duyệt nguyên văn, duyệt có sửa, từ chối cho cả DW, không theo loại, và không đếm quyết định Tự động (`packages/python/dw_platform/src/dw_platform/adapters/persistence/dw_autonomy_repo.py:61-131`). Thiếu: số theo loại quyết định và tỉ lệ Tự động.
- `platform.audit_events` chỉ có index trang và index theo lượt chạy, tạo `ON ONLY` rồi theo từng partition (`db/migrations/versions/fd2cd56a8f6e_paged_lists_read_through_indexes_that_.py:47-76`). Thiếu: index cho đếm `dw.decision.auto` theo DW và thời gian.
- Lần nâng chỉ do Business Owner mở, Validator hay Technical Owner quyết, người đề nghị không tự quyết (`packages/python/dw_platform/src/dw_platform/application/dw_autonomy.py:64-73`, `packages/python/dw_platform/src/dw_platform/application/dw_autonomy.py:219-246`). Ràng buộc: đề nghị của hệ thống phải về lại đúng đường này.
- Lần hạ có hiệu lực ngay, chỉ khi mức chưa đổi giữa chừng (`packages/python/dw_platform/src/dw_platform/application/dw_autonomy.py:194-213`); lần nâng duyệt sau một lần hạ thành `dw.autonomy.raise_stale` (`packages/python/dw_platform/src/dw_platform/application/dw_autonomy.py:279-304`). Ràng buộc: tự hạ dùng cùng phép ghi có điều kiện.
- Thang: A3 tự làm quyết định ngoài đảo được, chỉ A4 tự làm quyết định ngoài không đảo được, không mức nào tự làm `critical` (`packages/python/dw_kernel/src/dw_kernel/autonomy.py:58-99`). Ràng buộc: "mức cao nhất còn Hỏi" của một loại tính từ thang này, không bảng thứ hai.
- Mức hiệu lực là thấp nhất của trần, mức đã kiếm và trần công ty, đọc lúc hỏi, `A0` khi không đọc được (`packages/python/dw_platform/src/dw_platform/application/digital_workers.py:478-551`). Ràng buộc: lấy mẫu chỉ xét sau phép tính này.
- Admission theo loại approval chạy trước khi ghi quyết định; sự kiện `<type>.decided` chỉ phát cho approval không gắn lượt chạy (`packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:325-342`). Thiếu: một mục đăng ký theo loại chạy trong giao dịch của quyết định một approval gắn lượt chạy, sau khi quyết định được ghi.
- Mở trang `/approvals/<id>` ghi một biên nhận xem có `viewed_at` (`apps/web/app/approvals/[id]/page.tsx:74`, `packages/python/dw_platform/src/dw_platform/adapters/persistence/tables.py:420-433`); quyết định từ hộp duyệt không qua trang đó. Chưa rõ: một lần duyệt không đọc có nhận ra được từ biên nhận này không; mục Ngoài phạm vi.
- Cấu hình DW, kể cả trần của từng loại, cố định suốt đời DW (`packages/python/dw_platform/src/dw_platform/domain/digital_worker.py:112-117`), và gói Marketing cho `email.send` trần A2 (`configs/packs/marketing/workflows/lead_care@1.0.0.yaml:16-18`). Ràng buộc: DW chăm sóc lead hiện có không kiếm quá A2 ở gửi thư.
- Chữ Tự động / Hỏi / Chặn của một loại do `decision_mode` quyết (`packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/outline.py:218-221`). Ràng buộc: thêm trạng thái lấy mẫu ở hàm này, không ở trang.
- Chính sách nền tảng là tệp có phiên bản dưới `configs/policies` (`configs/policies/marketing_send@1.0.0.yaml:1-8`). Ràng buộc: các con số của spec này là một chính sách như vậy.
- Bộ sinh 200 lead giả lập theo hạt giống (`tests/e2e/marketing_pilot/generator.py:285-286`). Ràng buộc: lượt đo dùng đúng bộ này.
- DO-18 cho mọi tin gửi ra trong thí điểm một phê duyệt (`.claude/plans/studio/requirements.md:405`). Chưa rõ: còn đúng khi `email.send` kiếm A4 không; Q11 của requirements.

## Mục tiêu

### R1 — Scorecard theo loại quyết định

Business Owner thấy cho từng loại quyết định DW tự làm bao nhiêu và người phải sửa bao nhiêu (ADR-0129 (Proposed) quyết 1, KQ16).

- R1.1 `GET /v1/digital-workers/{id}/scorecard?days=<n>` PHẢI trả thêm, cho mỗi loại quyết định của DW, trong cùng cửa sổ của digital-worker:R7.1: số quyết định Tự động (dòng audit `dw.decision.auto` của DW có `decision_class` đó, theo `occurred_at`), số approval `dw.decision` theo `decided_at` tách bắt buộc và lấy mẫu, mỗi phần tách duyệt nguyên văn, duyệt có sửa và từ chối, tỉ lệ Tự động và tỉ lệ duyệt có sửa.
- R1.2 Tỉ lệ Tự động của một loại PHẢI bằng số Tự động chia tổng số Tự động và số approval `dw.decision` đã quyết, tỉ lệ duyệt có sửa bằng số duyệt có sửa chia số đã duyệt, và mỗi tỉ lệ là `null` khi mẫu số bằng 0.
- R1.3 Scorecard theo loại PHẢI đọc bằng ba câu gộp dưới RLS của người gọi với `workspace_id` của DW, đọc audit qua một index dẫn bằng `tenant_id`, không qua bảng đếm nào.
- R1.4 NẾU người gọi không giữ `dw.read` trong workspace của DW hay DW thuộc tenant khác, THÌ route PHẢI trả 404 `not_found` như digital-worker:R1.5 và không trả số nào.

### R2 — Đề nghị nâng khi đủ bằng chứng

Hệ thống đề nghị nâng một loại khi người đã duyệt nguyên văn đủ N lần liền ở mức hiện tại (ADR-0129 (Proposed) quyết 2, 3).

- R2.1 Lane `dw_autonomy_evidence` PHẢI coi một loại quyết định của một DW `operating` là đủ bằng chứng khi N approval `dw.decision` mới nhất của loại đó, quyết sau `level_changed_at` của loại và sau lần từ chối đề nghị gần nhất của loại, đều duyệt nguyên văn bởi Validator hay Business Owner của DW, với N đọc từ chính sách `dw_autonomy_evidence` [CAN LAM RO: Q1].
- R2.2 KHI một loại đủ bằng chứng, lane PHẢI mở một approval `dw.autonomy.raise` không gắn lượt chạy, `requested_by` là `system_actor('dw_autonomy_evidence')`, payload gồm `dw_id`, `decision_class`, `from_level`, `to_level` (mức kế tiếp), `proposed_by = 'evidence'` và số đếm cùng id các approval làm bằng chứng, cùng audit `dw.autonomy.raise_proposed` đứng tên actor của lane, trong một giao dịch.
- R2.3 NẾU mức kế tiếp cao hơn trần của loại, loại là `critical`, trần công ty đã giữ mức hiệu lực của loại dưới mức hiện tại, hay loại đã có một `dw.autonomy.raise` đang chờ, THÌ lane PHẢI không mở approval nào và không ghi gì.
- R2.4 NẾU N trong chính sách trống hay không đọc được, THÌ lane PHẢI không đề nghị nâng nào.

### R3 — Hai người cho một lần nâng do hệ thống đề nghị

Lane không phải người, nên Business Owner nhận đề nghị rồi người thứ hai duyệt như hôm nay (ADR-0128 (Proposed) quyết 5, ADR-0129 (Proposed) quyết 3, D11).

- R3.1 NẾU người quyết một `dw.autonomy.raise` có `proposed_by = 'evidence'` không phải Business Owner hiện tại của DW, đọc trong giao dịch của quyết định, THÌ `ApproveAndResumeService.decide` PHẢI trả 409 `not_eligible_decider` và không ghi quyết định nào.
- R3.2 KHI Business Owner duyệt một đề nghị `proposed_by = 'evidence'`, handler của `dw.autonomy.raise.decided` PHẢI mở một `dw.autonomy.raise` mới với `requested_by` là Business Owner đó, `proposed_by = 'business_owner'` và cùng `from_level`, `to_level`, không đổi mức, và quyết định của nó đi đúng digital-worker:R8.3 và R8.6.
- R3.3 NẾU lúc handler chạy mức đã kiếm của loại khác `from_level` hay DW đã `retired`, THÌ handler PHẢI không mở approval thứ hai và ghi `dw.autonomy.raise_stale`.
- R3.4 KHI Business Owner từ chối một đề nghị `proposed_by = 'evidence'`, bộ đếm bằng chứng của loại đó PHẢI tính lại từ thời điểm của quyết định từ chối.

### R4 — Tự hạ khi có tín hiệu xấu

Một loại đang được tự làm mà người bắt đầu từ chối hay sửa nhiều thì về lại Hỏi ngay (ADR-0129 (Proposed) quyết 4).

- R4.1 KHI một approval `dw.decision` có `sampled = true` bị từ chối, nền tảng PHẢI, trong giao dịch của quyết định, hạ `earned_level` của loại về mức cao nhất mà thang còn đòi người cho loại đó, đặt `level_changed_at`, và ghi `dw.autonomy.lowered` đứng tên `system_actor('dw_autonomy_evidence')` với `approval_id` và `decided_by` trong `details`.
- R4.2 KHI tỉ lệ duyệt có sửa của M approval `dw.decision` lấy mẫu mới nhất của một loại vượt ngưỡng của chính sách `dw_autonomy_evidence`, nền tảng PHẢI hạ như R4.1 trong giao dịch của quyết định làm vượt [CAN LAM RO: Q3].
- R4.3 NẾU mức đã kiếm đã bằng hay thấp hơn mức đích, hay đã đổi trong lúc quyết định, THÌ phép hạ PHẢI không ghi gì, và lần hạ không bao giờ nâng mức.
- R4.4 NẾU M hay ngưỡng trong chính sách trống hay không đọc được, THÌ một lần duyệt có sửa của quyết định lấy mẫu PHẢI hạ như R4.1.

### R5 — Duyệt theo ngoại lệ có lấy mẫu ở A3 và A4

Ở A3, A4 người không duyệt mọi quyết định mà duyệt ngoại lệ cộng một mẫu, trước tác động (ADR-0129 (Proposed) quyết 5).

- R5.1 KHI `DecisionGate.check` được hỏi cho một loại có mức hiệu lực A3 hay A4 mà `requires_person` sai, cổng PHẢI trả lệnh mở `dw.decision` với `sampled = true` trong payload khi `sha256(run_id, step_id, decision_class)` rơi dưới tỉ lệ lấy mẫu của chính sách [CAN LAM RO: Q2], và trả `auto` khi không.
- R5.2 NẾU tỉ lệ lấy mẫu trống hay không đọc được, hay lời gọi thiếu `run_id` hoặc `step_id`, THÌ cổng PHẢI coi quyết định là lấy mẫu.
- R5.3 Một approval `dw.decision` lấy mẫu PHẢI đi đúng đường của digital-worker:R5.3 tới R5.6 (người quyết, bản sửa, che đề xuất) và lượt chạy chờ nó trước tác động như một quyết định bắt buộc.
- R5.4 TRONG KHI một loại ở mức hiệu lực A0 tới A2, cổng PHẢI không lấy mẫu.

### R6 — Màn hình

Business Owner đọc bằng chứng theo loại trên trang DW (antd).

- R6.1 Bảng loại quyết định của `/digital-workers/[id]` PHẢI hiện thêm, mỗi loại, tỉ lệ Tự động và tỉ lệ duyệt có sửa của 30 ngày, số duyệt nguyên văn liền đã có trên N, và chữ "Tự động, lấy mẫu" khi `decision_mode` của loại là lấy mẫu.
- R6.2 Thẻ `dw.autonomy.raise` trên `/approvals` PHẢI ghi rõ "Hệ thống đề nghị theo bằng chứng" và số bằng chứng khi `proposed_by = 'evidence'`, với nút duyệt chỉ bật cho Business Owner kèm lý do bằng chữ cho người khác.
- R6.3 Thẻ `dw.decision` lấy mẫu PHẢI ghi "Quyết định lấy mẫu" để người duyệt biết DW lẽ ra tự làm.

## Trong phạm vi

- Cột `platform.dw_decision_classes.level_changed_at`; khóa `sampled` trong payload `dw.decision`, `proposed_by` và bằng chứng trong payload `dw.autonomy.raise`; index một phần trên `platform.audit_events` cho `dw.decision.auto`.
- Chính sách `configs/policies/dw_autonomy_evidence@1.0.0.yaml` (N, tỉ lệ lấy mẫu, M, ngưỡng sửa), mọi giá trị trống tới khi đo.
- Lane `dw_autonomy_evidence`; admission cho `dw.autonomy.raise` `proposed_by = 'evidence'`; nhánh mở raise thứ hai trong handler `dw.autonomy.raise.decided`; mục đăng ký sau quyết định cho `dw.decision` (R4); lấy mẫu trong `DecisionGate.check` và `decision_mode`.
- Trường mới của `GET /v1/digital-workers/{id}/scorecard`; bảng loại quyết định trên `/digital-workers/[id]`; hai thẻ trên `/approvals`.
- Lượt đo trên DW chăm sóc lead với 200 lead giả lập (Tiêu chí thành công).

## Ngoài phạm vi

| Việc                                                                                                               | Vì sao                                                                                                                                             | Chủ                       |
| ------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------- |
| Giá trị N, tỉ lệ lấy mẫu, M, ngưỡng sửa                                                                            | đo trước ở lượt đo của spec này, rồi Đạt đặt (ADR-0129 (Proposed) quyết 7)                                                                         | Đạt                       |
| Đổi trần của một DW đang chạy, hay trần `email.send` của gói Marketing                                             | trần cố định theo cấu hình DW; ADR-0129 (Proposed) mục Open 1                                                                                      | Đạt, rồi `digital-worker` |
| Loại khỏi bằng chứng một lần duyệt không đọc                                                                       | biên nhận xem chỉ ghi khi mở trang một approval, quyết từ hộp duyệt không có, và chưa có ngưỡng; đối trọng của KQ2; ADR-0129 (Proposed) mục Open 2 | đợt sau                   |
| DO-18 khi `email.send` kiếm A4                                                                                     | Q11 của `requirements.md`                                                                                                                          | Đạt                       |
| Tín hiệu xấu từ kết quả nghiệp vụ (hủy đăng ký, khiếu nại sau thư)                                                 | cần sự kiện kết quả của leadcare, chưa có                                                                                                          | đợt sau                   |
| Đổi ở `digital-worker`: R7.1 nói scorecard chỉ có số của cả DW                                                     | R1.1 thêm số theo loại vào cùng route; R7.1 cần dẫn sang R1.1                                                                                      | `digital-worker`          |
| Đổi ở `digital-worker`: R8.2 và R8.3 chỉ biết lần nâng do Business Owner mở                                        | R2.2, R3.1, R3.2 thêm đề nghị của lane với admission riêng; R8.2 cần nói "Business Owner hay lane theo autonomy-evidence:R2.2"                     | `digital-worker`          |
| Đổi ở `digital-worker`: R8.1 chỉ cho Business Owner, Technical Owner hạ                                            | R4.1, R4.2 thêm lần hạ theo luật, đứng tên actor của lane                                                                                          | `digital-worker`          |
| Đổi ở `digital-worker`: R5.2 nói `requires_person` sai thì luôn `auto`                                             | R5.1 lấy mẫu ở A3, A4                                                                                                                              | `digital-worker`          |
| Đổi ở `digital-worker`: R9.2 có ba chữ Tự động, Hỏi, Chặn                                                          | R6.1 thêm "Tự động, lấy mẫu"                                                                                                                       | `digital-worker`          |
| Đổi ở `digital-worker`: Dữ liệu của `platform.dw_decision_classes` chưa có `level_changed_at`                      | R2.1, R4.1 cần thời điểm đổi mức                                                                                                                   | `digital-worker`          |
| Đổi ở `digital-worker`: Ngoài phạm vi ghi "KPI có đích và mức dịch vụ của DW: đợt sau" mà không nhắc tỉ lệ Tự động | KQ16 là thước đo của D19                                                                                                                           | `digital-worker`          |

## Dữ liệu

- `platform.dw_decision_classes`: thêm `level_changed_at timestamptz NOT NULL DEFAULT now()`, đặt bởi mọi phép đổi `earned_level` (hạ tay, nâng, hạ theo luật) trong cùng câu lệnh.
- `platform.approval_requests.payload` của `dw.decision`: thêm `sampled boolean`, chỉ cổng ghi; thiếu khóa đọc là `false` chỉ cho approval mở trước migration, vì mọi approval mới đều mang khóa (test: approval mới thiếu `sampled` là lỗi).
- `platform.approval_requests.payload` của `dw.autonomy.raise`: thêm `proposed_by` trong `evidence, business_owner` và `evidence` gồm số đếm và id approval; chỉ định danh và mức, như ghi chú ở `dw_autonomy.py` (hộp duyệt hiện payload cho người giữ `approvals.read`).
- Index `platform.audit_events (tenant_id, resource_id, occurred_at) WHERE action = 'dw.decision.auto'`, tạo `ON ONLY` rồi theo từng partition như `fd2cd56a8f6e`; index trên `platform.approval_requests` cho đếm `dw.decision` theo `payload->>'dw_id'`, `payload->>'decision_class'`, `decided_at`, dẫn bằng `tenant_id`.
- Chính sách `dw_autonomy_evidence@1.0.0`: `raise_after_as_is` (N), `sample_rate` (0-1), `edit_window` (M), `edit_rate_limit` (0-1); mọi giá trị `null` trong bản đầu; công ty chỉ siết qua `TenantOverlay` (N lớn hơn, tỉ lệ lấy mẫu lớn hơn, ngưỡng sửa nhỏ hơn; ADR-0110 (Accepted)).

## API

| Route                                                                                  | Scope và chức năng                          | Lỗi chính                                |
| -------------------------------------------------------------------------------------- | ------------------------------------------- | ---------------------------------------- |
| `GET /v1/digital-workers/{id}/scorecard?days=` (thêm trường)                           | `dw.read`                                   | 404 `not_found`, 422 `days_out_of_range` |
| `POST /v1/approvals/{id}/decisions` cho `dw.autonomy.raise` `proposed_by = 'evidence'` | `approvals.decide` và Business Owner của DW | 409 `not_eligible_decider`               |

## Màn hình

R6, trên các trang của digital-worker:R9 (antd, chữ từ `apps/web/lib/digital-workers/labels.ts`). Tỉ lệ `null` hiện "Chưa có quyết định", không phải 0%.

## Kiểm soát

| #     | Kiểm soát                                                                         | Yêu cầu    | Test âm                                                                                                                                                     |
| ----- | --------------------------------------------------------------------------------- | ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| AEV1  | scorecard theo loại không đọc chéo tenant hay workspace                           | R1.3, R1.4 | tenant B gọi scorecard DW của tenant A: 404; DW của A ở workspace khác cùng tenant có audit `dw.decision.auto`: không vào số của DW này                     |
| AEV2  | tỉ lệ đếm từ dữ liệu, mẫu số 0 là `null`                                          | R1.2       | DW không quyết định nào: hai tỉ lệ `null`; 3 Tự động, 1 bắt buộc duyệt nguyên văn: tỉ lệ Tự động 0,75, tỉ lệ sửa 0                                          |
| AEV3  | đề nghị chỉ khi N quyết định liền nhất đều nguyên văn, sau lần đổi mức            | R2.1       | N−1 nguyên văn rồi một duyệt có sửa rồi N−1 nguyên văn: không đề nghị; N nguyên văn trước `level_changed_at`: không đề nghị                                 |
| AEV4  | quyết định của người ngoài Validator, Business Owner không là bằng chứng          | R2.1       | N lần duyệt nguyên văn ghi tay bằng một người khác: không đề nghị                                                                                           |
| AEV5  | không đề nghị quá trần, cho `critical`, khi trần công ty đã giữ, hay khi đang chờ | R2.3       | mức kế tiếp vượt trần, loại `critical`, trần công ty A1 với mức A2, một raise đang chờ: đếm approval không đổi                                              |
| AEV6  | chính sách trống thì không đề nghị                                                | R2.4       | `raise_after_as_is: null` với 1.000 lần nguyên văn: không approval nào                                                                                      |
| AEV7  | đề nghị của lane chỉ Business Owner nhận                                          | R3.1       | Validator, Technical Owner và người ngoài DW giữ `approvals.decide` quyết đề nghị `evidence`: 409, không dòng quyết định                                    |
| AEV8  | Business Owner nhận đề nghị không đổi mức; người thứ hai vẫn cần                  | R3.2       | BO duyệt đề nghị `evidence`: mức không đổi, một raise mới `requested_by` = BO; BO tự quyết raise mới đó: 409; Validator duyệt: mức tăng một bậc             |
| AEV9  | đề nghị cũ không mở raise thứ hai                                                 | R3.3       | hạ mức sau khi lane đề nghị rồi BO duyệt: không raise thứ hai, có `dw.autonomy.raise_stale`                                                                 |
| AEV10 | từ chối đề nghị đặt lại bộ đếm                                                    | R3.4       | BO từ chối: lane chạy lại với cùng N quyết định cũ: không đề nghị mới                                                                                       |
| AEV11 | mẫu bị từ chối hạ mức trong giao dịch của quyết định                              | R4.1       | từ chối mẫu của loại ngoài đảo được ở A3: mức A2 ngay sau commit, lượt khác của DW hỏi cổng sau đó: `requires_person` đúng; rollback quyết định: mức vẫn A3 |
| AEV12 | hạ về mức cao nhất còn Hỏi, không thấp hơn, không bao giờ nâng                    | R4.1, R4.3 | loại ngoài không đảo được ở A4 bị từ chối mẫu: A3, không A2; mức đã A2 khi quyết: không đổi, không audit                                                    |
| AEV13 | lần hạ theo luật đứng tên lane, không đứng tên người                              | R4.1       | audit `dw.autonomy.lowered` có `actor_id` = `system_actor('dw_autonomy_evidence')`, `details.decided_by` là người từ chối                                   |
| AEV14 | ngưỡng sửa trống thì một lần sửa mẫu hạ mức                                       | R4.2, R4.4 | `edit_rate_limit: null`, một mẫu duyệt có sửa: hạ; với ngưỡng đặt, tỉ lệ dưới ngưỡng: không hạ                                                              |
| AEV15 | lấy mẫu tất định theo lượt, bước, loại, không do model chọn                       | R5.1       | cùng `run_id`, `step_id`, loại hỏi hai lần: cùng câu trả lời; đổi đề xuất hay `reason`: câu trả lời không đổi                                               |
| AEV16 | tỉ lệ lấy mẫu trống hay thiếu khóa lượt thì hỏi người                             | R5.2       | `sample_rate: null` ở A4: mọi quyết định mở `dw.decision` `sampled = true`; gọi không `step_id`: mở approval                                                |
| AEV17 | quyết định lấy mẫu chờ trước tác động và đi đúng cửa duyệt                        | R5.3       | mẫu `email.send` ở A4: công cụ gửi không chạy trước quyết định; người ngoài Validator, BO quyết: 409                                                        |
| AEV18 | không lấy mẫu dưới A3                                                             | R5.4       | loại nội bộ ở A2 với `sample_rate: 1`: `auto`, không approval                                                                                               |
| AEV19 | `critical` không bao giờ tự làm, kể cả qua bằng chứng                             | R2.3, R5.1 | loại `critical` ở A4 với `sample_rate: 0`: vẫn `dw.decision` bắt buộc; 1.000 nguyên văn: không đề nghị                                                      |
| AEV20 | nút nhận đề nghị chỉ bật cho Business Owner, máy chủ vẫn từ chối                  | R6.2, R3.1 | trang render cho Validator: nút tắt kèm lý do; gọi thẳng API: 409                                                                                           |

## Tiêu chí thành công

- Góp vào KQ16: lượt đo chạy DW chăm sóc lead trên 200 lead của `tests/e2e/marketing_pilot/generator.py` (hạt giống của marketing-pilot/01), mọi đề xuất do một người thật quyết (trưởng Marketing hay người thay được Đạt chỉ định, không script), ghi theo loại quyết định số duyệt nguyên văn, có sửa, từ chối và thời gian quyết; từ đó Đạt đặt N, tỉ lệ lấy mẫu, M và ngưỡng sửa (Q1-Q3) và ghi số vào chính sách.

## Tiêu chí xong

- Mọi tiêu chí R có test; mọi kiểm soát có test âm đã thấy đỏ khi gỡ kiểm soát (`scripts/mutate.py`).
- `make test-unit test-contract test-architecture` xanh, integration của `dw_platform`, `dw_agent_runtime`, `apps/api`, `apps/worker` xanh; `test_rls_coverage.py`, `test_privileges.py` xanh khi có migration.

## Phụ thuộc

- ADR-0129 (Proposed), ADR-0128 (Proposed) quyết 3, 5, 8, 9; ADR-0011 (Accepted) cho actor của lane; ADR-0110 (Accepted) cho chính sách chỉ siết.
- `DecisionGate.check`, `DecisionAutonomy`, `DwAutonomyService`, `RaiseSettler`, `ApproveAndResumeService` với `type_admissions`, digital-worker:R5.3, digital-worker:R5.6, digital-worker:R7.1, digital-worker:R8.3, digital-worker:R8.4, digital-worker:R8.6; `dw_kernel.autonomy.requires_person` và `effect_rung`.
- Kiểm lại khi: ADR-0128 (Proposed) hay ADR-0129 (Proposed) đổi trạng thái → cả spec; `digital-worker` nhận các dòng "Đổi ở `digital-worker`" của Ngoài phạm vi → R1.1, R2.2, R4.1, R5.1; Q11 được trả lời → R5; usage-and-limits chuyển nguồn chi phí → không đổi spec này; trần của DW đổi được → R2.3.

## Câu hỏi còn mở

- Q1. N, số lần duyệt nguyên văn liền để lane đề nghị nâng một loại quyết định, là bao nhiêu? Chủ: Đạt, sau lượt đo của Tiêu chí thành công. Chặn: R2.1.
- Q2. Tỉ lệ lấy mẫu ở A3 và A4 là bao nhiêu, một tỉ lệ cho mọi loại hay theo bậc hiệu ứng? Chủ: Đạt, sau lượt đo. Chặn: R5.1.
- Q3. M và ngưỡng tỉ lệ duyệt có sửa để tự hạ là bao nhiêu? Chủ: Đạt, sau lượt đo. Chặn: R4.2.

## Quyết định

- 4/11/2026 (Đạt): D19, và bốn việc của spec này: scorecard theo loại, hệ thống mở `dw.autonomy.raise` khi đủ N lần duyệt nguyên văn mà vẫn cần người thứ hai, tự hạ khi có tín hiệu xấu, duyệt theo ngoại lệ có lấy mẫu ở A3, A4; N và tỉ lệ lấy mẫu đo trên lead-care với 200 lead giả lập; chưa cắt ticket; không sửa `digital-worker/spec.md`.
- 4/11/2026 (agent, tạm): Hai người cho lần nâng của lane là Business Owner nhận đề nghị rồi Validator hay Technical Owner duyệt, bằng hai approval `dw.autonomy.raise` nối nhau qua handler `.decided`, vì cửa duyệt chỉ nhận một quyết định mỗi approval và lane không là người (D11). Sửa: R3. Nếu sai thì: một approval do Validator hay Technical Owner quyết là đủ, R3.1 và R3.2 bỏ, AEV7 và AEV8 đổi.
- 4/11/2026 (agent, tạm): Tín hiệu xấu là từ chối một quyết định lấy mẫu và tỉ lệ sửa mẫu vượt ngưỡng; hạ về mức cao nhất còn Hỏi, không một bậc, vì một bậc dưới A4 vẫn tự làm loại ngoài đảo được. Sửa: R4. Nếu sai thì: hạ một bậc, AEV12 đổi.
- 4/11/2026 (agent, tạm): Lấy mẫu trước tác động cho mọi loại, kể cả loại đảo được, để cổng giữ một câu trả lời. Sửa: R5.3. Nếu sai thì: loại đảo được lấy mẫu sau tác động và R5.3 tách hai đường.
- 4/11/2026 (agent, tạm): Bằng chứng đọc từ audit và approval qua index, không bảng đếm (`failure-modes.md` #2). Nếu sai thì: P95 của scorecard vượt ngân sách của `latency.md` ở lượt đo, thì thêm một bảng gộp theo ngày có test so với audit.
- 4/11/2026 (agent, tạm): Chính sách trống thì đóng: không đề nghị, lấy mẫu mọi quyết định A3, A4, một lần sửa mẫu là hạ (`failure-modes.md` #7). Nếu sai thì: tính năng tắt khi trống, và loại đang A3 tự làm như hôm nay.

## Danh sách ticket
