# Yêu cầu cấp cao: Studio

Status: needs-triage
Area: studio · Viết: 23/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

## Mục đích tài liệu

Tài liệu này là danh mục yêu cầu cấp cao của Studio: ai dùng, cần gì, vì sao, thành công đo bằng gì, và mỗi yêu cầu thuộc đợt nào. Nó không quyết định cách làm: dữ liệu, route, công nghệ và thư viện nằm ở ADR-0100 (Proposed) tới ADR-0125 (Proposed) và ở 25 spec của area. Người đọc là Đạt (duyệt), người viết spec (lấy mã YC vào cột Yêu cầu cấp area của Lộ trình trong [studio.md](../studio.md)) và người kiểm nhất quán.

Đợt theo roadmap của area: W1 là P0 cộng lát Marketing mỏng, W2 là v1 GA, W3 là v1.5 và v2. Yêu cầu W3 không có mã YC; chúng nằm ở Không làm.

## Vấn đề

Mỗi công ty khách của nền tảng có quy trình riêng. Hôm nay mọi đối tượng, quy trình, agent và công cụ là mã của nền tảng, nên mỗi nhu cầu mới của một phòng Marketing là một yêu cầu cho kỹ sư và một bản phát hành: quản trị viên nghiệp vụ không tự dựng được gì, người dùng cuối chờ, còn vai trò, khóa model và trần chi phí là cấu hình chung của cả deployment chứ không của từng công ty. Đối thủ đã cho người không lập trình dựng agent và quy trình, nhưng theo tám ảnh chụp demo thì để hở cô lập công ty, quyền trên bản ghi áp cho agent, và chạy thử không tác động thật.

Vì sao bây giờ: Luật 91/2025/QH15 và Nghị định 356/2025/NĐ-CP có hiệu lực từ 01/01/2026, Luật AI 134/2025/QH15 từ 01/03/2026, nên xử lý dữ liệu lead có kiểm soát là điều kiện để bán ở Việt Nam; các hãng lớn đã hội tụ về một bộ khái niệm điều khiển agent trong năm 2026; và người đặt yêu cầu đã chọn hướng (D1-D14) cùng miền thí điểm Marketing (D4) ngày 22 và 23/10/2026.

Cái giá của việc không làm: mỗi khách mới là một nhánh mã hay một dự án tùy biến; thí điểm Marketing (D4) không có gì để chạy; và khi khách tự ghép công cụ ngoài, dữ liệu cá nhân của lead đi qua những chỗ PDPL (Luật 91/2025/QH15, Nghị định 356/2025/NĐ-CP) không kiểm được.

## Người dùng

- Quản trị viên công ty (`tenant_admin`): người quản lý hệ thống ở phía khách (vai hiện có `org_admin`); không lập trình. Việc chính: dựng workspace, mời người, gán vai trò mẫu; cài gói Marketing và chọn người duyệt tin tiếp thị; kết nối hộp thư, Facebook Page, Zalo OA và cho người dựng dùng; đặt trần chi phí theo workspace và quy trình; xem ai duyệt tin nào, gửi cho ai, chi phí tháng này. Vướng hôm nay: vai trò là danh mục chung chỉ đổi qua migration, và không có trần chi tiêu theo ngày hay màn mức độ sử dụng.
- Người dựng (`builder`): quản trị viên nghiệp vụ của một phòng (D2); dựng không viết mã, không có quyền quản trị công ty. Việc chính: thêm trường vào Lead và đặt loại dữ liệu cá nhân; đổi ngưỡng điểm, chạy Mô phỏng, gửi phát hành chờ người khác duyệt; đọc bước lỗi trong lịch sử chạy và sửa; cấu hình trợ lý và chạy bộ đề kiểm định trước khi phát hành. Vướng hôm nay: đối tượng, quy trình và agent là mã của nền tảng, nên mỗi thay đổi chờ kỹ sư và một bản phát hành.
- Thành viên workspace, tức nhân viên Marketing và nhân viên kinh doanh (`member`): người dùng cuối làm việc với lead hằng ngày. Việc chính: mở "Lead mới hôm nay", lọc theo chiến dịch, sửa thông tin thiếu; hỏi trợ lý về lead và chiến dịch, nhận câu trả lời có link; bảo trợ lý chạy một quy trình được phép; nhận lead được giao, gọi điện, ghi tương tác, đổi trạng thái. Vướng hôm nay: chưa biết đội thí điểm đang làm những việc này bằng công cụ gì, vì đội đó chưa được chọn (DO-22).
- Người duyệt (`approver`): ví dụ trưởng Marketing; giữ quyền duyệt tin tiếp thị. Việc chính: xem điểm, lý do, bản xem trước và trạng thái đồng ý trước khi duyệt; duyệt trên điện thoại hoặc bằng mã qua Zalo; xem phê duyệt quá hạn của nhóm và nhận chuyển cấp. Vướng hôm nay: nền tảng có yêu cầu phê duyệt cho lượt chạy của agent, chưa có cho quy trình do công ty dựng.
- Người vận hành (`platform_operator`): nhân viên vận hành nền tảng; không thấy bản ghi Studio của khách. Việc chính: tạo công ty và gói dịch vụ; đóng băng toàn nền tảng hay một công ty khi có sự cố; theo dõi chi phí nhà cung cấp và lỗi qua trace không nội dung; trợ giúp khách qua quyền truy cập do khách cấp (ADR-0024 (Proposed)). Vướng hôm nay: chưa có công tắc đóng băng hay tắt khẩn cấp, và cả deployment dùng một bộ khóa model.
- Hệ thống tích hợp (`integrator`): form website, Facebook, hệ thống của khách; gửi dữ liệu không qua tài khoản người dùng. Việc chính: gửi sự kiện có chữ ký tới nguồn dữ liệu; xoay bí mật có thời gian chồng; xem lịch sử sự kiện và phát lại sự kiện bị cách ly. Vướng hôm nay: chưa có cửa nhận dữ liệu có chữ ký cho quy trình của một công ty.
- Kiểm soát viên và người phụ trách bảo vệ dữ liệu (`auditor_dpo`): chỉ đọc; trả lời cơ quan và chủ thể dữ liệu. Việc chính: truy chuỗi lead, đồng ý, phê duyệt, tin đã gửi; trả lời yêu cầu của chủ thể dữ liệu trong 2 ngày làm việc; rà quyền theo quý. Vướng hôm nay: chưa có bản ghi đồng ý, chưa truy được từ lead tới tin đã gửi, và sổ sử dụng theo lượt gọi đã bị gỡ ngày 21/09/2026.
- Chủ thể dữ liệu, tức lead (`data_subject`): không đăng nhập; chịu tác động của mọi quy trình. Việc chính: điền form có ô đồng ý và link thông báo xử lý dữ liệu; bấm hủy đăng ký hay trả lời từ khóa; yêu cầu xem hoặc xóa dữ liệu qua kênh của công ty. Vướng hôm nay: khi công ty tự ghép công cụ ngoài, yêu cầu xem hay xóa của họ không có một nơi trả lời (GIẢ ĐỊNH).

## Yêu cầu

100 yêu cầu ở 18 nhóm, A tới R: 65 ở W1 và 35 ở W2; 93 chức năng và 7 phi chức năng (YC3, YC4, YC20, YC41, YC44, YC92, YC100).

Ở W2: YC9, YC10, YC11, YC16, YC21, YC24, YC28, YC29, YC36, YC37, YC38, YC45, YC46, YC52, YC53, YC56, YC57, YC58, YC65, YC66, YC67, YC68, YC69, YC74, YC75, YC79, YC83, YC90, YC91, YC92, YC93, YC97, YC98, YC99, YC100; mọi YC khác ở W1. Trong số đó, YC9, YC10, YC21, YC36, YC52, YC53, YC56, YC65, YC74 và YC83 là phần một brief muốn ở W1 mà roadmap dời sang W2.

YC ở W1 có một phần đến sau, ghi ở Ngoài phạm vi của spec phục vụ nó: YC7, YC12, YC25, YC33, YC49, YC50, YC54, YC55, YC63, YC72, YC82. Spec nào phục vụ YC nào chỉ ghi ở cột Yêu cầu cấp area của Lộ trình trong [studio.md](../studio.md).

### A. Nền móng và khung Studio

- YC1 Thanh điều hướng trên cùng PHẢI có đúng một mục "Studio" chứa mọi khu vực của Studio (đối tượng, quy trình, agent, kết nối, mức độ sử dụng), với nhãn tiếng Việt và giờ theo Asia/Ho_Chi_Minh.
- YC2 Lát Marketing PHẢI dựng được hoàn toàn qua bề mặt tenant của Studio (API công khai và màn hình), không có mã nghiệp vụ marketing hay migration riêng trong nền tảng.
- YC3 Dữ liệu Studio của tenant A (bản ghi, sự kiện, lượt chạy, tương tác, kết nối, thành phần) PHẢI cho 0 dòng đọc hay ghi được từ tenant B qua API, agent, tìm kiếm, webhook và xuất, kể cả khi đọc thẳng một partition.
- YC4 Mỗi kiểm soát của Studio, và mỗi lỗi P0 đã đo trong nền tảng mà Studio đứng lên (13 lỗi), PHẢI có một test âm đã được thấy đỏ khi gỡ kiểm soát hay hoàn tác bản vá; lát Marketing có 18 kiểm soát MP1 tới MP18.
- YC5 KHI người gọi gửi lại một yêu cầu ghi với cùng khóa chống lặp, API Studio PHẢI trả lại kết quả lần đầu chỉ cho chính người đó và không ghi lần hai.
- YC6 KHI một tenant được offboarding, lane offboarding PHẢI xuất rồi xóa mọi dữ liệu Studio của tenant đó (bản ghi, lịch sử, sự kiện, lượt chạy, bí mật), mỗi dòng xuất đúng một lần.

### B. Tổ chức và chủ thể

- YC7 Quản trị viên công ty PHẢI thêm và tạm khóa được một thành viên công ty không phụ thuộc workspace nào, với tạm khóa có hiệu lực ở mọi API và lượt chạy dưới danh nghĩa người đó.
- YC8 ĐỐI VỚI lượt chạy không có người kích hoạt (nguồn dữ liệu, lịch, sự kiện bản ghi), lượt chạy PHẢI chạy dưới danh nghĩa một tài khoản dịch vụ do người giữ mọi quyền của nó gắn và người khác duyệt, không bao giờ dưới danh nghĩa người phát hành.
- YC9 Quản trị viên công ty PHẢI mô hình hóa được cơ cấu công ty: cây workspace tối đa 6 cấp với một gốc, nhóm có thành viên từ mọi workspace, và cấp trên trực tiếp của mỗi người, không vòng nào.
- YC10 NẾU người chịu trách nhiệm của một agent hay quy trình rời công ty, THÌ thao tác phát hành PHẢI từ chối bản mới với lý do "không có người chịu trách nhiệm" cho tới khi có người thay.
- YC11 Đăng nhập vào một công ty PHẢI theo chính sách của chính công ty đó: chỉ nhà cung cấp danh tính của công ty khi bắt buộc SSO, và xác thực hai yếu tố khi chạm dữ liệu nhạy cảm hay quyền trọng yếu.

### C. Vai trò và quyền

- YC12 Quản trị viên công ty PHẢI tạo, sửa, nhân bản và xóa mềm vai trò của công ty, trong đó mỗi quyền trên đối tượng mang một mức truy cập (Của tôi, Của nhóm tôi, Workspace của tôi, Workspace của tôi và cấp dưới, Toàn công ty) cộng dồn qua mọi lần gán.
- YC13 NẾU một thay đổi vai trò cấp quyền mà người làm không tự giữ ở mức bằng hoặc rộng hơn, tự cấp cho chính người làm, hay để công ty không còn Chủ sở hữu, THÌ API quản trị vai trò PHẢI từ chối kèm lý do và không đổi gì.
- YC14 KHI một quyền bị thu hồi (vai trò, thành viên, mức truy cập, chia sẻ, quy tắc), yêu cầu đầu tiên sau khi thay đổi được ghi PHẢI đã chịu quyền mới, kể cả khi thay đổi đến từ lane nền hay nhập dữ liệu.
- YC15 NẾU một người gọi thẳng API của một hành động mà giao diện ẩn hay khóa với họ, THÌ API PHẢI từ chối và không đổi gì.
- YC16 Quản trị viên công ty PHẢI sửa vai trò trên một màn ma trận đối tượng × hành động × mức và xem vì sao một người giữ một quyền, với ô vượt quyền của chính họ bị khóa kèm lý do bằng lời.

### D. Quyền trên bản ghi

