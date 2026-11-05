import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, test, type Page, type Route } from "@playwright/test";

/**
 * The workflow builder in a browser (workflow-builder-ui R2.2, R2.5, R2.6):
 * built only with the keyboard on the canvas, and through the outline at a
 * 320 px phone without sideways scroll. The artifact, the catalogue and the
 * draft are answered by `page.route` with F1 and the fake catalogue in the
 * route's shape, so the spec needs the running stack for the sign-in only
 * (the API on `E2E_API_URL` with the seed). Every PUT is kept to check
 * `If-Match`.
 */

const API_URL = process.env.E2E_API_URL ?? "http://127.0.0.1:8000";
const SUBJECT = "dev|chi.le";
const ARTIFACT = "00000000-0000-4000-8000-0000000000a1";
const FIXTURES = join(__dirname, "../lib/__fixtures__/workflows");

type FakeType = {
  type: string;
  label_vi: string;
  ports:
    | { kind: "none" }
    | {
        kind: "fixed";
        items: { name: string; label_vi: string; required: boolean }[];
      }
    | {
        kind: "map";
        key: string;
        default?: { name: string; label_vi: string };
      };
};

/** `catalogue.json` as `GET /api/v1/studio/node-types` answers it (the same
 * conversion as `lib/__tests__/workflow-catalogue.ts`). */
function nodeTypes() {
  const fake = JSON.parse(
    readFileSync(join(FIXTURES, "catalogue.json"), "utf8"),
  ) as {
    types: FakeType[];
  };
  return fake.types.map((t) => {
    const required: string[] = [];
    let ports: unknown = { kind: "fixed", ports: [] };
    if (t.ports.kind === "map") {
      required.push(t.ports.key);
      ports = {
        kind: "keyed",
        key: t.ports.key,
        default: t.ports.default ?? null,
      };
    } else if (t.ports.kind === "fixed") {
      for (const p of t.ports.items) if (p.required) required.push(p.name);
      ports = {
        kind: "fixed",
        ports: t.ports.items.map(({ name, label_vi }) => ({ name, label_vi })),
      };
    }
    return {
      type: t.type,
      label_vi: t.label_vi,
      config_schema: { type: "object", required, properties: {} },
      output: { kind: "fixed", schema: {} },
      error: { on_error: ["continue", "route"], schema: {} },
      ports,
      side_effect_level: "none",
    };
  });
}

async function login(page: Page): Promise<void> {
  const users = await (
    await page.request.get(`${API_URL}/api/v1/dev/demo-users`)
  ).json();
  const index = users.findIndex(
    (user: { subject: string }) => user.subject === SUBJECT,
  );
  expect(index).toBeGreaterThanOrEqual(0);
  await page.goto("/dev-login");
  const buttons = page.getByRole("button", { name: "Đăng nhập" });
  await buttons.first().waitFor({ state: "visible" });
  await buttons.nth(index).click();
  await page.waitForURL("**/");
}

async function serve(page: Page) {
  let version = 1;
  let document = JSON.parse(
    readFileSync(join(FIXTURES, "f1-lead-intake.json"), "utf8"),
  );
  const puts: { ifMatch: string | null; document: unknown }[] = [];
  const draft = () => ({
    artifact_id: ARTIFACT,
    id: "00000000-0000-4000-8000-0000000000d1",
    document_schema: "dw.workflow/v1",
    document,
    version,
    based_on_version_id: null,
  });
  await page.route("**/api/v1/studio/node-types", (route) =>
    route.fulfill({ json: { catalogue_hash: "e2e", types: nodeTypes() } }),
  );
  await page.route(`**/api/v1/studio/artifacts/${ARTIFACT}`, (route) =>
    route.fulfill({
      json: {
        id: ARTIFACT,
        kind: "workflow",
        api_name: "tiep_nhan_lead",
        owning_workspace_id: "00000000-0000-4000-8000-0000000000aa",
        labels: [],
        last_version_no: 0,
        version: 1,
        created_at: "2026-11-01T00:00:00Z",
        updated_at: "2026-11-01T00:00:00Z",
        display_stage: "draft",
      },
    }),
  );
  await page.route(
    `**/api/v1/studio/artifacts/${ARTIFACT}/draft`,
    (route: Route) => {
      const request = route.request();
      if (request.method() === "PUT") {
        const ifMatch = request.headers()["if-match"] ?? null;
        puts.push({ ifMatch, document: request.postDataJSON().document });
        if (ifMatch !== `"${version}"`) {
          return route.fulfill({
            status: 412,
            json: { code: "precondition_failed", message: "x", details: {} },
          });
        }
        document = request.postDataJSON().document;
        version += 1;
        return route.fulfill({ json: { ...draft(), warnings: [] } });
      }
      return route.fulfill({ json: draft() });
    },
  );
  return { puts, current: () => document };
}

test("builds on the canvas with the keyboard only", async ({ page }, info) => {
  test.skip(
    info.project.name !== "chromium",
    "the canvas is the desktop editor",
  );
  const server = await serve(page);
  await login(page);
  await page.goto(`/studio/workflows/${ARTIFACT}/builder`);
  const first = page.getByRole("button", {
    name: /^Chuẩn hóa số điện thoại và email,/,
  });
  await first.waitFor();
  await first.focus();
  await page.keyboard.press("ArrowDown");
  await expect(
    page.getByRole("button", { name: /^Lưu hoặc cập nhật Lead,/ }),
  ).toBeFocused();
  // Thêm sau through the menu.
  await page.keyboard.press("Shift+F10");
  await page.getByRole("menuitem", { name: "Thêm sau" }).click();
  await page.getByRole("button", { name: "Hỏi AI" }).first().press("Enter");
  await expect.poll(() => server.puts.length).toBeGreaterThan(0);
  expect(server.puts[0]!.ifMatch).toBe('"1"');
  // Delete, then Ctrl+Z and Ctrl+Shift+Z.
  await page.keyboard.press("Delete");
  await expect(page.getByText(/^Đã xóa «Hỏi AI»/)).toBeVisible();
  await page.keyboard.press("Control+z");
  await page.keyboard.press("Control+Shift+z");
  // Enter opens the configuration, Esc closes it.
  await first.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  // Ctrl+K reaches a step by name.
  await page.keyboard.press("Control+k");
  await page
    .getByRole("textbox", { name: "Tìm Bước theo tên" })
    .fill("cham diem");
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("button", { name: /^Chấm điểm lead bằng AI,/ }),
  ).toBeFocused();
});

test("builds through the outline at 320 px without sideways scroll", async ({
  page,
}, info) => {
  test.skip(
    info.project.name !== "phone-320",
    "the outline is the phone's editor",
  );
  const server = await serve(page);
  await login(page);
  await page.goto(`/studio/workflows/${ARTIFACT}/builder`);
  await page.getByRole("tree").waitFor();
  const row = page.getByRole("treeitem", { name: /^Chuẩn hóa số điện thoại/ });
  await row.getByRole("button", { name: /^Thao tác/ }).click();
  await page.getByRole("menuitem", { name: "Thêm sau" }).click();
  await page.getByRole("button", { name: "Hỏi AI" }).first().click();
  await expect(page.getByRole("treeitem", { name: /^Hỏi AI/ })).toHaveAttribute(
    "aria-level",
    "1",
  );
  await expect.poll(() => server.puts.length).toBeGreaterThan(0);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(
    overflow,
    `the builder scrolls sideways by ${overflow}px`,
  ).toBeLessThanOrEqual(0);
});
