import { theme, type MappingAlgorithm, type ThemeConfig } from "antd";

/**
 * The one owner of colour, type, radius and the header's size (CLAUDE.md
 * "Web UI"). Tailwind reads these through the CSS variables antd emits;
 * nothing restates a value.
 *
 * Palette A of design v3, as the S0 spec's token table gives it (values from
 * the v3 shell CSS where the catalogue differs). The catalogue's light error
 * #e0352b is 4.46:1 on white and its dark #ff453a is 3.41:1 under white text;
 * the shell CSS's #c4271e and #d63a30 are the ones taken here, with the dark
 * error text split out as #ff6b61.
 */

/**
 * The class antd declares its CSS variables on (`.css-var-dw { --ant-… }`).
 * antd puts it on each of its own components; the root layout also puts it on
 * `<html>`, so plain elements and portals that are not antd's (a Radix dialog,
 * a toast) read the same tokens.
 */
export const THEME_CSS_VAR_CLASS = "css-var-dw";

/** Height of the top navbar. The header's 1px bottom rule sits inside it. */
const HEADER_HEIGHT = 56;

const light = {
  colorPrimary: "#0071e3",
  colorLink: "#0060c0",
  colorSuccess: "#1f9d4c",
  colorSuccessText: "#146c33",
  colorWarning: "#c26a00",
  colorWarningText: "#9a5200",
  colorError: "#c4271e",
  colorErrorText: "#c4271e",
  colorText: "#1d1d1f",
  colorTextSecondary: "#515154",
  colorTextTertiary: "#6e6e73",
  colorBgLayout: "#f5f5f7",
  colorBgContainer: "#ffffff",
  colorBorderSecondary: "#e3e3e8",
};

const dark: typeof light = {
  colorPrimary: "#0071e3",
  colorLink: "#4da3ff",
  colorSuccess: "#30d158",
  colorSuccessText: "#30d158",
  colorWarning: "#ff9f0a",
  colorWarningText: "#ff9f0a",
  colorError: "#d63a30",
  colorErrorText: "#ff6b61",
  colorText: "#f5f5f7",
  colorTextSecondary: "#c7c7cc",
  colorTextTertiary: "#8e8e93",
  colorBgLayout: "#000000",
  colorBgContainer: "#1c1c1e",
  colorBorderSecondary: "#3a3a3c",
};

/**
 * The workflow canvas's vocabulary (workflow-builder-ui R1.9, V4.27): a draft
 * for Đạt's review, written once here so a change at review touches only this
 * file. Each step-type group, keyed by the group code `GET
 * /api/v1/studio/node-types` returns (not by a type's prefix), has a colour
 * per mode, at least 3:1 on the card (`colorBgContainer`, antd `Card`'s
 * background) and never one of antd's light preset tints
 * (`.claude/rules/ui-quality.md` §12), and an `@ant-design/icons` icon, kept
 * beside this file in `canvas-icons.tsx`: a client module, because the root
 * layout reads `THEME_CSS_VAR_CLASS` from here on the server, where the icons
 * cannot load (`next build` fails on their React context).
 * "error" is the colour of the error lane and its "Khi lỗi" badge, not a
 * group; "edge" is a connection's stroke, 3:1 on the card and on the page.
 *
 * Every colour is a token antd already has: an antd preset shade of that mode
 * (light purple-6, cyan-7, gold-8, magenta-7, green-7; dark blue-7, purple-8,
 * cyan-7, gold-7, magenta-7, green-7) or a palette token above (colorPrimary,
 * colorError, colorTextTertiary). `buildTheme` passes them to antd as custom
 * tokens, which antd 6.6.5 emits as `--ant-canvas-<name>` on
 * `THEME_CSS_VAR_CLASS` (measured 2026-11-04), so the canvas's stylesheet
 * reads the same values the contrast test measures: one owner, two readers.
 */
export const CANVAS_GROUPS = [
  "trigger",
  "ai",
  "data",
  "logic",
  "human",
  "tool",
] as const;
export type CanvasGroup = (typeof CANVAS_GROUPS)[number];
export type CanvasColour = CanvasGroup | "error" | "edge";

const canvasLight: Record<CanvasColour, string> = {
  trigger: light.colorPrimary,
  ai: "#722ed1",
  data: "#08979c",
  logic: "#ad6800",
  human: "#c41d7f",
  tool: "#389e0d",
  error: light.colorError,
  edge: light.colorTextTertiary,
};

const canvasDark: Record<CanvasColour, string> = {
  trigger: "#3c89e8",
  ai: "#ab7ae0",
  data: "#33bcb7",
  logic: "#e8b339",
  human: "#e0529c",
  tool: "#6abe39",
  error: dark.colorError,
  edge: dark.colorTextTertiary,
};

