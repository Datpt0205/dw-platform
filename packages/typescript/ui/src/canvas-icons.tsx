"use client";

import {
  BranchesOutlined,
  DatabaseOutlined,
  ForkOutlined,
  HourglassOutlined,
  LogoutOutlined,
  PartitionOutlined,
  RetweetOutlined,
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

/**
 * The icon of each mark the canvas's grammar draws beside its words, never
 * instead of them (workflow-builder-ui R1.5, BU14): the "Song song" frame,
 * the loop's "Lặp lại" way back, a "Thoát vòng lặp" exit, the "Quy trình con"
 * mark, and a wait ("Chờ tất cả nhánh xong", "Chờ Quy trình con xong").
 */
export const CANVAS_MARKS = {
  parallel: ForkOutlined,
  repeat: RetweetOutlined,
  exit: LogoutOutlined,
  subworkflow: PartitionOutlined,
  wait: HourglassOutlined,
} as const;

export type CanvasMark = keyof typeof CANVAS_MARKS;
