/**
 * Every word `/studio` shows, by key (DO-57: Vietnamese only in v1, but through
 * message keys from the start, so a second language is a second table and not
 * an edit of every screen).
 */
export const STUDIO_MESSAGES = {
  "nav.label": "Studio",
  "nav.hint": "Đối tượng, quy trình, agent và kết nối của công ty",
  "menu.label": "Khu vực Studio",
  "menu.all": "Tất cả thành phần",
  "list.title": "Tất cả thành phần",
  "list.subtitle":
    "Mọi thành phần công ty dựng trong Studio mà bạn được xem, ở mọi workspace bạn với tới.",
  "list.column.apiName": "Tên API",
  "list.column.kind": "Loại",
  "list.column.version": "Phiên bản",
  "list.column.updatedAt": "Cập nhật (giờ Việt Nam)",
  "list.reload": "Tải lại",
  "list.noun": "thành phần",
  "list.empty.title": "Chưa có thành phần nào",
  "list.empty.description":
    "Thành phần công ty dựng trong Studio sẽ hiện ở đây. Chọn một khu vực ở menu Studio để tạo thành phần đầu tiên.",
} as const;

export type StudioMessageKey = keyof typeof STUDIO_MESSAGES;

/** The Vietnamese text of one key. */
export function t(key: StudioMessageKey): string {
  return STUDIO_MESSAGES[key];
}

/**
 * A kind's label: its area's label once a spec registers the kind
 * (`STUDIO_SECTIONS`), the kind's own code until then.
 */
export function kindLabel(
  kind: string,
  sections: readonly { key: string; label: string }[],
): string {
  return sections.find((section) => section.key === kind)?.label ?? kind;
}