- YC17 Mỗi bản ghi PHẢI có người phụ trách và workspace sở hữu, không bao giờ trống, trên một đối tượng có mặc định truy cập mà đối tượng mới luôn là Riêng tư.
- YC18 Quyền trên bản ghi PHẢI được quyết định ở một chỗ cho mọi đường đọc và ghi (API, agent, quy trình, xuất, lane nền, dịch vụ viết bằng ngôn ngữ khác), không vai trò nào vượt qua kể cả của nhà vận hành, và đường không mang ngữ cảnh người hành động thấy 0 bản ghi.
- YC19 Agent và quy trình PHẢI đọc và ghi bản ghi bằng quyền của người kích hoạt (hoặc tài khoản dịch vụ chạy dưới danh nghĩa) giao với giới hạn dữ liệu của phiên bản đã phát hành, đánh giá lại ở từng bước và từng lời gọi công cụ.
- YC20 Ở cỡ D12 (10 triệu bản ghi mỗi đối tượng, 50 triệu mỗi tenant, 5.000 người dùng, 200 workspace, cây workspace sâu 6) với mọi hồ sơ quyền, danh sách bản ghi PHẢI trả trang đầu 50 dòng trong p95 ≤ 50 ms và một bản ghi trong p95 ≤ 5 ms, đo phía máy chủ trên máy tham chiếu.
- YC21 Người phụ trách và quản trị viên PHẢI mở rộng được tầm thấy của bản ghi bằng ba lớp còn lại của D3 (cấp trên thấy bản ghi của cấp dưới, chia sẻ tay có hạn, quy tắc chia sẻ theo tiêu chí có phiên bản), với thu hồi có hiệu lực từ câu lệnh kế tiếp.

### E. Bảo mật trường

- YC22 Mỗi trường PHẢI ở chế độ `Bảo mật trường` Mở hoặc Bảo vệ, với trường dữ liệu cá nhân mặc định Bảo vệ, trường Nhạy cảm không bao giờ đổi được sang Mở, và trường Bảo vệ chỉ hiện với vai trò được cấp Xem hoặc Xem và sửa (cộng dồn qua mọi vai trò).
- YC23 Giá trị một trường Đã ẩn với một người PHẢI vắng mặt ở mọi đường ra tới người đó (API, describe, đầu vào và đầu ra công cụ của agent, chuỗi có biến của quy trình, trang duyệt, lịch sử chạy) và không lọc, sắp, đếm hay ghi được qua đó.
- YC24 Xuất dữ liệu, lịch sử thay đổi bản ghi, webhook gửi đi và chỉ mục truy xuất PHẢI áp cùng quyết định Đã ẩn như API bản ghi, với mỗi lần đọc trường Nhạy cảm có nhật ký kiểm toán chỉ gồm id và tên trường.

### F. Đối tượng và bản ghi

- YC25 Quản trị viên PHẢI tạo được đối tượng và trường (văn bản, số, tiền, ngày, ngày giờ, đúng sai, danh sách chọn, email, điện thoại, url) với tên API bất biến và nhãn tiếng Việt, không cần nhà vận hành hay migration.
- YC26 Mọi đường ghi bản ghi (API, bước quy trình, công cụ agent, nhập, hàng loạt, lane nền) PHẢI chạy cùng một bộ kiểm dữ liệu, quyền và `Bảo mật trường`, và phát cùng sự kiện bản ghi trong cùng giao dịch.
- YC27 Danh sách và biểu mẫu bản ghi PHẢI sinh từ mô tả đối tượng theo người xem, lọc và sắp trên trường lọc được theo thứ tự tiếng Việt ("An, Ánh, Ân, Bình, Đạt"), và phân trang không trùng không sót.
- YC28 Người dựng PHẢI thêm, đổi hay bỏ trường và `Điều kiện để lưu được` trên màn trình dựng đối tượng, với việc bỏ một trường mà phiên bản đang dùng của quy trình hay agent đọc tới bị từ chối kèm `Nơi đang dùng`.
- YC29 Trường do AI ghi (điểm, hạng, lý do) PHẢI mang nguồn gốc (lượt chạy, thời điểm, phiên bản prompt, hồ sơ model) và nhãn "AI" trên giao diện, và người có quyền sửa được giá trị đó với nhật ký giá trị cũ và mới.

### G. Phiên bản, cấu hình riêng và chế độ chạy

- YC30 Mỗi thành phần Studio (đối tượng, quy trình, agent, công cụ, kỹ năng, bộ công cụ) PHẢI có đúng một bản nháp sửa được và các phiên bản đã phát hành bất biến, đánh số tăng dần không dùng lại và mang mã băm tái tạo được.
- YC31 NẾU một thành phần đang được phiên bản đã phát hành của thành phần khác dùng, THÌ thao tác xóa PHẢI từ chối và liệt kê `Nơi đang dùng`, chỉ nêu tên những gì người gọi đọc được.
- YC32 Mỗi lượt chạy PHẢI ghim mọi thứ nó dùng (phiên bản, cấu hình riêng, giá trị điểm gắn, chế độ chạy, model) và chỉ đọc từ bản kê đó, kể cả khi tiếp tục sau 3 ngày chờ duyệt hay lâu hơn.
- YC33 Mỗi lượt chạy PHẢI có chế độ chạy (Thật, Chạy thử, Mô phỏng) do máy chủ đặt theo cửa vào, không bao giờ nới hơn chế độ của lượt cha hay của lượt trước khi chờ duyệt, và cửa chạy thử không nhận chế độ Thật.
- YC34 TRONG KHI lượt chạy ở chế độ Mô phỏng, mọi lệnh có tác động ra ngoài hay ghi bản ghi thật PHẢI bị giả lập tại điểm thực thi, được đánh dấu là giả lập và không rời nền tảng.
- YC35 KHI một người đề xuất giá trị điểm gắn (kết nối, biến) cho một thành phần, giá trị PHẢI chỉ có hiệu lực sau khi một người khác người đề xuất duyệt, và phiên bản thiếu giá trị đã duyệt không kích hoạt được.
- YC36 TRONG KHI lượt chạy ở chế độ Chạy thử, tin nhắn PHẢI chỉ tới người trong Danh sách người nhận thử còn hạn (tối đa 90 ngày), còn lại bị giả lập kèm lý do.
- YC37 Công ty PHẢI có được phiên bản riêng của prompt, đặc tả công cụ, bộ công cụ, hồ sơ model và chính sách qua đề xuất có duyệt, chỉ siết mà không nới chính sách nền tảng, và rơi về mặc định nền tảng chứ không bao giờ sang công ty khác.

### H. Gói nghiệp vụ

- YC38 KHI người có quyền cài gói cài một gói mà gói dịch vụ của công ty cho phép, trình cài PHẢI tạo đối tượng, vai trò mẫu, quy trình và trợ lý thành bản sao có nguồn gốc của công ty, trong một giao dịch, chỉ qua API công khai và không kích hoạt gì, với phiên bản mới của gói về sau chỉ đến như đề xuất ba bên vào bản nháp.

### I. Quy trình và trình kích hoạt

- YC39 Người dựng PHẢI vẽ quy trình trên sơ đồ dùng được ở màn rộng 320 px và chỉ bằng bàn phím, gồm các bước cấu hình bằng biểu mẫu, với giá trị riêng của công ty chỉ vào qua tên điểm gắn.
- YC40 Biểu thức và chuỗi có biến của công ty PHẢI được tính ở máy chủ với trần chi phí, chỉ tham chiếu bước chắc chắn đã chạy trước, kiểm kiểu lúc phát hành, và không bao giờ được chạy như mã.
- YC41 KHI API hay một worker dừng giữa lượt chạy hay ngay sau một quyết định duyệt, lượt chạy PHẢI tiếp tục ở worker khác trong ≤ 90 giây với mỗi tác động được nhà cung cấp nhận đúng 1 lần, và không chờ sau 10.000 lượt đang xếp của một tenant khác.
- YC42 NẾU sự kiện gửi tới nguồn dữ liệu sai chữ ký, lệch giờ quá ±5 phút, sai lược đồ hay nhắm một định danh nguồn không tồn tại (định danh có ít nhất 128 bit ngẫu nhiên), THÌ nguồn dữ liệu PHẢI từ chối mà không tạo lượt chạy và không lặp lại giá trị đã gửi.
- YC43 KHI cùng một sự kiện (cùng `webhook-id`) tới lại trong 72 giờ, nguồn dữ liệu PHẢI trả thành công kèm dấu "trùng" mà không tạo lead hay lượt chạy thứ hai.
- YC44 Nguồn dữ liệu PHẢI trả lời thành công trong p95 ≤ 1 giây (lưu rồi chạy sau) cho tối đa 60 sự kiện mỗi phút (mặc định, công ty đổi được; phần vượt bị từ chối, không gọi AI), với 100% sự kiện đã trả thành công hoặc thành lead hoặc nằm trong lịch sử sự kiện kèm lỗi đọc được.
- YC45 Quy trình PHẢI có nhánh song song với điểm nối, lặp trên danh sách có giới hạn, hẹn giờ bền qua khởi động lại (lệch < 1 phút), quy trình con sâu tối đa 3 cấp không vòng, và hủy dừng mọi bước trong 5 giây.
- YC46 Người dựng PHẢI kích hoạt quy trình bằng lịch theo múi giờ công ty, bằng sự kiện bản ghi (không tự kích hoạt lại, chuỗi sâu tối đa 8) và như một công cụ của agent không bao giờ báo thành công khi còn chờ người.

### J. Bước quy trình và phê duyệt

- YC47 Bước AI PHẢI trả đầu ra theo lược đồ người dựng đặt, kiểm ở máy chủ, sửa tối đa một lần, và khi vẫn sai thì đi nhánh lỗi mà quy trình không dừng (ở lát: hạng "chưa rõ" và lead vẫn được giao).
- YC48 Mọi giá trị chèn vào prompt và mọi kết quả công cụ đưa cho model PHẢI được bao là dữ liệu từ bên ngoài và cắt ở 16 KiB, để nội dung lead không đóng được khối và thành chỉ dẫn.
- YC49 NẾU bản ghi mang cờ `Từ chối xử lý tự động` hay `Hạn chế xử lý`, THÌ bước AI PHẢI bỏ qua bản ghi đó mà không gọi model.
- YC50 Giao người phụ trách, bằng tay hay bằng bước quy trình, PHẢI chỉ chọn thành viên đang hoạt động có quyền làm người phụ trách bản ghi đó trong tầm giao, có nhật ký kiểm toán, xoay vòng theo người lâu nhất chưa nhận (100 lead cho 3 người lệch ≤ 1), và giao người dự phòng đã cấu hình khi không ai hợp lệ.
- YC51 Trang duyệt tin tiếp thị PHẢI chỉ nhận quyết định của người giữ quyền duyệt khác người tạo lượt chạy, sau khi hiện đúng tham số sẽ được thực thi (điểm, lý do, kênh, bản xem trước, trạng thái đồng ý) và kèm lý do khi từ chối, với bước bị chặn nếu tham số đổi sau khi duyệt.
- YC52 Người duyệt PHẢI quyết định được trên điện thoại (trang 320 px) và qua Zalo bằng mã một lần, với phê duyệt quá hạn được nhắc, chuyển cấp rồi đi nhánh hết hạn, không bao giờ tự duyệt.
- YC53 Người dùng PHẢI thấy phê duyệt, việc cần làm và ủy quyền của mình trong một hộp việc có hạn, và được báo việc mới trong ứng dụng hay qua bot Zalo nội bộ chỉ bằng tiêu đề và link, không có dữ liệu cá nhân của lead.

### K. Agent và model

- YC54 Người dựng PHẢI tạo được agent gồm chỉ dẫn, hồ sơ model trong danh sách gói cho phép, bộ công cụ ghim theo phiên bản và `Người được dùng`, không viết mã.
- YC55 NẾU người ngoài `Người được dùng` gọi một agent, hoặc một người mở hội thoại của người khác, THÌ trang chat PHẢI trả "không tìm thấy" như với thứ không tồn tại.
- YC56 Người dựng PHẢI cấu hình agent trên màn dựng agent (chỉ dẫn, công cụ, người được dùng, lời chào, tối đa 6 gợi ý, "Hỏi trước") với câu trả lời trích dẫn bản ghi bằng link và trích dẫn không có trong bằng chứng của lượt đó bị gỡ.
- YC57 Agent liên kết, agent con, agent trong bước quy trình và nguồn tri thức PHẢI luôn hẹp hơn agent hay người gọi chúng: sâu tối đa 3 cấp, không vòng, agent điều phối không giữ công cụ tác động, tri thức chỉ gồm bản ghi người hỏi thấy lúc hỏi.
- YC58 Quản trị viên công ty PHẢI kết nối được model của chính công ty (khóa trong kho bí mật) và chọn nó cho agent sau khi thăm dò năng lực đạt, với lỗi kết nối làm lượt chạy thất bại thay vì chuyển sang route khác.

