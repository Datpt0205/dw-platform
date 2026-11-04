# 28 — SDK `mcp` 2.x sau cổng MCP: client tiêm vào, chuyển hướng, năng lực khai báo, resume sau elicitation

Type: prototype
Status: ready-for-agent
Area: studio · Viết: 23/10/2026
FOG: FOG-69 `mcp-sdk`

## Câu hỏi

1. `mcp` 2.x có nhận một client httpx2 tiêm vào kèm proxy và timeout, chỉ theo chuyển hướng cùng origin, không khai năng
   lực nào khi không có callback, và chạy được với máy chủ thật đời 2025 không?
2. Khi resume sau một yêu cầu bổ sung thông tin (elicitation), lời gọi MCP đầu tiên có được phát lại dưới executor của
   nền tảng không?
3. Client Python chính thức đã hỗ trợ extension Tasks chưa?
4. Khách Marketing sẽ dùng máy chủ MCP nào, và chúng hỗ trợ CIMD, đăng ký trước hay chỉ DCR? (Chuyển sang
   ticket 02, câu 10, ngày 4/11/2026.)

## Vì sao

Tư thế bảo mật của client MCP dựa vào hành vi SDK chưa ai chạy (failure-modes #4). Một lời gọi bị phát lại ngoài
executor là tác động không qua chính sách, idempotency và audit.

## Mở khóa

- Spec: `mcp-client` (W2), `tools-and-skills`.
- ADR: 0116.
- DO: DO-46 (URL máy chủ tùy ý hay chỉ danh mục nền tảng; elicitation ở v1 hay v1.5; traceparent), DO-47.
- Liên quan ticket 21: backend ghim địa chỉ dùng chung cho stack httpx2 của cổng MCP. Không ticket W1 nào trùng: MCP
  ở W2.

## Dựng tối thiểu

Một tiến trình `mcp-gateway` nguyên mẫu dùng `mcp` 2.x với client httpx2 tiêm vào qua egress proxy; hai máy chủ MCP thật
đời 2025, và một máy chủ giả trả chuyển hướng khác origin và một elicitation; executor nguyên mẫu ghi lại mỗi lời gọi.

## Phép đo quyết định

| Đo                                          | Ngưỡng                   | Quyết định                                             |
| ------------------------------------------- | ------------------------ | ------------------------------------------------------ |
| Chuyển hướng khác origin                    | Bị từ chối               | SDK chính thức dùng được sau cổng MCP không (ADR 0116) |
| Năng lực khai báo khi không có callback     | Không khai gì            | Cấu hình client                                        |
| Lời gọi phát lại sau elicitation            | 0 lời gọi ngoài executor | Elicitation ở v1 hay v1.5 (DO-46)                      |
| Máy chủ của khách: CIMD, đăng ký trước, DCR | Danh sách theo máy chủ   | Luồng đăng ký client                                   |

## Nguồn

- Brief B8b.
- [research.md](../research.md) mục 7 (extension Tasks, client httpx2 tiêm vào: chưa kiểm).

## Việc của agent (phân loại 4/11/2026)

- Câu hỏi: câu 1-3; câu 4 đã chuyển sang ticket 02.
- Cách làm: spike dưới `tests/spike/mcp/`, venv tạm với `mcp` 2.x mới nhất ghim đúng phiên bản (không vào
  `uv.lock`: theo ADR-0116 `mcp` chỉ ở `mcp-gateway`); client httpx2 tiêm vào kèm proxy và timeout; máy chủ giả
  tại chỗ trả chuyển hướng cùng origin, khác origin và một elicitation; một máy chủ tham chiếu công khai của dự án
  Model Context Protocol chạy tại chỗ làm máy chủ thật; executor nguyên mẫu ghi lại mỗi lời gọi. Câu 3 đọc mã nguồn
  và changelog của SDK, ghi commit.
- Đầu ra: `## Answer` ở đây và một dòng vào mục Open của ADR-0116 (Accepted).
- Đạt khi: chuyển hướng khác origin bị từ chối; không khai năng lực nào khi không có callback; 0 lời gọi phát lại
  ngoài executor sau elicitation; câu 3 trả có hay không kèm dẫn chứng. Trượt một dòng thì ghi cấu hình bù, hay đề
  xuất elicitation sang v1.5 (DO-46).

## Comments

- 2026-11-04 (agent, phân loại G12, theo ủy quyền 31/10/2026): `ready-for-agent`. Chưa câu nào được đo; MCP ở W2 và `mcp` chưa có trong `uv.lock`. Câu 4 hỏi khách nên chuyển sang ticket 02; câu 1-3 chỉ cần SDK công khai và máy chủ chạy tại chỗ.
