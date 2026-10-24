# 15 — Agent của tenant trên runner hiện có: bản deepagents, ghép middleware, host graph đã biên dịch

Type: prototype
Status: needs-triage
Area: studio · Viết: 23/10/2026
FOG: FOG-34 `deepagents-pin`, FOG-35 `middleware-compose`, FOG-36 `agent-hosting`

## Câu hỏi

1. Bản deepagents chính xác nào (0.7.23 trở lên; repo khóa 0.7.15 ở `uv.lock:680`) và những gì đi theo: langchain
   1.4.1 lên 1.4.6, langchain-core 1.6.3 lên 1.6.12, langsmith 0.12 lên 0.14 (FOG-34)?
2. Stack middleware của agent con có còn chỉ dựng từ `sub_agent_spec`, để middleware kiểm soát lượt chạy tới được agent
   liên kết không; `CompiledSubAgent` có giữ `recursion_limit` 9999 không, và gắn lại có sửa được không (FOG-34)?
3. Wrapper công cụ của `FilesystemMiddleware` có để `GraphBubbleUp` (interrupt phê duyệt) đi qua không; disclosure
   `include_tools` và các middleware Offered, Scoped, chọn công cụ của nền tảng có ghép đúng theo cả hai thứ tự không;
   `ToolCallLimitMiddleware` và `ModelCallLimitMiddleware` làm gì với lời gọi công cụ song song (FOG-35)?
4. Runner có host được một graph `create_agent` đã biên dịch với checkpointer SQL, resume sạch sau khi lượt chạy bị
   dừng ở middleware hay executor mà không chạy lại lời gọi công cụ đã xong không; thời gian biên dịch, bộ nhớ và cỡ
   LRU theo (tenant, phiên bản, mã băm đã ghim) mà worker trên host 2 vCPU chịu được, khi mỗi nội dung của một bản Nháp
   đem chạy mô phỏng là một mục riêng (FOG-36)?

## Vì sao

Kỹ năng, công tắc tắt khẩn cấp và trần số bước dựa vào bên trong thư viện đã từng đổi (failure-modes #4). Một interrupt
phê duyệt bị wrapper nuốt là cổng duyệt bị vượt (failure-modes #5). Câu 4 quyết đóng băng có dừng rồi tiếp tục được
không, và đặt trần cho cache biên dịch (failure-modes #6).

## Mở khóa

- Spec: `agent-builder` (01, 03), `agent-lifecycle` (01, công tắc), `tools-and-skills` (02, kỹ năng),
  `usage-and-limits` (04, trần số bước), `workflow-engine` (bước agent).
- ADR: 0116 (Open 5), 0117, 0120.
- DO: DO-28 (Đạt chốt 23/10/2026, phương án C: đóng băng hủy lượt đang chạy ở cửa kế tiếp, từ chối ngay lượt tương
  tác và giữ lượt do trình kích hoạt tới khi gỡ; đóng băng tiếp tục được ở W3, `requirements.md` mục Không làm), DO-45.
- Ticket W1: `agent-builder/01`, `agent-lifecycle/01` (P0).

## Dựng tối thiểu

Một agent `create_agent` với hai công cụ giả (một cần phê duyệt) và một agent liên kết; stack middleware của nền tảng ở
hai thứ tự; chạy trong runner hiện có với checkpointer SQL; nâng deepagents trên nhánh nháp rồi chạy lại bộ test agent.

## Phép đo quyết định

| Đo                                             | Ngưỡng                                                                                   | Quyết định                                        |
| ---------------------------------------------- | ---------------------------------------------------------------------------------------- | ------------------------------------------------- |
| Interrupt phê duyệt ở cả hai thứ tự middleware | Luôn tới runner; test đỏ khi wrapper nuốt nó                                             | Thứ tự middleware cố định                         |
| Lời gọi công cụ chạy lại sau resume            | 0                                                                                        | Đóng băng dừng rồi tiếp tục (W3) có khả thi không |
| Middleware kiểm soát trong agent liên kết      | Có mặt ở mọi lời gọi                                                                     | Bản deepagents và cách gắn                        |
| Biên dịch: thời gian, RSS mỗi graph            | Ghi số dưới giới hạn worker 1 CPU / 1 GB (`infra/compose/docker-compose.prod.yml:40-41`) | Cỡ LRU theo (tenant, phiên bản, mã băm đã ghim)   |

## Nguồn

- Brief B8b, B9, B10a, B10b; `uv.lock:1974`, `uv.lock:2002`, `uv.lock:2133` (langchain, langchain-core, langsmith).
- [research.md](../research.md) mục 4 và 6 (host graph `create_agent`, `FilesystemMiddleware`, bản deepagents chưa
  kiểm).

## Comments

- 2026-10-24 (agent, tạm): câu 4 và dòng biên dịch của Phép đo quyết định đo cache graph agent theo khóa
  `(tenant_id, agent_version_id, pinned_hash)`, vì Kiểm định thử nhận bản Nháp của agent, và một bản Nháp chỉ được
  biên dịch dưới mã băm tạm mà bản kê của lượt `simulate` ghim (ADR-0117 (Accepted) quyết 5, ADR-0109 (Accepted)
  quyết 6), nên mỗi nội dung nháp đem chạy mô phỏng là một mục cache riêng; quy trình đã khóa cache như vậy
  (ADR-0112 (Accepted) quyết 4). Sửa: Câu hỏi (câu 4), Phép đo quyết định (dòng biên dịch). Nếu sai thì: bản Nháp
  của agent không chạy được, cache giữ khóa `(tenant_id, agent_version_id)`, và câu 4 đo cỡ LRU theo (tenant, phiên
  bản) như trước.
