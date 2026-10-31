import type {
  DwClassStanding,
  WorkHolderKind,
  WorkStatus,
} from "@dw/api-client";

/**
 * What a Digital Worker's codes read as, and in which tone: the one table per
 * code, read by every DW screen (ui-quality §1). A tone is an antd Tag colour
 * the `@dw/ui` theme owns; a code the server sends and this table does not
 * know reads as itself, neutral, never as a known state.
 */
export interface Label {
  label: string;
  color: string;
}

const DW_STATE: Record<string, Label> = {
  draft: { label: "Bản nháp", color: "default" },
  operating: { label: "Đang chạy", color: "success" },
  paused: { label: "Tạm dừng", color: "warning" },
  retired: { label: "Đã nghỉ", color: "default" },
};

export const WORK_STATUS: Record<WorkStatus, Label> = {
  open: { label: "Mở", color: "default" },
  in_progress: { label: "Đang làm", color: "processing" },
  waiting_approval: { label: "Chờ duyệt", color: "warning" },
  waiting_timer: { label: "Chờ hẹn giờ", color: "geekblue" },
  handed_off: { label: "Đã bàn giao", color: "gold" },
  done: { label: "Xong", color: "success" },
  failed: { label: "Lỗi", color: "error" },
  cancelled: { label: "Đã hủy", color: "default" },
};

export const HOLDER_KIND: Record<WorkHolderKind, string> = {
  digital_worker: "Digital Worker",
  person: "Người",
};

/** "Tự động / Hỏi / Chặn" (D18): blocked is a hard stop, asking a wait. */
export const DECISION_MODE: Record<DwClassStanding["mode"], Label> = {
  auto: { label: "Tự động", color: "success" },
  ask: { label: "Hỏi", color: "warning" },
  blocked: { label: "Chặn", color: "error" },
};

/** The four fields of a handoff packet, in the order the spec lists them. */
export const HANDOFF_FIELDS = [
  ["problem", "Vấn đề"],
  ["context", "Bối cảnh"],
  ["tried", "Đã thử"],
  ["recommendation", "Đề xuất"],
] as const;

export function dwState(state: string): Label {
  return DW_STATE[state] ?? { label: state, color: "default" };
}

export function workStatus(status: string): Label {
  return (
    WORK_STATUS[status as WorkStatus] ?? { label: status, color: "default" }
  );
}

/** A step type as a person reads it; an unknown type reads as its code. */
const STEP_TYPE: Record<string, string> = {
  "ai.llm@1": "AI soạn",
  "human.approval@1": "Người duyệt",
  "tool.call@1": "Công cụ",
  "time.wait@1": "Chờ",
  "logic.switch@1": "Rẽ nhánh",
};

export function stepType(type: string): string {
  return STEP_TYPE[type] ?? type;
}

/** A lane's port: `approved`, `rejected`, `default`, `cases.<value>`. */
export function laneLabel(port: string): string {
  if (port === "approved") return "Khi duyệt";
  if (port === "rejected") return "Khi từ chối";
  if (port === "default") return "Trường hợp khác";
  if (port.startsWith("cases.")) return `Khi bằng "${port.slice(6)}"`;
  return port;
}
