# 05 — Phân tích bộ ba nguy hiểm và năng lực khi gửi kiểm định

Status: needs-triage
Blocked by: 03, .claude/plans/studio/workflow-engine/issues/01-tai-lieu-workflow-va-kiem-xuat-ban.md, .claude/plans/studio/agent-lifecycle/issues/03-hop-dong-vong-doi-va-niem-phong.md, .claude/plans/studio/agent-builder/issues/02-loai-agent-va-khung-prompt.md
Area: studio
Yêu cầu: R2.6, R4.1, R4.2, R4.3, R4.4, R4.5, R4.6, CP6, CP12, CP13, CP14, CP15

## Mục tiêu

Khi gửi kiểm định, một module thuần đọc nhãn năng lực của loại node và loại công cụ; một đường nối đầu vào
không tin cậy, dữ liệu riêng và tác động ra ngoài phải qua node phê duyệt; agent mang cả ba nhãn phải tự
chủ ≤ A2; trường dữ liệu cá nhân không vào prompt trên tuyến ra nước ngoài; kết quả ghi vào
`studio.version_assessments` để lane `studio_gate` đọc (spec R2.6, R4; ADR-0125 (Accepted)).

## Việc cần làm

1. Module thuần `capability_analysis(definition)` trả một kết quả Phân tích năng lực (một dòng
   `studio.version_assessments`): nhãn `untrusted_source`, `private_data`, `external_effect` đăng ký theo loại
   node và loại công cụ ở composition root (bảng nhãn `NodeTypeSpec` của ADR-0112 (Accepted)); một loại lạ
   mang cả ba nhãn; chạy trên cùng `WorkflowIR` và module đồ thị (`reachable`, `dominators`, `paths_to`) mà
   bộ kiểm phát hành dùng. Đăng ký nó vào bảng kiểm theo loại lúc gửi kiểm định của agent-lifecycle/03
   (agent-lifecycle:R2.7).
2. Quy tắc quy trình: mọi đường từ `untrusted_source` qua `private_data` tới `external_effect` phải có một
   node `human.approval` chi phối node tác động; thiếu → gửi kiểm định trả 422 `trifecta_path_unapproved`
   kèm đường vi phạm.
3. Quy tắc agent: mang cả ba nhãn thì Mức tự chủ khai ≤ A2 (công cụ `external` và `critical` luôn hỏi);
   trên A2 → 422 `capability_trifecta_autonomy` kèm hai cách sửa (hạ tự chủ, hoặc tách phần đọc nội dung
   không tin cậy khỏi phần giữ tác động); công cụ thiếu một phân loại → 422 `tool_unclassified`.
4. Migration (id hex ngẫu nhiên) tạo `studio.version_assessments` (một dòng mỗi phiên bản và Mã băm định
   nghĩa; tín hiệu, đường vi phạm, kết luận, phiên bản bộ phân tích; RLS theo công ty; `dw_app` SELECT,
   INSERT); ghi kết quả trong giao dịch gửi kiểm định, không thêm cột lên dòng phiên bản; kết quả đi trong
   payload phê duyệt phát hành (ADR-0120 (Accepted)); không cấu hình nào hạ sàn.
5. Kiểm R2.6 trong cùng phân tích: một đường đưa giá trị trường dữ liệu cá nhân vào prompt khi
   `effective_route_class` của ticket 03 là ra nước ngoài → 422 `residency_refused` kèm đường (MP7).
6. `configs/policies/studio_risk@1.0.0.yaml`: dữ liệu gợi ý tầng rủi ro (cột tầng trên
   `studio.version_assessments` là W2, ticket 18).
7. Case trong bộ eval bảo mật: workflow pilot bỏ node phê duyệt; đường `score → send` không qua `approve`.

## Tiêu chí chấp nhận

- [ ] R4.1: node loại lạ hay công cụ loại lạ → `capability_analysis` gán cả ba nhãn; nhãn đọc từ bảng điều
      phối ở composition root, không từ nhánh trong module.
- [ ] R4.2 (CP12): bỏ node phê duyệt khỏi workflow pilot → gửi kiểm định 422 `trifecta_path_unapproved` nêu
      đường; đường chấm điểm tới gửi tin không qua node `approve` → 422 nêu đường; node phê duyệt chỉ trên một
      nhánh → vẫn 422.
- [ ] R4.3 (CP13): agent có cả ba nhãn ở A3 → 422 `capability_trifecta_autonomy`; gỡ kiểm → test đỏ.
- [ ] R4.4 (CP14): phiên bản dùng công cụ thiếu một trong ba phân loại → 422 `tool_unclassified`.
- [ ] R4.5 (CP15): overlay công ty bỏ node phê duyệt hay nâng Mức tự chủ trên A2 cho phiên bản bộ ba → gửi
      kiểm định 422, phiên bản vẫn Nháp.
- [ ] R4.6: gửi kiểm định một quy trình hợp lệ → đúng một dòng `studio.version_assessments` cho Mã băm định
      nghĩa của phiên bản, ghi trong cùng giao dịch; rollback giao dịch gửi kiểm định → không dòng nào.
- [ ] R2.6 (CP6): gắn `full_name` vào prompt trên tuyến `cross_border_full` → gửi kiểm định 422
      `residency_refused` kèm đường, phiên bản vẫn Nháp; gỡ kiểm → test đỏ.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/autonomy.py:14-33`; spec: R4.3 (thang tự chủ, hai
  sàn `critical` và `approval_policy: always`).
- ADR-0125 (Accepted) quyết 1, 2, 3, 5.

## Comments

- 2026-10-23 (agent): gộp B11-security compliance-pdpl 08 và phần phân tích năng lực của B10a-lifecycle
  agent-lifecycle 08. Phân tích chạy khi gửi kiểm định (submit), kết quả đi vào phê duyệt phát hành; bản
  ghi tầng rủi ro AI `studio.version_assessments`, tờ giải thích và taint động là W2.
- 2026-10-23 (agent): áp quyết định của Đạt ngày 23/10/2026 (B:agent-lifecycle:R6.1~compliance-pdpl:R4.2 (a),
  ADR-0125 (Accepted)): tiêu đề "khi gửi kiểm định"; kết quả ghi vào `studio.version_assessments` do ticket
  này tạo (cột tầng rủi ro là W2), không cột `capability_report`; tên theo glossary; đăng ký qua bảng kiểm
  theo loại của agent-lifecycle/03; kiểm R2.6 chuyển từ ticket 03 về đây nên chờ ticket 03.
