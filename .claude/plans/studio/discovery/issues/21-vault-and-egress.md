# 21 — Kho bí mật và egress: OpenBao Transit, smokescreen, che giá trị bí mật, danh sách hậu tố công khai

Type: prototype
Status: needs-triage
Area: studio · Viết: 23/10/2026
FOG: FOG-25 `openbao`, FOG-26 `smokescreen`, FOG-27 `redaction`

## Câu hỏi

1. OpenBao 2.7.x Transit có tương đương API đã tài liệu hóa của Vault không (`datakey/plaintext`, `rewrap`,
   `deletion_allowed`); độ trễ mỗi lời gọi trên host, bộ nhớ, backend lưu trữ, mở niêm phong không cần người; ở tốc độ
   gọi của thí điểm có cần cache khóa dữ liệu không (FOG-25)?
2. smokescreen: giấy phép, dựng từ commit ghim, cỡ image, nhận diện vai không cần mTLS, dải chặn mặc định
   (100.64.0.0/10, multicast, NAT64), CONNECT tới cổng SMTP, IPv6, CONNECT với httpx2; stack httpx2 và httpcore2 của cổng
   MCP có dùng chung backend ghim địa chỉ được không (FOG-26)?
3. Nhà cung cấp dội lại token dưới những dạng mã hóa nào (JSON-escaped, URL-encoded, base64, cắt cụt), và che theo giá
   trị tốn bao nhiêu trên thân lớn; danh sách hậu tố công khai lấy từ thư viện, hay chép vào repo có làm mới (FOG-27)?

## Vì sao

Phải mở niêm phong tay sau mỗi lần khởi động thì trình kết nối nằm chết; cache thêm vào mà không đo là bản sao thứ hai
của vật liệu khóa. Tin vào mặc định của smokescreen là failure-modes #4; một chính sách địa chỉ phải đúng cho cả MCP.
Test canary chỉ kiểm giá trị thô không thể đỏ khi token bị dội lại đã mã hóa (failure-modes #3); danh sách hậu tố cũ cho
phép wildcard trên hậu tố mới.

## Mở khóa

- Spec: `connections-and-vault` (02 kho bí mật; 03 egress client và máy chủ được phép; smokescreen ở W2), `mcp-client`.
- ADR: 0115 (Open 5).
- DO: DO-47 (OpenBao là dịch vụ tầng 0 có đường mở niêm phong tự động, mạng `dw-egress` với smokescreen ghim), DO-24
  (D14: nâng host trước khi OpenBao và egress proxy ra).
- Ticket W1: `connections-and-vault/02`, `connections-and-vault/03` (P0).

## Dựng tối thiểu

OpenBao 2.7.x một node trong compose với Transit và một khóa của công ty, chạy `datakey` và `rewrap`, khởi động lại có
và không có mở niêm phong tự động; smokescreen dựng từ commit ghim, với một client httpx2 thử dải chặn, IPv6 và CONNECT
tới cổng SMTP; một bộ test canary đưa token giả qua từng dạng mã hóa vào thân phản hồi và log.

## Phép đo quyết định

| Đo                                   | Ngưỡng                                        | Quyết định                                       |
| ------------------------------------ | --------------------------------------------- | ------------------------------------------------ |
| Tương đương API Transit              | Mọi lời gọi cần dùng chạy đúng                | DO-47: nhận OpenBao làm dịch vụ tầng 0 hay không |
| Khởi động lại không có người         | Trình kết nối chạy lại không cần thao tác tay | Đường mở niêm phong                              |
| Độ trễ mỗi lời gọi ở tốc độ thí điểm | Chưa có ngưỡng; ghi p95                       | Có cache khóa dữ liệu không                      |
| Dải chặn, IPv6, CONNECT              | Bị chặn như chính sách của egress client      | Cấu hình smokescreen; MCP dùng chung backend     |
| Canary theo từng dạng mã hóa         | Mọi dạng được che; test đỏ khi bỏ một dạng    | Bộ che theo giá trị                              |

YC61: bí mật không bao giờ ở dạng rõ, kể cả khi dịch vụ khóa không sẵn sàng.

## Nguồn

- Brief B8a (F2, F3, F7, F8, F9, F14), B8b; `docs/adr/0115-tenant-credentials-vault-and-one-egress-client.md` (Open 5).
- [research.md](../research.md) mục 8 (giấy phép và dải chặn của smokescreen, Transit và độ trễ OpenBao chưa kiểm).

## Comments
