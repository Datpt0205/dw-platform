import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  CANVAS_VOCABULARY,
  canvasTokenName,
  type CanvasColour,
} from "../../../../packages/typescript/ui/src/theme";
import { globMatches, sources } from "./source-tree";

/**
 * The canvas takes every colour from the theme (workflow-builder-ui R1.5,
 * R1.9, BU14; `.claude/rules/ui-quality.md` §1, §12). Under
 * `app/studio/**\/canvas/**`, in the builder's components beside it
 * (`app/studio/workflows/*\/builder/**`), and in `lib/workflow-layout.ts` and
 * `lib/workflow-graph.ts` once they exist, no file names a colour of its own:
 * not a hex value, not a colour function, and not a CSS colour name given to a
 * colour declaration, a custom property (`--xy-*` included) or a `style`,
 * `stroke`, `fill` or `color` in a component (`<Tag color="magenta">` is one of
 * antd's light preset tints). The root is a parameter, so the cases that must
 * go red run on a scratch tree.
 */

const WEB = resolve(__dirname, "../..");
const CANVAS_GLOB = "app/studio/**/canvas/**";
/** The builder's own components beside the canvas (BU14: "thành phần builder"). */
const BUILDER_GLOB = "app/studio/workflows/*/builder/**";
const PURE_MODULES = ["lib/workflow-layout.ts", "lib/workflow-graph.ts"];

/** CSS named colours (CSS Color 4), less the three that name no colour. */
const NAMED = new Set(
  (
    "aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue " +
    "blueviolet brown burlywood cadetblue chartreuse chocolate coral cornflowerblue cornsilk " +
    "crimson cyan darkblue darkcyan darkgoldenrod darkgray darkgreen darkgrey darkkhaki " +
    "darkmagenta darkolivegreen darkorange darkorchid darkred darksalmon darkseagreen " +
    "darkslateblue darkslategray darkslategrey darkturquoise darkviolet deeppink deepskyblue " +
    "dimgray dimgrey dodgerblue firebrick floralwhite forestgreen fuchsia gainsboro ghostwhite " +
    "gold goldenrod gray green greenyellow grey honeydew hotpink indianred indigo ivory khaki " +
    "lavender lavenderblush lawngreen lemonchiffon lightblue lightcoral lightcyan " +
    "lightgoldenrodyellow lightgray lightgreen lightgrey lightpink lightsalmon lightseagreen " +
    "lightskyblue lightslategray lightslategrey lightsteelblue lightyellow lime limegreen linen " +
    "magenta maroon mediumaquamarine mediumblue mediumorchid mediumpurple mediumseagreen " +
    "mediumslateblue mediumspringgreen mediumturquoise mediumvioletred midnightblue mintcream " +
    "mistyrose moccasin navajowhite navy oldlace olive olivedrab orange orangered orchid " +
    "palegoldenrod palegreen paleturquoise palevioletred papayawhip peachpuff peru pink plum " +
    "powderblue purple rebeccapurple red rosybrown royalblue saddlebrown salmon sandybrown " +
    "seagreen seashell sienna silver skyblue slateblue slategray slategrey snow springgreen " +
    "steelblue tan teal thistle tomato turquoise violet wheat white whitesmoke yellow " +
    "yellowgreen"
  ).split(" "),
);

const HEX = /#(?:[0-9a-f]{8}|[0-9a-f]{6}|[0-9a-f]{3,4})(?![\w-])/i;
const FUNCTION = /\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\(/i;
/** A CSS declaration whose value is a colour: by its property's name. */
const CSS_COLOUR_PROPERTY =
  /^(?:--.*|.*(?:color|background|border|outline|fill|stroke|shadow|decoration|caret|accent|column-rule).*)$/i;
/** A JSX attribute or a style key that takes a colour. */
const TSX_COLOUR_KEY =
  /\b([\w-]*(?:colou?r|background|border|outline|fill|stroke|shadow)[\w-]*)\s*[:=]\s*\{?\s*["'`]([^"'`]*)["'`]/gi;

function stripComments(text: string, css: boolean): string {
  const blocks = text.replace(/\/\*[\s\S]*?\*\//g, " ");
  return css ? blocks : blocks.replace(/(^|[^:"'`])\/\/[^\n]*/g, "$1");
}

/** A colour name among a value's words; `var(...)` is a token, not a word. */
function namedColour(value: string): string | undefined {
  const words = value
    .replace(/var\([^)]*\)/g, " ")
    .toLowerCase()
    .split(/[^a-z]+/);
  return words.find((word) => NAMED.has(word));
}

/** Every colour one file names, as "<file>: <what>". */
export function colourFindings(path: string, text: string): string[] {
  const css = path.endsWith(".css");
  const body = stripComments(text, css);
  const found: string[] = [];
  const hex = HEX.exec(body);
  if (hex) found.push(`${path}: ${hex[0]}`);
  const fn = FUNCTION.exec(body);
  if (fn) found.push(`${path}: ${fn[0]}`);
  if (css) {
    for (const m of body.matchAll(/([\w-]+)\s*:\s*([^;{}]+)/g)) {
      const [, property, value] = m as unknown as [string, string, string];
      const name = CSS_COLOUR_PROPERTY.test(property)
        ? namedColour(value)
        : undefined;
      if (name) found.push(`${path}: ${property}: ${name}`);
    }
  } else {
    for (const m of body.matchAll(TSX_COLOUR_KEY)) {
      const [, key, value] = m as unknown as [string, string, string];
      const name = namedColour(value);
      if (name) found.push(`${path}: ${key}: ${name}`);
    }
  }
  return found;
}

