import { render, waitFor } from "@testing-library/react";
import { App } from "antd";
import { vi } from "vitest";
import { ApiClient } from "@dw/api-client";
import {
  NODE_TYPES,
  loadFixture,
} from "../../../../../../lib/__tests__/workflow-catalogue";

/**
 * The builder against a fake of the routes it calls, through the real
 * `ApiClient` (so `If-Match` is read off the request the client actually
 * sends), at a chosen viewport width. Each test file mocks `lib/session` to
 * `server.client()` and `next/dynamic` to the canvas itself.
 */

export const ARTIFACT = "00000000-0000-4000-8000-0000000000a1";

export interface Call {
  method: string;
  path: string;
  ifMatch: string | null;
  body: unknown;
}

export class FakeServer {
  kind = "workflow";
  document: Record<string, unknown>;
  version = 1;
  hasDraft = true;
  /** Answer the next PUTs with 412, as a second tab's save would. */
  stale = false;
  /** Refuse a route the way the server's authorization would. */
  refuse: { types?: number; save?: number } = {};
  /** What the kind's check answers each save with (`warnings`). */
  warnings: { pointer: string; code: string; detail: string }[] = [];
  calls: Call[] = [];

  constructor(fixture = "f1") {
    this.document = loadFixture(fixture);
  }

  get puts(): Call[] {
    return this.calls.filter((c) => c.method === "PUT");
  }

  /** What the server holds after a save from somewhere else. */
  savedElsewhere(document: Record<string, unknown>) {
    this.document = document;
    this.version += 1;
    this.stale = true;
  }

  client(): ApiClient {
    return new ApiClient({
      baseUrl: "",
      fetchImpl: async (input, init) => {
        const path = String(input);
        const method = init?.method ?? "GET";
        const headers = new Headers(init?.headers);
        const body = init?.body ? JSON.parse(String(init.body)) : undefined;
        this.calls.push({
          method,
          path,
          ifMatch: headers.get("If-Match"),
          body,
        });
        const json = (status: number, payload: unknown) =>
          new Response(JSON.stringify(payload), {
            status,
            headers: { "Content-Type": "application/json" },
          });
        const refusal = (status: number, code: string) =>
          json(status, { code, message: `refused: ${code}`, details: {} });
        const draftPath = `/api/v1/studio/artifacts/${ARTIFACT}/draft`;
        if (path === "/api/v1/studio/node-types" && this.refuse.types) {
          return refusal(this.refuse.types, "permission_denied");
        }
        if (path === "/api/v1/studio/node-types") {
          return json(200, { catalogue_hash: "fake", types: NODE_TYPES });
        }
        if (path === `/api/v1/studio/artifacts/${ARTIFACT}`) {
          return json(200, {
            id: ARTIFACT,
            kind: this.kind,
            api_name: "tiep_nhan_lead",
            owning_workspace_id: "00000000-0000-4000-8000-0000000000aa",
            labels: [],
            last_version_no: 0,
            version: 1,
            created_at: "2026-11-01T00:00:00Z",
            updated_at: "2026-11-01T00:00:00Z",
            display_stage: "draft",
          });
        }
        if (path === draftPath && method === "GET") {
          if (!this.hasDraft) return refusal(404, "not_found");
          return json(200, this.draft());
        }
        if (path === draftPath && method === "PUT" && this.refuse.save) {
          return refusal(this.refuse.save, "permission_denied");
        }
        if (path === draftPath && method === "PUT") {
          if (this.stale || headers.get("If-Match") !== `"${this.version}"`) {
            return refusal(412, "precondition_failed");
          }
          this.document = (
            body as { document: Record<string, unknown> }
          ).document;
          this.version += 1;
          return json(200, { ...this.draft(), warnings: this.warnings });
        }
        return refusal(404, "not_found");
      },
    });
  }

  draft() {
    return {
      artifact_id: ARTIFACT,
      id: "00000000-0000-4000-8000-0000000000d1",
      document_schema: "dw.workflow/v1",
      document: this.document,
      version: this.version,
      based_on_version_id: null,
    };
  }
}

/** antd's breakpoints read `matchMedia`: answer them for one width. */
export function setWidth(width: number) {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    configurable: true,
    value: (query: string) => {
      const min = /min-width:\s*(\d+)px/.exec(query);
      const max = /max-width:\s*(\d+(?:\.\d+)?)px/.exec(query);
      const matches =
        (min ? width >= Number(min[1]) : true) &&
        (max ? width <= Number(max[1]) : true);
      return {
        matches,
        media: query,
        onchange: null,
        addListener: () => {},
        removeListener: () => {},
        addEventListener: () => {},
        removeEventListener: () => {},
        dispatchEvent: () => false,
      };
    },
  });
}

export function installShims() {
  globalThis.DOMMatrixReadOnly ??= class {
    m22 = 1;
  } as unknown as typeof DOMMatrixReadOnly;
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText: vi.fn(async () => {}) },
  });
}

export async function renderBuilder(
  Builder: (props: {
    artifactId: string;
    saveDelayMs?: number;
    viewerId?: string | null;
  }) => React.ReactNode,
  ready: () => HTMLElement | null,
  viewerId: string | null = null,
) {
  const view = render(
    <App>
      <div style={{ width: 1280, height: 800 }}>
        <Builder artifactId={ARTIFACT} saveDelayMs={0} viewerId={viewerId} />
      </div>
    </App>,
  );
  await waitFor(() => {
    if (!ready()) throw new Error("not ready");
  });
  return view;
}

/* Queries by attribute: `getByRole` with a name walks the accessibility tree
 * of the whole canvas and takes tens of seconds per call in jsdom. */

export function allByLabel(
  label: string | RegExp,
  root: ParentNode = document,
): HTMLElement[] {
  return [...root.querySelectorAll<HTMLElement>("[aria-label]")].filter(
    (el) => {
      const value = el.getAttribute("aria-label") ?? "";
      return typeof label === "string" ? value === label : label.test(value);
    },
  );
}

export function byLabel(
  label: string | RegExp,
  root: ParentNode = document,
): HTMLElement {
  const found = allByLabel(label, root)[0];
  if (!found) throw new Error(`nothing labelled ${String(label)}`);
  return found;
}

export function queryByLabel(
  label: string | RegExp,
  root: ParentNode = document,
): HTMLElement | null {
  return allByLabel(label, root)[0] ?? null;
}

/** Buttons whose text is exactly `text`. */
export function buttonsByText(
  text: string,
  root: ParentNode = document,
): HTMLElement[] {
  return [...root.querySelectorAll<HTMLElement>("button")].filter(
    (b) => (b.textContent ?? "").trim() === text,
  );
}

/** A canvas stop (a card's name button) by the step's name. */
export function stopNamed(name: string | RegExp): HTMLElement {
  const found = [...document.querySelectorAll<HTMLElement>("[data-stop]")].find(
    (el) => {
      const label = el.getAttribute("aria-label") ?? "";
      return typeof name === "string"
        ? label.startsWith(`${name}, `)
        : name.test(label);
    },
  );
  if (!found) throw new Error(`no stop named ${String(name)}`);
  return found;
}

/** An outline row by its tree key (rc-tree ids each row `<tree id>-<key>`). */
export function treeItem(key: string): HTMLElement | null {
  return (
    [...document.querySelectorAll<HTMLElement>("[role=treeitem]")].find((el) =>
      el.id.endsWith(`-${key}`),
    ) ?? null
  );
}
