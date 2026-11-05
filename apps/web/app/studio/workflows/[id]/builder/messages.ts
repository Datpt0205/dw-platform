/**
 * Every word the workflow builder shows, by key (DO-57: Vietnamese only in
 * v1, through message keys, so a second language is a second table). Step
 * and lane names are not here: they are the step's `description` or the
 * catalogue's `label_vi` (workflow-nodes R1.2), never translated by the page.
 */
export const BUILDER_MESSAGES = {
  "page.title": "Trình dựng quy trình",
  "page.noDraft.title": "Quy trình chưa có bản Nháp",
  "page.noDraft.description":
    "Trình dựng chỉ sửa bản Nháp. Quy trình này chưa có bản Nháp nào để sửa.",
  "page.notWorkflow": "Không tìm thấy quy trình này.",
  "view.canvas": "Sơ đồ",
  "view.outline": "Danh sách",
  "view.label": "Cách xem",
  "save.saving": "Đang lưu…",
  "save.saved": "Đã lưu",
  "save.failed": "Lưu thất bại",
  "save.retry": "Thử lại",
  "save.idle": "Chưa có thay đổi",
  "conflict.title": "Bản nháp đã đổi ở nơi khác",
  "conflict.description":
    "Một tab hay một người khác đã lưu bản nháp này sau khi bạn mở. Tự lưu đã dừng; nội dung bạn đang sửa vẫn còn trên trang tới khi bạn tải bản mới nhất.",
  "conflict.reload": "Tải bản mới nhất",
  "palette.title": "Chọn Loại bước",
  "group.trigger": "Kích hoạt",
  "group.ai": "AI",
  "group.data": "Dữ liệu",
  "group.logic": "Logic",
  "group.human": "Con người",
  "group.tool": "Công cụ",
  "palette.drag": "Kéo «{name}» vào một ô",
  "palette.search": "Tìm Loại bước",
  "palette.empty": "Không có Loại bước nào khớp",
  "palette.side": "Loại bước",
  "palette.dragHint": "Kéo một Loại bước vào một ô trên Sơ đồ.",
  "card.unknown": "Loại bước không có trong danh mục",
  "card.menu": "Thao tác",
  "card.drag": "Kéo để dời",
  "card.retry": "Thử lại ×{n}",
  "card.timeout": "Hết giờ {n} s",
  "card.onError": "Khi lỗi: {what}",
  "onError.fail": "Dừng quy trình",
  "onError.continue": "Bỏ qua và chạy tiếp",
  "onError.route": "Đi vào làn Khi lỗi",
  "lane.error": "Khi lỗi",
  "lane.root": "Quy trình",
  "menu.addBefore": "Thêm trước",
  "menu.addAfter": "Thêm sau",
  "menu.move": "Di chuyển…",
  "menu.addLane": "Thêm nhánh",
  "menu.removeLane": "Bỏ nhánh…",
  "menu.delete": "Xóa",
  "menu.copyRef": "Sao chép tham chiếu",
  "menu.addStep": "Thêm Bước",
  "slot.after": "Thêm Bước sau «{name}»",
  "slot.first": "Thêm Bước vào đầu «{lane}»",
  "slot.empty": "Thêm Bước vào «{lane}»",
  "slot.emptyText": "Thêm Bước",
  "move.title": "Di chuyển «{name}»",
  "move.target": "Chuyển tới",
  "move.ok": "Di chuyển",
  "move.first": "Vào đầu «{lane}»",
  "move.after": "Sau «{name}»",
  "addLane.title": "Thêm nhánh cho «{name}»",
  "addLane.key": "Khóa của nhánh",
  "addLane.port": "Nhánh",
  "addLane.ok": "Thêm nhánh",
  "addLane.exists": "Đã có nhánh này",
  "addLane.invalid": "Khóa của nhánh không được để trống",
  "removeLane.title": "Bỏ nhánh của «{name}»",
  "removeLane.lane": "Nhánh",
  "removeLane.ok": "Bỏ nhánh",
  "refused.into_itself": "Không dời được một Bước vào bên trong chính nó.",
  "refused.unknown_type":
    "Loại bước này không có trong danh mục nên không sửa được trên trang.",
  "refused.other": "Không làm được thao tác này.",
  "announce.added": "Đã thêm «{name}» vào {lane}, vị trí {n}.",
  "announce.moved": "Đã dời «{name}» sang {lane}, vị trí {n}.",
  "announce.deleted": "Đã xóa {names} khỏi {lane}.",
  "announce.laneAdded": "Đã thêm nhánh «{lane}» cho «{name}».",
  "announce.laneRemoved": "Đã bỏ nhánh «{lane}» của «{name}».",
  "announce.undo": "Đã hoàn tác.",
  "announce.redo": "Đã làm lại.",
  "announce.lane": "«{lane}» của «{parent}»",
  "deleted.title": "Đã xóa {names}",
  "deleted.undo": "Hoàn tác",
  copied: "Đã chép {ref}",
  "config.title": "Cấu hình «{name}»",
  "config.tab.fields": "Cấu hình",
  "config.tab.onError": "Khi lỗi",
  "config.name": "Tên Bước",
  "config.name.help": "Để trống thì Bước mang tên Loại bước.",
  "config.json.invalid": "Chưa đúng JSON",
  "config.unknown":
    "Loại bước này không có trong danh mục, nên trang không có biểu mẫu cho nó. Bộ kiểm khi gửi kiểm định báo Bước này.",
  "config.onError": "Khi Bước lỗi",
  "config.retry": "Số lần chạy tối đa",
  "config.backoff": "Giãn cách giữa các lần",
  "config.backoff.fixed": "Cố định",
  "config.backoff.exponential": "Tăng dần",
  "config.timeout": "Hết giờ sau (giây)",
  "goto.title": "Đi tới Bước",
  "goto.search": "Tìm Bước theo tên",
  "goto.empty": "Không có Bước nào khớp",
  "goto.hint": "Ctrl+K",
  "keys.hint":
    "Phím: ↑↓ giữa các Bước, ←→ giữa các làn, Enter mở cấu hình, Shift+F10 mở menu, Delete xóa, Ctrl+Z hoàn tác, Ctrl+Shift+Z làm lại, Ctrl+K đi tới Bước.",
  "canvas.label": "Sơ đồ quy trình",
  "a11y.node":
    "Bước trên Sơ đồ. Enter mở cấu hình, Shift+F10 mở menu thao tác, phím mũi tên đi giữa các Bước.",
  "a11y.edge": "Đường nối giữa hai Bước.",
  "a11y.handle": "Điểm neo của đường nối",
  "a11y.live": "Đã chọn một Bước.",
  "outline.label": "Danh sách Bước của quy trình",
  cancel: "Hủy",
  undo: "Hoàn tác",
  redo: "Làm lại",
} as const;

export type BuilderMessageKey = keyof typeof BUILDER_MESSAGES;

/** The Vietnamese text of one key, `{name}` placeholders filled in. */
export function bt(
  key: BuilderMessageKey,
  values: Record<string, string | number> = {},
): string {
  return BUILDER_MESSAGES[key].replace(/\{(\w+)\}/g, (_, name: string) =>
    name in values ? String(values[name]) : `{${name}}`,
  );
}

/** A search key: lower case, no diacritics, "đ" as "d", so "ha noi" finds
 * "Hà Nội" (ui-quality.md §8). */
export function fold(text: string): string {
  return text
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/đ/g, "d")
    .replace(/Đ/g, "D")
    .toLowerCase();
}
