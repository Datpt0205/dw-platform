import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { NAV_ITEMS } from "../registry";

/**
 * The unit that owns data is called "workspace" on screen (DO-04); "phòng ban"
 * is not the glossary's word for it (org-and-principals R9.1).
 */
describe("workspace terminology", () => {
  it("no navigation item calls a workspace a department", () => {
    const text = JSON.stringify(NAV_ITEMS);
    expect(text).not.toMatch(/phòng ban/i);
  });

  it("the workspaces page does not call a workspace a department", () => {
    const page = readFileSync(
      resolve(__dirname, "../../../app/admin/workspaces/page.tsx"),
      "utf8",
    );
    expect(page).not.toMatch(/phòng ban/i);
  });
});
