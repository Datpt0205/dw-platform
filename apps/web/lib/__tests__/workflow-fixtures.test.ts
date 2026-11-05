import { readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { CANVAS_GROUPS } from "../../../../packages/typescript/ui/src/theme";

/**
 * F1-F9 (workflow-builder-ui/01) are `dw.workflow/v1` documents in wf-lite's
 * one shape (ADR-0112 (Accepted) Amendments 2026-11-03), so the layout of
 * ticket 02 is built against the format the server holds and not a second
 * tree. A step is `{id, type, description, config}` plus the keys
 * workflow-engine/01 adds (`retry`, `timeout_s`, `on_error`, `error_lane`);
 * a lane sits inside `config` under its port's name, found here through the
 * fake `catalogue.json` (shaped like `GET /api/v1/studio/node-types`), never a
 * lane name written in code. Steps and depth count as workflow-engine/01
 * step 1 does: every step of every lane, `error_lane` included, `triggers[]`
 * not; a step of `steps[]` is at depth 1. Ticket 02 adds
 * `WorkflowDocument.model_validate` over the same files once the model has
 * those keys.
 */

const DIR = resolve(__dirname, "../__fixtures__/workflows");
const MAX_TREE_STEPS = 500;
const MAX_NESTING = 10;
const STEP_ID = /^[a-z][a-z0-9_]{0,39}$/;
const STEP_TYPE = /^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*@[1-9][0-9]*$/;

type Ports =
  | { kind: "none" }
  | { kind: "fixed"; items: { name: string; required: boolean }[] }
  | { kind: "map"; key: string; default?: { name: string } };

interface CatalogueType {
  type: string;
  group: string;
  on_error: string[];
  ports: Ports;
}

interface Step {
  id: string;
  type: string;
  description?: string;
  config: Record<string, unknown>;
  retry?: { max_attempts: number; backoff: string };
  timeout_s?: number;
  on_error?: string;
  error_lane?: Step[];
}

const catalogue = JSON.parse(
  readFileSync(join(DIR, "catalogue.json"), "utf8"),
) as { groups: { code: string }[]; types: CatalogueType[] };
const TYPES = new Map(catalogue.types.map((t) => [t.type, t]));

/** A step's lanes by port, read through the catalogue; the error lane last. */
function lanes(step: Step): [string, Step[]][] {
  const ports = TYPES.get(step.type)!.ports;
  const config = step.config;
  const found: [string, Step[]][] = [];
  if (ports.kind === "fixed") {
    for (const { name } of ports.items) {
      if (name in config) found.push([name, config[name] as Step[]]);
    }
  }
  if (ports.kind === "map") {
    const map = (config[ports.key] ?? {}) as Record<string, Step[]>;
    for (const [key, lane] of Object.entries(map)) {
      found.push([`${ports.key}.${key}`, lane]);
    }
    if (ports.default && ports.default.name in config) {
      found.push([ports.default.name, config[ports.default.name] as Step[]]);
    }
  }
  if (step.error_lane) found.push(["error_lane", step.error_lane]);
  return found;
}

function walk(
  steps: Step[],
  visit: (step: Step, depth: number) => void,
  depth = 1,
) {
  for (const step of steps) {
    visit(step, depth);
    for (const [, lane] of lanes(step)) walk(lane, visit, depth + 1);
  }
}

const FILES = readdirSync(DIR)
  .filter((name) => /^f\d+-.*\.json$/.test(name))
  .sort((a, b) => fixtureNumber(a) - fixtureNumber(b));

function fixtureNumber(name: string): number {
  return Number(name.split("-")[0]!.slice(1));
}

function load(name: string) {
  return JSON.parse(readFileSync(join(DIR, name), "utf8")) as Record<
    string,
    unknown
  > & { triggers: Step[]; steps: Step[] };
}

function measure(name: string): { count: number; depth: number } {
  let count = 0;
  let depth = 0;
  walk(load(name).steps, (_, d) => {
    count++;
    depth = Math.max(depth, d);
  });
  return { count, depth };
}

describe("F1-F10 are dw.workflow/v1 documents in wf-lite's shape", () => {
  it("are ten, F1 to F9 of ticket 01 and F10 of ticket 04", () => {
    expect(FILES.map((name) => name.split("-")[0])).toEqual([
      "f1",
      "f2",
      "f3",
      "f4",
      "f5",
      "f6",
      "f7",
      "f8",
      "f9",
      "f10",
    ]);
  });

  it.each(FILES)(
    "%s: Studio's envelope, no key or version, no layout",
    (name) => {
      const doc = load(name);
      expect(doc.schema).toBe("dw.workflow/v1");
      expect(Object.keys(doc).sort()).toEqual(
        expect.arrayContaining(["schema", "steps", "triggers"]),
      );
      for (const key of ["key", "version", "edges", "nodes", "positions"]) {
        expect(doc).not.toHaveProperty(key);
      }
      expect(doc.triggers.length).toBeGreaterThan(0);
      for (const trigger of doc.triggers) {
        expect(TYPES.get(trigger.type)?.group).toBe("trigger");
        for (const key of ["retry", "timeout_s", "on_error", "error_lane"]) {
          expect(trigger).not.toHaveProperty(key);
        }
      }
    },
  );

  it.each(FILES)(
    "%s: every step has the Studio step keys and a known type",
    (name) => {
      const ids = new Set<string>();
      walk(load(name).steps, (step) => {
        const where = `${name}: ${step.id}`;
        expect(step.id, where).toMatch(STEP_ID);
        expect(
          step.id.startsWith("join__") || step.id.startsWith("wait__"),
        ).toBe(false);
        expect(ids.has(step.id), `${where} repeats`).toBe(false);
        ids.add(step.id);
        expect(step.type, where).toMatch(STEP_TYPE);
        const type = TYPES.get(step.type);
        expect(type, `${where}: ${step.type}`).toBeDefined();
        expect(type!.group).not.toBe("trigger");
        expect(Object.keys(step).sort(), where).toEqual(
          expect.arrayContaining([
            "config",
            "description",
            "on_error",
            "retry",
            "timeout_s",
          ]),
        );
        for (const key of Object.keys(step)) {
          expect(
            [
              "id",
              "type",
              "description",
              "config",
              "retry",
              "timeout_s",
              "on_error",
              "error_lane",
            ],
            `${where}: ${key}`,
          ).toContain(key);
        }
        expect(type!.on_error, where).toContain(step.on_error);
        expect("error_lane" in step, where).toBe(step.on_error === "route");
        expect(step.timeout_s!).toBeGreaterThanOrEqual(1);
        expect(step.timeout_s!).toBeLessThanOrEqual(900);
        expect(step.retry!.max_attempts).toBeGreaterThanOrEqual(1);
        expect(step.retry!.max_attempts).toBeLessThanOrEqual(5);
        // Every port the type declares as required has its lane (Studio's
        // every_port_lane); `[]` counts.
        const ports = type!.ports;
        if (ports.kind === "fixed") {
          for (const port of ports.items.filter((p) => p.required)) {
            expect(
              Array.isArray(step.config[port.name]),
              `${where}: ${port.name}`,
            ).toBe(true);
          }
        }
        if (ports.kind === "map") {
          expect(
            Object.keys(step.config[ports.key] ?? {}).length,
          ).toBeGreaterThan(0);
          if (ports.default) {
            expect(Array.isArray(step.config[ports.default.name]), where).toBe(
              true,
            );
          }
        }
      });
    },
  );

  it("count and depth as workflow-engine/01 counts them, at the platform caps", () => {
    const measured = Object.fromEntries(
      FILES.map((name) => [name.split("-")[0]!, measure(name)]),
    );
    expect(measured.f1!.count).toBe(15);
    expect(measured.f6!.count).toBe(300);
    expect(measured.f7!.count).toBe(MAX_TREE_STEPS);
    expect(measured.f7!.depth).toBe(MAX_NESTING);
    for (const { depth } of Object.values(measured)) {
      expect(depth).toBeLessThanOrEqual(MAX_NESTING);
    }
  });

  it("F2 nests an 8-lane switch two deep; F3 a parallel of 3 in a loop in a switch", () => {
    const f2 = load("f2-switch-8-nested.json").steps.find(
      (s) => s.type === "logic.switch@1",
    )!;
    expect(lanes(f2)).toHaveLength(8);
    for (const [port, lane] of lanes(f2).filter(([p]) => p !== "default")) {
      const inner = lane.find((s) => s.type === "logic.switch@1");
      expect(inner, port).toBeDefined();
      expect(lanes(inner!)).toHaveLength(8);
    }
    const kinds: string[] = [];
    walk(load("f3-parallel-in-loop-in-switch.json").steps, (step, depth) => {
      if (step.type === "logic.parallel@1") {
        kinds.push(`${depth}:${lanes(step).length}`);
      }
    });
    expect(kinds).toEqual(["3:3"]);
  });

  it("F4 has an error lane on every step of its main sequence", () => {
    for (const step of load("f4-error-lane-everywhere.json").steps) {
      expect(step.on_error, step.id).toBe("route");
    }
  });

  it("F5 has a loop around an approval and an approval everyone must give", () => {
    const steps = load("f5-rework-loop-approval.json").steps;
    const loop = steps.find((s) => s.type === "logic.loop@1")!;
    expect(
      (loop.config.body as Step[]).some((s) => s.type === "human.approval@2"),
    ).toBe(true);
    const all = steps.find((s) => s.config.approval_rule === "all")!;
    expect((all.config.assignees as string[]).length).toBeGreaterThan(1);
  });

  it("F9 leaves its inner loop by Thoát vòng lặp from a rejection", () => {
    const breaks: number[] = [];
    walk(load("f9-three-level-approval-rework.json").steps, (step, depth) => {
      if (step.type === "logic.break@1") breaks.push(depth);
    });
    expect(breaks.length).toBeGreaterThanOrEqual(3);
  });

  it("the catalogue gives every type a group the vocabulary colours, and a lane source", () => {
    expect(catalogue.groups.map((g) => g.code)).toEqual([...CANVAS_GROUPS]);
    const groups = new Set(catalogue.groups.map((g) => g.code));
    for (const type of catalogue.types) {
      expect(groups, type.type).toContain(type.group);
      expect(["none", "fixed", "map"]).toContain(type.ports.kind);
    }
  });
});
