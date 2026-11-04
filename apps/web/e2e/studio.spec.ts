import { expect, test, type Page } from "@playwright/test";

/**
 * `/studio` lists what `GET /api/v1/studio/artifacts` returns and does not
 * scroll sideways, at a 320px phone included (studio-skeleton R7.4). The list
 * is answered by `page.route`, three artifacts whose `api_name` is 40
 * characters, the ceiling of tenant-config:R2.2, so the table has real rows
 * whatever kinds the running app registers.
 *
 * Needs the stack for the sign-in: the API on 8000 with the seed.
 */

const API_URL = process.env.E2E_API_URL ?? "http://127.0.0.1:8000";
const SUBJECT = "dev|chi.le";

const NAMES = ["a", "b", "c"].map((letter) =>
  `${letter}_${"x".repeat(38)}`.slice(0, 40),
);

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

test("/studio lists the artifacts and fits the viewport", async ({ page }) => {
  await page.route("**/api/v1/studio/artifacts*", (route) =>
    route.fulfill({
      json: {
        items: NAMES.map((name, i) => ({
          id: `00000000-0000-4000-8000-00000000000${i}`,
          kind: "object",
          api_name: name,
          owning_workspace_id: "00000000-0000-4000-8000-0000000000aa",
          labels: [],
          last_version_no: i + 1,
          version: 1,
          created_at: "2026-11-01T00:00:00Z",
          updated_at: "2026-11-03T17:05:00Z",
        })),
        next_cursor: null,
      },
    }),
  );
  await login(page);
  await page.goto("/studio");
  await expect(
    page.getByRole("heading", { level: 1, name: "Tất cả thành phần" }),
  ).toBeVisible();
  for (const name of NAMES) {
    expect(name).toHaveLength(40);
    await expect(page.getByRole("cell", { name })).toBeVisible();
  }
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(
    overflow,
    `/studio scrolls sideways by ${overflow}px`,
  ).toBeLessThanOrEqual(0);
});
