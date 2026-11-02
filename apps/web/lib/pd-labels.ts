/**
 * Loại dữ liệu cá nhân và loại dữ liệu nhạy cảm as a person reads them
 * (compliance-pdpl R1.3). The codes belong to `dw_kernel.personal_data`;
 * `__tests__/pd-labels.test.ts` reads them from the generated
 * `contracts/jsonschema/pd_classification.json` and fails a code without a
 * label here, or a label for a code the kernel does not hold. Category words
 * are the glossary's (`docs/platform/CONTEXT.md`); sensitive types are the
 * points of Nghị định 356/2025/NĐ-CP Điều 4 khoản 1, shortened.
 */

export const PD_CATEGORY_LABELS: Readonly<Record<string, string>> = {
  none: "Không",
  basic: "Cơ bản",
  sensitive: "Nhạy cảm",
};

export const SENSITIVE_TYPE_LABELS: Readonly<Record<string, string>> = {
  racial_ethnic_origin: "Nguồn gốc chủng tộc, dân tộc",
  political_religious_views: "Quan điểm chính trị, tôn giáo, tín ngưỡng",
  private_life: "Đời sống riêng tư, bí mật cá nhân, bí mật gia đình",
  health: "Tình trạng sức khỏe",
  biometric_genetic: "Sinh trắc học, đặc điểm di truyền",
  sex_life_orientation: "Đời sống tình dục, xu hướng tình dục",
  crime_violation: "Tội phạm, vi phạm pháp luật",
  location: "Vị trí qua dịch vụ định vị",
  identity_credentials: "Tài khoản định danh điện tử, ảnh thẻ căn cước",
  financial: "Tài khoản ngân hàng, tài chính, tín dụng",
  behaviour_tracking: "Theo dõi hành vi trên không gian mạng",
  legally_confidential: "Dữ liệu pháp luật yêu cầu giữ bí mật",
};

/**
 * A code with no label (one the kernel gained before this table) reads as
 * "Loại chưa biết", never as the raw code and never as "Không": an unknown
 * category is not the absence of personal data.
 */
const UNKNOWN = "Loại chưa biết";

export function pdCategoryLabel(code: string): string {
  return PD_CATEGORY_LABELS[code] ?? UNKNOWN;
}

export function sensitiveTypeLabel(code: string): string {
  return SENSITIVE_TYPE_LABELS[code] ?? UNKNOWN;
}