### L. Công cụ, kết nối và kho bí mật

- YC59 Model PHẢI chỉ gọi được công cụ trong bộ công cụ đã ghim của phiên bản agent, với đầu vào và đầu ra của mỗi lời gọi được kiểm theo lược đồ của công cụ và chính sách của công ty.
- YC60 Mức sàn duyệt của công cụ (trọng yếu, luôn duyệt, bộ ba nguy hiểm) PHẢI không bị hạ bởi cấu hình công ty, người dựng hay mức tự chủ; công ty chỉ siết thêm được.
- YC61 Mọi bí mật của công ty (token OAuth, khóa API, mật khẩu, khóa ký) PHẢI được mã hóa dưới khóa riêng của công ty, không bao giờ ở dạng rõ (kể cả khi dịch vụ khóa không sẵn sàng) và không bao giờ xuất hiện trong phản hồi API, trạng thái lượt chạy, công cụ, bản kê, trace, log hay nhật ký kiểm toán.
- YC62 Quản trị viên PHẢI thêm, kiểm tra, tắt và thu hồi kết nối dùng chung của một workspace trên trang Kết nối, thấy sức khỏe và "Được dùng bởi", với tắt hay thu hồi có hiệu lực trước lần gọi ra ngoài kế tiếp của mọi lượt chạy.
- YC63 Mọi lời gọi ra ngoài PHẢI chỉ tới địa chỉ Internet công cộng trong danh sách máy chủ được phép của công ty, không bao giờ tới địa chỉ nội bộ, link-local hay CGNAT, kể cả sau chuyển hướng hay đổi DNS.
- YC64 Quy trình PHẢI gửi được email tới lead qua kết nối hộp thư SMTP của chính công ty, như một hành động khai trong bản mô tả trình kết nối.
- YC65 KHI người dùng kết nối một nhà cung cấp qua OAuth, kết nối PHẢI chỉ kích hoạt khi chính người khởi tạo xác nhận trong phiên của họ, lấy công ty từ phiên cấp quyền chứ không từ URL trả về, và chuyển "Cần kết nối lại" khi token bị thu hồi.
- YC66 Quản trị viên nghiệp vụ PHẢI tạo được công cụ HTTP bằng biểu mẫu hoặc từ OpenAPI và kỹ năng theo định dạng Agent Skills mở, không viết mã, xem "Bản mô hình nhìn thấy" trước khi phát hành, và kỹ năng không cấp thêm công cụ nào.
- YC67 KHI một lượt chạy đã nhận nội dung từ bên ngoài, mọi công cụ tác động ra ngoài sau đó PHẢI cần người duyệt, ở mọi mức tự chủ.
- YC68 Định nghĩa công cụ của một máy chủ MCP PHẢI được một người khác người đăng ký duyệt trên đúng văn bản model sẽ đọc, bị ngưng khi định nghĩa đổi, và mọi lưu lượng MCP đi qua một cổng tách biệt không giữ bí mật.

### M. Chạy mã

- YC69 Bước mã Python, chỉ có với quyền viết mã và quyền lợi gói cho bước mã, PHẢI chạy mỗi lần trong một container mới dùng một lần trên 1 máy riêng không chứa dữ liệu nền tảng, không mạng, không bí mật, có trần CPU, bộ nhớ, tiến trình, đĩa, thời gian và đầu ra, được chứng minh bằng bộ script thù địch đạt 100% ở cổng phát hành.

### N. Vòng đời, cổng chất lượng, đóng băng và tắt khẩn cấp

- YC70 Thao tác phát hành PHẢI chỉ đưa một phiên bản (đi qua Nháp, Đang kiểm định, Chờ duyệt, Đang dùng, Đã gỡ; tối đa một bản Đang dùng) vào Đang dùng khi lượt kiểm định chạy ở Mô phỏng đạt trên đúng mã băm định nghĩa của nó (bộ kiểm định an ninh nền tảng đạt 100%) và một người không phải tác giả hay người gửi đã duyệt.
- YC71 NẾU phiên bản có đường từ đầu vào bên ngoài qua dữ liệu riêng tới tác động ra ngoài mà không qua bước phê duyệt, hoặc dùng công cụ thiếu phân loại, THÌ thao tác phát hành PHẢI từ chối kèm đường vi phạm.
- YC72 KHI nhà vận hành hay quản trị viên công ty đóng băng, mọi lượt chạy của phạm vi đó PHẢI dừng ở cửa kế tiếp (nhận lượt chạy, lời gọi model, lời gọi công cụ, quyết định duyệt) trong ≤ 5 giây ở mọi tiến trình, không tác động đang chờ nào được thực hiện và sự kiện vào vẫn được giữ.
- YC73 KHI người có quyền tắt khẩn cấp một agent hay quy trình, công tắc Tắt khẩn cấp PHẢI chặn lượt chạy mới, hủy lượt và phê duyệt đang chờ, tắt trình kích hoạt và chặn tin đã xếp hàng, với bật lại cần một người thứ hai.
- YC74 Người dựng PHẢI nhập câu kiểm định của công ty bằng biểu mẫu (chọn bộ chấm, đặt kỳ vọng), với câu gắn nhất quán chỉ đạt khi đạt cả 3 lần và kiểm định trực tuyến cảnh báo khi tỷ lệ đạt cuộn rơi dưới ngưỡng.
- YC75 Tổng quan đội ngũ PHẢI đếm phiên bản theo giai đoạn, cảnh báo bị tắt, nháp để lâu, lệch cấu hình và kiểm định dưới ngưỡng, và mở trang phiên bản có so sánh từng trường, đọc từ dữ liệu theo quyền người xem chứ không từ trace.

### O. Sử dụng và hạn mức

- YC76 Mỗi lượt gọi model (chat, có cấu trúc, embedding) PHẢI ghi đúng một bản ghi sử dụng gắn công ty, workspace, lượt chạy, agent hoặc quy trình kèm phiên bản, mục đích, bên trả phí và phiên bản bảng giá, với chi phí ước tính thay cho 0 khi nhà cung cấp không trả số dùng, và màn Mức độ sử dụng của quản trị viên đọc chính sổ này.
- YC77 KHI một lượt chạy xin bắt đầu mà phần còn lại của một hạn mức cứng trong chuỗi (gói, công ty, workspace, agent hay quy trình, người dùng, lượt chạy) không đủ, cửa nhận lượt chạy PHẢI từ chối với lý do vượt hạn mức, không gọi model và vẫn giữ sự kiện đã nhận.
- YC78 Mọi lời gọi model của một lượt chạy, qua bất kỳ đường nào (agent, bước AI, embedding, rerank, nạp tri thức), PHẢI chịu trần chi phí và giới hạn hành vi hữu hạn của lượt đó (kẹp bởi gói), dừng ở ranh giới kế tiếp khi chạm trần, không cắt giữa một bước gửi.
- YC79 Hạn mức PHẢI đặt được theo người dùng và theo mục đích (dựng có AI, chạy thử, kiểm định) với cảnh báo đúng một lần ở 80% và 100% mỗi chính sách và kỳ, và lượt gọi qua model của chính công ty luôn đo token mà không tính vào hạn mức tiền của nền tảng.

### P. Quan sát, lịch sử chạy và kiểm toán

- YC80 Span, log và trace vận hành PHẢI chỉ mang định danh không nội dung, không bao giờ nội dung prompt, đầu ra, giá trị trường hay định danh người dùng, và một trace id đi từ trình duyệt tới worker.
- YC81 Người dựng PHẢI xem lịch sử chạy từng bước của quy trình và agent (trạng thái, thời gian, lỗi, token, chi phí, đầu vào và đầu ra đã che) theo quyền, với lượt chạy chạm tới bản ghi người xem không thấy trả "không tìm thấy".
- YC82 Mỗi lần gửi tin, tin bị chặn, phê duyệt, đổi người phụ trách, đổi đồng ý, đổi vai trò hay quyền, chuyển giai đoạn và đặt công tắc PHẢI ghi một sự kiện nhật ký kiểm toán trong cùng giao dịch, chỉ có id và mã, đủ để kiểm soát viên truy chuỗi lead, đồng ý, phê duyệt, tin đã gửi.
- YC83 Kiểm soát viên PHẢI lọc nhật ký kiểm toán phía máy chủ theo hành động, người làm, tài nguyên, lượt chạy và khoảng ≤ 93 ngày, và xuất nó qua tác vụ nền với link hết hạn sau 7 ngày.

### Q. Dữ liệu cá nhân và tuân thủ

- YC84 Mỗi trường (đối tượng, nguồn dữ liệu, lược đồ công cụ) PHẢI mang loại dữ liệu cá nhân (Không, Cơ bản, Nhạy cảm), và tạo trường thiếu phân loại bị từ chối.
- YC85 Mọi lời gọi model của Studio (agent, bước AI, kiểm định) PHẢI dùng hồ sơ model mà gói của công ty cho phép, ghim vào lượt chạy, theo lộ trình dữ liệu chặt nhất của công ty, workspace và agent (mặc định Chỉ trong Việt Nam, `Nơi xử lý dữ liệu` không khai coi là nước ngoài), với lộ trình ghi trên từng lời gọi.
- YC86 NẾU lead không có đồng ý đúng mục đích còn hiệu lực, đang bị chặn liên hệ, ngoài khung giờ gửi hay vượt tần suất, THÌ công cụ gửi tin PHẢI không gọi nhà cung cấp và ghi một Tương tác bị chặn kèm lý do, với đồng ý bị rút (link hủy đăng ký, từ khóa trả lời) hết hiệu lực trong ≤ 5 phút.
- YC87 Đầu vào của bước AI chấm điểm lead PHẢI không chứa định danh trực tiếp (họ tên, số điện thoại, email, Zalo id), với số điện thoại và email trong lời nhắn tự do bị che.
- YC88 Mỗi kho dữ liệu cá nhân mới (lịch sử sự kiện, bước chạy, payload, sổ sử dụng) PHẢI có hạn lưu được một lane đọc và thực thi, với lịch sử sự kiện và đầu vào đầu ra từng bước giữ 30 ngày trong thí điểm.
- YC89 TRONG KHI chưa có ý kiến luật sư Việt Nam về PDPL và Luật AI, sổ sự cố dữ liệu cá nhân và cờ `Hạn chế xử lý` trên bản ghi, lát Marketing PHẢI chỉ chạy trên lead giả lập.
- YC90 KHI chủ thể dữ liệu yêu cầu xem, sửa, hạn chế hay xóa, người phụ trách bảo vệ dữ liệu PHẢI tìm được mọi dữ liệu của người đó trên mọi kho (bản ghi, tương tác, bước chạy, sự kiện, sổ sử dụng) và phản hồi đầu trong 2 ngày làm việc; với một sự cố, người đó khoanh được công ty, chủ thể, loại dữ liệu và số bản ghi để báo trong 72 giờ.
- YC91 ĐỐI VỚI lộ trình ra nước ngoài, công ty PHẢI có xác nhận chuyển dữ liệu cho bên nhận đó và hai người duyệt khi nới lộ trình, với trường Nhạy cảm không bao giờ ra nước ngoài.
- YC92 Mọi URL công khai và 100% chặng nội bộ ở uat và production PHẢI dùng TLS hợp lệ, với checkpoint lượt chạy mã hóa bằng khóa theo công ty và mọi bản sao lưu được mã hóa.
- YC93 Mỗi phiên bản agent và quy trình phát hành PHẢI mang mức rủi ro AI, lý do, mục đích và tờ giải thích cách nó quyết định, với mức cao bị từ chối ở v1 và kênh trò chuyện với người dùng cuối báo đang tương tác với AI.

### R. Lát thí điểm Marketing

