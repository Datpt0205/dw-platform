import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * `@xyflow/react` 12.12.0 keeps its state in `zustand` 4.x, and its next major
 * moves to zustand 5 (ADR-0101 (Accepted) decision 1; workflow-builder-ui
 * R1.1, BU1). The lockfile, the whole workspace's, holds exactly one zustand,
 * at 4.5.6 or above and never 5.x: a second copy, a downgrade or a 5.x is a
 * deliberate change that comes with a new measurement, never a side effect of
 * someone else's install.
 */

const LOCKFILE = resolve(__dirname, "../../../../pnpm-lock.yaml");

/** Every version of `name` the lockfile's `packages:` section resolves. */
export function resolvedVersions(lock: string, name: string): string[] {
  const escaped = name.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&");
  const key = new RegExp(
    `^ {2}'?${escaped}@(\\d+\\.\\d+\\.\\d+[^'(:\\s]*)`,
    "gm",
  );
  const packages = lock.split(/^packages:\s*$/m)[1]?.split(/^\S/m)[0] ?? "";
  return [...new Set([...packages.matchAll(key)].map((m) => m[1]!))];
}

function atLeast(version: string, floor: [number, number, number]): boolean {
  const parts = version.split(/[.-]/).slice(0, 3).map(Number);
  for (let i = 0; i < 3; i++) {
    if (parts[i]! !== floor[i]) return parts[i]! > floor[i]!;
  }
  return true;
}

/** Why the lockfile's zustand is not the one the canvas was measured on. */
export function zustandProblems(lock: string): string[] {
  const versions = resolvedVersions(lock, "zustand");
  if (versions.length !== 1) {
    return [`zustand: ${versions.length} versions (${versions.join(", ")})`];
  }
  const [version] = versions as [string];
  if (!atLeast(version, [4, 5, 6]))
    return [`zustand ${version} is below 4.5.6`];
  if (atLeast(version, [5, 0, 0]))
    return [`zustand ${version} is 5.x or later`];
  return [];
}

const lock = (...versions: string[]) =>
  [
    "lockfileVersion: '9.0'",
    "",
    "importers: {}",
    "",
    "packages:",
    "",
    ...versions.flatMap((v) => [`  zustand@${v}:`, "    resolution: {}", ""]),
    "snapshots:",
    "",
    ...versions.map((v) => `  zustand@${v}(react@19.2.8): {}`),
    "",
  ].join("\n");

describe("one zustand of the 4.x line (workflow-builder-ui R1.1)", () => {
  it("holds in the workspace's lockfile, with @xyflow/react at 12.12.0", () => {
    const text = readFileSync(LOCKFILE, "utf8");
    expect(zustandProblems(text)).toEqual([]);
    expect(resolvedVersions(text, "@xyflow/react")).toEqual(["12.12.0"]);
  });

  it("accepts one version from 4.5.6 to below 5", () => {
    expect(zustandProblems(lock("4.5.6"))).toEqual([]);
    expect(zustandProblems(lock("4.5.7"))).toEqual([]);
  });

  it("refuses a second copy, a 5.x and a version below 4.5.6", () => {
    expect(zustandProblems(lock("4.5.7", "5.0.8"))).toEqual([
      "zustand: 2 versions (4.5.7, 5.0.8)",
    ]);
    expect(zustandProblems(lock("5.0.8"))).toEqual([
      "zustand 5.0.8 is 5.x or later",
    ]);
    expect(zustandProblems(lock("4.5.5"))).toEqual([
      "zustand 4.5.5 is below 4.5.6",
    ]);
    expect(zustandProblems(lock("4.4.7"))).toEqual([
      "zustand 4.4.7 is below 4.5.6",
    ]);
    expect(zustandProblems(lock())).toEqual(["zustand: 0 versions ()"]);
  });
});
