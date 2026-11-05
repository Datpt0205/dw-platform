"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  Alert,
  App,
  Button,
  Card,
  Flex,
  Form,
  InputNumber,
  Select,
  Skeleton,
  Table,
  Typography,
} from "antd";
import { DashboardOutlined, ReloadOutlined } from "@ant-design/icons";
import type { LimitLine, LimitMetric, LimitWindow } from "@dw/api-client";
import { PageHeader, RegionState } from "@dw/ui";
import { LoadError } from "../../../components/load-error";
import { formatDate } from "../../../lib/dates";
import { errorMessage, reasonCode } from "../../../lib/error-message";
import { apiClient } from "../../../lib/session";
import { useCachedResource } from "../../../lib/use-cached-resource";
import {
  LimitsProgress,
  METRIC_LABELS,
  SCOPE_LABELS,
  formatAmount,
  pairLabel,
} from "../limits";

/**
 * Cấu hình hạn mức (usage-and-limits ticket 03, spec "Màn hình"): the company's
 * hard limits at the company and at each workspace, with the plan's cap and the
 * effective limit. W1 only lowers or sets a new one, at once and audited; a
 * raise or a removal needs a second person, which W1 does not have, so the
 * server refuses it (409) whatever this form sends. `GET /api/v1/limits` needs
 * `platform.usage.read`, a write `platform.limits.manage`; hiding nothing here
 * is the control.
 */

const PAIRS = Object.keys(METRIC_LABELS).map((value) => ({
  value,
  label: METRIC_LABELS[value],
}));

type Draft = {
  scope: "tenant" | "workspace";
  workspace_id?: string;
  pair: string;
  limit_value: number;
};

/** The Vietnamese sentence of a refusal the form can name. */
const REFUSALS: Record<string, string> = {
  second_person_required:
    "Nới hay gỡ hạn mức cần người thứ hai duyệt, chưa có ở bản này. Chỉ hạ được.",
  limit_above_plan: "Hạn mức cao hơn Trần của gói.",
  scope_kind_mismatch: "Phạm vi không đúng loại thành phần.",
};

