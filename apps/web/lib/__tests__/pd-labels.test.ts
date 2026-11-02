import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  PD_CATEGORY_LABELS,
  SENSITIVE_TYPE_LABELS,
  pdCategoryLabel,
  sensitiveTypeLabel,
} from "../pd-labels";

/**
 * compliance-pdpl R1.3: every `pd_category` and `sensitive_type` the kernel
 * holds has a Vietnamese label, and no label names a code it does not. The
 * codes come from the generated JSON Schema, never a list copied here.
 */

const SCHEMA = resolve(
  __dirname,
  "../../../../contracts/jsonschema/pd_classification.json",
);

type Property = { enum: (string | null)[] };
const properties = (
  JSON.parse(readFileSync(SCHEMA, "utf-8")) as {
    properties: Record<string, Property>;
  }
).properties;

function codes(property: string): string[] {
  const values = properties[property]?.enum ?? [];
  return values.filter((value): value is string => value !== null);
}

describe("personal-data labels", () => {
  it.each([
    ["pd_category", PD_CATEGORY_LABELS],
    ["sensitive_type", SENSITIVE_TYPE_LABELS],
  ] as const)("label exactly the codes of %s", (property, labels) => {
    const kernel = codes(property);
    expect(kernel.length).toBeGreaterThan(0);
    expect(Object.keys(labels).sort()).toEqual([...kernel].sort());
    for (const code of kernel) {
      expect(labels[code]?.trim()).toBeTruthy();
    }
  });

  it("reads an unknown code as unknown, never as none", () => {
    expect(pdCategoryLabel("sensitive")).toBe("Nhạy cảm");
    expect(pdCategoryLabel("restricted")).toBe("Loại chưa biết");
    expect(sensitiveTypeLabel("health")).toBe("Tình trạng sức khỏe");
    expect(sensitiveTypeLabel("other")).toBe("Loại chưa biết");
  });
});
