import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, relative, resolve } from "node:path";
import { loadESLint } from "eslint";
import { afterEach, describe, expect, it } from "vitest";

/**
 * One component system (CLAUDE.md "Web UI"): antd. Since ADR-0101 (Accepted)
 * decision 4 this is an allowlist, not a list of what was removed: a module
 * nobody listed fails, wherever it comes from. `apps/web` and `@dw/ui` may
 * use the runtime modules in `ALLOWED`; test and config files may also use the
 * dev tools in `DEV_ONLY`; and a library that supports antd without bringing a
 * component set of its own joins through an `EXCEPTIONS` entry, valid only
 * under its glob in `apps/web` and only while its ADR is Accepted and names it.
 * `@dw/ui` takes no exception (ADR-0101 (Accepted) decision 1).
 *
 * ESLint (`apps/web/.eslintrc.json`) carries the same allowlist for the app,
 * but `@dw/ui` has no lint step, CSS has none, and a dependency can come back
 * in a manifest without any import; this reads all of them.
 */

const WEB = resolve(__dirname, "../..");
const REPO = resolve(WEB, "../..");
const UI = join(REPO, "packages/typescript/ui");
const ADR_DIR = join(REPO, "docs/adr");

/** Runtime modules either package may use; each also covers its subpaths. */
export const ALLOWED = [
  "antd",
  "@ant-design/icons",
  "@ant-design/nextjs-registry",
  "dayjs",
  "keycloak-js",
  "next",
  "react",
  "react-dom",
  "@dw/*",
];

/** Tools a test file, a config file or a stylesheet may import, never a page. */
export const DEV_ONLY = [
  "vitest",
  "@testing-library/react",
  "@playwright/test",
  "jsdom",
  "@vitejs/plugin-react",
  "tailwindcss",
  "@tailwindcss/postcss",
  "eslint",
  "eslint-config-next",
  "typescript",
  "@types/*",
];

/**
 * A library admitted by its own ADR: `glob` is rooted at `apps/web` (`**` for
 * the whole app, a narrower path for one place), and `adr` is the four-digit
 * number of an Accepted ADR in `docs/adr/` that names `module` in backticks.
 */
export interface UiException {
  module: string;
  glob: string;
  adr: string;
}

/** Empty until workflow-builder-ui/01 adds `@xyflow/react` on
 * `app/studio/**\/canvas/**` with ADR 0101, in the change that first imports it. */
export const EXCEPTIONS: UiException[] = [];

/** The config files a package may hold at its root, by exact path. */
const CONFIG_FILES = new Set([
  "vitest.config.mts",
  "vitest.setup.ts",
  "playwright.config.ts",
  "postcss.config.mjs",
  "next.config.ts",
]);

/** What `@dw/ui` exported before: none of these may be imported from it. */
const REMOVED_PRIMITIVES = new Set([
  "Alert",
  "AlertDescription",
  "AlertTitle",
  "Badge",
  "badgeVariants",
  "Button",
  "buttonVariants",
  "Card",
  "CardContent",
  "CardDescription",
  "CardFooter",
  "CardHeader",
  "CardTitle",
  "Input",
  "Label",
  "Select",
  "Separator",
  "Skeleton",
  "Switch",
  "Table",
  "TableBody",
  "TableCell",
  "TableHead",
  "TableHeader",
  "TableRow",
  "Tabs",
  "TabsContent",
  "TabsList",
  "TabsTrigger",
  "Textarea",
  "cn",
]);

/** A package the guard reads: `apps/web` is the only one exceptions reach. */
export interface UiPackage {
  /** How a finding names it: `apps/web`, `packages/typescript/ui`. */
  name: string;
  root: string;
  isWeb: boolean;
}

const WEB_PKG: UiPackage = { name: "apps/web", root: WEB, isWeb: true };
const UI_PKG: UiPackage = {
  name: "packages/typescript/ui",
  root: UI,
  isWeb: false,
};
const PACKAGES = [WEB_PKG, UI_PKG];

const SKIPPED_DIRS = new Set(["node_modules", ".next", "test-results"]);
const SOURCE = /\.(ts|tsx|mts|cts|js|jsx|mjs|cjs|css)$/;
const THIS_FILE = "lib/__tests__/antd-only.test.ts";

