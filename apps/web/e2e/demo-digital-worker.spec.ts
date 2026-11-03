import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { expect, test, type Locator, type Page } from "@playwright/test";

/**
 * The digital-worker demo's screenshots (leadcare ticket 02, R4.3): one per
 * screen, each showing the lead `make demo-dw` just ran, into
 * docs/demo/digital-worker/<NN>-<screen>.png.
 *
 * Runs only inside `make demo-dw` (scripts/demo_dw.sh), which passes the
 * state the seed and the run wrote in DW_DEMO_STATE; elsewhere it skips. Two
 * phases, picked by --grep: `@approval` while the Validator's approval waits
 * (the run calls it before it decides), the rest once the lead reached sales.
 *
 * Sign-in is dev mode, as /dev-login does it, for people the seed invited
 * rather than the static roster: the token comes from
 * scripts/issue_dev_token.py, the one owner of its format.
 *
 * With DW_DEMO_REVIEW_DIR set, each screen is also shot dark, and light and
 * dark at 991px (below antd's lg), into that directory, for review only.
 */

const STATE_PATH = process.env.DW_DEMO_STATE;
const REVIEW_DIR = process.env.DW_DEMO_REVIEW_DIR;
const REPO_ROOT = path.resolve(__dirname, "..", "..", "..");
const OUT_DIR = path.join(REPO_ROOT, "docs", "demo", "digital-worker");

interface DemoPerson {
  subject: string;
  email: string;
  display_name: string;
  user_id: string;
}

interface DemoState {
  dw_id: string;
  tenant_name: string;
  people: Record<
    | "business_owner"
    | "technical_owner"
    | "work_assigner"
    | "validator"
    | "sales",
    DemoPerson
  >;
  lead?: {
    email: string;
    name: string;
    item_id?: string;
    handoff?: { problem: string };
  };
}

function state(): DemoState {
  return JSON.parse(readFileSync(STATE_PATH as string, "utf-8")) as DemoState;
}

test.skip(!STATE_PATH, "runs inside `make demo-dw` only (DW_DEMO_STATE)");

async function signIn(
  page: Page,
  person: DemoPerson,
  tenantName: string,
): Promise<void> {
  const token = execFileSync(
    "uv",
    [
      "run",
      "--no-sync",
      "python",
      "scripts/issue_dev_token.py",
      person.subject,
      "--email",
      person.email,
      "--hours",
      "1",
    ],
    { cwd: REPO_ROOT, encoding: "utf-8" },
  ).trim();
  await page.addInitScript((value) => {
    window.localStorage.setItem("dw.dev.token", value);
  }, token);
  await page.goto("/");
  // The header names the company once the session's workspace is resolved.
  await expect(page.getByText(tenantName).first()).toBeVisible();
}

/** The screen as the ticket asks for it, and, for review, its variants. */
async function shoot(page: Page, name: string, target?: Locator) {
  mkdirSync(OUT_DIR, { recursive: true });
  // A cached list redraws dimmed while it revalidates; shoot the settled page.
  await page.waitForLoadState("networkidle");
  await expect(page.locator(".ant-spin-spinning")).toHaveCount(0);
  const take = (file: string) =>
    target
      ? target.screenshot({ path: file })
      : page.screenshot({ path: file, fullPage: true });
  await take(path.join(OUT_DIR, `${name}.png`));
  if (!REVIEW_DIR) return;
  mkdirSync(REVIEW_DIR, { recursive: true });
  const desktop = page.viewportSize() ?? { width: 1280, height: 720 };
  for (const [suffix, scheme, width] of [
    ["dark", "dark", desktop.width],
    ["991-light", "light", 991],
    ["991-dark", "dark", 991],
  ] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    await page.setViewportSize({ width, height: desktop.height });
    await page.waitForTimeout(500);
    await take(path.join(REVIEW_DIR, `${name}-${suffix}.png`));
  }
  await page.emulateMedia({ colorScheme: "light" });
  await page.setViewportSize(desktop);
}

test("@approval the Validator's card while the approval waits", async ({
  page,
}) => {
  const demo = state();
  const lead = demo.lead;
  expect(lead, "the run writes its lead before this phase").toBeTruthy();
  await signIn(page, demo.people.validator, demo.tenant_name);
  await page.goto("/approvals");
  const card = page.locator(".ant-card").filter({ hasText: lead!.email });
  await expect(card).toBeVisible();
  await expect(
    card.getByRole("button", { name: "Duyệt", exact: true }),
  ).toBeEnabled();
  // The whole page: an element shot of a card taller than the window puts
  // the sticky navbar over its title.
  await shoot(page, "04-approvals-dw-decision");
});

test("the screens once the lead reached sales", async ({ page }) => {
  const demo = state();
  const lead = demo.lead;
  expect(lead?.item_id, "the run records its item on success").toBeTruthy();
  expect(lead?.handoff, "and the packet it handed to sales").toBeTruthy();
  const sales = demo.people.sales.display_name;
  await signIn(page, demo.people.business_owner, demo.tenant_name);

  await page.goto("/digital-workers");
  await expect(
    page.getByRole("link", { name: "Chăm sóc lead" }).first(),
  ).toBeVisible();
  await shoot(page, "01-digital-workers");

  await page.goto(`/digital-workers/${demo.dw_id}`);
  await expect(
    page.getByRole("heading", { level: 1, name: "Chăm sóc lead" }),
  ).toBeVisible();
  await expect(
    page.getByText(demo.people.validator.display_name).first(),
  ).toBeVisible();
  await shoot(page, "02-digital-worker");

  await page.goto("/work");
  await expect(
    page.getByRole("heading", { level: 1, name: "Hàng đợi việc" }),
  ).toBeVisible();
  await expect(page.getByText(sales).first()).toBeVisible();
  await shoot(page, "03-work");

  await page.goto(`/work?item=${lead!.item_id}`);
  const drawer = page.getByRole("dialog", { name: "Việc" });
  await expect(drawer.getByText("Gói bàn giao")).toBeVisible();
  await expect(drawer.getByText(sales)).toBeVisible();
  await expect(drawer.getByText(lead!.handoff!.problem)).toBeVisible();
  await shoot(page, "05-work-handed-off", drawer);
});
