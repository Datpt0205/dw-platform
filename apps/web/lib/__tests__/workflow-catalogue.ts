import { readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";
import type { StepTypeSpec } from "../workflow-graph";

/**
 * The fake catalogue of workflow-builder-ui/01 (`catalogue.json`), read as
 * `GET /api/v1/studio/node-types` answers (`NodeTypeView`): `map` ports are
 * `keyed`, `fixed` ports carry `ports`, and each type's `config_schema`
 * requires the lanes the fake marks required (the keyed object included), so
 * the tree reads lanes exactly as it reads the route's. Each type carries the
 * route's `block`, `ends_run` and `exits_loop` (ticket 04), the tier B types
 * included (`logic.parallel@1`, `logic.loop@1`, `logic.break@1`,
 * `flow.subworkflow@1`), so the canvas is drawn from the flags before
 * workflow-nodes registers them. `logic.switch@1` keeps the route's schema
 * (`on` and `cases` required, `default` not) with a `default` value of its
 * own, which a new step must carry; the approval, loop and sub-workflow types
 * carry the config keys workflow-nodes declares for them (R11.1, R12.1,
 * R13.1). The fixtures stay as ticket 01 wrote them; this is the one place
 * their catalogue changes shape, for tests only.
 */

const DIR = resolve(__dirname, "../__fixtures__/workflows");

type FakePorts =
  | { kind: "none" }
  | {
      kind: "fixed";
      items: { name: string; label_vi: string; required: boolean }[];
    }
  | { kind: "map"; key: string; default?: { name: string; label_vi: string } };

interface FakeType {
  type: string;
  label_vi: string;
  ports: FakePorts;
  block: StepTypeSpec["block"];
  ends_run: boolean;
  exits_loop: boolean;
}

const LANE = { type: "array", items: { type: "object" } };

function toSpec(fake: FakeType): StepTypeSpec {
  const properties: Record<string, unknown> = {};
  const required: string[] = [];
  let ports: StepTypeSpec["ports"];
  if (fake.ports.kind === "map") {
    properties[fake.ports.key] = { type: "object", additionalProperties: LANE };
    required.push(fake.ports.key);
    if (fake.ports.default) properties[fake.ports.default.name] = LANE;
    ports = {
      kind: "keyed",
      key: fake.ports.key,
      default: fake.ports.default ?? null,
    };
  } else if (fake.ports.kind === "fixed") {
    for (const port of fake.ports.items) {
      properties[port.name] = LANE;
      if (port.required) required.push(port.name);
    }
    ports = {
      kind: "fixed",
      ports: fake.ports.items.map(({ name, label_vi }) => ({ name, label_vi })),
    };
  } else {
    ports = { kind: "fixed", ports: [] };
  }
  if (fake.type === "logic.switch@1") {
    properties.on = { type: "string", minLength: 1 };
    properties.match = { type: "string", enum: ["first"], default: "first" };
    required.unshift("on");
  }
  if (fake.type.startsWith("human.approval@")) {
    // workflow-nodes R9.1, R12.1: a scope, the people (a list or an
    // expression) and the rule, `any` when absent.
    properties.required_scope = { type: "string", minLength: 1 };
    properties.assignees = {
      oneOf: [{ type: "array", items: { type: "string" } }, { type: "string" }],
    };
    properties.approval_rule = { type: "string", enum: ["any", "all"] };
    properties.subject = { type: "string" };
    required.unshift("required_scope");
  }
  if (fake.type === "logic.loop@1") {
    properties.condition = { type: "string", minLength: 1 };
    properties.max_iterations = { type: "integer", minimum: 1 };
    required.unshift("condition", "max_iterations");
  }
  if (fake.type === "flow.subworkflow@1") {
    properties.workflow = { type: "string", pattern: "^[a-z][a-z0-9_]{1,39}$" };
    properties.inputs = { type: "object" };
    required.unshift("workflow");
  }
  return {
    type: fake.type,
    label_vi: fake.label_vi,
    config_schema: { type: "object", required, properties },
    ports,
    block: fake.block,
    ends_run: fake.ends_run,
    exits_loop: fake.exits_loop,
  };
}

const fake = JSON.parse(readFileSync(join(DIR, "catalogue.json"), "utf8")) as {
  types: FakeType[];
};

export const NODE_TYPES: StepTypeSpec[] = fake.types.map(toSpec);

export const FIXTURES: string[] = readdirSync(DIR)
  .filter((name) => /^f\d+-.*\.json$/.test(name))
  .sort((a, b) => fixtureNumber(a) - fixtureNumber(b));

function fixtureNumber(name: string): number {
  return Number(/^f(\d+)-/.exec(name)![1]);
}

export function loadFixture(name: string): Record<string, unknown> {
  const prefix = /^f\d+$/.test(name)
    ? FIXTURES.find((f) => f.startsWith(`${name}-`))!
    : name;
  return JSON.parse(readFileSync(join(DIR, prefix), "utf8")) as Record<
    string,
    unknown
  >;
}
