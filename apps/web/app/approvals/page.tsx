"use client";

import { useCallback, useState, type ReactNode } from "react";
import Link from "next/link";
import {
  Alert,
  Button,
  Card,
  Flex,
  Input,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import {
  CheckOutlined,
  CheckSquareOutlined,
  CloseOutlined,
  ExportOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import type { Approval } from "@dw/contracts";
import { PageHeader, RegionState } from "@dw/ui";
import { DwDecisionCard } from "../../components/digital-workers/dw-decision-card";
import { LoadError } from "../../components/load-error";
import { LoadMore } from "../../components/load-more";
import {
  ToolApprovalPayload,
  approvalTitle,
} from "../../components/tool-approval";
import { approvalClient, approvalInbox } from "../../lib/approvals/registry";
import { APPROVAL_STATUS } from "../../lib/approvals/status";
import { useAuth } from "../../lib/auth/auth-context";
import { formatDateTime } from "../../lib/dates";
import { errorMessage } from "../../lib/error-message";
import { apiClient } from "../../lib/session";
import { useCachedPages } from "../../lib/use-cached-pages";

/**
 * Approval types drawn by a card of their own instead of the generic one: one
 * entry per type, so the list below holds no branch per type.
 */
const CARDS: Record<
  string,
  (props: { approval: Approval; onDecided: () => void }) => ReactNode
> = {
  "dw.decision": DwDecisionCard,
};

export default function ApprovalsPage() {
  const { hasScope } = useAuth();
  const [comments, setComments] = useState<Record<string, string>>({});
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const canDecide = hasScope("approvals.decide");

  const {
    items: approvals,
    loading,
    loadingMore,
    error: loadError,
    hasMore,
    loadMore,
    reload,
  } = useCachedPages(
    "approvals:pending",
    useCallback(
      (cursor: string | null) => apiClient().listApprovals({ cursor }),
      [],
    ),
  );

  /**
   * The scope stamped on this approval that keeps the viewer from deciding it
   * (ADR 0004), or null. The server says whether they may (`can_decide`, the
   * decision's own checks); the session's `hasScope` is not asked, because it
   * lets `platform_admin` pass a scope a stamped approval does not. The server
   * lists a stamped approval only to who may decide it and to its requester
   * (ADR 0004, amendment 2026-10-07), so in practice this locks the
   * requester's own; the lock stays for any other answer the server gives.
   */
  function missingScope(approval: Approval): string | null {
    return approval.can_decide ? null : approval.required_scope;
  }

  /** A strict approval type refuses a blank comment server-side; say so here. */
  function missingComment(approval: Approval): boolean {
    return approval.requires_comment && !(comments[approval.id] ?? "").trim();
  }

  // The decision resumes a checkpointed run, and graphs are registered per
  // process — so the client is picked from the approval's own type, never
  // assumed to be the platform API.
  async function decide(approval: Approval, approve: boolean) {
    setBusyId(approval.id);
    try {
      await approvalClient(approval.approval_type).decideApproval(approval.id, {
        approve,
        comment: comments[approval.id] ?? "",
      });
      setComments((current) => ({ ...current, [approval.id]: "" }));
      setError(null);
      reload();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusyId(null);
    }
  }

  const pending = approvals.filter((item) => item.status === "pending");
  const decided = approvals.filter((item) => item.status !== "pending");

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        icon={<CheckSquareOutlined />}
        title="Duyệt"
        subtitle="Một lượt chạy muốn thay đổi thứ gì ngoài hệ thống sẽ dừng ở đây tới khi có người quyết. Chưa việc nào ở trang này đã xảy ra."
        actions={
          <Button
            icon={<ReloadOutlined aria-hidden />}
            aria-label="Tải lại"
            onClick={reload}
          />
        }
      />
      <Flex vertical gap="middle">
        {error != null && <Alert type="error" showIcon title={error} />}
        {loadError != null && <LoadError error={loadError} onRetry={reload} />}
        {loading && loadError == null && <RegionState kind="loading" />}
        {!loading && loadError == null && pending.length === 0 && (
          <RegionState
            kind="empty"
            title="Không có yêu cầu nào chờ quyết"
            description="Yêu cầu hiện ở đây ngay khi một worker tới thao tác mà chính sách không cho nó tự làm."
          />
        )}

        {pending.map((approval) => {
          const OwnCard = CARDS[approval.approval_type];
          if (OwnCard)
            return (
              <OwnCard
                key={approval.id}
                approval={approval}
                onDecided={reload}
              />
            );
          // A context with its own inbox decides there: one door per approval.
          const inbox = approvalInbox(approval);
          const lacking = missingScope(approval);
          const lockReason =
            lacking === null
              ? null
              : `Chỉ người có quyền ${lacking} được quyết yêu cầu này`;
          // Withdrawing your own request is not deciding it: the server lets
          // the requester reject without the stamped scope, so the page does too.
          const approveLocked = lacking !== null;
          const rejectLocked = lacking !== null && !approval.requested_by_me;
          // A disabled button takes no pointer events, so the tooltip hangs on
          // a wrapper; the same sentence also sits beside the buttons as text.
          const withLock = (locked: boolean, button: ReactNode) =>
            locked ? (
              <Tooltip title={lockReason}>
                <span className="inline-flex">{button}</span>
              </Tooltip>
            ) : (
              button
            );
          return (
            <Card
              key={approval.id}
              title={
                <Link href={`/approvals/${approval.id}`}>
                  {approvalTitle(approval.approval_type)}
                </Link>
              }
              extra={
                <Tag color={APPROVAL_STATUS[approval.status].color}>
                  {APPROVAL_STATUS[approval.status].label}
                </Tag>
              }
            >
              <Flex vertical gap="middle">
                <Typography.Text>
                  <Typography.Text code className="break-all">
                    {approval.approval_type}
                  </Typography.Text>{" "}
                  {approval.reason}
                </Typography.Text>
                <ToolApprovalPayload payload={approval.payload} />
                {inbox?.kind === "link" && (
                  <div>
                    <Button
                      type="primary"
                      href={inbox.href}
                      icon={<ExportOutlined aria-hidden />}
                    >
                      {inbox.label}
                    </Button>
                  </div>
                )}
                {inbox?.kind === "misconfigured" && (
                  <Typography.Text type="secondary">
                    Yêu cầu này được quyết ở nơi khác.
                  </Typography.Text>
                )}
                {inbox === null && !canDecide && (
                  <Typography.Text type="secondary">
                    Vai của bạn không có quyền quyết yêu cầu, nên bạn chỉ xem
                    được.
                  </Typography.Text>
                )}
                {inbox === null && canDecide && (
                  <Flex vertical gap="small">
                    <label htmlFor={`comment-${approval.id}`}>
                      <Typography.Text strong>
                        {approval.requires_comment
                          ? "Nhận xét (bắt buộc)"
                          : "Nhận xét (không bắt buộc)"}
                      </Typography.Text>
                    </label>
                    <Input.TextArea
                      id={`comment-${approval.id}`}
                      rows={2}
                      value={comments[approval.id] ?? ""}
                      onChange={(event) =>
                        setComments((current) => ({
                          ...current,
                          [approval.id]: event.target.value,
                        }))
                      }
                      placeholder="Lý do của quyết định"
                    />
                    <Flex wrap gap="small" align="center">
                      {withLock(
                        approveLocked,
                        <Button
                          type="primary"
                          icon={<CheckOutlined aria-hidden />}
                          onClick={() => void decide(approval, true)}
                          loading={busyId === approval.id}
                          disabled={approveLocked || missingComment(approval)}
                        >
                          Duyệt
                        </Button>,
                      )}
                      {withLock(
                        rejectLocked,
                        <Button
                          danger
                          icon={<CloseOutlined aria-hidden />}
                          onClick={() => void decide(approval, false)}
                          disabled={
                            rejectLocked ||
                            busyId === approval.id ||
                            missingComment(approval)
                          }
                        >
                          Từ chối
                        </Button>,
                      )}
                      {lockReason !== null && (
                        <Typography.Text type="secondary">
                          {lockReason}
                          {approval.requested_by_me &&
                            ". Bạn vẫn rút được yêu cầu của mình."}
                        </Typography.Text>
                      )}
                    </Flex>
                  </Flex>
                )}
              </Flex>
            </Card>
          );
        })}

        {decided.length > 0 && (
          <Card title="Quyết định gần đây">
            <Typography.Paragraph type="secondary">
              Đã quyết; giữ ở đây để lần ra người đã cho một lượt chạy đi tiếp.
            </Typography.Paragraph>
            <Table<Approval>
              rowKey="id"
              size="small"
              pagination={false}
              scroll={{ x: "max-content" }}
              dataSource={decided}
              columns={[
                {
                  title: "Quyết lúc",
                  dataIndex: "decided_at",
                  render: (value: string | null) => formatDateTime(value),
                },
                {
                  title: "Loại",
                  dataIndex: "approval_type",
                  render: (value: string) => (
                    <Typography.Text code>{value}</Typography.Text>
                  ),
                },
                {
                  title: "Lý do",
                  dataIndex: "reason",
                  ellipsis: true,
                },
                {
                  title: "Lượt chạy",
                  dataIndex: "run_id",
                  render: (value: string | null) =>
                    value ? (
                      <Typography.Text code>{value}</Typography.Text>
                    ) : (
                      "—"
                    ),
                },
                {
                  title: "Kết quả",
                  dataIndex: "status",
                  render: (value: Approval["status"]) => (
                    <Tag color={APPROVAL_STATUS[value].color}>
                      {APPROVAL_STATUS[value].label}
                    </Tag>
                  ),
                },
              ]}
            />
          </Card>
        )}

        {!loading && pending.length > 0 && (
          <LoadMore
            hasMore={hasMore}
            loading={loadingMore}
            onLoadMore={loadMore}
            shown={approvals.length}
            noun="yêu cầu"
          />
        )}
      </Flex>
    </div>
  );
}