- YC94 KHI một lead từ form website tới nguồn dữ liệu, quy trình Tiếp nhận lead PHẢI kiểm trùng, chấm điểm, tạo hoặc cập nhật Lead, giao cho một nhân viên Sales, chờ phê duyệt rồi gửi đúng một email.
- YC95 Quy trình Tiếp nhận lead PHẢI kiểm trùng theo số điện thoại (chuẩn hóa về +84) rồi email (chữ thường), không bao giờ chỉ theo tên ("0901 234 567" và "+84901234567" là một Lead; cùng tên khác số là hai Lead).
- YC96 Trợ lý Marketing PHẢI trả lời câu hỏi về lead, chiến dịch và tương tác theo đúng quyền của người hỏi bằng công cụ đọc, không giữ công cụ gửi tin hay sửa bản ghi.
- YC97 Quy trình Tiếp nhận lead PHẢI nhận lead từ Facebook Lead Ads (đối soát mỗi 15 phút để không mất lead khi webhook rớt), Zalo OA và TikTok Lead Generation, và gửi tin Zalo ZNS theo mẫu đã duyệt.
- YC98 Sau tin đầu, quy trình Chăm sóc lead PHẢI gửi tối đa 3 tin vào 09:00 ngày làm việc (Asia/Ho_Chi_Minh), cách nhau 2 ngày làm việc, mỗi tin qua phê duyệt, rồi báo người phụ trách "cần gọi điện".
- YC99 Thí điểm PHẢI đi qua ba giai đoạn theo thứ tự: dữ liệu giả lập, chạy bóng (lead thật, chế độ Chạy thử, chỉ gửi tới danh sách nhân viên), rồi chạy thật với phê duyệt mỗi tin.
- YC100 Host chính đã nâng lên ít nhất 4 vCPU / 16 GB (D14), với mã của công ty chạy trên một VM riêng, PHẢI chạy được 2.000 lead mỗi ngày của thí điểm, với bước AI p95 ≤ 20 giây và lượt tiếp nhận (không kể chờ duyệt) p95 ≤ 60 giây.

## Không làm

- Nhúng một bộ máy bên thứ ba (n8n, Dify, Windmill, Activepieces) hay một bộ quyết định quyền thứ hai (OpenFGA, SpiceDB, Cerbos): giấy phép cấm nhúng đa tenant, và hai nơi quyết định là hai câu trả lời (ADR-0112 (Proposed), ADR-0105 (Proposed)).
- Workspace làm môi trường (dev, staging): workspace là đơn vị nghiệp vụ (D1); môi trường v1 là bản nháp, phiên bản và chế độ chạy (ADR-0111 (Proposed)).
- Vai trò là nút trong cây phân cấp kiểu Salesforce: vai trò là bộ quyền có mức; tầm thấy đến từ mức, cây workspace, cấp trên và chia sẻ (ADR-0104 (Proposed)).
- Mã nghiệp vụ marketing trong nền tảng (`dw_marketing`): lát chứng minh Studio chỉ qua bề mặt tenant (YC2, ADR-0100 (Proposed)).
- Siêu agent giữ mọi công cụ: `CLAUDE.md`, mục "Non-negotiable architecture", cấm nó; agent điều phối không giữ công cụ tác động (YC57).
- SCIM 2.0, tự cấu hình SSO, client credentials ký bằng khóa riêng: v2, đợt sau (W3); spec `org-and-principals`; nguồn B2 SCIM-01, B2 KEY-02.
- Vai trò cho đội, luật tách nhiệm do công ty định nghĩa, điều kiện thuộc tính (ABAC): v1.5, v2, đợt sau (W3); spec `tenant-rbac`; nguồn B3 RBAC-25..27.
- Biên agent theo phạm vi, nhân viên trợ giúp đọc một bản ghi theo grant: v2, đợt sau (W3); spec `record-access`; nguồn B4 REC-21.
- Che một phần giá trị trường và người thứ hai cho quyền xem trường Nhạy cảm: v1.5, v2, đợt sau (W3); spec `field-security`; nguồn B4 FLS-15, B4 FLS-16.
- Loại bản ghi, trường công thức và tổng hợp, tìm toàn văn, XLSX: v1.5, v2, đợt sau (W3); spec `custom-objects`; nguồn B5 OBJ-36..40.
- Công ty thử nghiệm và đưa gói lên công ty chính (dw.package/v1, promotion): v2, đợt sau (W3); spec `tenant-config`; nguồn B6 ENV-01..03.
- Chờ sự kiện tương quan, chuyển lượt đang chờ sang phiên bản mới, trợ lý AI dựng quy trình: v1.5, v2, đợt sau (W3); spec `workflow-engine`; nguồn B7a TRG-09, B7a WFE-21, B7b BUI-11, B7b NODE-25.
- Máy chủ MCP và A2A của nền tảng, elicitation vào hộp việc, Tasks extension: v1.5, v2, đợt sau (W3); spec `mcp-client`; nguồn B8b MCP-10..12.
- Trình kết nối do công ty tự viết, BYOK hay HSM, giải mã chỉ trong dịch vụ egress, nhóm trình kết nối Sales và Finance: v2, đợt sau (W3); spec `connections-and-vault`; nguồn B8a MNF-08, B8a VLT-12, B8a EGR-13, B8a PIL-06.
- Công cụ mã theo phiên agent, backend Kubernetes, tắt khẩn cấp xóa container: v1.5, v2, đợt sau (W3); spec `code-sandbox`; nguồn B9 SBX-10..12.
- Đóng băng tiếp tục được, công tắc theo workspace, kết nối và tuyến model, mô phỏng nhiều lượt: v1.5, v2, đợt sau (W3); spec `agent-lifecycle`; nguồn B10a KF-10, B10a KF-11, B10a EV-17.
- Hạn mức kiểu xin nâng, dự báo tốc độ chi, phát hiện chi tiêu bất thường: v1.5, đợt sau (W3); spec `usage-and-limits`; nguồn B10b LIM-17, B10b LIM-18.
- Chuỗi băm chống sửa cho nhật ký kiểm toán, SIEM, lấy mẫu đuôi: v1.5, v2, đợt sau (W3); spec `telemetry-and-audit`; nguồn B10b AUD-05, B10b TEL-09, B11 REG-02.
- Messenger trả lời trong cửa sổ 24 giờ, chat với lead: v1.5, đợt sau (W3); spec `marketing-pilot`; nguồn B12 MKT-16.
- Phân loại kết nối kiểu DLP (Business, Non-business, Blocked), kiểm cả lúc dựng và lúc chạy (BS05 trong [brainstorm.md](discovery/brainstorm.md)): không có YC hay dòng roadmap nào; W1 đã có danh sách máy chủ được phép (YC63), lộ trình dữ liệu (YC85) và kiểm bộ ba nguy hiểm lúc phát hành (YC71); xem lại sau thí điểm.
- Chạy bóng phiên bản mới trên lưu lượng thật (BS07): chưa vào roadmap; W2 có so sánh bản ứng viên với bản Đang dùng (YC75); đợt sau (W3).
- Chợ gói nghiệp vụ có duyệt (BS14): chưa vào roadmap; W2 có gói nền tảng cài thành bản sao (YC38); đợt sau (W3).
- Gửi lead đủ điều kiện về Meta qua Conversions API (BS22): không có YC hay dòng roadmap nào, và không KQ nào của thí điểm cần nó; xem lại sau chạy bóng.
- Định giá theo kết quả (BS42): chưa đo được chi phí theo kết quả (KQ12) và cách tính giá còn nợ (DO-59); xem lại ở W3.

## Kết quả đo được

| #    | Kết quả                                                                                                               | Đơn vị                                            | Hiện nay                                          | Đích                                                                        | Đối trọng                                                                                                                                                                                  | Cách đo                                                                                                               |
| ---- | --------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- | ------------------------------------------------- | --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------- |
| KQ1  | [W2] Thời gian phản hồi lead: từ lúc Lead được tạo tới tin gửi đi đầu tiên, chỉ tính giờ làm việc                     | phút (p50) và giờ (p90)                           | chưa biết (khách thí điểm đo trước khi chạy bóng) | p50 ≤ 15 phút, p90 ≤ 2 giờ                                                  | Tỷ lệ tin bị từ chối khi duyệt và tỷ lệ hủy đăng ký sau tin đầu không tăng; tin gửi khi thiếu đồng ý hay thiếu duyệt vẫn bằng 0 (đẩy nhanh bằng cách duyệt vội hay bỏ kiểm sẽ hiện ở đây). | Lead.created_at tới Tương tác outbound đầu tiên `sent`, từ sổ sự kiện của tenant thí điểm (nguồn B12 MET-01)          |
| KQ2  | [W2] Thời gian chờ duyệt tin tiếp thị                                                                                 | phút (p50), giờ làm việc                          | chưa biết                                         | p50 ≤ 10 phút                                                               | Tỷ lệ quyết định trong dưới 5 giây sau khi mở trang duyệt (duyệt không đọc) không vượt 5%; tỷ lệ từ chối không rơi về 0.                                                                   | Thời điểm tạo phê duyệt tới thời điểm quyết định, từ nhật ký kiểm toán (nguồn B12 MET-02)                             |
| KQ3  | [W1] Tự động hóa và kiểm trùng: tỷ lệ lead không nhập tay; tỷ lệ trùng lọt; số lần gộp nhầm                           | %, %, số lần                                      | chưa biết (marketing-pilot/01 đo trên bộ giả lập) | ≥ 90%; ≤ 1%; 0                                                              | Gộp nhầm bằng 0 trên bộ thử có cặp cùng tên khác số (nới khóa kiểm trùng để giảm trùng lọt sẽ làm gộp nhầm tăng).                                                                          | Bộ sinh lead giả lập có hạt giống ở W1; đối chiếu tay 200 lead thật ở W2 (nguồn B12 MET-03)                           |
| KQ4  | [W2] Chất lượng chấm điểm: độ khớp hạng với người trên bộ vàng; tỷ lệ đạt cả 3 lần (pass^3)                           | %                                                 | chưa biết                                         | ≥ 80%; ≥ 95%                                                                | Tỷ lệ hạng "chưa rõ" không vượt 10% (model né bằng "chưa rõ" sẽ hiện ở đây); bộ vàng do người Marketing gán, không lấy từ đầu ra model.                                                    | Bộ vàng ≥ 50 lead chạy ở cổng phát hành (nguồn B12 MET-04)                                                            |
| KQ5  | [W2] Tỷ lệ tin được duyệt                                                                                             | % tin đề xuất                                     | chưa biết                                         | ≥ 80%                                                                       | Tin gửi khi thiếu đồng ý bằng 0 và tỷ lệ hủy đăng ký sau tin không tăng (duyệt dễ dãi đẩy số này lên).                                                                                     | Đếm quyết định duyệt và từ chối kiểu `studio.step.approval` trong thí điểm (nguồn B12 MET-05)                         |
| KQ6  | [W1] An toàn: tin gửi khi thiếu đồng ý hay thiếu duyệt; đọc chéo tenant trong diễn tập; bộ kiểm định an ninh nền tảng | số lần, số lần, % đạt                             | chưa biết (chưa có Studio)                        | 0; 0; 100%                                                                  | Số câu trong bộ an ninh và số kiểm soát có test âm đã thấy đỏ (18 ở lát) không giảm giữa hai phiên bản; bỏ câu khó để đạt 100% sẽ hiện ở đây.                                              | Bộ e2e và đột biến của marketing-pilot/05; diễn tập chéo tenant MP4 (nguồn B12 MET-06)                                |
| KQ7  | [W1] Không mất lead: sự kiện đã trả thành công khớp Lead cộng lỗi đọc được                                            | % khớp                                            | chưa biết                                         | 100%                                                                        | Tỷ lệ sự kiện vào cách ly hay lỗi không vượt 2% (đẩy sự kiện khó vào "lỗi" để giữ 100% sẽ hiện ở đây).                                                                                     | Đối chiếu số sự kiện, số Lead và số lỗi sau tải thử 500 sự kiện (nguồn B12 MKN-06)                                    |
| KQ8  | [W1] Thời gian trả lời của nguồn dữ liệu                                                                              | ms (p95)                                          | chưa biết                                         | ≤ 1.000 ms                                                                  | Chỉ số không mất lead vẫn 100% (trả lời sớm rồi rơi sự kiện sẽ hiện ở đó).                                                                                                                 | Đo trên compose với 500 sự kiện giả lập (nguồn B12 MKN-05)                                                            |
| KQ9  | [W1] Hiệu lực của đóng băng và tắt khẩn cấp ở mọi tiến trình                                                          | giây (tối đa)                                     | chưa biết (hôm nay chưa có công tắc)              | ≤ 5 giây                                                                    | Số lần từ chối nhầm khi không có công tắc nào bật bằng 0 (công tắc quá nhạy chặn việc thật).                                                                                               | Test đặt công tắc giữa lượt chạy rồi đếm lời gọi tới nhà cung cấp giả (nguồn B10a KF-08)                              |
| KQ10 | [W1] Tự chủ của người dựng: người không lập trình đổi ngưỡng điểm và người duyệt rồi phát hành lại                    | phút                                              | chưa biết                                         | ≤ 30 phút, không cần kỹ sư                                                  | Số phiên bản bị cổng chặn hay bị gỡ trong 7 ngày sau đó không tăng (phát hành vội sẽ hiện ở đây).                                                                                          | Phiên quan sát với một người dựng thật ở cuối W1 và ở W2 (nguồn B12 MET-08)                                           |
| KQ11 | [W2] Trợ lý Marketing: câu trả lời đúng có trích dẫn trên 30 câu chuẩn; số lần lộ trường Đã ẩn                        | %, số lần                                         | chưa biết                                         | ≥ 85%; 0                                                                    | Tỷ lệ câu "tôi không biết" không vượt 10% (trợ lý né trả lời để không sai sẽ hiện ở đây).                                                                                                  | Bộ 30 câu chuẩn ở cổng phát hành; quét câu trả lời tìm giá trị đã gieo của trường ẩn (nguồn B12 MET-09)               |
| KQ12 | [W2] Chi phí AI mỗi lead đủ điều kiện                                                                                 | USD chi phí ước tính mỗi lead (đơn vị theo DO-59) | chưa biết                                         | đặt sau 2 tuần chạy bóng (F6); trước đó không vượt trần tháng của workspace | Chất lượng chấm điểm (KQ4) không giảm (đổi sang model rẻ hơn để hạ chi phí sẽ hiện ở đó).                                                                                                  | Sổ sử dụng gộp theo quy trình chia cho sự kiện kết quả `lead.qualified` (nguồn B12 MET-07)                            |
| KQ13 | [W2] v1 GA: bốn lớp quyền trên bản ghi của D3 có test âm ở mọi đường ra (API, agent, quy trình, tìm kiếm, xuất)       | % ô (lớp × đường ra) có test âm đã thấy đỏ        | chưa biết (W1 chỉ có lớp a)                       | 100%                                                                        | Danh sách bản ghi vẫn p95 ≤ 50 ms ở cỡ D12, tức 10 triệu bản ghi mỗi đối tượng và 50 triệu mỗi tenant (thêm lớp quyền làm chậm danh sách sẽ hiện ở đó).                                    | Ma trận kiểm soát của record-access và field-security, chạy đột biến ở CI (nguồn B4 REC-NF2)                          |
| KQ14 | [W2] v1 GA: thời gian từ khi cài gói Marketing vào công ty mới tới lead đầu tiên vào quy trình                        | ngày làm việc                                     | chưa biết                                         | ≤ 1 ngày làm việc, không cần kỹ sư nền tảng                                 | Số lần nhà vận hành can thiệp dữ liệu hay cấu hình cho khách mới bằng 0.                                                                                                                   | Đo trên công ty thí điểm thứ hai bằng nhật ký kiểm toán (cài gói tới `studio.record.created` đầu tiên) (nguồn B12 12) |

