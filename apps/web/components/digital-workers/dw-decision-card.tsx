"use client";

import { useCallback, useState, type ReactNode } from "react";
import Link from "next/link";
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Flex,
  Form,
  Input,
  InputNumber,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import { CheckOutlined, CloseOutlined, EditOutlined } from "@ant-design/icons";
import type { DigitalWorker } from "@dw/api-client";
import type { Approval } from "@dw/contracts";
import { APPROVAL_STATUS } from "../../lib/approvals/status";
import { errorMessage } from "../../lib/error-message";
import { apiClient } from "../../lib/session";
import { useCachedResource } from "../../lib/use-cached-resource";

type Json = Record<string, unknown>;

interface FieldSchema {
  type?: string;
  title?: string;
  maxLength?: number;
}

function isObject(value: unknown): value is Json {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** What a `dw.decision` carries (digital-worker R5.1), read defensively: the
 * proposal is masked for anyone but the DW's people (R5.6). */
function readPayload(payload: Json) {
  const proposal = isObject(payload.proposal) ? payload.proposal : null;
  const schema = isObject(payload.proposal_schema)
    ? payload.proposal_schema
    : null;
  const properties =
    schema && isObject(schema.properties)
      ? (schema.properties as Record<string, FieldSchema>)
      : {};
  const required =
    schema && Array.isArray(schema.required) ? schema.required.map(String) : [];
  const locked = Array.isArray(payload.locked_fields)
    ? payload.locked_fields.map(String)
    : [];
  return {
    dwId: typeof payload.dw_id === "string" ? payload.dw_id : null,
    decisionClass:
      typeof payload.decision_class === "string" ? payload.decision_class : "—",
    level:
      typeof payload.effective_level === "string"
        ? payload.effective_level
        : "—",
    proposal,
    properties,
    required,
    locked,
  };
}

const FIELD_LABEL: Record<string, string> = {
  to: "Người nhận",
  subject: "Tiêu đề",
  body: "Nội dung",
};

/**
 * Field names in the order a person reads them: the schema's `required` list
 * first (an array, so its order survives jsonb, which re-sorts object keys),
 * then any other property, then anything else the proposal carries.
 */
function fieldOrder(names: string[], required: string[]): string[] {
  const first = required.filter((name) => names.includes(name));
  return [...first, ...names.filter((name) => !first.includes(name))];
}

function fieldLabel(name: string, field: FieldSchema | undefined): string {
  return FIELD_LABEL[name] ?? field?.title ?? name;
}

/**
 * One `dw.decision` approval as a card (digital-worker R9.4): which DW asks,
 * for which decision class, at which effective level, and the proposal it
 * makes. "Duyệt" takes it as is, "Sửa rồi duyệt" approves an edit made in a
 * form drawn from the proposal's schema with its locked fields fixed, and
 * "Từ chối" needs a reason (D18). The server decides who may: the buttons
 * follow `can_decide`, never the session.
 */
export function DwDecisionCard({
  approval,
  onDecided,
}: {
  approval: Approval;
  onDecided: () => void;
}) {
  const shown = readPayload(approval.payload);
  const [comment, setComment] = useState("");
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState<"approve" | "edit" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [form] = Form.useForm<Json>();
  const worker = useCachedResource<DigitalWorker | null>(
    `digital-worker:${shown.dwId ?? "none"}`,
    useCallback(
      () =>
        shown.dwId
          ? apiClient().getDigitalWorker(shown.dwId)
          : Promise.resolve(null),
      [shown.dwId],
    ),
  );
  const status = APPROVAL_STATUS[approval.status];
  const pending = approval.status === "pending";
  const lockReason = approval.can_decide
    ? null
    : "Chỉ Validator hay Business Owner của Digital Worker này được quyết";
  const needsComment = approval.requires_comment && !comment.trim();

  async function decide(kind: "approve" | "edit" | "reject", edited?: Json) {
    setBusy(kind);
    try {
      await apiClient().decideApproval(approval.id, {
        approve: kind !== "reject",
        comment,
        ...(edited ? { edited_proposal: edited } : {}),
      });
      setError(null);
      setEditing(false);
      onDecided();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  const dwName = worker.data?.name ?? shown.dwId ?? "Digital Worker";
  const editable = fieldOrder(Object.keys(shown.properties), shown.required)
    .map((name): [string, FieldSchema] => [name, shown.properties[name] ?? {}])
    .filter(
      ([, field]) =>
        field.type === "string" ||
        field.type === "number" ||
        field.type === "integer",
    );

  const withLock = (button: ReactNode) =>
    lockReason ? (
      <Tooltip title={lockReason}>
        <span className="inline-flex">{button}</span>
      </Tooltip>
    ) : (
      button
    );

  return (
    <Card
      title={
        <Link href={`/approvals/${approval.id}`}>Quyết định của {dwName}</Link>
      }
      extra={<Tag color={status.color}>{status.label}</Tag>}
    >
      <Flex vertical gap="middle">
        <Descriptions
          column={{ xs: 1, md: 3 }}
          size="small"
          items={[
            {
              key: "dw",
              label: "Digital Worker",
              children: shown.dwId ? (
                <Link href={`/digital-workers/${shown.dwId}`}>{dwName}</Link>
              ) : (
                "—"
              ),
            },
            {
              key: "class",
              label: "Loại quyết định",
              children: (
                <Typography.Text code>{shown.decisionClass}</Typography.Text>
              ),
            },
            {
              key: "level",
              label: "Mức hiệu lực",
              children: shown.level,
            },
          ]}
        />
        <Typography.Text>{approval.reason}</Typography.Text>

        {shown.proposal === null ? (
          <Typography.Text>
            Chỉ người của Digital Worker này đọc được đề xuất.
          </Typography.Text>
        ) : editing ? (
          <Form<Json>
            form={form}
            layout="vertical"
            validateTrigger="onBlur"
            scrollToFirstError={{ focus: true }}
            initialValues={shown.proposal}
            onFinish={(values) =>
              void decide("edit", { ...shown.proposal, ...values })
            }
          >
            {editable.map(([name, field]) => {
              const locked = shown.locked.includes(name);
              const label = fieldLabel(name, field);
              return (
                <Form.Item
                  key={name}
                  name={name}
                  label={label}
                  extra={
                    locked ? "Trường này cố định, không sửa được." : undefined
                  }
                  rules={[
                    { required: true, message: `${label} không được để trống` },
                  ]}
                >
                  {field.type === "string" ? (
                    (field.maxLength ?? 0) > 200 ? (
                      <Input.TextArea
                        rows={6}
                        maxLength={field.maxLength}
                        disabled={locked}
                      />
                    ) : (
                      <Input maxLength={field.maxLength} disabled={locked} />
                    )
                  ) : (
                    <InputNumber disabled={locked} className="w-full" />
                  )}
                </Form.Item>
              );
            })}
            <Flex wrap gap="small">
              <Button
                type="primary"
                htmlType="submit"
                icon={<CheckOutlined aria-hidden />}
                loading={busy === "edit"}
                disabled={needsComment}
              >
                Duyệt bản đã sửa
              </Button>
              <Button onClick={() => setEditing(false)}>Thôi sửa</Button>
            </Flex>
          </Form>
        ) : (
          <Descriptions
            column={1}
            size="small"
            bordered
            styles={{ label: { whiteSpace: "nowrap" } }}
            items={fieldOrder(Object.keys(shown.proposal), shown.required)
              .map((name) => [name, shown.proposal?.[name]] as const)
              .map(([name, value]) => ({
                key: name,
                label: fieldLabel(name, shown.properties[name]),
                children: (
                  <Typography.Paragraph className="whitespace-pre-wrap">
                    {typeof value === "string" ? value : JSON.stringify(value)}
                  </Typography.Paragraph>
                ),
              }))}
          />
        )}

        {error !== null && <Alert type="error" showIcon title={error} />}

        {pending && (
          <Flex vertical gap="small">
            <label htmlFor={`comment-${approval.id}`}>
              <Typography.Text strong>
                Lý do (bắt buộc khi từ chối)
              </Typography.Text>
            </label>
            <Input.TextArea
              id={`comment-${approval.id}`}
              rows={2}
              value={comment}
              onChange={(event) => setComment(event.target.value)}
              placeholder="Ví dụ: thư chưa nêu giá ưu đãi"
            />
            <Flex wrap gap="small" align="center">
              {!editing &&
                withLock(
                  <Button
                    type="primary"
                    icon={<CheckOutlined aria-hidden />}
                    onClick={() => void decide("approve")}
                    loading={busy === "approve"}
                    disabled={
                      lockReason !== null || needsComment || busy !== null
                    }
                  >
                    Duyệt
                  </Button>,
                )}
              {!editing &&
                shown.proposal !== null &&
                editable.length > 0 &&
                withLock(
                  <Button
                    icon={<EditOutlined aria-hidden />}
                    onClick={() => setEditing(true)}
                    disabled={lockReason !== null || busy !== null}
                  >
                    Sửa rồi duyệt
                  </Button>,
                )}
              {withLock(
                <Button
                  danger
                  icon={<CloseOutlined aria-hidden />}
                  onClick={() => void decide("reject")}
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
                !comment.trim() && (
                  <Typography.Text>Ghi lý do để từ chối.</Typography.Text>
                )
              )}
            </Flex>
          </Flex>
        )}
      </Flex>
    </Card>
  );
}
