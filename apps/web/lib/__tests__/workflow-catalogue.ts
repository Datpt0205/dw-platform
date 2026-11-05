import { readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";
import type { StepTypeSpec } from "../workflow-graph";

/**
 * The fake catalogue of workflow-builder-ui/01 (`catalogue.json`), read as
 * `GET /api/v1/studio/node-types` answers (`NodeTypeView`): `map` ports are
 * `keyed`, `fixed` ports carry `ports`, and each type's `config_schema`
 * requires the lanes the fake marks required (the keyed object included), so
 * the tree reads lanes exactly as it reads the route's. `logic.switch@1`
 * keeps the route's schema (`on` and `cases` required, `default` not) with a
 * `default` value of its own, which a new step must carry. The fixtures stay
 * as ticket 01 wrote them; this is the one place their catalogue changes
 * shape, for tests only.
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
  return {
    type: fake.type,
    label_vi: fake.label_vi,
    config_schema: { type: "object", required, properties },
    ports,
  };
}

const fake = JSON.parse(readFileSync(join(DIR, "catalogue.json"), "utf8")) as {
  types: FakeType[];
};

export const NODE_TYPES: StepTypeSpec[] = fake.types.map(toSpec);

export const FIXTURES: string[] = readdirSync(DIR)
  .filter((name) => /^f\d-.*\.json$/.test(name))
  .sort();

export function loadFixture(name: string): Record<string, unknown> {
  const prefix =
    name.length === 2 ? FIXTURES.find((f) => f.startsWith(name))! : name;
  return JSON.parse(readFileSync(join(DIR, prefix), "utf8")) as Record<
    string,
    unknown
  >;
}