export default function LimitsPage() {
  const { message } = App.useApp();
  const [form] = Form.useForm<Draft>();
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  // One key per press of the same payload; a changed payload gets a new one.
  const keyFor = useRef<{ payload: string; key: string } | null>(null);

  const limits = useCachedResource(
    "usage:limits",
    useCallback(() => apiClient().listLimits(), []),
  );
  const workspaces = useCachedResource(
    "usage:limits:workspaces",
    useCallback(() => apiClient().listAdminWorkspaces(), []),
  );
  const names = useMemo(() => {
    const found = new Map<string, string>();
    for (const workspace of workspaces.data ?? []) {
      found.set(workspace.workspace_id, workspace.name);
    }
    return found;
  }, [workspaces.data]);
  const scopeName = useCallback(
    (line: LimitLine) =>
      line.scope_type === "workspace"
        ? (names.get(line.scope_id) ?? "Workspace")
        : (SCOPE_LABELS[line.scope_type] ?? line.scope_type),
    [names],
  );
  const scope = Form.useWatch("scope", form) ?? "tenant";

  const submit = async (draft: Draft) => {
    const lines = limits.data ?? [];
    const [metric, windowKind] = draft.pair.split("/") as [
      LimitMetric,
      LimitWindow,
    ];
    const tenantLine = lines.find((line) => line.scope_type === "tenant");
    const scopeId =
      draft.scope === "tenant"
        ? (tenantLine?.scope_id ?? null)
        : (draft.workspace_id ?? null);
    if (scopeId == null) {
      setProblem("Chưa xác định được phạm vi để đặt hạn mức.");
      return;
    }
    const existing = lines.find(
      (line) =>
        line.scope_type === draft.scope &&
        line.scope_id === scopeId &&
        line.metric === metric &&
        line.window_kind === windowKind,
    );
    const value = String(draft.limit_value);
    const payload = `${draft.scope}:${scopeId}:${draft.pair}:${value}`;
    if (keyFor.current?.payload !== payload) {
      keyFor.current = { payload, key: crypto.randomUUID() };
    }
    setSaving(true);
    setProblem(null);
    try {
      await apiClient().putLimit(
        draft.scope,
        scopeId,
        metric,
        windowKind,
        value,
        keyFor.current.key,
        existing?.version ?? undefined,
      );
      keyFor.current = null;
      message.success("Đã đặt hạn mức; áp dụng ngay cho lượt chạy kế tiếp.");
      limits.reload();
    } catch (error) {
      setProblem(REFUSALS[reasonCode(error) ?? ""] ?? errorMessage(error));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        icon={<DashboardOutlined />}
        title="Cấu hình hạn mức"
        subtitle="Hạn mức cứng của công ty và từng workspace theo ngày, tháng; chỉ hạ hoặc đặt mới, áp dụng ngay."
        actions={
          <>
            <Link href="/usage">Mức độ sử dụng</Link>
            <Button
              icon={<ReloadOutlined aria-hidden />}
              aria-label="Tải lại"
              onClick={limits.reload}
            />
          </>
        }
      />
      <Flex vertical gap="middle">
        {limits.error != null && (
          <LoadError error={limits.error} onRetry={limits.reload} />
        )}
        {limits.loading && limits.error == null && (
          <Skeleton active paragraph={{ rows: 4 }} />
        )}
        {limits.data != null && (
          <>
            <LimitsProgress lines={limits.data} scopeName={scopeName} />
            <Card title="Các hạn mức">
              <Table<LimitLine>
                rowKey={(line) =>
                  `${line.scope_type}:${line.scope_id}:${line.metric}:${line.window_kind}`
                }
                size="small"
                pagination={false}
                scroll={{ x: "max-content" }}
                dataSource={limits.data}
                locale={{
                  emptyText: (
                    <RegionState
                      kind="empty"
                      title="Gói và công ty chưa đặt hạn mức nào"
                    />
                  ),
                }}
                columns={[
                  {
                    title: "Phạm vi",
                    key: "scope",
                    render: (_, l) => scopeName(l),
                  },
                  {
                    title: "Hạn mức",
                    key: "pair",
                    render: (_, l) => pairLabel(l),
                  },
                  {
                    title: "Trần của gói",
                    key: "plan",
                    align: "right",
                    render: (_, l) =>
                      l.plan_limit == null
                        ? "Không giới hạn"
                        : formatAmount(l.metric, l.plan_limit),
                  },
                  {
                    title: "Hạn mức hiệu lực",
                    key: "effective",
                    align: "right",
                    render: (_, l) => formatAmount(l.metric, l.effective_limit),
                  },
                  {
                    title: "Đã dùng",
                    key: "used",
                    align: "right",
                    render: (_, l) => formatAmount(l.metric, l.used),
                  },
                  {
                    title: "Đặt lại lúc",
                    key: "resets",
                    render: (_, l) => formatDate(l.resets_at),
                  },
                ]}
              />
            </Card>
          </>
        )}
        <Card title="Đặt hoặc hạ một hạn mức">
          <Typography.Paragraph>
            Hạn mức mới hay thấp hơn áp dụng ngay và được ghi nhật ký. Nâng hay
            gỡ một hạn mức cần người thứ hai duyệt, chưa có ở bản này.
          </Typography.Paragraph>
          {problem != null && (
            <Alert type="error" showIcon message={problem} className="mb-4" />
          )}
          <Form<Draft>
            form={form}
            layout="vertical"
            validateTrigger="onBlur"
            scrollToFirstError={{ focus: true }}
            initialValues={{ scope: "tenant", pair: "cost_usd/month" }}
            onFinish={submit}
          >
            <Flex wrap gap="middle" align="end">
              <Form.Item label="Phạm vi" name="scope">
                <Select
                  className="w-40"
                  options={[
                    { value: "tenant", label: "Công ty" },
                    { value: "workspace", label: "Workspace" },
                  ]}
                />
              </Form.Item>
              {scope === "workspace" && (
                <Form.Item
                  label="Workspace"
                  name="workspace_id"
                  rules={[{ required: true, message: "Chọn một workspace" }]}
                >
                  <Select
                    className="w-56"
                    loading={workspaces.loading}
                    options={(workspaces.data ?? []).map((workspace) => ({
                      value: workspace.workspace_id,
                      label: workspace.name,
                    }))}
                  />
                </Form.Item>
              )}
              <Form.Item label="Hạn mức" name="pair">
                <Select className="w-48" options={PAIRS} />
              </Form.Item>
              <Form.Item
                label="Giá trị"
                name="limit_value"
                rules={[{ required: true, message: "Nhập giá trị hạn mức" }]}
              >
                <InputNumber min={0} className="w-40" />
              </Form.Item>
              <Form.Item>
                <Button type="primary" htmlType="submit" loading={saving}>
                  Đặt hạn mức
                </Button>
              </Form.Item>
            </Flex>
          </Form>
        </Card>
      </Flex>
    </div>
  );
}
