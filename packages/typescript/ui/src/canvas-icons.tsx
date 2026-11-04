"use client";

import {
  BranchesOutlined,
  DatabaseOutlined,
  RobotOutlined,
  ThunderboltOutlined,
  ToolOutlined,
  UserOutlined,
  WarningOutlined,
} from "@ant-design/icons";
import type { CanvasGroup } from "./theme";

/**
 * The workflow canvas's icon per step-type group, and the error lane's: the
 * icon half of `CANVAS_VOCABULARY` in `theme.ts` (workflow-builder-ui R1.9), a
 * draft for Đạt's review. A client module of its own, because `theme.ts` is
 * also read on the server, where `@ant-design/icons` cannot load.
 */
export const CANVAS_ICONS = {
  trigger: ThunderboltOutlined,
  ai: RobotOutlined,
  data: DatabaseOutlined,
  logic: BranchesOutlined,
  human: UserOutlined,
  tool: ToolOutlined,
  error: WarningOutlined,
} satisfies Record<CanvasGroup | "error", unknown>;