/** The files the rule covers under a root laid out like `apps/web`. */
export function coveredFiles(root: string): string[] {
  const app = existsSync(join(root, "app"))
    ? sources(join(root, "app")).map((p) => `app/${p}`)
    : [];
  return [
    ...app.filter(
      (p) =>
        (globMatches(CANVAS_GLOB, p) || globMatches(BUILDER_GLOB, p)) &&
        /\.(ts|tsx|css)$/.test(p),
    ),
    ...PURE_MODULES.filter((p) => existsSync(join(root, p))),
  ];
}

export function colourProblems(root: string): string[] {
  return coveredFiles(root).flatMap((path) =>
    colourFindings(path, readFileSync(join(root, path), "utf8")),
  );
}

const scratch: string[] = [];
afterEach(() => {
  for (const dir of scratch.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

function tree(files: Record<string, string>): string {
  const base = mkdtempSync(join(tmpdir(), "canvas-colours-"));
  scratch.push(base);
  for (const [path, text] of Object.entries(files)) {
    mkdirSync(dirname(join(base, path)), { recursive: true });
    writeFileSync(join(base, path), text);
  }
  return base;
}

const AT = "app/studio/workflows/[id]/builder/canvas";

describe("the canvas names no colour of its own (BU14)", () => {
  it("holds for the real canvas", () => {
    expect(coveredFiles(WEB)).toContain(`${AT}/workflow-canvas.tsx`);
    expect(coveredFiles(WEB)).toContain(`${AT}/workflow-canvas.css`);
    expect(coveredFiles(WEB)).toContain(
      "app/studio/workflows/[id]/builder/workflow-builder.tsx",
    );
    expect(colourProblems(WEB)).toEqual([]);
  });

  it.each([
    ["a.css", ".x { color: #1677ff; }", "#1677ff"],
    ["a.css", ".x { --xy-edge-stroke: rgba(0,0,0,.45); }", "rgba("],
    ["a.css", ".x { border-color: hsla(0,0%,0%,.5); }", "hsla("],
    ["a.css", ".x { background: white; }", "background: white"],
    ["a.css", ".x { --xy-edge-stroke: grey; }", "--xy-edge-stroke: grey"],
    ["a.css", ".x { outline: 1px solid oklch(0.5 0.1 200); }", "oklch("],
    ["a.css", ".x { color: #fff8; }", "#fff8"],
    ["a.tsx", 'export const s = { stroke: "#b1b1b7" };', "#b1b1b7"],
    [
      "a.tsx",
      'export const t = <Tag color="magenta">x</Tag>;',
      "color: magenta",
    ],
    [
      "a.tsx",
      'export const d = <div style={{ backgroundColor: "red" }} />;',
      "backgroundColor: red",
    ],
    ["a.tsx", 'export const p = <path fill="black" />;', "fill: black"],
    ["a.ts", "export const c = `rgb(${1}, 2, 3)`;", "rgb("],
  ])("goes red on %s with %s, naming the file", (name, text, what) => {
    const root = tree({ [`${AT}/${name}`]: text });
    expect(colourProblems(root)).toEqual([`${AT}/${name}: ${what}`]);
  });

  it("reads lib/workflow-layout.ts and lib/workflow-graph.ts once they exist", () => {
    const root = tree({
      "lib/workflow-layout.ts": 'export const c = "#000";',
      "lib/workflow-graph.ts": "export const c = 'hsl(0 0% 0%)';",
      "lib/other.ts": 'export const c = "#000";',
    });
    expect(colourProblems(root)).toEqual([
      "lib/workflow-layout.ts: #000",
      "lib/workflow-graph.ts: hsl(",
    ]);
  });

  it("passes theme variables, the words that name no colour, and comments", () => {
    const root = tree({
      [`${AT}/a.css`]: [
        "/* the library's #b1b1b7 grey, replaced */",
        ".x { border: 1px solid var(--ant-color-border); }",
        ".y { --xy-handle-background-color: transparent; color: currentColor; }",
        ".z { --xy-node-border: none; fill: inherit; }",
        ".w { --xy-edge-stroke: var(--ant-canvas-edge); }",
      ].join("\n"),
      [`${AT}/b.tsx`]: [
        "// a #fff comment",
        'export const b = <Card style={{ width: 256, borderColor: "var(--ant-color-border)" }} />;',
        'export const label = "Phóng to";',
      ].join("\n"),
      "app/studio/w/a.css": ".x { color: red; }",
    });
    expect(colourProblems(root)).toEqual([]);
  });

  it("reads only the vocabulary's own canvas tokens", () => {
    const known = new Set(
      (Object.keys(CANVAS_VOCABULARY.colours.light) as CanvasColour[]).map(
        (name) =>
          `--ant-${canvasTokenName(name).replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`)}`,
      ),
    );
    const read = coveredFiles(WEB).flatMap((path) => [
      ...readFileSync(join(WEB, path), "utf8").matchAll(/--ant-canvas-[\w-]+/g),
    ]);
    expect(read.length).toBeGreaterThan(0);
    for (const [name] of read) expect(known).toContain(name);
  });
});