Đích của KQ1 tới KQ6, KQ10 và KQ11 là đề xuất của brief sản phẩm B12, xác nhận với khách thí điểm trước chạy bóng (DO-22, lựa chọn tạm ở Quyết định). Đối trọng là chỉ số sẽ cho thấy kết quả đang bị làm đẹp.

## Bằng chứng

- Hôm nay một miền nghiệp vụ vào nền tảng chỉ qua một bounded context viết bằng mã, với mười lăm điểm cắm và migration riêng, nên nhu cầu mới của một công ty là việc của kỹ sư và một bản phát hành. Nguồn: `CLAUDE.md`, mục "Adding a bounded context (the plug-in points)". Tin cậy: cao.
- Vai trò và bộ quyền là danh mục chung của cả deployment, chỉ đổi qua migration; cả deployment dùng một bộ khóa model; không gói nào có trần chi tiêu theo ngày, và sổ sử dụng theo lượt gọi đã bị gỡ ngày 21/09/2026 vì không ai đọc. Nguồn: [research.md](discovery/research.md) mục 2, 9 và 11 (đọc mã). Tin cậy: cao.
- Nền móng có lỗ đã đo: đăng nhập nối định danh mới theo email chữ thường trên bảng người dùng chung, không lọc công ty, là đường chiếm tài khoản khi công ty mang nhà cung cấp danh tính riêng; token còn hợp lệ 8 giờ sau khi nhà cung cấp danh tính khóa một người; bộ chặn địa chỉ nội bộ để lọt dải CGNAT và có cửa sổ đổi DNS giữa lúc kiểm và lúc kết nối. Nguồn: [research.md](discovery/research.md) mục 13 và 8 (đo 22/10/2026). Tin cậy: cao.
- Môi trường chạy mã hiện có chạy mọi lời gọi trong một container và tối đa một lời gọi cùng lúc, nên không dùng được cho mã của công ty (D7). Nguồn: [research.md](discovery/research.md) mục 10 (đọc mã). Tin cậy: cao.
- Đối thủ chang.fpt.net đã cho người không lập trình dựng agent, quy trình, bộ đề kiểm định và một control plane, nhưng ảnh không cho thấy công ty hay workspace, quyền theo bản ghi hay trường; nút Publish vẫn hiện trên năm dòng kiểm định trượt; id quản trị là số nguyên; trang quản trị hiện "Not secure". Nguồn: [teardown-chang.md](discovery/teardown-chang.md), "Điểm yếu quan sát được" 1 tới 5 (tám ảnh chụp ngày 22/10/2026, chưa kiểm bằng tài khoản). Tin cậy: vừa.
- Luật 91/2025/QH15 và Nghị định 356/2025/NĐ-CP có hiệu lực từ 01/01/2026 với hạn cụ thể: trả lời chủ thể dữ liệu trong 2 ngày làm việc, báo sự cố trong 72 giờ, nộp hồ sơ chuyển dữ liệu ra nước ngoài trong 60 ngày, phạt tới 5% doanh thu năm trước; Luật AI 134/2025/QH15 có hiệu lực từ 01/03/2026. Nguồn: [research.md](discovery/research.md) mục 12 (bản dịch tiếng Anh không chính thức và bài của hãng luật). Tin cậy: vừa.
- Các hãng lớn hội tụ về một bộ khái niệm điều khiển agent: sổ đăng ký có vòng đời duyệt, người chịu trách nhiệm cho mỗi agent, chính sách ép ở cổng công cụ ngoài model, kiểm định trước phát hành và hạn mức có dừng cứng. Nguồn: [research.md](discovery/research.md) mục 16; [brainstorm.md](discovery/brainstorm.md), "Thị trường cuối 2026" (tài liệu của hãng). Tin cậy: cao.
- Không sản phẩm nào gộp đủ cô lập công ty và workspace, quyền tới bản ghi và trường, đối tượng tùy biến, quy trình kéo thả, MCP, hạn mức và vòng đời; đối thủ Việt Nam bán bằng mẫu theo ngành và xử lý trong nước, ít công bố về quản trị. Nguồn: [research.md](discovery/research.md) mục 16 (nhận định tổng hợp của nghiên cứu, không phải số đo). Tin cậy: thấp.
- Mua hay nhúng bị giấy phép loại: n8n, Dify và Windmill cấm vận hành đa tenant hay phục vụ như dịch vụ, Activepieces và Kestra để đa tenant ở bản trả phí, còn Nango, NocoDB và Directus cũng có điều khoản loại cách dùng này. Nguồn: [research.md](discovery/research.md) mục 1, 3 và 8. Tin cậy: cao.
- Chế độ thử của nhà cung cấp không tin được: sự kiện thử gửi tới Meta vẫn được dùng để nhắm quảng cáo, và API gửi tin ZNS không có tham số thử, nên chạy không tác động phải được ép ở điểm tác động của nền tảng. Nguồn: [research.md](discovery/research.md) mục 14. Tin cậy: cao.
- Biểu thức chạy được mã là mặt tấn công đã bị khai thác (một lỗ RCE của n8n vào danh sách KEV của CISA ngày 11/03/2026), nên văn bản do công ty viết phải được tính bằng một ngôn ngữ biểu thức có trần. Nguồn: [research.md](discovery/research.md) mục 3. Tin cậy: cao.
- Quyết định quyền trên bản ghi ngay trong cơ sở dữ liệu là khả thi ở 2 triệu bản ghi: điều kiện mức truy cập trên cột có index cộng một mảng ngoại lệ trả trang đầu trong 0,13-0,4 ms, so với 1,1-1,4 s khi join bảng chia sẻ theo từng bản ghi. Nguồn: [research.md](discovery/research.md) mục 2 (đo 22/10/2026). Tin cậy: vừa.

## Bằng chứng ngược

- Thị trường đang bỏ sơ đồ vẽ agent: OpenAI đóng Agent Builder và Evals ngày 30/11/2026, Flowise thành repo chỉ đọc ngày 13/08/2026, Copilot Studio tách harness tất định khỏi harness tự tìm đường. D2 nói kéo thả; kế hoạch chỉ vẽ quy trình tất định và cấu hình agent bằng biểu mẫu, nhưng một sản phẩm sơ đồ vẫn có thể chết như Flowise. Nguồn: [research.md](discovery/research.md) mục 16; [brainstorm.md](discovery/brainstorm.md), "Người đặt yêu cầu đã nói rõ" điểm 1. Tin cậy: cao.
- Nghi thức spec-driven có giá và chưa được chứng minh: thử nghiệm ngẫu nhiên của METR thấy lập trình viên giàu kinh nghiệm chậm hơn 19% khi dùng AI, tệp ngữ cảnh kiểu AGENTS.md có xu hướng giảm tỉ lệ thành công và tăng chi phí, Thoughtworks cảnh báo "agent instruction bloat"; bộ tài liệu này (100 YC, 26 ADR, 25 spec, 91 ticket W1) là đúng loại chi phí đó, và chưa có đánh giá có đối chứng nào cho thấy nó làm kết quả tốt hơn. Nguồn: [research.md](discovery/research.md) mục 17. Tin cậy: vừa.
- Khối lượng lớn so với nhịp đã đo: các kế hoạch của repo đã đóng 22 ticket kể từ khi kế hoạch đầu tiên vào repo ngày 29/09/2026, khoảng 6 ticket mỗi tuần; W1 của Studio có 91 ticket, khoảng bốn lần số đó, và W2 (35 YC) chưa cắt ticket. Nguồn: đếm `Status: resolved` trong `.claude/plans/*/*/issues/` và `git log` ngày 23/10/2026; [studio.md](../studio.md). Tin cậy: vừa.
- Quy mô D12 chưa được đo: mọi số đo quyền dưới RLS chạy ở 1,2 tới 2 triệu bản ghi trên máy dev, chưa số nào ở 10 triệu bản ghi mỗi đối tượng hay trên host thật (2 vCPU / 8 GB hôm nay, ít nhất 4 vCPU / 16 GB sau D14); toán tử không leakproof (jsonb, numeric, LIKE, mảng) mất index dưới RLS và rơi về quét cả tenant, khoảng 1,1-1,2 s mỗi 1 triệu bản ghi. Nguồn: [research.md](discovery/research.md) mục 1, 2 và "Giới hạn chung của đợt nghiên cứu". Tin cậy: cao.
- Động cơ chạy hiện có chưa chở nổi tải của Studio: saver checkpoint không chở nổi 100 lượt chạy có đầu ra 100 KB, và một map 100 phần tử ở 1000 lượt chạy cùng lúc làm 506 lượt hỏng vì hết pool kết nối. Nguồn: [research.md](discovery/research.md) mục 5 (đo trên container 4 vCPU / 3 GiB, không phải host thật). Tin cậy: vừa.
- Rủi ro pháp lý chưa ai ký nhận: Điều 21 Nghị định 356 có thể xếp Studio vào dịch vụ xử lý dữ liệu cá nhân cần giấy chứng nhận của Bộ Công an (Điều 24-25); chưa có ý kiến luật sư Việt Nam, và luật được đọc qua bản dịch không chính thức. Nguồn: [research.md](discovery/research.md) mục 12. Tin cậy: vừa.
- Thứ D8 và D13 dựa vào có chuỗi cung ứng đã bị chiếm: thư viện cổng model bị chiếm hai lần năm 2026 (24/03 và 21/10, điều tra chưa xong) và có khoảng 17 advisory trong năm; một thư viện MCP có lỗ RCE mức Critical phía client ngày 16/10/2026. Nguồn: [research.md](discovery/research.md) mục 9 và 7. Tin cậy: cao.
- Thời gian duyệt của nhà cung cấp, không phải mã, quyết ngày thí điểm có Zalo và Facebook: Meta cần App Review và xác minh doanh nghiệp, còn ZNS không công bố chế độ thử. Nguồn: [brainstorm.md](discovery/brainstorm.md), "Người đặt yêu cầu đã nói rõ" điểm 3. Tin cậy: vừa.
- Thị trường dùng môi trường làm đường đổi an toàn (Copilot Studio khuyên ít nhất ba môi trường, Workato có DEV, TEST, PROD), còn D1 không cho workspace làm môi trường; khách quen Power Platform sẽ hỏi "dev, test, prod ở đâu". Nguồn: [brainstorm.md](discovery/brainstorm.md), "Người đặt yêu cầu đã nói rõ" điểm 4. Tin cậy: vừa.
- Chưa có khách thí điểm có tên, người tài trợ hay cam kết nào: DO-22 mới được trả lời tạm là "một đội marketing thật", và mọi đích của KQ là đề xuất của brief sản phẩm. Nguồn: [map.md](discovery/map.md), "Lựa chọn tạm của agent". Tin cậy: cao.
- Thị trường để người duyệt thứ hai là tùy chọn (duyệt khi triển khai của Workato còn là beta), còn với D11 một công ty chỉ có một quản trị viên thì không phát hành được gì. Nguồn: [brainstorm.md](discovery/brainstorm.md), "Người đặt yêu cầu đã nói rõ" điểm 5, nơi chính brainstorm ghi bằng chứng này yếu. Tin cậy: thấp.
- Đã tìm bằng chứng thị trường ngược với D3, D6, D7 và D8 trong research và brainstorm, không thấy; cái giá của các quyết định đó là hạ tầng của ta (D14). Nguồn: [brainstorm.md](discovery/brainstorm.md), cuối mục "Người đặt yêu cầu đã nói rõ". Tin cậy: vừa.