export const CANVAS_VOCABULARY = {
  colours: { light: canvasLight, dark: canvasDark },
  /** A step card: fixed size, so the layout measures nothing it draws; tall
   * enough for the name, the type line and a row of badges (88 px held only
   * two of the three, workflow-builder-ui/01). */
  card: { width: 256, height: 120 },
  /** Connections: a solid stroke for the flow, a dashed one for the error
   * lane and the loop's return arrow (SVG `stroke-dasharray`). */
  edge: { width: 1.5, dash: "6 4" },
} as const;

/** The custom token antd emits as `--ant-canvas-<name>` for a canvas colour. */
export function canvasTokenName(name: CanvasColour): string {
  return `canvas${name[0]!.toUpperCase()}${name.slice(1)}`;
}

function canvasTokens(mode: ColorMode): Record<string, string> {
  const colours = CANVAS_VOCABULARY.colours[mode];
  return Object.fromEntries(
    (Object.keys(colours) as CanvasColour[]).map((name) => [
      canvasTokenName(name),
      colours[name],
    ]),
  );
}

/** The dark danger button's hover: lighter than its #ff6b61 label, as antd
 * lightens a hover in dark mode. */
const DARK_ERROR_TEXT_HOVER = "#ff8a82";

/**
 * These five are antd *seed* tokens. antd drops a seed key from the token
 * override and keeps what the algorithm derived from it, which in light is
 * the seed itself and in dark is not: the dark algorithm turns #0071e3 into
 * #0363c4 (antd 6.6.5, theme/util/alias.js). Running after the base
 * algorithm, this puts the seeds back, so both modes render what the palette
 * says. The colours derived around them (hover, border, background) stay
 * antd's.
 */
const keepSeedColors: MappingAlgorithm = (seed, map) => ({
  ...map!,
  colorPrimary: seed.colorPrimary,
  colorLink: seed.colorLink,
  colorSuccess: seed.colorSuccess,
  colorWarning: seed.colorWarning,
  colorError: seed.colorError,
});

export type ColorMode = "light" | "dark";

/**
 * @param fontFamily the family the app loaded (next/font renames it, so the
 *   app passes what it got); antd's own system stack follows it.
 */
export function buildTheme(mode: ColorMode, fontFamily: string): ThemeConfig {
  const palette = mode === "dark" ? dark : light;
  return {
    algorithm: [
      mode === "dark" ? theme.darkAlgorithm : theme.defaultAlgorithm,
      keepSeedColors,
    ],
    cssVar: { key: THEME_CSS_VAR_CLASS },
    token: {
      ...palette,
      // Not antd's own tokens: antd emits them as `--ant-canvas-*` for the
      // workflow canvas's stylesheet (CANVAS_VOCABULARY).
      ...canvasTokens(mode),
      borderRadius: 8,
      borderRadiusLG: 12,
      controlHeight: 32,
      fontSize: 14,
      fontFamily: `${fontFamily}, ${theme.defaultSeed.fontFamily}`,
    },
    components: {
      Layout: {
        headerHeight: HEADER_HEIGHT,
        headerBg: palette.colorBgContainer,
      },
      Menu: {
        // The selected item's bar lands on the header's bottom rule.
        horizontalLineHeight: `${HEADER_HEIGHT - 1}px`,
        // No rule down the side of the menu in the navigation drawer.
        activeBarBorderWidth: 0,
        // antd colours the current item with colorPrimary. In the drawer and
        // the "…" popup it sits on colorPrimaryBg, where light #0071e3 is
        // 4.27:1 and the link colour 5.57:1, so it takes the link colour in
        // both modes.
        itemSelectedColor: palette.colorLink,
        // On the dark header colorPrimary, current or hovered, is 3.62:1 and
        // the link colour 6.48:1. On the light header it is 4.70:1 and stays.
        ...(mode === "dark" && {
          horizontalItemSelectedColor: palette.colorLink,
          horizontalItemHoverColor: palette.colorLink,
        }),
      },
      // A status tag writes its text in the status colour on that colour's
      // own tint. The status colour is for icons, borders and fills: light
      // success on its tint is 2.96:1 and warning 3.27:1, dark error 3.4:1.
      // The status text colours are the ones made for text.
      Tag: {
        colorSuccess: palette.colorSuccessText,
        colorWarning: palette.colorWarningText,
        colorError: palette.colorErrorText,
      },
      // A danger button that is not filled writes its label in colorError:
      // dark #d63a30 on the card is 3.65:1. In dark mode it takes the error
      // text colour, and a filled one, now that light, takes the card colour
      // for its label instead of white (white on #ff6b61 is 2.6:1).
      ...(mode === "dark" && {
        Button: {
          colorError: palette.colorErrorText,
          colorErrorHover: DARK_ERROR_TEXT_HOVER,
          colorErrorActive: palette.colorError,
          dangerColor: palette.colorBgContainer,
        },
      }),
    },
  };
}
