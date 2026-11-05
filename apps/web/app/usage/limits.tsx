"use client";

import { Card, Flex, Progress, Typography } from "antd";
import type { LimitLine } from "@dw/api-client";
import { formatDate } from "../../lib/dates";
import { formatCount, formatUsd } from "../../lib/money";

/**
 * What each hard limit of the company has used this period (usage-and-limits
 * ticket 03, spec "Màn hình"): one antd Progress per limit, `used` and what
 * running leases hold over the effective limit, read from `GET /api/v1/limits`.
 * The labels and amounts are the ones the limits screen uses, from here.
 */

export const METRIC_LABELS: Record<string, string> = {
  "cost_usd/day": "Chi phí mỗi ngày",
  "cost_usd/month": "Chi phí mỗi tháng",
  "tokens/month": "Token mỗi tháng",
  "runs/day": "Lượt chạy mỗi ngày",
};

export const SCOPE_LABELS: Record<string, string> = {
  tenant: "Công ty",
  workspace: "Workspace",
  agent: "Agent",
  workflow: "Quy trình",
};

/** An amount of a limit's metric as text: USD for money, a count otherwise. */
export function formatAmount(metric: string, value: string): string {
  return metric === "cost_usd" ? formatUsd(value) : formatCount(Number(value));
}

export function pairLabel(
  line: Pick<LimitLine, "metric" | "window_kind">,
): string {
  return (
    METRIC_LABELS[`${line.metric}/${line.window_kind}`] ??
    `${line.metric}/${line.window_kind}`
  );
}

function percent(line: LimitLine): number {
  const limit = Number(line.effective_limit);
  if (!(limit > 0)) return 100;
  const spent = Number(line.used) + Number(line.reserved);
  return Math.min(100, Math.round((spent / limit) * 100));
}

export function LimitsProgress({
  lines,
  scopeName,
}: {
  lines: LimitLine[];
  scopeName: (line: LimitLine) => string;
}) {
  if (lines.length === 0) return null;
  return (
    <Card title="Hạn mức của kỳ này">
      <Flex vertical gap="middle">
        {lines.map((line) => {
          const value = percent(line);
          return (
            <div
              key={`${line.scope_type}:${line.scope_id}:${line.metric}:${line.window_kind}`}
            >
              <Flex justify="space-between" wrap gap="small">
                <Typography.Text strong>
                  {pairLabel(line)} · {scopeName(line)}
                </Typography.Text>
                <Typography.Text type="secondary">
                  {formatAmount(line.metric, line.used)} /{" "}
                  {formatAmount(line.metric, line.effective_limit)} · đặt lại{" "}
                  {formatDate(line.resets_at)}
                </Typography.Text>
              </Flex>
              <Progress
                percent={value}
                status={value >= 100 ? "exception" : "normal"}
                aria-label={`${pairLabel(line)} đã dùng ${value}%`}
              />
            </div>
          );
        })}
      </Flex>
    </Card>
  );
}
