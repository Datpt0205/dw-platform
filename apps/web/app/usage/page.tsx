"use client";

import { Suspense, useCallback, useMemo } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  Alert,
  Button,
  Card,
  DatePicker,
  Flex,
  Segmented,
  Skeleton,
  Statistic,
  Table,
  Tag,
  Typography,
} from "antd";
import { DashboardOutlined, ReloadOutlined } from "@ant-design/icons";
import dayjs, { type Dayjs } from "dayjs";
import type {
  UsageGroup,
  UsageGroupBy,
  UsageSummaryQuery,
} from "@dw/api-client";
import { PageHeader, RegionState } from "@dw/ui";
import { LoadError } from "../../components/load-error";
import { formatDate } from "../../lib/dates";
import { formatCount, formatUsd } from "../../lib/money";
import { apiClient } from "../../lib/session";
import { useCachedResource } from "../../lib/use-cached-resource";
import { LimitsProgress, SCOPE_LABELS } from "./limits";

/**
 * Mức độ sử dụng (usage-and-limits ticket 02, spec "Màn hình"): what the
 * company's model calls cost over a period, grouped by workspace, agent or
 * workflow, or purpose, never by person in W1 (DO-51.2). Reads
 * `GET /api/v1/usage/summary`, which answers 403 without `platform.usage.read`
 * whatever this page shows. Filters live in the URL, so a link from an agent's
 * or a workflow's page lands on its own figures. No chart library in v1
 * (DO-42.3). Each hard limit's progress this period reads `GET /api/v1/limits`
 * (ticket 03); its settings are on `/usage/limits`.
 */

const GROUPS: { value: UsageGroupBy; label: string }[] = [
  { value: "workspace", label: "Theo workspace" },
  { value: "artifact", label: "Theo agent, quy trình" },
  { value: "purpose", label: "Theo mục đích" },
];

const PURPOSES: Record<string, string> = {
  run: "Lượt chạy",
  test_run: "Chạy thử",
  builder_assist: "Dựng có AI",
  eval_offline: "Kiểm định",
  eval_online: "Kiểm định trực tuyến",
  ingestion: "Nạp tri thức",
  retrieval: "Truy xuất",
  compaction: "Rút gọn hội thoại",
  memory: "Bộ nhớ",
};

const ARTIFACT_KINDS: Record<string, string> = {
  agent: "Agent",
  workflow: "Quy trình",
};

function artifactKind(
  value: string | null,
): UsageSummaryQuery["artifact_kind"] {
  return value === "agent" || value === "workflow" ? value : undefined;
}

function isGroupBy(value: string | null): value is UsageGroupBy {
  return GROUPS.some((group) => group.value === value);
}

function groupName(group: UsageGroup, by: UsageGroupBy): string {
  if (by === "workspace") return group.label ?? group.key ?? "Cấp công ty";
  if (by === "purpose") return PURPOSES[group.key ?? ""] ?? group.key ?? "—";
  if (group.key == null) return "Không thuộc agent hay quy trình";
  const kind = ARTIFACT_KINDS[group.artifact_kind ?? ""] ?? "Thành phần";
  return group.label ?? `${kind} ${group.key.slice(0, 8)}`;
}

/** The URL that narrows the page to one group, or none for a group that is
 * not a filter (a purpose, the company level, calls of no component). */
function narrowTo(group: UsageGroup, by: UsageGroupBy): string | null {
  if (group.key == null || by === "purpose") return null;
  const params = new URLSearchParams();
  if (by === "workspace") params.set("workspace_id", group.key);
  else {
    params.set("artifact_id", group.key);
    if (group.artifact_kind) params.set("artifact_kind", group.artifact_kind);
  }
  return `/usage?${params.toString()}`;
}

export default function UsagePage() {
  // `useSearchParams` needs a Suspense boundary above the component calling it.
  return (
    <Suspense fallback={<Skeleton active paragraph={{ rows: 6 }} />}>
      <UsageSummaryPage />
    </Suspense>
  );
}

