"use client";

import { useCallback } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  Card,
  Col,
  Descriptions,
  Flex,
  Row,
  Statistic,
  Table,
  Tag,
  Typography,
} from "antd";
import { RobotOutlined } from "@ant-design/icons";
import type {
  DigitalWorker,
  DwClassStanding,
  DwDecisionClass,
  DwScorecard,
  WorkflowOutline,
} from "@dw/api-client";
import { PageHeader, RegionState } from "@dw/ui";
import { LoadError } from "../../../components/load-error";
import { WorkflowTree } from "../../../components/digital-workers/workflow-tree";
import { formatDate } from "../../../lib/dates";
import { memberName, useWorkspaceMembers } from "../../../lib/directory";
import { DECISION_MODE, dwState } from "../../../lib/digital-workers/labels";
import { formatUsd } from "../../../lib/money";
import { apiClient } from "../../../lib/session";
import { useCachedResource } from "../../../lib/use-cached-resource";

const BREADCRUMB = [
  { title: <Link href="/digital-workers">Digital Worker</Link> },
];

/** "45%" or "—" when the window held no item: no rate is not a rate of 0. */
function percent(rate: number | null): string {
  return rate === null ? "—" : `${Math.round(rate * 100)}%`;
}

/**
 * One DW: its profile and four people, each decision class with its ceiling,
 * earned and effective level as "Tự động / Hỏi / Chặn", the 30-day scorecard
 * and the pinned workflow (digital-worker R9.2). A DW the API refuses or does
 * not know shows that state and nothing else (R9.5).
 */
export default function DigitalWorkerPage() {
  const { id } = useParams<{ id: string }>();
  const worker = useCachedResource<DigitalWorker>(
    `digital-worker:${id}`,
    useCallback(() => apiClient().getDigitalWorker(id), [id]),
  );

  if (worker.error != null) {
    return (
      <div className="mx-auto max-w-6xl">
        <PageHeader breadcrumb={BREADCRUMB} title="Digital Worker" />
        <LoadError error={worker.error} onRetry={worker.reload} />
      </div>
    );
  }
  if (worker.data === null) {
    return (
      <div className="mx-auto max-w-6xl">
        <PageHeader breadcrumb={BREADCRUMB} title="Digital Worker" />
        <RegionState kind="loading" />
      </div>
    );
  }
  return <Profile worker={worker.data} />;
}

function Profile({ worker }: { worker: DigitalWorker }) {
  const members = useWorkspaceMembers();
  const state = dwState(worker.state);
  const workflow = useCachedResource<WorkflowOutline>(
    `digital-worker:${worker.id}:workflow`,
    useCallback(
      () => apiClient().getDigitalWorkerWorkflow(worker.id),
      [worker.id],
    ),
  );
  const scorecard = useCachedResource<DwScorecard>(
    `digital-worker:${worker.id}:scorecard:30`,
    useCallback(
      () => apiClient().getDigitalWorkerScorecard(worker.id, 30),
      [worker.id],
    ),
  );
  const person = (userId: string | null) =>
    memberName(members, userId) ?? "Chưa có";

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        breadcrumb={BREADCRUMB}
        icon={<RobotOutlined />}
        title={worker.name}
        subtitle={worker.mandate}
        tags={<Tag color={state.color}>{state.label}</Tag>}
      />
      <Flex vertical gap="middle">
        <Card title="Hồ sơ">
          <Descriptions
            column={{ xs: 1, md: 2 }}
            items={[
              { key: "key", label: "Mã", children: worker.key },
              {
                key: "workflow",
                label: "Quy trình đã ghim",
                children: `${worker.workflow_key}@${worker.workflow_version}`,
              },
              {
                key: "kinds",
                label: "Loại việc",
                children: worker.work_kinds.join(", "),
              },
              {
                key: "tools",
                label: "Công cụ được phép",
                children: worker.allowed_tools.join(", ") || "Không có",
              },
              {
                key: "business_owner",
                label: "Business Owner",
                children: person(worker.people.business_owner_id),
              },
              {
                key: "technical_owner",
                label: "Technical Owner",
                children: person(worker.people.technical_owner_id),
              },
              {
                key: "work_assigner",
                label: "Người giao việc",
                children: person(worker.people.work_assigner_id),
              },
              {
                key: "validator",
                label: "Validator",
                children: person(worker.people.validator_id),
              },
              {
                key: "created",
                label: "Tạo ngày",
                children: formatDate(worker.created_at),
              },
            ]}
          />
        </Card>

        <Card title="Loại quyết định">
          <DecisionClasses
            classes={worker.decision_classes}
            standings={workflow.data?.decision_classes ?? null}
            loading={workflow.loading}
            error={workflow.error}
          />
        </Card>

        <Card
          title="Kết quả 30 ngày"
          extra={
            scorecard.data && (
              <Typography.Text>
                Từ {formatDate(scorecard.data.since)}
              </Typography.Text>
            )
          }
        >
          {scorecard.error != null ? (
            <LoadError
              error={scorecard.error}
              onRetry={scorecard.reload}
              compact
            />
          ) : scorecard.data === null ? (
            <RegionState kind="loading" compact />
          ) : (
            <Scorecard card={scorecard.data} />
          )}
        </Card>

        <Card title="Quy trình">
          {workflow.error != null ? (
            <LoadError
              error={workflow.error}
              onRetry={workflow.reload}
              compact
            />
          ) : workflow.data === null ? (
            <RegionState kind="loading" compact />
          ) : (
            <WorkflowTree steps={workflow.data.steps} />
          )}
        </Card>
      </Flex>
    </div>
  );
}

