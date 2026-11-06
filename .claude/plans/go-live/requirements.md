# Yêu cầu cấp cao: Go-live

Status: needs-triage
Area: go-live · Viết: 6/11/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

## Mục đích tài liệu

Tài liệu này quyết định đích của nền tảng từ nay: chạy trên production thật để doanh nghiệp thuê bao và dùng, không dừng ở test hay demo. Nó nói cần gì và vì sao, cho các spec của area `go-live` và cho thứ tự hàng đợi ở `.claude/plans/studio.md`. Nó không quyết định cách làm, và không thay yêu cầu của Studio ở `.claude/plans/studio/requirements.md`.

## Vấn đề

Đạt, 6/11/2026: "ưu tiên hàng đầu là triển khai được lên production thật để khách vào dùng luôn chứ không dừng lại ở test hay demo", và doanh nghiệp "vào thuê subscription cũng như dựng workflow DW chạy thật".

Kế hoạch tới hôm nay dừng trước đích đó. Lối ra W1a của Studio là bộ kiểm thử trên profile `test` với model giả và SMTP giả. Lối ra W1b là uat với lead giả lập. W2 ("v1 GA") chưa cắt ticket nào. Không dòng nào của roadmap Studio nói về tài khoản của khách, thu tiền hay vận hành hằng ngày.

Đo trên code ngày 6/11/2026, một doanh nghiệp hôm nay không vào dùng được, vì năm chỗ độc lập nhau:

- Người được mời không có cách nào có mật khẩu.
- Digital Worker không gửi được thư thật: công cụ của gói từ chối mọi lần gửi trên môi trường triển khai, không tạo được Kết nối, và không có kho khóa.
- Lệnh triển khai production không có lớp HTTPS.
- Mọi tuyến model thật ở nước ngoài, trong khi mặc định của công ty là chỉ trong Việt Nam.
- Không có chỗ nào ghi một công ty đã trả tiền tới ngày nào.

Cái giá của việc không làm: làm xong hết ticket vẫn không có khách nào dùng được, không có đồng doanh thu nào, và mọi giả định về thị trường vẫn chưa được kiểm.

## Người dùng

- Chủ sở hữu công ty khách: người ký hợp đồng và trả tiền; hôm nay không vào được, không thấy gói hay hạn dùng.
- Thành viên công ty khách: được mời nhưng không nhận được gì và không đăng nhập được.
- Người vận hành (`platform_operator`): đội của Đạt; tạo công ty, xem hợp đồng và hạn, đóng băng; hôm nay phải vào bảng quản trị Keycloak qua đường hầm SSH để làm việc mà khách phải tự làm được.
- Người trực sự cố: chưa có ai, chưa có kênh báo, chưa có sổ tay xử lý.
- Chủ thể dữ liệu (lead): không đăng nhập; là người luật bảo vệ.

## Yêu cầu

- YC1 Nền tảng PHẢI phục vụ khách trên một môi trường production có tên miền thật và chứng chỉ hợp lệ.
- YC2 KHI người vận hành phát hành một bản, quá trình triển khai PHẢI kết thúc bằng bản mới chạy khỏe hoặc bản cũ vẫn chạy.
- YC3 NẾU bản mới không khỏe, THÌ người vận hành PHẢI quay về được bản trước trong 30 phút.
- YC4 Công ty khách PHẢI lưu được bí mật kết nối của mình trên production.
- YC20 Digital Worker PHẢI gửi và đọc được thư thật qua hộp thư của công ty trên production.
- YC5 Bản lên production PHẢI đã chạy khỏe trên uat trước đó.
- YC6 KHI người vận hành tạo công ty hay quản trị viên mời người, người được mời PHẢI nhận được thư để tự đặt mật khẩu.
- YC7 KHI người dùng quên mật khẩu, người dùng PHẢI tự đặt lại được.
- YC8 NẾU một người đăng nhập mà chưa được mời vào công ty nào, THÌ nền tảng PHẢI không cho thấy dữ liệu nào của công ty nào.
- YC9 Người vận hành PHẢI ghi được mỗi công ty đang ở gói nào, kỳ nào, giá nào.
- YC10 TRONG KHI kỳ thuê bao của một công ty đã hết quá hạn cho phép, nền tảng PHẢI không bắt đầu lượt chạy mới của công ty đó và không xóa dữ liệu nào của nó.
- YC11 Chủ sở hữu công ty PHẢI thấy được gói, hạn dùng và mức đã dùng so với trần của gói.
- YC12 Mỗi gói PHẢI có trần chi phí AI theo tháng.
- YC13 Người vận hành PHẢI lấy được bảng đối soát theo tháng của mỗi công ty để lập hóa đơn.
- YC14 Dữ liệu của mọi công ty PHẢI được sao lưu tự động ra ngoài host production mỗi ngày.
- YC15 KHI host production mất hẳn, người vận hành PHẢI dựng lại được dịch vụ trên host mới từ bản sao lưu.
- YC16 KHI dịch vụ của khách ngừng, người trực PHẢI nhận được cảnh báo trong 5 phút.
- YC17 NẾU công ty chưa qua cổng dữ liệu thật, THÌ nền tảng PHẢI từ chối nhận dữ liệu cá nhân thật của công ty đó.
- YC18 KHI chủ sở hữu vào lần đầu, nền tảng PHẢI ghi lại phiên bản điều khoản và DPA họ đã chấp nhận.
- YC19 Web PHẢI hiện một địa chỉ liên hệ để khách báo lỗi.