## Phương án

### A — Nhỏ nhất làm được

- Phác thảo: chỉ W1 (65 YC). Vá các lỗi P0 đã đo ở nền tảng, dựng khung Studio và chuẩn ứng dụng, rồi làm lát Marketing mỏng trên một công ty thí điểm có hai workspace ngang hàng: Lead và Campaign tạo qua API công khai, vai trò ba mức, lớp (a) của quyền trên bản ghi, bảo mật trường, nguồn dữ liệu từ form website, chấm điểm bằng AI, giao Sales, một phê duyệt, một email qua hộp thư của chính công ty, Mô phỏng, cổng phát hành hai người, đóng băng và tắt khẩn cấp, sổ sử dụng và hạn mức cứng, lịch sử chạy; chỉ lead giả lập (YC89). W1 khép ở email đầu tiên đã duyệt của một lượt chạy Thật (YC94).
- Ngân sách thời gian: 4 tháng (đề xuất tạm của agent, chờ Đạt đặt; xem Quyết định ngày 23/10/2026).
- Đánh đổi: được bằng chứng rằng Studio dựng được chỉ qua bề mặt tenant (YC2) và mọi ranh giới tin cậy có test âm (KQ6) trước khi chạm dữ liệu thật; mất Zalo, Facebook, chăm sóc lead, ba lớp quyền còn lại của D3, model của công ty và bước mã, nên chưa bán được như v1 vì D3 đòi đủ bốn lớp ở v1.
- Chỗ dễ sa lầy: quyền trên bản ghi ở cỡ D12, nơi số đo của record-access/01 có thể buộc làm lại; động cơ chạy bền (tiếp tục sau khi dừng, mỗi tác động đúng một lần, công bằng giữa các công ty); và nghi thức spec cho 91 ticket.

### B — Không làm gì

- Phác thảo: Studio không được dựng; mỗi miền của khách vẫn là một bounded context viết bằng mã theo `CLAUDE.md`, và thí điểm Marketing (D4) hoặc thành một sản phẩm viết cứng, hoặc không chạy.
- Ngân sách thời gian: không.
- Đánh đổi: được không thêm bề mặt nào phải bảo vệ và giữ đội cho sản phẩm hiện có; mất thí điểm D4, mỗi khách mới thành một nhánh mã hay dự án tùy biến, và câu chuyện không viết mã thuộc về đối thủ.
- Chỗ dễ sa lầy: khách tự ghép công cụ ngoài, nên dữ liệu cá nhân của lead đi qua chỗ PDPL không kiểm được; các lỗi P0 đã đo vẫn còn nếu không có việc riêng để vá.

### C — v1 GA một lần

- Phác thảo: dựng đủ 100 YC của W1 và W2 (bốn lớp quyền của D3, model của công ty, bước mã, Zalo, Facebook, chăm sóc lead, gói nghiệp vụ, MCP) rồi mới chạy thí điểm.
- Ngân sách thời gian: 9 tháng (đề xuất tạm của agent, chờ Đạt đặt; W2 chưa cắt ticket nên số này yếu hơn số của A).
- Đánh đổi: được một v1 bán được ngay lần gặp khách đầu; mất mọi phản hồi từ thí điểm cho tới khi phần lớn việc đã xong, trong khi duyệt của nhà cung cấp và ý kiến luật sư vẫn quyết ngày chạy thật.
- Chỗ dễ sa lầy: chạy mã của công ty trên một VM chưa biết có ảo hóa phần cứng không, bốn lớp quyền ở cỡ D12, chuỗi cung ứng của cổng model, và W2 chưa cắt ticket.

Đề xuất: A, rồi phần W2 của C chỉ sau khi W1 đo được KQ3 và KQ6 tới KQ10 và qua lần kiểm nhất quán của W1, vì A thử rẻ nhất các giả định rủi ro nhất (chỉ qua bề mặt tenant, cô lập công ty, động cơ chạy) trong khi hồ sơ nhà cung cấp và ý kiến luật sư, đường găng thật của W2, chạy song song từ tuần đầu; B bỏ D4, còn C đặt cược chín tháng mà không có phản hồi của thí điểm. Đây cũng là thứ tự của roadmap.

## Câu hỏi hoài nghi

- Phần khó nhất về kỹ thuật là gì, và repo này đã làm thứ gì gần giống chưa? Quyết định ai thấy bản ghi nào ở một chỗ cho mọi đường (API, agent, quy trình, xuất, lane nền) ở cỡ D12, và lượt chạy bền với mỗi tác động đúng một lần. Repo đã có RLS FORCE được test trên mọi bảng tenant, phê duyệt tạm dừng rồi tiếp tục một lượt chạy có checkpoint, outbox và khóa chống lặp; chưa có lược đồ do công ty định nghĩa, quyền theo từng bản ghi hay hàng đợi lượt chạy. Số đo ở 2 triệu bản ghi hứa hẹn, ở 10 triệu chưa có (record-access/01). Kết luận: chưa chắc.
- Điều gì ta chưa biết cách làm, và phải tốn gì để biết? Chạy mã của công ty trong container mới trên VM riêng của D14, nơi chưa biết có ảo hóa phần cứng không, chọn runtime cho ngôn ngữ biểu thức, chạy agent của công ty dưới runner có checkpoint, cỡ checkpoint khi chạy đông, token và chữ ký của Zalo ZNS, hành vi của cổng model theo từng nhà cung cấp. Mỗi điều là một spike W1 hay một ticket khám phá trong [map.md](discovery/map.md), trả lời bằng số đo trước khi ADR của nó được chấp nhận; cái giá là các spike P0 của W1. Kết luận: chưa chắc.
- Ta dựa vào thứ gì ngoài tầm tay (thư viện, nhà cung cấp, area khác), và nếu nó đổi thì sao? Thư viện điều phối lượt chạy (hành vi tiếp tục đổi theo phiên bản), deepagents (khoảng 15 bản trong năm tuần), cổng model mà D8 chọn (bị chiếm hai lần năm 2026), SDK MCP (mới và nhiều advisory), duyệt ứng dụng của Meta, Zalo, Google (vài tuần) và luật sư. Đỡ bằng ghim đúng phiên bản và đo lại mỗi lần nâng (`.claude/rules/failure-modes.md` mục 4), cổng model của công ty là lane riêng không trạng thái (D13), và hồ sơ nhà cung cấp nộp từ tuần đầu W1. Kết luận: chưa chắc.
- Ai dùng nó trong tuần đầu, và điều gì khiến họ quay lại hay bỏ đi? Chưa biết: chưa có khách thí điểm có tên (DO-22 tạm nói một đội marketing thật, dữ liệu giả lập tới khi ký DPA). Người dựng của đội đó quay lại nếu đổi ngưỡng điểm và phát hành lại trong 30 phút mà không cần kỹ sư (KQ10); họ bỏ nếu hàng duyệt chậm (KQ2) hay công ty chỉ có một quản trị viên (D11). Cách biết: người đặt yêu cầu chọn đội, người tài trợ và đích theo DO-22; hạn: trước chạy bóng. Kết luận: chưa chắc.
- Xong rồi thì ai giữ nó chạy, và mỗi tháng tốn gì? Đội nền tảng vận hành thêm kho bí mật, proxy ra ngoài, cổng MCP, lane model của công ty và VM chạy mã (D14), cộng các lane giữ hạn lưu và phân vùng. Chi phí tháng chưa biết; cách biết: đo bộ nhớ trên host trước khi chốt cỡ (D14), và chi phí AI mỗi lead (KQ12) sau 2 tuần chạy bóng. Kết luận: chưa chắc.
- Làm cái này thì phải nói không với việc gì? Với sản phẩm bounded context mới trong lúc làm W1 và W2, giao diện tiếng Anh (DO-57), SCIM và tự cấu hình SSO, công ty thử nghiệm, máy chủ MCP của nền tảng, chat với lead và trợ lý AI dựng quy trình (Không làm), và với khách chỉ có một quản trị viên (D11). Kết luận: vững.
- Điều gì giết area này; có dữ liệu cá nhân hay ràng buộc pháp lý nào? Một lần đọc chéo công ty (YC3), một tin gửi khi thiếu đồng ý (KQ6), một bí mật của công ty lộ qua thư viện bị chiếm, hay Nghị định 356 đòi giấy chứng nhận dịch vụ xử lý dữ liệu cá nhân trước khách trả tiền đầu tiên (DO-53). Lead mang số điện thoại, email, Zalo id và bản ghi đồng ý; YC89 giữ lát W1 trên lead giả lập tới khi có ý kiến luật sư. Cách biết: ý kiến luật sư, bắt đầu tuần đầu W1; hạn: trước chạy bóng trên dữ liệu thật. Kết luận: chưa chắc.
- Vì sao là bây giờ, và nó thay thế hay làm yếu thứ gì đang có? Luật 91/2025/QH15 có hiệu lực từ 01/01/2026 và Luật AI từ 01/03/2026, các hãng hội tụ về bộ khái niệm điều khiển agent trong 2026, và người đặt yêu cầu đã chọn hướng cùng miền thí điểm ngày 22 và 23/10/2026. Nó thay danh mục vai trò chung bằng vai trò là dữ liệu của công ty, đưa sổ sử dụng trở lại (đảo migration `aefe7c1f5d9b`), và sửa ba chỗ của `CLAUDE.md` (nền tảng AI chứ không phải khung ứng dụng chung, mọi bảng tenant có `workspace_id`, chỉ antd) khi ADR-0100 (Proposed) và ADR-0101 (Proposed) được chấp nhận. Kết luận: vững.
- Câu nào ta ngại hỏi nhất ở đây, và câu trả lời thật là gì? Có ai trả tiền cho Studio không, và đội có dựng nổi nó trước khi thị trường đổi tiếp không. Câu trả lời thật là chưa biết: chưa có khách thí điểm có tên, chưa có giá (DO-59), và W1 lớn khoảng bốn lần số ticket repo đã đóng. W1 khép ở email đầu tiên đã duyệt (YC94) và ticket W2 chỉ được cắt sau lần kiểm nhất quán của W1, nên đó là chỗ quyết có làm tiếp hay không. Kết luận: nứt.

## Ràng buộc

