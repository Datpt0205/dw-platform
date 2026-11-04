import { readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

/**
 * Walking a package's sources and matching them against a path glob, for the
 * guards that read source text: `antd-only.test.ts` (the UI allowlist) and
 * `canvas-colours.test.ts` (the canvas's colours). One copy, so the two cannot
 * disagree about what lies under `app/studio/**\/canvas/**`.
 */

const SKIPPED_DIRS = new Set(["node_modules", ".next", "test-results"]);
const SOURCE = /\.(ts|tsx|mts|cts|js|jsx|mjs|cjs|css)$/;

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