## Không làm

- Tự đăng ký và cổng thanh toán tự động: chỉ đáng làm khi đã có người trả tiền; khách đầu ký hợp đồng và trả tay; đợt sau, khi có từ năm khách.
- Hóa đơn điện tử tích hợp thẳng: bảng đối soát cho kế toán lập tay là đủ cho khách đầu; đợt sau.
- Nhiều vùng, tự co giãn, Kubernetes: một host compose có sao lưu ngoài host là đủ tới khi số khách đòi khác; đợt sau.
- Trợ lý Marketing và lối ra W1b như điều kiện của production: production không chờ chúng (Quyết định 6/11/2026).
- Chạy dữ liệu cá nhân thật khi chưa có ý kiến luật sư và DPA: một thất bại kể cả khi chạy được.

## Kết quả đo được

| #   | Kết quả                                           | Đơn vị        | Hiện nay  | Đích    | Đối trọng                         | Cách đo                               |
| --- | ------------------------------------------------- | ------------- | --------- | ------- | --------------------------------- | ------------------------------------- |
| KQ1 | Công ty khách đang trả tiền trên production       | công ty       | 0         | 1       | Không sự cố đọc chéo công ty nào  | Bảng thuê bao                         |
| KQ2 | Từ lúc tạo công ty tới lần đăng nhập đầu của chủ  | phút          | chưa biết | dưới 30 | Không thư mời nào vào nhầm người  | Hai mốc trong audit                   |
| KQ3 | Thời gian dịch vụ sẵn sàng theo tháng             | %             | chưa biết | 99,5    | Số lần triển khai không giảm      | Giám sát từ ngoài host                |
| KQ4 | Thời gian dựng lại trên host mới                  | giờ           | chưa biết | dưới 4  | Mất dữ liệu dưới 24 giờ           | Diễn tập từ số không, ghi vào runbook |
| KQ5 | Chi phí vận hành và AI mỗi công ty so với giá gói | % của giá gói | chưa biết | dưới 60 | Trần chi phí không chặn khách oan | Sổ sử dụng cộng hóa đơn hạ tầng       |

## Bằng chứng

- Người được mời không có đường có mật khẩu: realm tắt tự đăng ký và quên mật khẩu, không có máy chủ thư, ứng dụng không gọi quản trị Keycloak. Nguồn: `infra/keycloak/dw-realm.json`, `customer-access/spec.md`. Tin cậy: cao.
- Đường gửi thư của DW bị chặn ở ba lớp độc lập: từ chối `send_sink_only`, danh mục kết nối rỗng, chưa có kho khóa. Nguồn: `real-mail/spec.md`, kiểm chứng ngày 6/11/2026. Tin cậy: cao.
- Mọi tuyến model thật khai nước ngoài, và lời khai đó chưa đo. Nguồn: `configs/models/gateway.yaml`. Tin cậy: vừa.
- Lát Digital Worker đã chạy thật một lần với model thật và màn hình. Nguồn: `docs/demo/digital-worker/`, leadcare/02. Tin cậy: vừa (chưa chạy lại sau 18 ticket ngày 6/11/2026).
- Luật buộc có cơ sở xử lý dữ liệu cá nhân trước khi bán ở Việt Nam. Nguồn: Luật 91/2025/QH15, Nghị định 356/2025/NĐ-CP theo `.claude/plans/studio/requirements.md`. Tin cậy: vừa (chờ luật sư).