function UsageSummaryPage() {
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams();
  const asked = search.get("group_by");
  const groupBy: UsageGroupBy = isGroupBy(asked) ? asked : "workspace";
  const query: UsageSummaryQuery = useMemo(
    () => ({
      group_by: groupBy,
      from: search.get("from") ?? undefined,
      to: search.get("to") ?? undefined,
      workspace_id: search.get("workspace_id") ?? undefined,
      artifact_kind: artifactKind(search.get("artifact_kind")),
      artifact_id: search.get("artifact_id") ?? undefined,
    }),
    [groupBy, search],
  );
  const filtered = Boolean(
    query.workspace_id || query.artifact_id || query.artifact_kind,
  );

  const { data, loading, error, reload } = useCachedResource(
    `usage:summary:${search.toString()}`,
    useCallback(() => apiClient().getUsageSummary(query), [query]),
  );
  // Same key as the summary (`platform.usage.read`); a refusal leaves the
  // block out, the summary above says why.
  const limits = useCachedResource(
    "usage:limits",
    useCallback(() => apiClient().listLimits(), []),
  );

  const setParams = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(search.toString());
    for (const [name, value] of Object.entries(changes)) {
      if (value) next.set(name, value);
      else next.delete(name);
    }
    const text = next.toString();
    router.replace(text ? `${pathname}?${text}` : pathname);
  };

  const range: [Dayjs, Dayjs] | null =
    data != null ? [dayjs(data.first_day), dayjs(data.last_day)] : null;

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        icon={<DashboardOutlined />}
        title="Mức độ sử dụng"
        subtitle="Chi phí và token của các lượt gọi model của công ty, ngày tính theo múi giờ của công ty."
        actions={
          <>
            <DatePicker.RangePicker
              aria-label="Khoảng ngày"
              format="DD/MM/YYYY"
              allowClear={false}
              value={range}
              onChange={(values) =>
                setParams({
                  from: values?.[0]?.format("YYYY-MM-DD") ?? null,
                  to: values?.[1]?.format("YYYY-MM-DD") ?? null,
                })
              }
            />
            <Link href="/usage/limits">Cấu hình hạn mức</Link>
            <Button
              icon={<ReloadOutlined aria-hidden />}
              aria-label="Tải lại"
              onClick={reload}
            />
          </>
        }
      />
      <Flex vertical gap="middle">
        <Flex wrap gap="small" align="center">
          <Segmented<UsageGroupBy>
            options={GROUPS}
            value={groupBy}
            onChange={(value) => setParams({ group_by: value })}
          />
          {filtered && (
            <>
              {query.workspace_id && <Tag>Một workspace</Tag>}
              {query.artifact_id && (
                <Tag>
                  {ARTIFACT_KINDS[query.artifact_kind ?? ""] ??
                    "Một thành phần"}
                </Tag>
              )}
              <Button
                type="link"
                onClick={() =>
                  setParams({
                    workspace_id: null,
                    artifact_id: null,
                    artifact_kind: null,
                  })
                }
              >
                Xóa bộ lọc
              </Button>
            </>
          )}
        </Flex>

        {error != null && <LoadError error={error} onRetry={reload} />}
        {loading && error == null && (
          <Skeleton active paragraph={{ rows: 6 }} />
        )}

        {data != null && error == null && (
          <>
            <Typography.Text type="secondary">
              Từ {formatDate(data.first_day)} đến {formatDate(data.last_day)} (
              {data.timezone})
            </Typography.Text>
            {(data.unpriced_calls > 0 || data.estimated_calls > 0) && (
              <Alert
                type="warning"
                showIcon
                message="Tổng chi phí có phần chưa chắc chắn"
                description={
                  <>
                    {data.unpriced_calls > 0 && (
                      <div>
                        {formatCount(data.unpriced_calls)} lượt gọi chưa có giá
                        trong Bảng giá, nên không cộng vào chi phí.
                      </div>
                    )}
                    {data.estimated_calls > 0 && (
                      <div>
                        {formatCount(data.estimated_calls)} lượt gọi mà nhà cung
                        cấp không báo số token, nên chi phí là ước tính.
                      </div>
                    )}
                  </>
                }
              />
            )}
            {limits.data != null && (
              <LimitsProgress
                lines={limits.data}
                scopeName={(line) =>
                  SCOPE_LABELS[line.scope_type] ?? line.scope_type
                }
              />
            )}
            <Card>
              <Flex wrap gap="large">
                <Statistic title="Chi phí" value={formatUsd(data.cost_usd)} />
                <Statistic
                  title="Lượt gọi model"
                  value={formatCount(data.calls)}
                />
                <Statistic
                  title="Token vào"
                  value={formatCount(data.input_tokens)}
                />
                <Statistic
                  title="Token ra"
                  value={formatCount(data.output_tokens)}
                />
              </Flex>
            </Card>
            {data.groups.length === 0 ? (
              <RegionState
                kind="empty"
                title={
                  filtered
                    ? "Không có lượt gọi nào khớp bộ lọc trong khoảng này"
                    : "Chưa có lượt gọi model nào trong khoảng này"
                }
              />
            ) : (
              <Card>
                <Table<UsageGroup>
                  rowKey={(group) =>
                    `${group.artifact_kind ?? ""}:${group.key ?? "none"}`
                  }
                  size="small"
                  pagination={false}
                  scroll={{ x: "max-content" }}
                  dataSource={data.groups}
                  columns={[
                    {
                      title: "Nhóm",
                      key: "group",
                      render: (_, group) => {
                        const name = groupName(group, data.group_by);
                        const href = narrowTo(group, data.group_by);
                        return href ? <Link href={href}>{name}</Link> : name;
                      },
                    },
                    {
                      title: "Lượt gọi",
                      dataIndex: "calls",
                      align: "right",
                      render: (value: number) => formatCount(value),
                    },
                    {
                      title: "Token vào",
                      dataIndex: "input_tokens",
                      align: "right",
                      render: (value: number) => formatCount(value),
                    },
                    {
                      title: "Token ra",
                      dataIndex: "output_tokens",
                      align: "right",
                      render: (value: number) => formatCount(value),
                    },
                    {
                      title: "Chi phí",
                      dataIndex: "cost_usd",
                      align: "right",
                      render: (value: string) => formatUsd(value),
                    },
                    {
                      title: "Ghi chú",
                      key: "notes",
                      render: (_, group) => (
                        <Flex gap="small" wrap>
                          {group.unpriced_calls > 0 && (
                            <Tag color="warning">
                              {formatCount(group.unpriced_calls)} chưa có giá
                            </Tag>
                          )}
                          {group.estimated_calls > 0 && (
                            <Tag>
                              {formatCount(group.estimated_calls)} ước tính
                            </Tag>
                          )}
                        </Flex>
                      ),
                    },
                  ]}
                />
              </Card>
            )}
          </>
        )}
      </Flex>
    </div>
  );
}
