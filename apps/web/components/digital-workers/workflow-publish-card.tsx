"use client";

import { useCallback, useState, type ReactNode } from "react";
import Link from "next/link";
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Flex,
  Input,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import { CheckOutlined, CloseOutlined } from "@ant-design/icons";
import type { DigitalWorker, WorkflowDraftReview } from "@dw/api-client";
import type { Approval } from "@dw/contracts";
import { APPROVAL_STATUS } from "../../lib/approvals/status";
import { errorMessage, reasonCode } from "../../lib/error-message";
import { apiClient } from "../../lib/session";
import { useCachedResource } from "../../lib/use-cached-resource";
import { SimulationResult, WorkflowDiff } from "./workflow-review";

function text(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

/**
 * One `dw.workflow.publish` approval as a card (wf-ai R7.2): which DW, the
 * draft's hash, what it changes against the workflow the DW runs and its
 * passed simulation with the tools it would call. The review is read from the
 * DW (`/workflow-draft/review`), never from the approval's payload, which
 * carries identifiers and hashes only; the card says when the draft is no
 * longer the one submitted, since its publication then comes back. The
 * server decides who may: the buttons follow `can_decide`.
 */
export function WorkflowPublishCard({
  approval,
  onDecided,
}: {
  approval: Approval;
  onDecided: () => void;
}) {
  const dwId = text(approval.payload.dw_id);
  const contentSha = text(approval.payload.content_sha256) ?? "";
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const worker = useCachedResource<DigitalWorker | null>(
    `digital-worker:${dwId ?? "none"}`,
    useCallback(
      () => (dwId ? apiClient().getDigitalWorker(dwId) : Promise.resolve(null)),
      [dwId],
    ),
  );
  const review = useCachedResource<WorkflowDraftReview | null>(
    `digital-worker:${dwId ?? "none"}:draft-review:${approval.id}`,
    useCallback(
      () =>
        dwId ? apiClient().reviewWorkflowDraft(dwId) : Promise.resolve(null),
      [dwId],
    ),
  );
  const status = APPROVAL_STATUS[approval.status];
  const pending = approval.status === "pending";
  const lockReason = approval.can_decide
    ? null
    : "Chỉ Validator hay Technical Owner của Digital Worker này, không phải người đã soạn hay gửi bản nháp, được quyết";
  const needsComment = approval.requires_comment && !comment.trim();
  const dwName = worker.data?.name ?? dwId ?? "Digital Worker";

  async function decide(approve: boolean) {
    setBusy(approve ? "approve" : "reject");
    try {
      await apiClient().decideApproval(approval.id, { approve, comment });
      setError(null);
      onDecided();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  const withLock = (button: ReactNode) =>
    lockReason ? (
      <Tooltip title={lockReason}>
        <span className="inline-flex">{button}</span>
      </Tooltip>
    ) : (
      button
    );

  const found = review.data;
  const sameDraft =
    found !== null &&
    found.approval_id === approval.id &&
    found.content_sha256 === contentSha;

  return (
    <Card
      title={
        <Link href={`/approvals/${approval.id}`}>
          Phát hành quy trình của {dwName}
        </Link>
      }
      extra={<Tag color={status.color}>{status.label}</Tag>}
    >
      <Flex vertical gap="middle">
        <Descriptions
          column={{ xs: 1, md: 2 }}
          size="small"
          items={[
            {
              key: "dw",
              label: "Digital Worker",
              children: dwId ? (
                <Link href={`/digital-workers/${dwId}`}>{dwName}</Link>
              ) : (
                "—"
              ),
            },
            {
              key: "content",
              label: "Mã nội dung",
              children: (
                <Typography.Text code>
                  {contentSha.slice(0, 12)}
                </Typography.Text>
              ),
            },
          ]}
        />
        <ReviewBody review={review} pending={pending} sameDraft={sameDraft} />

        {error !== null && <Alert type="error" showIcon title={error} />}

        {pending && (
          <Flex vertical gap="small">
            <label htmlFor={`comment-${approval.id}`}>
              <Typography.Text strong>Lý do (bắt buộc)</Typography.Text>
            </label>
            <Input.TextArea
              id={`comment-${approval.id}`}
              rows={2}
              value={comment}
              onChange={(event) => setComment(event.target.value)}
              placeholder="Ví dụ: đã xem mô phỏng, thêm lần nhắc hợp lý"
            />
            <Flex wrap gap="small" align="center">
              {withLock(
                <Button
                  type="primary"
                  icon={<CheckOutlined aria-hidden />}
                  onClick={() => void decide(true)}
                  loading={busy === "approve"}
                  disabled={
                    lockReason !== null || needsComment || busy !== null
                  }
                >
                  Duyệt và phát hành
                </Button>,
              )}
              {withLock(
                <Button
                  danger
                  icon={<CloseOutlined aria-hidden />}
                  onClick={() => void decide(false)}
                  loading={busy === "reject"}
                  disabled={
                    lockReason !== null || !comment.trim() || busy !== null
                  }
                >
                  Từ chối
                </Button>,
              )}
              {lockReason !== null ? (
                <Typography.Text>{lockReason}.</Typography.Text>
              ) : (
                needsComment && (
                  <Typography.Text>Ghi lý do để quyết.</Typography.Text>
                )
              )}
            </Flex>
          </Flex>
        )}
      </Flex>
    </Card>
  );
}

function ReviewBody({
  review,
  pending,
  sameDraft,
}: {
  review: {
    data: WorkflowDraftReview | null;
    loading: boolean;
    error: unknown;
  };
  pending: boolean;
  sameDraft: boolean;
}) {
  if (review.error != null) {
    const reason = reasonCode(review.error);
    if (reason === "not_dw_person") {
      return (
        <Typography.Text>
          Chỉ người của Digital Worker này đọc được bản nháp.
        </Typography.Text>
      );
    }
    if (reason === "draft_not_found") {
      return (
        <Typography.Text>
          Bản nháp không còn: nó đã được phát hành hay đã được thay.
        </Typography.Text>
      );
    }
    return <Alert type="error" showIcon title={errorMessage(review.error)} />;
  }
  if (review.data === null) {
    return <Typography.Text>Đang tải bản nháp…</Typography.Text>;
  }
  const found = review.data;
  return (
    <Flex vertical gap="middle">
      {pending && !sameDraft && (
        <Alert
          type="warning"
          showIcon
          title="Bản nháp đã đổi từ khi gửi duyệt; quyết định này sẽ không phát hành gì."
        />
      )}
      {pending && !found.base_current && (
        <Alert
          type="warning"
          showIcon
          title="Quy trình Digital Worker đang chạy đã đổi từ khi soạn bản này; duyệt sẽ không phát hành gì."
        />
      )}
      <Typography.Text strong>
        Thay đổi so với quy trình đang chạy
      </Typography.Text>
      <WorkflowDiff changes={found.diff} />
      <Typography.Text strong>Mô phỏng</Typography.Text>
      {found.simulation ? (
        <SimulationResult simulation={found.simulation} />
      ) : (
        <Typography.Text>Chưa có mô phỏng.</Typography.Text>
      )}
    </Flex>
  );
}