## Bằng chứng ngược

- Chưa có khách nào đã nói sẽ trả tiền, nên production có thể chạy không người dùng. Nguồn: `.claude/plans/studio/requirements.md`, Câu hỏi hoài nghi. Tin cậy: cao.
- Host hôm nay 2 vCPU / 8 GB, thấp hơn mức D14 đòi cho kho bí mật; số tải thật chưa đo. Nguồn: `.claude/plans/studio/requirements.md`, Bằng chứng ngược. Tin cậy: cao.
- Đã tìm khách đã trả tiền, bảng giá có số và đơn vị nhận hợp đồng trong repo, không thấy. Nguồn: tìm trong `.claude/plans`. Tin cậy: cao.

## Phương án

### A — Nhỏ nhất làm được

- Phác thảo: một host production, khách vào bằng lời mời, hợp đồng và thu tiền ngoài hệ thống, người vận hành ghi kỳ thuê bao trong nền tảng. Sản phẩm ngày đầu là Digital Worker chăm sóc lead đã chạy được; Studio tới theo các bản cập nhật khi hàng đợi của nó xong.
- Ngân sách thời gian: 4 tuần cho phần agent làm được, cộng thời gian của luật sư và khách.
- Đánh đổi: được một đường thật tới khách đầu tiên; mất tự phục vụ và thu tiền tự động.
- Chỗ dễ sa lầy: kho bí mật trên host thật, và tuyến model trong Việt Nam.

### B — Không làm gì

- Phác thảo: tiếp tục hàng đợi Studio tới W1a, W1b rồi cắt W2.
- Ngân sách thời gian: không.
- Đánh đổi: được đủ tính năng hơn trước khi ra mắt; mất thời gian và không có phản hồi từ khách thật.
- Chỗ dễ sa lầy: dựng thêm những thứ chưa ai cần, trong khi cả năm chỗ chặn ở trên vẫn còn.

### C — SaaS tự phục vụ ngay

- Phác thảo: tự đăng ký, dùng thử, cổng thanh toán, hóa đơn điện tử trước khách đầu tiên.
- Ngân sách thời gian: 3 tháng.
- Đánh đổi: được quy trình đẹp; mất nhiều tháng cho một luồng chưa ai đi qua.
- Chỗ dễ sa lầy: cổng thanh toán và hóa đơn điện tử cần pháp nhân và hợp đồng thật.

Đề xuất: A, rồi phần tự phục vụ của C khi có từ năm khách trả tiền, vì A là đường ngắn nhất để biết có ai trả tiền không.

## Câu hỏi hoài nghi