function DecisionClasses({
  classes,
  standings,
  loading,
  error,
}: {
  classes: DwDecisionClass[];
  standings: DwClassStanding[] | null;
  loading: boolean;
  error: unknown;
}) {
  const standingOf = (key: string) =>
    standings?.find((standing) => standing.key === key);
  return (
    <Table<DwDecisionClass>
      rowKey="key"
      size="small"
      pagination={false}
      scroll={{ x: "max-content" }}
      dataSource={classes}
      locale={{ emptyText: "Digital Worker này không có loại quyết định nào." }}
      columns={[
        {
          title: "Loại",
          dataIndex: "key",
          render: (key: string) => (
            <Typography.Text code>{key}</Typography.Text>
          ),
        },
        { title: "Trần", dataIndex: "ceiling" },
        { title: "Đã kiếm", dataIndex: "earned_level" },
        {
          title: "Hiệu lực",
          key: "effective",
          render: (_, cls) => {
            const standing = standingOf(cls.key);
            if (standing) {
              const mode = DECISION_MODE[standing.mode];
              return (
                <Flex gap="small" align="center">
                  <Tag color={mode.color}>{mode.label}</Tag>
                  <Typography.Text>{standing.effective_level}</Typography.Text>
                </Flex>
              );
            }
            // The page never derives the level itself: without the server's
            // answer it says it does not know.
            if (loading) return <Typography.Text>Đang tải…</Typography.Text>;
            return (
              <Typography.Text>
                {error != null ? "Chưa đọc được" : "Không rõ"}
              </Typography.Text>
            );
          },
        },
      ]}
    />
  );
}

function Scorecard({ card }: { card: DwScorecard }) {
  return (
    <Row gutter={[16, 16]}>
      <Col xs={12} md={6}>
        <Statistic title="Việc nhận" value={card.items.total} />
      </Col>
      <Col xs={12} md={6}>
        <Statistic
          title="Tự làm xong"
          value={percent(card.items.done_alone_rate)}
        />
      </Col>
      <Col xs={12} md={6}>
        <Statistic
          title="Bàn giao cho người"
          value={percent(card.items.handed_off_rate)}
        />
      </Col>
      <Col xs={12} md={6}>
        <Statistic
          title="Chi phí model"
          value={formatUsd(card.model_cost_usd)}
        />
      </Col>
      <Col xs={24}>
        <Typography.Text>
          Quyết định: duyệt nguyên {card.decisions.approved_as_is}, sửa rồi
          duyệt {card.decisions.approved_edited}, từ chối{" "}
          {card.decisions.rejected}.
        </Typography.Text>
      </Col>
    </Row>
  );
}