- D1-D14 và ADR-0100 (Proposed) tới ADR-0125 (Proposed): hướng do người đặt yêu cầu chọn ngày 22/10 và 23/10/2026, riêng ADR-0108 (Proposed), ADR-0109 (Proposed), ADR-0113 (Proposed), ADR-0116 (Proposed) và ADR-0122 (Proposed) do agent đề xuất ngày 23/10/2026; Đạt chưa duyệt ADR nào. Cách làm của mọi YC ở đây nằm ở các ADR đó, nên một ADR đổi thì các YC dựa vào nó được xem lại.
- `CLAUDE.md`, đầu tệp và mục "Adding a bounded context (the plug-in points)": nền tảng nhận miền nghiệp vụ chỉ qua bounded context; Studio là một chỗ cắm khác, nên chỉ được dựng khi ADR-0100 (Proposed) được chấp nhận cùng các sửa đổi nó ghi.
- `CLAUDE.md`, mục "A second language, and where its boundary has to be": câu "an AI platform, not a general application framework" trái với một hệ thống ghi chép do công ty định hình (YC2, YC25); câu ấy chỉ đổi khi ADR-0100 (Proposed) được chấp nhận.
- `CLAUDE.md`, mục "Non-negotiable architecture": agent và quy trình do công ty dựng gây tác động thật, nên mọi luật về chính sách, khóa chống lặp, kiểm toán, phê duyệt, phiên bản và không siêu agent của mục này áp nguyên cho chúng (YC30, YC32, YC57, YC59, YC82).
- `CLAUDE.md`, mục "Tenancy and authorization": dữ liệu Studio là dữ liệu của công ty, nên YC3, YC14, YC15 và YC18 chịu nguyên mục này; định nghĩa đối tượng toàn công ty cần một ngoại lệ cho câu "mọi bảng tenant có `workspace_id`", ghi ở ADR-0100 (Proposed).
- `CLAUDE.md`, mục "Per-tenant artifacts": YC37 cho mỗi công ty bản riêng của prompt, công cụ, hồ sơ model và chính sách, nên việc rơi về và việc lấy công ty phải theo đúng mục này.
- `CLAUDE.md`, mục "Agent and tool rules": Studio thêm cửa vào lượt chạy (nguồn dữ liệu, lịch, sự kiện bản ghi), nên quota của gói (YC77), đầu vào không tin cậy trong prompt (YC48) và kiểm toán của lane nền (YC82) phải áp ở mọi cửa đó.
- `CLAUDE.md`, mục "Data model rules": sổ sử dụng, bước chạy và sự kiện vào là kho chỉ thêm không giới hạn, và danh sách bản ghi phân trang ở cỡ D12 (YC20, YC76, YC88), nên chịu luật phân vùng và index của mục này.
- `CLAUDE.md`, mục "Web UI": sơ đồ quy trình (YC39) cần một thư viện ngoài antd, chỉ được khi ADR-0101 (Proposed) được chấp nhận và mục này sửa.
- `CLAUDE.md`, mục "Environments": uat và production theo cùng luật, nên TLS (YC92) và VM riêng cho mã của công ty (D14) áp cho cả hai, không chỉ production.
- `CLAUDE.md`, mục "Observability and evaluation": mỗi agent và quy trình công ty phát hành cần bộ kiểm định có prompt injection, đọc chéo công ty và thiếu bằng chứng (YC70), và trace chỉ mang định danh an toàn (YC80).
- D11, hai người luôn luôn: công ty chỉ có một quản trị viên thì không phát hành được gì, nên bán hàng phải nói Studio cần ít nhất hai quản trị viên (ADR-0110 (Proposed), ADR-0120 (Proposed)).
- D12, quy mô: 10 triệu bản ghi mỗi đối tượng, 50 triệu mỗi công ty, 5.000 người dùng, 200 workspace, cây workspace sâu 6; mọi số đo của kế hoạch theo cỡ này (ADR-0107 (Proposed)).
- D14, hạ tầng: kho bí mật và proxy ra ngoài chờ host chính lên ít nhất 4 vCPU / 16 GB, và mã của công ty chờ một VM riêng ở uat và production, nên YC61, YC63, YC69 và YC100 chờ hạ tầng (ADR-0115 (Proposed), ADR-0119 (Proposed)).
- Luật 91/2025/QH15 và Nghị định 356/2025/NĐ-CP (hiệu lực 01/01/2026): lead là dữ liệu cá nhân, nên hạn trả lời chủ thể, báo sự cố và hồ sơ chuyển ra nước ngoài bó YC84 tới YC91; Luật AI 134/2025/QH15 (hiệu lực 01/03/2026) bó YC93; mọi cách hiểu luật ở đây chờ ý kiến luật sư (ADR-0123 (Proposed), ADR-0124 (Proposed)).
- Giấy phép: bộ máy quy trình, kho tích hợp và sản phẩm sinh API có sẵn cấm hay thu phí vận hành đa tenant ([research.md](discovery/research.md) mục 1, 3, 8 và 15), nên Studio tự dựng trên nền tảng hiện có, và thứ gì nhúng vào phải có giấy phép cho vận hành đa tenant có thu phí.

## Câu hỏi còn mở

- Q1. Quy trình con và agent liên kết sâu tối đa 3 cấp (B7a WFE-17, B9 AGT-16, và ADR-0117 (Proposed) cho chuỗi agent) hay 4 (B7b NODE-22)? Chủ: Đạt, khi duyệt ADR-0112 (Proposed). Chặn: YC45, YC57.
- Q2. Nguồn dữ liệu trả lời trong p95 ≤ 1 giây (B12 MKN-05, như YC44 và KQ8) hay dưới 1 giây ở p99 (B7a DHB-02, như ADR-0113 (Proposed))? Chủ: Đạt, theo số đo của spec `workflow-triggers`. Chặn: YC44, KQ8.
- Q3. Tóm tắt ticket workflow-triggers/02 không nêu giới hạn 60 sự kiện mỗi phút mỗi nguồn dữ liệu của YC44: giới hạn đó có ở W1 không? Chủ: Đạt. Chặn: YC44.
- Q5. Trường do AI ghi có nguồn gốc và nhãn "AI" (YC29; B12 MKT-07 muốn ở P1) không có ticket W1: thêm vào W1 hay chấp nhận W2? Chủ: Đạt. Chặn: YC29.
- Q6. B12 muốn người dự phòng khi giao lead là nhóm "Bàn tiếp nhận lead", nhưng nhóm ở W2: W1 giao cho một người dự phòng đã cấu hình có đủ không? Chủ: Đạt. Chặn: YC50.
- Q8. Chi phí mỗi lead (KQ12) đo bằng đơn vị nào và đích là bao nhiêu, khi cách đóng gói và tính giá (DO-59) chưa chốt? Chủ: Đạt. Chặn: KQ12.
- Q9. Người dự phòng, cờ `Hạn chế xử lý` và sổ sự cố đến ở W2 trong khi bước AI và lát W1 đã dựa vào chúng: việc lát W1 chỉ chạy lead giả lập có đủ để không kéo chúng về W1 không? Chủ: Đạt. Chặn: YC89.

## Quyết định