- Phần khó nhất về kỹ thuật là gì, và repo này đã làm thứ gì gần giống chưa? Kho khóa OpenBao trên host thật, đường thư thật và lối tài khoản qua Keycloak; compose, Caddy và lệnh triển khai đã có sẵn. Kết luận: vững.
- Điều gì ta chưa biết cách làm, và phải tốn gì để biết? Tuyến model trong Việt Nam có ai bán và giá bao nhiêu; cách biết: Đạt hỏi nhà cung cấp, hạn hai tuần. Kết luận: chưa chắc.
- Ta dựa vào thứ gì ngoài tầm tay (thư viện, nhà cung cấp, area khác), và nếu nó đổi thì sao? Nhà cung cấp model, máy chủ thư, host. Đổi model là đổi hồ sơ, đổi thư là đổi kết nối. Kết luận: vững.
- Ai dùng nó trong tuần đầu, và điều gì khiến họ quay lại hay bỏ đi? Chưa biết: chưa có khách có tên; cách biết: Đạt chốt một khách trước khi production mở. Kết luận: nứt.
- Xong rồi thì ai giữ nó chạy, và mỗi tháng tốn gì? Chưa có người trực, chi phí tháng chưa đo; cách biết: KQ5 sau tháng đầu. Kết luận: nứt.
- Làm cái này thì phải nói không với việc gì? Với W2 của Studio, trợ lý Marketing và các gói nghiệp vụ mới cho tới khi có khách đầu. Kết luận: vững.
- Điều gì giết area này; có dữ liệu cá nhân hay ràng buộc pháp lý nào? Một lần đọc chéo công ty, một thư gửi khi thiếu đồng ý, hay vận hành dữ liệu thật khi chưa có cơ sở pháp lý. Kết luận: vững.
- Vì sao là bây giờ, và nó thay thế hay làm yếu thứ gì đang có? Nền tảng đã đủ lõi, và mỗi tuần dựng thêm mà chưa có khách là rủi ro lớn hơn rủi ro kỹ thuật. Nó đổi thứ tự hàng đợi Studio, không bỏ gì. Kết luận: vững.
- Câu nào ta ngại hỏi nhất ở đây, và câu trả lời thật là gì? Có ai trả tiền không. Chưa biết, và không ticket nào trả lời thay được. Kết luận: nứt.

## Ràng buộc

- `CLAUDE.md`, mục "Environments": uat và production cùng luật, nên mọi kiểm soát `is_deployed` áp ở cả hai.
- `CLAUDE.md`, mục "Non-negotiable architecture": mọi lời gọi model qua `ResidencyGate`, nên tuyến nước ngoài cần công ty đổi lớp, không nới ở code.
- ADR-0009 (Accepted): ba tên miền sau Caddy là hình của một lần triển khai có host.
- ADR-0115 (Accepted): bí mật của công ty nằm dưới OpenBao, không có đường lùi về khóa dev.
- ADR-0123 (Accepted): nới lớp tuyến dữ liệu cần hai người.

## Câu hỏi còn mở

- Q1. Khách thí điểm đầu tiên là ai? Chủ: Đạt. Chặn: KQ1, operator-tasks/01.
- Q2. Tuyến model cho khách đầu là nhà cung cấp trong Việt Nam hay công ty chọn xuyên biên giới sau khi luật sư xác nhận? Chủ: Đạt. Chặn: YC17, operator-tasks/04.

## Quyết định

- 6/11/2026 (Đạt): Đích của nền tảng là production thật để doanh nghiệp thuê bao và dựng DW chạy thật, không dừng ở test hay demo; đây là ưu tiên hàng đầu.
- 6/11/2026 (agent, tạm): Chọn phương án A. Nếu sai thì: cắt thêm spec tự đăng ký và thanh toán ngay.
- 6/11/2026 (agent, tạm): Production không chờ trợ lý Marketing, nên không đi qua marketing-pilot/04 và /06. Mâu thuẫn nguồn: `.claude/plans/studio/requirements.md` đặt uat trong lối ra W1b kèm trợ lý, Đạt 6/11/2026 đặt production lên đầu; theo Đạt. Nếu sai thì: production chờ agent-builder/04.
- 6/11/2026 (agent, tạm): Cổng E3 giữ nguyên: dữ liệu cá nhân thật chỉ sau ý kiến luật sư và DPA đã ký, nên "khách vào dùng luôn" trước E3 nghĩa là dùng với dữ liệu giả lập. Nếu sai thì: chỉ Đạt được quyết bỏ cổng này, sau khi hỏi luật sư.
- 6/11/2026 (agent, tạm): Ứng viên Tự đăng ký và thanh toán tự động: dừng; bằng chứng yếu.
- 6/11/2026 (agent, tạm): Ứng viên Lối tài khoản khách qua lời mời: làm; bằng chứng mạnh.
- 6/11/2026 (agent, tạm): Ứng viên Thuê bao do người vận hành ghi: làm; bằng chứng đủ.
- 6/11/2026 (agent, tạm): Ứng viên Gửi và đọc thư thật của DW: làm; bằng chứng mạnh.
- 6/11/2026 (agent, tạm): Ứng viên Triển khai production một lệnh có sao lưu và cảnh báo: làm; bằng chứng mạnh.