/** `entry` covers `specifier`: itself or a subpath, or anything under a `scope/*`. */
export function covers(entry: string, specifier: string): boolean {
  if (entry.endsWith("/*")) return specifier.startsWith(entry.slice(0, -1));
  return specifier === entry || specifier.startsWith(`${entry}/`);
}

/**
 * A path glob over `/`-separated segments: `**` is zero or more segments, and
 * `*` inside a segment is any run of characters but `/`. Nothing else.
 */
export function globMatches(glob: string, path: string): boolean {
  const pattern = glob.split("/");
  const parts = path.split("/");
  const segment = (g: string, p: string) =>
    new RegExp(
      `^${g
        .split("*")
        .map((s) => s.replace(/[.+?^${}()|[\]\\]/g, "\\$&"))
        .join("[^/]*")}$`,
    ).test(p);
  const match = (i: number, j: number): boolean => {
    if (i === pattern.length) return j === parts.length;
    if (pattern[i] === "**") {
      for (let k = j; k <= parts.length; k++) if (match(i + 1, k)) return true;
      return false;
    }
    const g = pattern[i];
    const p = parts[j];
    return (
      g !== undefined && p !== undefined && segment(g, p) && match(i + 1, j + 1)
    );
  };
  return match(0, 0);
}

/** A test file, a root config file or a stylesheet: where `DEV_ONLY` may go. */
export function mayUseDevTools(pkg: UiPackage, path: string): boolean {
  return (
    path.split("/").includes("__tests__") ||
    /\.test\.tsx?$/.test(path) ||
    (pkg.isWeb && path.startsWith("e2e/")) ||
    CONFIG_FILES.has(path) ||
    path.endsWith(".css")
  );
}

// Each statement form on its own, none able to run past its own end: an import
// clause holds no quote, so `import "x";` cannot be swallowed by the next
// statement's `from` the way the old lazy `[\s\S]*?` pattern was.
const STATEMENT = new RegExp(
  [
    /\bimport\s+(?:type\s+)?([\w$*\s{},]+?)\s*from\s*["']([^"'\n]+)["']/.source,
    /\bimport\s*["']([^"'\n]+)["']/.source,
    /\bexport\s+(?:type\s+)?(\*(?:\s+as\s+[\w$]+)?|\{[^}]*\})\s*from\s*["']([^"'\n]+)["']/
      .source,
    /\bimport\s*\(\s*["']([^"'\n]+)["']\s*\)/.source,
    /\brequire\s*\(\s*["']([^"'\n]+)["']\s*\)/.source,
    /@(?:import|plugin)\s+(?:url\(\s*)?["']([^"'\n]+)["']/.source,
  ].join("|"),
  "g",
);

/** Every bare module one source text names, with the names it imports. */
export function importsIn(
  text: string,
): { specifier: string; names: string[] }[] {
  const found: { specifier: string; names: string[] }[] = [];
  for (const m of text.matchAll(STATEMENT)) {
    const clause = m[1] ?? m[4] ?? "";
    const specifier = m[2] ?? m[3] ?? m[5] ?? m[6] ?? m[7] ?? m[8] ?? "";
    if (
      specifier.startsWith(".") ||
      specifier.startsWith("/") ||
      specifier.startsWith("@/") ||
      specifier.startsWith("node:")
    ) {
      continue;
    }
    const names = clause
      .replace(/[{}*]/g, "")
      .split(",")
      .map((raw) =>
        raw
          .trim()
          .replace(/^type\s+/, "")
          .split(/\s+as\s+/)[0]
          ?.trim(),
      )
      .filter((name): name is string => Boolean(name));
    found.push({ specifier, names });
  }
  return found;
}

/** Why `specifier` may not be imported from `path` of `pkg`, or null. */
export function refusal(
  pkg: UiPackage,
  path: string,
  specifier: string,
  exceptions: UiException[],
): string | null {
  if (ALLOWED.some((entry) => covers(entry, specifier))) return null;
  if (
    DEV_ONLY.some((entry) => covers(entry, specifier)) &&
    mayUseDevTools(pkg, path)
  ) {
    return null;
  }
  const admitting = exceptions.filter((e) => covers(e.module, specifier));
  if (admitting.length === 0) return specifier;
  if (!pkg.isWeb) return `${specifier} (no exception reaches @dw/ui)`;
  if (admitting.some((e) => globMatches(e.glob, path))) return null;
  return `${specifier} (only under ${admitting.map((e) => e.glob).join(", ")})`;
}