- 22/10/2026 (người đặt yêu cầu): D1: dữ liệu thuộc về workspace, và workspace lồng thành cây; bản ghi có người phụ trách (người hay nhóm) và workspace sở hữu; vai trò cấp quyền theo mức truy cập; Marketing với tới Sales bằng quyền, không bằng sao chép. ADR-0102 (Proposed), ADR-0104 (Proposed).
- 22/10/2026 (người đặt yêu cầu): D2: người dựng là quản trị viên nghiệp vụ làm không viết mã (kéo thả bước, biểu mẫu cấu hình, biểu thức đơn giản, mẫu theo miền, dựng có AI); bước mã chỉ có sau một quyền riêng và quyền lợi của gói dịch vụ. ADR-0117 (Proposed), ADR-0119 (Proposed).
- 22/10/2026 (người đặt yêu cầu): D3: quyền trên bản ghi ở v1 đủ bốn lớp: (a) người phụ trách và mặc định truy cập theo đối tượng, (b) cấp trên thấy và sửa bản ghi của cấp dưới, (c) quy tắc chia sẻ theo tiêu chí và chia sẻ tay có hạn, (d) bảo mật trường áp cả cho agent và kết quả tìm kiếm. ADR-0105 (Proposed), ADR-0106 (Proposed).
- 22/10/2026 (người đặt yêu cầu): D4: lát thí điểm đầu là Marketing: lead từ form, Facebook, Zalo, chấm điểm và làm giàu bằng AI, tạo bản ghi, giao Sales, tin Zalo hay email sau phê duyệt; đây là ví dụ xuyên suốt và gói nghiệp vụ đầu tiên. ADR-0124 (Proposed).
- 22/10/2026 (người đặt yêu cầu): D5: si-platform là tham chiếu cộng port có chọn lọc; mọi chỗ khác si-platform ghi trong ADR, trích bằng repo và tên tệp. ADR-0100 (Proposed).
- 22/10/2026 (người đặt yêu cầu): D6: sổ sử dụng theo lượt gọi quay lại (phân vùng tháng, giữ 13 tháng), gồm embedding, rerank và chạy mã, có người đọc từ ngày đầu; vì đảo migration `aefe7c1f5d9b` nên cần Đạt đồng ý. ADR-0121 (Proposed).
- 22/10/2026 (người đặt yêu cầu): D7: v1 có bước mã; mỗi lần chạy mã của công ty là một container mới, không mạng, có trần CPU, bộ nhớ, tiến trình, đĩa và thời gian; môi trường chạy mã hiện có không dùng cho việc này. ADR-0119 (Proposed).
- 22/10/2026 (người đặt yêu cầu): D8: công ty kết nối model và khóa của chính mình qua LiteLLM ngay ở v1; hồ sơ model của nền tảng vẫn chọn theo agent trong danh sách gói cho phép. ADR-0118 (Proposed).
- 22/10/2026 (người đặt yêu cầu): D9: mọi tài liệu kế hoạch Studio nằm trong repo này, area `studio`.
- 22/10/2026 (người đặt yêu cầu): D10: người đặt yêu cầu sẽ có tài khoản thử trên chang.fpt.net; [teardown-chang.md](discovery/teardown-chang.md) mang danh sách kiểm cho tài khoản đó.
- 23/10/2026 (người đặt yêu cầu): D11 (DO-07): hai người luôn luôn cho mọi thay đổi cấu hình của công ty, mọi lần phát hành agent hay quy trình, bật lại sau tắt khẩn cấp, duyệt định nghĩa công cụ MCP và nới lộ trình dữ liệu; công ty một quản trị viên không phát hành được; chỉ xem lại sau thí điểm khi có số liệu. ADR-0110 (Proposed), ADR-0120 (Proposed).
- 23/10/2026 (người đặt yêu cầu): D12 (DO-14): quy mô v1 và 12-24 tháng tới là 10 triệu bản ghi mỗi đối tượng, 50 triệu mỗi công ty, 5.000 người dùng, 200 workspace, cây workspace sâu 6; bản ghi phân vùng băm theo công ty từ revision đầu; công ty vượt cỡ chuyển sang cell riêng; mọi số đo theo cỡ này. ADR-0107 (Proposed).
- 23/10/2026 (người đặt yêu cầu): D13 (DO-19): model của công ty đi qua một lane LiteLLM riêng, không trạng thái, ghim theo digest, không cơ sở dữ liệu, không khóa nhà cung cấp trong môi trường; nền tảng giữ khóa của công ty trong kho bí mật và tiêm theo từng lời gọi; gateway hiện có của người đặt yêu cầu chỉ phục vụ model của nền tảng; alias chưa khai nơi xử lý dữ liệu coi là nước ngoài. ADR-0118 (Proposed).
- 23/10/2026 (người đặt yêu cầu): D14 (DO-24): nâng host chính lên ít nhất 4 vCPU / 16 GB trước khi kho bí mật và proxy ra ngoài chạy, và thêm một VM riêng cho chạy mã trước khi mã của công ty chạy ở uat hay production; đo trước khi chốt cỡ. ADR-0115 (Proposed), ADR-0119 (Proposed).
- 23/10/2026 (agent, tạm): DO-04: giữ "workspace" làm từ trên giao diện cho đơn vị sở hữu dữ liệu. Nếu sai thì: dùng "Đơn vị" ở mọi nơi và đổi tên các màn đã có, hay "Phòng ban"; thuật ngữ của các YC, glossary và màn hình đổi theo.
- 23/10/2026 (agent, tạm): DO-08: tên API bất biến sau lần phát hành đầu; đổi tên là một thành phần mới cộng một lần chuyển đổi. Nếu sai thì: tên API đổi được với bí danh; YC25 và spec `tenant-config`, `custom-objects` đổi theo.
- 23/10/2026 (agent, tạm): DO-10: bộ quyền bổ sung là một loại vai trò; mức "Của nhóm tôi" là bản ghi của tôi và của nhóm tôi; tách nhiệm xét theo người trên cả công ty. Nếu sai thì: bỏ bộ quyền bổ sung, mức nhóm gồm cả bản ghi riêng của thành viên khác, tách nhiệm xét theo từng membership; YC12 và spec `tenant-rbac`, `record-access` đổi theo.
- 23/10/2026 (agent, tạm): DO-11: mặc định truy cập công khai nghĩa là toàn công ty; cấp trên trực tiếp xem và sửa bắc cầu, không xóa, có công tắc theo đối tượng; khi giao, người giao chọn, mặc định giữ workspace sở hữu; chia sẻ tay còn sau khi đổi người phụ trách và hiện trong hộp thoại giao. Nếu sai thì: theo các biến thể kiểu Salesforce (công khai trong cây con, chỉ cấp dưới trực tiếp, workspace theo người phụ trách, chia sẻ bị bỏ); YC17, YC21 và spec `record-access`, `marketing-pilot` đổi theo.
- 23/10/2026 (agent, tạm): DO-18: quy trình Chăm sóc lead ở W2; mọi tin gửi ra trong thí điểm đều được duyệt, mỗi tin một phê duyệt trong hàng chờ thao tác nhanh bằng bàn phím. Hỏi: Q10. Nếu sai thì: chăm sóc lead vào W1 với duyệt theo lô; YC98 đổi đợt và cách duyệt.
- 23/10/2026 (agent, tạm): DO-20: ứng dụng nền tảng cho Meta và Zalo, Page và OA của khách nối bằng OAuth, ứng dụng Google nội bộ của khách; hồ sơ duyệt nộp từ tuần đầu. Nếu sai thì: ứng dụng của pháp nhân vận hành, hay ứng dụng riêng của từng khách; spec `connections-and-vault` và lịch W2 của YC97 đổi theo.
- 23/10/2026 (agent, tạm): DO-22: khách thí điểm là một đội marketing thật, với dữ liệu giả lập tới khi ký DPA; đích của KQ1 tới KQ6, KQ10 và KQ11, vốn là đề xuất của B12, được xác nhận với khách trước chạy bóng. Hỏi: Q7. Nếu sai thì: chỉ đội nội bộ; các KQ đó đo trên đội nội bộ và giai đoạn chạy bóng của YC99 đổi.
- 23/10/2026 (agent, tạm): DO-23: tài khoản thử chang.fpt.net chỉ quan sát như người dùng thường; không quét, tải hay dò; không chép dữ liệu cá nhân vào repo. Nếu sai thì: thêm phần dò bảo mật khi có văn bản cho phép của chủ hệ thống, và chỉ kết luận vào repo.
- 23/10/2026 (agent, tạm): DO-26: chế độ Chạy thử chặn ghi bản ghi như Mô phỏng ở P1; vùng tạm theo lượt chạy ở v1.5. Nếu sai thì: bản ghi thật gắn nhãn thử rồi xóa sau, hay vùng tạm ngay bây giờ; YC34, YC36 và spec `tenant-config`, `custom-objects`, `workflow-engine` đổi theo.
- 23/10/2026 (agent, tạm): DO-28: đóng băng hủy lượt đang chạy ở cửa kế tiếp, giữ nguyên lượt đang chờ, từ chối quyết định duyệt. Nếu sai thì: đỗ lượt chạy lại rồi chạy tiếp; YC72 và spec `agent-lifecycle`, `workflow-engine` đổi theo.
- 23/10/2026 (agent, tạm): DO-30: phiên bản quy trình con và bước agent ghim lúc gửi kiểm định; lệch cấu hình đề xuất cập nhật. Nếu sai thì: chúng đi theo bản Đang dùng; YC32 và spec `workflow-nodes`, `agent-builder`, `agent-lifecycle` đổi theo.
- 23/10/2026 (agent, tạm): DO-31: phê duyệt hết hạn làm lượt chạy thất bại với `approval_expired`; không gì tự duyệt khi hết giờ. Nếu sai thì: hết hạn thì tự từ chối rồi đi tiếp; YC52 và spec `workflow-nodes` đổi theo.
- 23/10/2026 (agent, tạm): DO-36: người duyệt phải đọc được các trường mà phê duyệt hiển thị; ứng viên duyệt theo mức truy cập của vai trò qua cây workspace. Nếu sai thì: duyệt nội dung đã che, chỉ người trong workspace của lượt chạy; YC51 và spec `workflow-nodes`, `field-security`, `tenant-rbac` đổi theo.
- 23/10/2026 (agent, tạm): DO-37: `Điều kiện để lưu được` nghĩa là "phải đúng", viết bằng ngôn ngữ biểu thức duy nhất với vector thử port từ si-platform (ADR-0114 (Proposed)). Nếu sai thì: nghĩa là "báo lỗi khi đúng" và port bộ đánh giá của si-platform; YC28 và spec `custom-objects`, `workflow-nodes` đổi theo.
- 23/10/2026 (agent, tạm): DO-39: link nhận lời mời do quản trị viên chép; MFA cho người vận hành, nhân viên hỗ trợ và người giữ quyền trọng yếu; sự kiện vào trả 503 khi công ty bị khóa; người chịu trách nhiệm rời đi thì chặn phát hành, phiên bản Đang dùng vẫn chạy. Nếu sai thì: lời mời qua email, MFA cho mọi người, giữ sự kiện như khi đóng băng, chuyển trách nhiệm cho cấp trên trực tiếp; YC7, YC10, YC11 và spec `org-and-principals`, `workflow-triggers`, `agent-lifecycle` đổi theo.
- 23/10/2026 (agent, tạm): DO-43: không chuyển từ model của công ty sang model nền tảng trả phí, trừ một route thứ hai trên kết nối của chính công ty; model của công ty ở cấp công ty được dùng công cụ; không endpoint tại chỗ ở v1; token của model công ty chỉ tính vào trần do công ty đặt. Nếu sai thì: rơi về model nền tảng và không cho model của công ty dùng công cụ; YC58, YC79 và spec `model-connections`, `tools-and-skills`, `usage-and-limits` đổi theo.
- 23/10/2026 (agent, tạm): DO-45: bước mã chỉ Python 3.12, không JavaScript, không chạy script của kỹ năng ở v1; mỗi phiên agent một container, hủy khi lượt chạy xong, sau 15 phút rảnh hay sau 2 giờ; tính phí theo vCPU và GB đặt trước nhân thời gian. Nếu sai thì: thêm JavaScript, mỗi lệnh một container, tính phí theo CPU đo được; YC69 và spec `code-sandbox`, `usage-and-limits` đổi theo.
- 23/10/2026 (agent, tạm): DO-48: SMTP chung là đường email ở P1; chỉ kết nối dùng chung theo workspace; cùng Page hay OA nối bởi hai công ty thì gửi tới cả hai, luật sư xác nhận. Nếu sai thì: Gmail API và kết nối cá nhân ngay P1, từ chối lần nối thứ hai; YC62, YC64 và spec `connections-and-vault`, `marketing-pilot` đổi theo.
- 23/10/2026 (agent, tạm): DO-50: kỳ của hạn mức tính theo múi giờ công ty; chạm hạn mức cứng giữa lượt chạy thì dừng; dựng có AI, chạy thử và kiểm định trả từ ngân sách công ty với trần mục đích riêng; chỉ lượt chạy gốc tính vào số lượt mỗi ngày. Nếu sai thì: kỳ theo UTC, hạ sang model rẻ hơn thay vì dừng, đếm mọi lượt con; YC78, YC79 và spec `usage-and-limits` đổi theo.
- 23/10/2026 (agent, tạm): DO-57: chỉ giao diện tiếng Việt, dùng khóa thông điệp từ đầu; demo và thí điểm trên host uat ở Việt Nam có chứng chỉ hợp lệ và HSTS. Nếu sai thì: song ngữ ở v1 và demo trên máy dev, nơi chứng chỉ nội bộ làm trình duyệt cảnh báo; YC1, YC92 và spec `marketing-pilot`, `studio-skeleton` đổi theo.
- 23/10/2026 (người đặt yêu cầu): D12 trả lời Q4: YC20 và đối trọng của KQ13 đo ở cỡ D12 (10 triệu bản ghi mỗi đối tượng, 50 triệu mỗi công ty, 5.000 người dùng, 200 workspace, cây sâu 6) thay cho 10 triệu mỗi tenant của blueprint; ngưỡng p95 ≤ 50 ms giữ nguyên, và record-access/01 đo ở cỡ đó. Hỏi: Q4. Sửa: YC20, KQ13.
- 23/10/2026 (người đặt yêu cầu): D14 đổi máy của YC100: thí điểm định cỡ trên host chính đã nâng lên ít nhất 4 vCPU / 16 GB, còn mã của công ty chạy trên một VM riêng, thay cho máy 2 vCPU / 8 GB của blueprint. Sửa: YC100.
- 23/10/2026 (agent, tạm): Mâu thuẫn nguồn: YC44 và KQ8 nói p95 ≤ 1 giây, ADR-0113 (Proposed) nói dưới 1 giây ở p99; theo số chặt hơn (p99) cho tới khi Q2 được trả lời, vì đạt p99 thì đạt cả p95. Nếu sai thì: ADR-0113 (Proposed) nới về p95 và test của nguồn dữ liệu đo p95.
- 23/10/2026 (agent, tạm): Ngân sách thời gian ở Phương án là 4 tháng cho A và 9 tháng cho C, đề xuất để Đạt đặt: các kế hoạch của repo đóng khoảng 6 ticket mỗi tuần từ 29/09/2026, nên 91 ticket W1 là khoảng 15 tuần, và W1 cộng W2 khoảng gấp đôi. Nếu sai thì: Đạt đặt số khác; khi hết ngân sách, phạm vi W1 cắt theo đường găng tới email đầu tiên đã duyệt (YC94), không kéo dài hạn.
- 23/10/2026 (agent, tạm): Ứng viên Phân loại kết nối kiểu DLP (BS05): dừng; bằng chứng yếu. Nếu sai thì: một YC mới ở nhóm L và một dòng Lộ trình W2 cho `connections-and-vault`.
- 23/10/2026 (agent, tạm): Ứng viên Chạy bóng phiên bản mới trên lưu lượng thật (BS07): dừng; bằng chứng yếu. Nếu sai thì: một YC W3 ở nhóm N.
- 23/10/2026 (agent, tạm): Ứng viên Nhãn AI và nguồn gốc cho tin do AI soạn (BS09): cần làm rõ; bằng chứng yếu. Gộp vào Q5 và câu hỏi đã gửi luật sư về nhãn AI cho tin nhắn. Nếu sai thì: một YC W1 ở nhóm R.
- 23/10/2026 (agent, tạm): Ứng viên Chợ gói nghiệp vụ có duyệt (BS14): dừng; bằng chứng yếu. Nếu sai thì: một YC W3 ở nhóm H.
- 23/10/2026 (agent, tạm): Ứng viên Gửi lead đủ điều kiện về Meta qua Conversions API (BS22): dừng; bằng chứng chưa biết. Brainstorm xếp nó ở W2 của `marketing-pilot`, nhưng roadmap và YC không có nó. Nếu sai thì: một YC W2 ở nhóm R và một dòng Lộ trình cho `marketing-pilot`.
- 23/10/2026 (agent, tạm): Ứng viên Giải thích điểm lead và nguồn gốc của trường do AI ghi (BS30): cần làm rõ; bằng chứng yếu. Đã có YC29 ở W2; Q5 hỏi có kéo về W1 không. Nếu sai thì: YC29 đổi đợt.
- 23/10/2026 (agent, tạm): Ứng viên Lịch làm việc và ngày lễ Việt Nam, gồm Tết âm lịch (BS35): làm, như một phần của YC90, YC98 và KQ1, vốn đếm ngày và giờ làm việc; bằng chứng đủ. Nếu sai thì: lịch làm việc thành một YC riêng mà công ty cấu hình được, với một dòng Lộ trình riêng.
- 23/10/2026 (agent, tạm): Ứng viên Phí gói cộng tín dụng AI gộp theo tháng (BS41): cần làm rõ; bằng chứng yếu. Gộp vào Q8 và DO-59. Nếu sai thì: một YC W2 ở nhóm O.
- 23/10/2026 (agent, tạm): Ứng viên Định giá theo kết quả (BS42): dừng; bằng chứng yếu. Nếu sai thì: một YC W3 ở nhóm O sau khi KQ12 đo được chi phí theo kết quả.
- 23/10/2026 (agent, tạm): Dòng phụ của mỗi YC trong blueprint (spec phục vụ, nguồn trong brief, vì sao, ghi chú) không chép vào đây: đợt và loại gom ở đầu mục Yêu cầu, spec ở Lộ trình, phần đến sau ở Ngoài phạm vi của spec, xung đột thành Q1 tới Q3, Q5, Q6 và Q9, còn ghi chú đã có câu trả lời thành các dòng D12 (Q4), DO-22 (Q7) và DO-18 (Q10) ở đây. Nếu sai thì: thêm lại "vì sao" của từng YC thành một dòng ngay dưới nó.
