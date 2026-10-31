"use client";

import { Card, Flex, Steps, Tag, Typography } from "antd";
import type { WorkflowOutlineStep } from "@dw/api-client";
import { laneLabel, stepType } from "../../lib/digital-workers/labels";

/**
 * A pinned workflow read-only, drawn in antd (digital-worker R9.2; no
 * `@xyflow/react`, which only Studio's canvas routes take): the steps in a
 * vertical `Steps`, and the lanes of an approval or a switch each in a `Card`
 * nested under the step that holds them.
 */
export function WorkflowTree({ steps }: { steps: WorkflowOutlineStep[] }) {
  return (
    <Steps
      orientation="vertical"
      size="small"
      current={-1}
      items={steps.map((step) => ({
        key: step.id,
        // A step not yet run is antd's "wait", whose title is the secondary
        // colour; a read-only outline is not a progress bar, so the title
        // keeps the text colour.
        title: (
          <Typography.Text strong>
            {step.description ?? step.id}
          </Typography.Text>
        ),
        content: <StepBody step={step} />,
      }))}
    />
  );
}

function StepBody({ step }: { step: WorkflowOutlineStep }) {
  return (
    <Flex vertical gap="small" className="pb-2">
      <Flex wrap gap="small" align="center">
        <Tag>{stepType(step.type)}</Tag>
        <Typography.Text code>{step.id}</Typography.Text>
        {step.decision_class && (
          <Typography.Text>
            Loại quyết định{" "}
            <Typography.Text code>{step.decision_class}</Typography.Text>
          </Typography.Text>
        )}
        {step.tool && (
          <Typography.Text>
            Công cụ <Typography.Text code>{step.tool}</Typography.Text>
          </Typography.Text>
        )}
      </Flex>
      {step.lanes.map((lane) => (
        <Card key={lane.port} size="small" title={laneLabel(lane.port)}>
          {lane.steps.length > 0 ? (
            <WorkflowTree steps={lane.steps} />
          ) : (
            <Typography.Text>Không có bước nào.</Typography.Text>
          )}
        </Card>
      ))}
    </Flex>
  );
}