/** What one file of `pkg` imports that it may not, as "<file>: <why>". */
export function refusedImports(
  pkg: UiPackage,
  path: string,
  text: string,
  exceptions: UiException[] = EXCEPTIONS,
): string[] {
  const where = `${pkg.name}/${path}`;
  const hits: string[] = [];
  for (const { specifier, names } of importsIn(text)) {
    const why = refusal(pkg, path, specifier, exceptions);
    if (why !== null) hits.push(`${where}: ${why}`);
    if (specifier === "@dw/ui") {
      for (const name of names) {
        if (REMOVED_PRIMITIVES.has(name)) {
          hits.push(`${where}: ${name} from @dw/ui`);
        }
      }
    }
  }
  return hits;
}

/** Every JS, TS and CSS source of a package, as paths relative to its root. */
export function sources(root: string): string[] {
  const found: string[] = [];
  const walk = (dir: string) => {
    for (const name of readdirSync(dir)) {
      if (SKIPPED_DIRS.has(name)) continue;
      const path = join(dir, name);
      if (statSync(path).isDirectory()) walk(path);
      else if (SOURCE.test(name)) {
        found.push(relative(root, path).split("\\").join("/"));
      }
    }
  };
  walk(root);
  return found;
}

/** Every refused import across `packages`. */
export function importProblems(
  packages: UiPackage[],
  exceptions: UiException[] = EXCEPTIONS,
): string[] {
  return packages.flatMap((pkg) =>
    sources(pkg.root)
      .filter((path) => !(pkg.isWeb && path === THIS_FILE))
      .flatMap((path) =>
        refusedImports(
          pkg,
          path,
          readFileSync(join(pkg.root, path), "utf8"),
          exceptions,
        ),
      ),
  );
}

/** Every dependency a manifest may not declare, as "<manifest>: <name>". */
export function manifestProblems(
  packages: UiPackage[],
  exceptions: UiException[] = EXCEPTIONS,
): string[] {
  return packages.flatMap((pkg) => {
    const manifest = JSON.parse(
      readFileSync(join(pkg.root, "package.json"), "utf8"),
    ) as Record<string, Record<string, string> | undefined>;
    const where = `${pkg.name}/package.json`;
    return (
      ["dependencies", "peerDependencies", "devDependencies"] as const
    ).flatMap((field) =>
      Object.keys(manifest[field] ?? {}).flatMap((name) => {
        if (ALLOWED.some((entry) => covers(entry, name))) return [];
        if (
          field === "devDependencies" &&
          DEV_ONLY.some((entry) => covers(entry, name))
        ) {
          return [];
        }
        const excepted = exceptions.some((e) => covers(e.module, name));
        if (excepted && pkg.isWeb) return [];
        return [
          `${where}: ${name} in ${field}${excepted ? " (no exception reaches @dw/ui)" : ""}`,
        ];
      }),
    );
  });
}

/**
 * Each exception whose `adr` is not an Accepted ADR in `adrDir` that names its
 * module in backticks. The directory is a parameter so a case can use a
 * scratch one rather than the current state of a real ADR.
 */
export function exceptionProblems(
  exceptions: UiException[],
  adrDir: string = ADR_DIR,
): string[] {
  return exceptions.flatMap((entry) => {
    const name = `{ module: ${entry.module}, glob: ${entry.glob}, adr: ${entry.adr} }`;
    const file = /^\d{4}$/.test(entry.adr)
      ? readdirSync(adrDir).find(
          (f) => f.startsWith(`${entry.adr}-`) && f.endsWith(".md"),
        )
      : undefined;
    if (file === undefined) return [`${name}: no ADR ${entry.adr}`];
    const text = readFileSync(join(adrDir, file), "utf8");
    const front = /^---\r?\n([\s\S]*?)\r?\n---\r?\n/.exec(text);
    const status = /^status:\s*(.*)$/m.exec(front?.[1] ?? "")?.[1] ?? "";
    if (!status.startsWith("Accepted")) {
      return [`${name}: ADR ${entry.adr} is "${status || "without status"}"`];
    }
    const body = text.slice(front?.[0].length ?? 0);
    if (!body.includes(`\`${entry.module}\``)) {
      return [`${name}: ADR ${entry.adr} does not name \`${entry.module}\``];
    }
    return [];
  });
}

