# 05 — Phân tích bộ ba nguy hiểm và năng lực khi phát hành

Status: needs-triage
Blocked by: .claude/plans/studio/workflow-engine/issues/01-tai-lieu-workflow-va-kiem-xuat-ban.md, .claude/plans/studio/agent-lifecycle/issues/03-hop-dong-vong-doi-va-niem-phong.md, .claude/plans/studio/agent-builder/issues/02-loai-agent-va-khung-prompt.md
Area: studio
Yêu cầu: R4.1, R4.2, R4.3, R4.4, R4.5, CP12, CP13, CP14, CP15

## Mục tiêu

Khi gửi kiểm định, một module thuần đọc nhãn năng lực của loại node và loại công cụ; một đường nối đầu vào
không tin cậy, dữ liệu riêng và tác động ra ngoài phải qua node phê duyệt; agent mang cả ba nhãn phải tự
chủ ≤ A2 (spec R4; ADR-0125 (Proposed)).

## Việc cần làm

1. Module thuần `capability_analysis(definition) -> CapabilityReport`: nhãn `untrusted_source`,
   `private_data`, `external_effect` đăng ký theo loại node và loại công cụ ở composition root (bảng nhãn
   `NodeTypeSpec` của ADR-0112 (Proposed)); một loại lạ mang cả ba nhãn; chạy trên cùng `WorkflowIR` và module đồ thị
   (`reachable`, `dominators`, `paths_to`) mà bộ kiểm phát hành dùng.
2. Quy tắc quy trình: mọi đường từ `untrusted_source` qua `private_data` tới `external_effect` phải có một
   node `human.approval` chi phối node tác động; thiếu → gửi kiểm định trả 422 kèm đường vi phạm.
3. Quy tắc agent: mang cả ba nhãn thì Mức tự chủ khai ≤ A2 (công cụ `external` và `critical` luôn hỏi);
   trên A2 → 422 `capability_trifecta_autonomy` kèm hai cách sửa (hạ tự chủ, hoặc tách phần đọc nội dung
   không tin cậy khỏi phần giữ tác động); công cụ thiếu một phân loại → 422 `tool_unclassified`.
4. Lưu `capability_report` và mã băm của nó trên phiên bản (agent-lifecycle sở hữu dòng phiên bản); kết
   quả đi trong payload phê duyệt phát hành (ADR-0120 (Proposed)); không cấu hình nào hạ sàn.
5. `configs/policies/studio_risk@1.0.0.yaml`: dữ liệu gợi ý tầng rủi ro (bản ghi tầng là W2, ticket 18).
6. Case trong bộ eval bảo mật: workflow pilot bỏ node phê duyệt; đường `score → send` không qua `approve`.

## Tiêu chí chấp nhận

- [ ] R4.1: node loại lạ hay công cụ loại lạ → `capability_analysis` gán cả ba nhãn; nhãn đọc từ bảng điều
      phối ở composition root, không từ nhánh trong module.
- [ ] R4.2 (CP12): bỏ node phê duyệt khỏi workflow pilot → gửi kiểm định 422 nêu đường; đường chấm điểm
      tới gửi tin không qua node `approve` → 422 nêu đường; node phê duyệt chỉ trên một nhánh → vẫn 422.
- [ ] R4.3 (CP13): agent có cả ba nhãn ở A3 → 422 `capability_trifecta_autonomy`; gỡ kiểm → test đỏ.
- [ ] R4.4 (CP14): phiên bản dùng công cụ thiếu một trong ba phân loại → 422 `tool_unclassified`.
- [ ] R4.5 (CP15): overlay công ty bỏ node phê duyệt hay nâng Mức tự chủ trên A2 cho phiên bản bộ ba →
      phát hành từ chối.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/autonomy.py:14-33`; spec: R4.3 (thang tự chủ, hai
  sàn `critical` và `approval_policy: always`).
- ADR-0125 (Proposed) quyết 1, 2, 3, 5.

## Comments

- 2026-10-23 (agent): gộp B11-security compliance-pdpl 08 và phần phân tích năng lực của B10a-lifecycle
  agent-lifecycle 08. Phân tích chạy khi gửi kiểm định (submit), kết quả đi vào phê duyệt phát hành; bản
  ghi tầng rủi ro AI `studio.version_assessments`, tờ giải thích và taint động là W2.
