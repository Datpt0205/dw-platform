"use client";

import { Alert, Flex, List, Tag, Typography } from "antd";
import type {
  WorkflowProblem,
  WorkflowSimulation,
  WorkflowStepChange,
} from "@dw/api-client";
import { formatDateTime } from "../../lib/dates";
import {
  SIMULATION_OUTCOME,
  STEP_CHANGE,
  lanePath,
  stepType,
} from "../../lib/digital-workers/labels";

/**
 * What a workflow proposal or draft changes, by step id (wf-ai R4.1): one
 * line per step added, removed, changed or moved, with where it sits. Read
 * by the assistant's page and the publication's approval card alike.
 */
export function WorkflowDiff({ changes }: { changes: WorkflowStepChange[] }) {
  if (changes.length === 0) {
    return (
      <Typography.Text>
        Không đổi bước nào so với bản đang chạy.
      </Typography.Text>
    );
  }
  return (
    <List
      size="small"
      bordered
      dataSource={changes}
      rowKey={(change) => `${change.change}:${change.step_id}`}
      renderItem={(change) => {
        const label = STEP_CHANGE[change.change];
        return (
          <List.Item>
            <Flex wrap gap="small" align="center">
              <Tag color={label.color}>{label.label}</Tag>
              <Typography.Text code>{change.step_id}</Typography.Text>
              <Typography.Text>{stepType(change.type)}</Typography.Text>
              <Typography.Text>
                {change.change === "moved" && change.from_lane !== null
                  ? `từ ${lanePath(change.from_lane)} tới ${lanePath(change.lane)}`
                  : lanePath(change.lane)}
              </Typography.Text>
            </Flex>
          </List.Item>
        );
      }}
    />
  );
}

/** The platform's problems with a proposal, in Vietnamese (wf-ai R3.1). */
export function WorkflowProblems({
  problems,
}: {
  problems: WorkflowProblem[];
}) {
  if (problems.length === 0) return null;
  return (
    <Alert
      type="error"
      showIcon
      title={`Còn ${problems.length} lỗi, chưa lưu được`}
      description={
        <ul className="m-0 pl-4">
          {problems.map((problem) => (
            <li key={`${problem.code}:${problem.path}`}>
              {problem.message_vi}{" "}
              <Typography.Text code>{problem.code}</Typography.Text>
            </li>
          ))}
        </ul>
      }
    />
  );
}

/** A dry run: its outcome, where it stopped, and what it would have called. */
export function SimulationResult({
  simulation,
}: {
  simulation: WorkflowSimulation;
}) {
  const outcome = SIMULATION_OUTCOME[simulation.outcome];
  return (
    <Flex vertical gap="small">
      <Flex wrap gap="small" align="center">
        <Tag color={outcome.color}>{outcome.label}</Tag>
        <Typography.Text>
          Chạy thử lúc {formatDateTime(simulation.created_at)}, không gửi gì ra
          ngoài.
        </Typography.Text>
      </Flex>
      {simulation.outcome === "failed" && (
        <Typography.Text>
          Dừng ở bước{" "}
          <Typography.Text code>{simulation.failed_step}</Typography.Text>
          {simulation.error ? `: ${simulation.error}` : ""}
        </Typography.Text>
      )}
      <Typography.Text strong>
        Công cụ sẽ được gọi ({simulation.tool_calls.length})
      </Typography.Text>
      {simulation.tool_calls.length === 0 ? (
        <Typography.Text>Không gọi công cụ nào.</Typography.Text>
      ) : (
        <ul className="m-0 pl-4">
          {simulation.tool_calls.map((call, index) => (
            <li key={index}>
              <Typography.Text code>{String(call.tool ?? "?")}</Typography.Text>
              {typeof call.decision_class === "string" && (
                <>
                  {" "}
                  theo loại quyết định{" "}
                  <Typography.Text code>{call.decision_class}</Typography.Text>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </Flex>
  );
}