// ---- scratch trees for the cases that must go red ---------------------------

const scratch: string[] = [];
afterEach(() => {
  for (const dir of scratch.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

/** A scratch `apps/web` and `@dw/ui` with these files. */
function tree(files: Record<string, string>): [UiPackage, UiPackage] {
  const base = mkdtempSync(join(tmpdir(), "antd-only-"));
  scratch.push(base);
  for (const [path, text] of Object.entries(files)) {
    mkdirSync(dirname(join(base, path)), { recursive: true });
    writeFileSync(join(base, path), text);
  }
  return [
    { name: "apps/web", root: join(base, "web"), isWeb: true },
    { name: "packages/typescript/ui", root: join(base, "ui"), isWeb: false },
  ];
}

const EMPTY = JSON.stringify({ dependencies: {} });
const CANVAS: UiException = {
  module: "@xyflow/react",
  glob: "app/studio/**/canvas/**",
  adr: "0101",
};
const APP_WIDE: UiException = { ...CANVAS, glob: "**" };

describe("antd is the only component system", () => {
  it("catches each way the old system could come back", () => {
    const refused = (text: string) =>
      refusedImports(WEB_PKG, "app/a.tsx", text);
    expect(refused('import { toast } from "sonner";')).toEqual([
      "apps/web/app/a.tsx: sonner",
    ]);
    expect(refused('import { Slot } from "@radix-ui/react-slot";')).toEqual([
      "apps/web/app/a.tsx: @radix-ui/react-slot",
    ]);
    expect(refused('import { Dialog } from "radix-ui";')).toEqual([
      "apps/web/app/a.tsx: radix-ui",
    ]);
    expect(refused('import { cva } from "class-variance-authority";')).toEqual([
      "apps/web/app/a.tsx: class-variance-authority",
    ]);
    expect(refused('import { X } from "lucide-react";')).toEqual([
      "apps/web/app/a.tsx: lucide-react",
    ]);
    expect(
      refused('import {\n  PageHeader,\n  Button as B,\n} from "@dw/ui";'),
    ).toEqual(["apps/web/app/a.tsx: Button from @dw/ui"]);
    expect(refused('import { PageHeader } from "@dw/ui";')).toEqual([]);
    expect(refused('import { Button } from "antd";')).toEqual([]);
  });

  it("no source in the web app or @dw/ui imports a module off the allowlist", () => {
    expect(importProblems(PACKAGES)).toEqual([]);
  });

  it("no manifest declares a module off the allowlist", () => {
    expect(manifestProblems(PACKAGES)).toEqual([]);
  });

  it("every exception has an Accepted ADR that names its module", () => {
    expect(exceptionProblems(EXCEPTIONS)).toEqual([]);
  });

  it("no shadcn primitive file is left in @dw/ui", () => {
    const left = readdirSync(join(UI, "src")).filter((name) =>
      /^(alert|badge|button|card|input|label|separator|skeleton|switch|table|tabs|cn)\.tsx?$/.test(
        name,
      ),
    );
    expect(left).toEqual([]);
  });
});

describe("the allowlist refuses what nobody admitted (R7.5, R7.6, SKEL15)", () => {
  it("matches globs by segment: * is one, ** is any number", () => {
    expect(
      globMatches("app/studio/**/canvas/**", "app/studio/w/canvas/a.tsx"),
    ).toBe(true);
    expect(
      globMatches("app/studio/**/canvas/**", "app/studio/canvas/a.tsx"),
    ).toBe(true);
    expect(
      globMatches("app/studio/**/canvas/**", "app/studio/a/b/canvas/c/d.tsx"),
    ).toBe(true);
    expect(globMatches("app/studio/**/canvas/**", "app/studio/w/a.tsx")).toBe(
      false,
    );
    expect(globMatches("app/studio/**/canvas/**", "app/x/canvas/a.tsx")).toBe(
      false,
    );
    expect(globMatches("**", "components/b.tsx")).toBe(true);
    expect(globMatches("app/*/a.tsx", "app/x/a.tsx")).toBe(true);
    expect(globMatches("app/*/a.tsx", "app/x/y/a.tsx")).toBe(false);
    expect(globMatches("app/*.tsx", "app/page.tsx")).toBe(true);
    expect(globMatches("app/*.tsx", "app/x/page.tsx")).toBe(false);
  });

  it("refuses a manifest that declares an unlisted library, naming both", () => {
    const [web, ui] = tree({
      "web/package.json": JSON.stringify({
        dependencies: { antd: "6", "@chakra-ui/react": "3" },
      }),
      "ui/package.json": EMPTY,
    });
    expect(manifestProblems([web, ui])).toEqual([
      "apps/web/package.json: @chakra-ui/react in dependencies",
    ]);
  });

  it("refuses an unlisted library in devDependencies too", () => {
    const [web, ui] = tree({
      "web/package.json": JSON.stringify({
        devDependencies: { vitest: "5", "@chakra-ui/react": "3" },
      }),
      "ui/package.json": EMPTY,
    });
    expect(manifestProblems([web, ui])).toEqual([
      "apps/web/package.json: @chakra-ui/react in devDependencies",
    ]);
  });

  it("refuses a dev tool in a manifest's runtime dependencies", () => {
    const [web, ui] = tree({
      "web/package.json": JSON.stringify({ dependencies: { vitest: "5" } }),
      "ui/package.json": EMPTY,
    });
    expect(manifestProblems([web, ui])).toEqual([
      "apps/web/package.json: vitest in dependencies",
    ]);
  });

  it("lets an app-wide exception into apps/web's manifest, never @dw/ui's", () => {
    const [web, ui] = tree({
      "web/package.json": JSON.stringify({
        dependencies: { "@xyflow/react": "12.12.0" },
      }),
      "ui/package.json": JSON.stringify({
        peerDependencies: { "@xyflow/react": "12.12.0" },
      }),
    });
    expect(manifestProblems([web, ui], [APP_WIDE])).toEqual([
      "packages/typescript/ui/package.json: @xyflow/react in peerDependencies (no exception reaches @dw/ui)",
    ]);
    expect(manifestProblems([web, ui], [])).toHaveLength(2);
  });

  it("refuses @xyflow/react in apps/web/app while no exception lists it", () => {
    const pkgs = tree({
      "web/app/studio/w/canvas/a.tsx":
        'import { ReactFlow } from "@xyflow/react";\n',
      "ui/src/x.ts": "",
    });
    expect(importProblems(pkgs, [])).toEqual([
      "apps/web/app/studio/w/canvas/a.tsx: @xyflow/react",
    ]);
  });

  it("admits a path exception under its glob only, subpaths included", () => {
    const pkgs = tree({
      "web/app/studio/w/canvas/a.tsx":
        'import { ReactFlow } from "@xyflow/react";\nimport "@xyflow/react/dist/base.css";\n',
      "web/app/studio/w/a.tsx": 'import { ReactFlow } from "@xyflow/react";\n',
      "ui/src/x.ts": "",
    });
    expect(importProblems(pkgs, [CANVAS])).toEqual([
      "apps/web/app/studio/w/a.tsx: @xyflow/react (only under app/studio/**/canvas/**)",
    ]);
  });

  it("admits an app-wide exception anywhere in apps/web and nowhere in @dw/ui", () => {
    const pkgs = tree({
      "web/app/x/a.tsx": 'import { ReactFlow } from "@xyflow/react";\n',
      "web/components/b.tsx": 'import { ReactFlow } from "@xyflow/react";\n',
      "ui/src/c.tsx": 'import { ReactFlow } from "@xyflow/react";\n',
    });
    expect(importProblems(pkgs, [APP_WIDE])).toEqual([
      "packages/typescript/ui/src/c.tsx: @xyflow/react (no exception reaches @dw/ui)",
    ]);
  });

  it("keeps dev tools to test files, root config files and stylesheets", () => {
    const pkgs = tree({
      "web/lib/a.ts": 'import { vi } from "vitest";\n',
      "web/vitest.setup.ts": 'import { vi } from "vitest";\n',
      "web/lib/vitest.setup.ts": 'import { vi } from "vitest";\n',
      "web/lib/__tests__/b.ts": 'import { vi } from "vitest";\n',
      "web/lib/c.test.tsx":
        'import { render } from "@testing-library/react";\n',
      "web/e2e/d.spec.ts": 'import { test } from "@playwright/test";\n',
      "web/app/globals.css": '@import "tailwindcss";\n',
      "ui/src/e.ts": 'import { vi } from "vitest";\n',
    });
    expect(importProblems(pkgs, []).sort()).toEqual([
      "apps/web/lib/a.ts: vitest",
      "apps/web/lib/vitest.setup.ts: vitest",
      "packages/typescript/ui/src/e.ts: vitest",
    ]);
  });

  it("reads every JS, TS and CSS extension, one finding per file", () => {
    const pkgs = tree({
      "web/lib/a.cjs": 'const c = require("@chakra-ui/react");\n',
      "web/lib/a.jsx": 'import { Box } from "@chakra-ui/react";\n',
      "web/lib/a.cts": 'import { Box } from "@chakra-ui/react";\n',
      "web/lib/a.mjs": 'export { Box } from "@chakra-ui/react";\n',
      "web/lib/a.js": 'const m = import("@chakra-ui/react");\n',
      "ui/src/a.mts": 'import type { BoxProps } from "@chakra-ui/react";\n',
    });
    expect(importProblems(pkgs, []).sort()).toEqual([
      "apps/web/lib/a.cjs: @chakra-ui/react",
      "apps/web/lib/a.cts: @chakra-ui/react",
      "apps/web/lib/a.js: @chakra-ui/react",
      "apps/web/lib/a.jsx: @chakra-ui/react",
      "apps/web/lib/a.mjs: @chakra-ui/react",
      "packages/typescript/ui/src/a.mts: @chakra-ui/react",
    ]);
  });

  it("does not let one statement swallow the next", () => {
    const text = 'import "@chakra-ui/react";\nimport { Button } from "antd";\n';
    expect(refusedImports(WEB_PKG, "app/a.tsx", text)).toEqual([
      "apps/web/app/a.tsx: @chakra-ui/react",
    ]);
    expect(importsIn(text).map((i) => i.specifier)).toEqual([
      "@chakra-ui/react",
      "antd",
    ]);
  });

  it("sees export-from and the CSS @import and @plugin directives", () => {
    expect(
      refusedImports(WEB_PKG, "app/a.ts", 'export * from "@chakra-ui/react";'),
    ).toEqual(["apps/web/app/a.ts: @chakra-ui/react"]);
    expect(
      refusedImports(
        WEB_PKG,
        "app/a.ts",
        'export type { BoxProps } from "@chakra-ui/react";',
      ),
    ).toEqual(["apps/web/app/a.ts: @chakra-ui/react"]);
    expect(
      refusedImports(WEB_PKG, "app/globals.css", '@plugin "daisyui";'),
    ).toEqual(["apps/web/app/globals.css: daisyui"]);
    expect(
      refusedImports(
        WEB_PKG,
        "app/globals.css",
        '@import "bootstrap/dist/x.css";',
      ),
    ).toEqual(["apps/web/app/globals.css: bootstrap/dist/x.css"]);
  });

  it("skips relative paths, the @/ alias and node: builtins", () => {
    expect(
      refusedImports(
        WEB_PKG,
        "app/a.ts",
        'import a from "./a";\nimport b from "../b";\nimport { c } from "@/lib/dates";\nimport fs from "node:fs";',
      ),
    ).toEqual([]);
  });

  it("gives @dw/ui no exception for an import either", () => {
    expect(
      refusedImports(UI_PKG, "src/a.tsx", 'import "@xyflow/react";', [
        APP_WIDE,
      ]),
    ).toEqual([
      "packages/typescript/ui/src/a.tsx: @xyflow/react (no exception reaches @dw/ui)",
    ]);
  });
});

describe("an exception stands only on an Accepted ADR that names it (R7.8)", () => {
  function adrs(files: Record<string, string>): string {
    const dir = mkdtempSync(join(tmpdir(), "antd-only-adr-"));
    scratch.push(dir);
    for (const [name, text] of Object.entries(files)) {
      writeFileSync(join(dir, name), text);
    }
    return dir;
  }
  const adr = (status: string, body: string) =>
    `---\nstatus: ${status}\ndate: 2026-10-23\n---\n\n# Title\n\n${body}\n`;

  it("accepts an Accepted ADR that names the module in backticks", () => {
    const dir = adrs({
      "0101-canvas.md": adr(
        "Accepted (Đạt, 2026-10-23)",
        "Uses `@xyflow/react`.",
      ),
    });
    expect(exceptionProblems([CANVAS], dir)).toEqual([]);
  });

  it("refuses a number with no ADR file", () => {
    const dir = adrs({ "0102-other.md": adr("Accepted", "`@xyflow/react`") });
    expect(exceptionProblems([CANVAS], dir)).toEqual([
      "{ module: @xyflow/react, glob: app/studio/**/canvas/**, adr: 0101 }: no ADR 0101",
    ]);
  });

  it("refuses a Proposed ADR", () => {
    const dir = adrs({
      "0101-canvas.md": adr("Proposed", "Uses `@xyflow/react`."),
    });
    expect(exceptionProblems([CANVAS], dir)).toEqual([
      '{ module: @xyflow/react, glob: app/studio/**/canvas/**, adr: 0101 }: ADR 0101 is "Proposed"',
    ]);
  });

  it("refuses an Accepted ADR that does not name the module", () => {
    const dir = adrs({
      "0101-canvas.md": adr(
        "Accepted",
        "Uses `@dagrejs/dagre` and @xyflow/react.",
      ),
    });
    expect(exceptionProblems([CANVAS], dir)).toEqual([
      "{ module: @xyflow/react, glob: app/studio/**/canvas/**, adr: 0101 }: ADR 0101 does not name `@xyflow/react`",
    ]);
  });

  it("reads the status from the front matter, not from the body", () => {
    const dir = adrs({
      "0101-canvas.md": adr("Proposed", "status: Accepted\n\n`@xyflow/react`"),
    });
    expect(exceptionProblems([CANVAS], dir)).toHaveLength(1);
  });

  it("refuses an adr that is not a four-digit number", () => {
    const dir = adrs({ "0101-canvas.md": adr("Accepted", "`@xyflow/react`") });
    expect(exceptionProblems([{ ...CANVAS, adr: "101" }], dir)).toEqual([
      "{ module: @xyflow/react, glob: app/studio/**/canvas/**, adr: 101 }: no ADR 101",
    ]);
  });
});

// ---- R7.7: ESLint carries the same allowlist for the app ------------------
//
// Run through `apps/web/.eslintrc.json` as `next lint` runs it, so a pattern
// that stops matching goes red here. These cases live in this file because
// they name modules off the allowlist, and this is the one file the import
// scan skips.

async function restricted(path: string, text: string): Promise<number[]> {
  const ESLint = await loadESLint({ useFlatConfig: false });
  const eslint = new ESLint({ cwd: WEB });
  const [result] = await eslint.lintText(text, {
    filePath: resolve(WEB, path),
  });
  return (result?.messages ?? [])
    .filter((m) => m.ruleId === "no-restricted-imports")
    .map((m) => m.line);
}

describe("ESLint carries the UI allowlist", { timeout: 60_000 }, () => {
  it("errors on an unlisted module and on nothing allowlisted", async () => {
    const text = [
      'import { Box } from "@chakra-ui/react";',
      'import { Button } from "antd";',
      'import { formatDateTime } from "../../lib/dates";',
      'import { formatMoney } from "@/lib/dates";',
      'import { useRouter } from "next/navigation";',
      'import type { Page } from "@dw/contracts";',
      'export * from "daisyui";',
      "export const x = [Box, Button, formatDateTime, formatMoney, useRouter];",
      "export type P = Page<number>;",
    ].join("\n");
    expect(await restricted("app/zz-probe/a.tsx", text)).toEqual([1, 7]);
  });

  it("keeps the static notice API refused", async () => {
    expect(
      await restricted(
        "app/zz-probe/a.tsx",
        'import { message } from "antd";\nexport const m = message;\n',
      ),
    ).toEqual([1]);
  });

  it("lets dev tools into test and root config files only", async () => {
    const text = 'import { vi } from "vitest";\nexport const v = vi;\n';
    expect(await restricted("lib/zz-probe/a.ts", text)).toEqual([1]);
    expect(await restricted("lib/zz-probe/vitest.setup.ts", text)).toEqual([1]);
    expect(await restricted("vitest.setup.ts", text)).toEqual([]);
    expect(await restricted("lib/zz-probe/__tests__/a.ts", text)).toEqual([]);
    expect(await restricted("lib/zz-probe/a.test.ts", text)).toEqual([]);
    expect(
      await restricted(
        "lib/zz-probe/a.test.ts",
        'import { Box } from "@chakra-ui/react";\nexport const b = Box;\n',
      ),
    ).toEqual([1]);
  });
});
