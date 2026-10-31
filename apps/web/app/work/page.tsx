"use client";

import { Suspense, useCallback } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  Button,
  Descriptions,
  Drawer,
  Flex,
  Grid,
  Select,
  Skeleton,
  Table,
  Tag,
  Typography,
} from "antd";
import { ReloadOutlined, UnorderedListOutlined } from "@ant-design/icons";
import type {
  WorkHolderKind,
  WorkItem,
  WorkStatus,
  WorkTrailEntry,
} from "@dw/api-client";
import { PageHeader, RegionState } from "@dw/ui";
import { LoadError } from "../../components/load-error";
import { LoadMore } from "../../components/load-more";
import { formatDateTime } from "../../lib/dates";
import { memberName, useWorkspaceMembers } from "../../lib/directory";
import {
  HANDOFF_FIELDS,
  HOLDER_KIND,
  WORK_STATUS,
  workStatus,
} from "../../lib/digital-workers/labels";
import { apiClient } from "../../lib/session";
import { useCachedPages } from "../../lib/use-cached-pages";
import { useCachedResource } from "../../lib/use-cached-resource";

export default function WorkPage() {
  // `useSearchParams` needs a Suspense boundary above the component calling it.
  return (
    <Suspense fallback={<Skeleton active paragraph={{ rows: 6 }} />}>
      <WorkQueue />
    </Suspense>
  );
}

function isStatus(value: string | null): value is WorkStatus {
  return value !== null && Object.hasOwn(WORK_STATUS, value);
}

function isHolder(value: string | null): value is WorkHolderKind {
  return value !== null && Object.hasOwn(HOLDER_KIND, value);
}

/**
 * The queue people and Digital Workers share (digital-worker R9.3), filtered
 * by status and by who holds the item. The filters and the open item live in
 * the URL, so a link sent to a colleague opens the same view.
 */
function WorkQueue() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const status = isStatus(params.get("status")) ? params.get("status") : null;
  const holder = isHolder(params.get("holder")) ? params.get("holder") : null;
  const openItem = params.get("item");
  const members = useWorkspaceMembers();

  const hrefWith = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params.toString());
    for (const [name, value] of Object.entries(changes)) {
      if (value === null) next.delete(name);
      else next.set(name, value);
    }
    const query = next.toString();
    return query ? `${pathname}?${query}` : pathname;
  };
  const setParams = (changes: Record<string, string | null>) =>
    router.replace(hrefWith(changes), { scroll: false });

  const { items, loading, loadingMore, error, hasMore, loadMore, reload } =
    useCachedPages(
      `work-items:${status ?? "all"}:${holder ?? "all"}`,
      useCallback(
        (cursor: string | null) =>
          apiClient().listWorkItems({
            cursor,
            status: status as WorkStatus | null,
            holder_kind: holder as WorkHolderKind | null,
          }),
        [status, holder],
      ),
    );
  const filtered = status !== null || holder !== null;

  const holderName = (item: WorkItem) =>
    item.holder_kind === "person"
      ? (memberName(members, item.holder_id) ?? "—")
      : "Digital Worker";

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        icon={<UnorderedListOutlined />}
        title="Hàng đợi việc"
        subtitle="Việc của người và của Digital Worker trong workspace này. Việc một Digital Worker bàn giao mang gói bàn giao cho người nhận."
        actions={
          <Button
            icon={<ReloadOutlined aria-hidden />}
            aria-label="Tải lại"
            onClick={reload}
          />
        }
      />
      <Flex vertical gap="middle">
        <Flex wrap gap="middle" align="center">
          <label className="flex items-center gap-2">
            <Typography.Text>Trạng thái</Typography.Text>
            <Select<string>
              aria-label="Trạng thái"
              className="min-w-44"
              allowClear
              placeholder="Mọi trạng thái"
              value={status ?? undefined}
              onChange={(value) => setParams({ status: value ?? null })}
              options={Object.entries(WORK_STATUS).map(([value, shown]) => ({
                value,
                label: shown.label,
              }))}
            />
          </label>
          <label className="flex items-center gap-2">
            <Typography.Text>Người giữ</Typography.Text>
            <Select<string>
              aria-label="Người giữ"
              className="min-w-44"
              allowClear
              placeholder="Mọi người giữ"
              value={holder ?? undefined}
              onChange={(value) => setParams({ holder: value ?? null })}
              options={Object.entries(HOLDER_KIND).map(([value, label]) => ({
                value,
                label,
              }))}
            />
          </label>
          {filtered && (
            <Button
              type="link"
              onClick={() => setParams({ status: null, holder: null })}
            >
              Xóa bộ lọc
            </Button>
          )}
        </Flex>

        {error != null && <LoadError error={error} onRetry={reload} />}
        {error == null && !loading && items.length === 0 && (
          <RegionState
            kind="empty"
            title={
              filtered
                ? "Không có việc nào khớp bộ lọc"
                : "Hàng đợi chưa có việc nào"
            }
            description={
              filtered
                ? "Bỏ bớt điều kiện để thấy việc khác."
                : "Việc tới từ cửa nhận việc của Digital Worker hay do người giao việc giao tay."
            }
            action={
              filtered ? (
                <Button
                  onClick={() => setParams({ status: null, holder: null })}
                >
                  Xóa bộ lọc
                </Button>
              ) : undefined
            }
          />
        )}
        {error == null && (loading || items.length > 0) && (
          <Table<WorkItem>
            rowKey="id"
            loading={loading}
            pagination={false}
            sticky
            scroll={{ x: "max-content" }}
            dataSource={items}
            locale={{ emptyText: " " }}
            columns={[
              {
                title: "Việc",
                dataIndex: "kind",
                render: (kind: string, item) => (
                  <Link href={hrefWith({ item: item.id })} scroll={false}>
                    {kind} · {item.source_key}
                  </Link>
                ),
              },
              {
                title: "Trạng thái",
                dataIndex: "status",
                render: (value: string) => {
                  const shown = workStatus(value);
                  return <Tag color={shown.color}>{shown.label}</Tag>;
                },
              },
              {
                title: "Người giữ",
                key: "holder",
                render: (_, item) => holderName(item),
              },
              {
                title: "Tạo lúc (giờ Việt Nam)",
                dataIndex: "created_at",
                render: (value: string) => formatDateTime(value),
              },
            ]}
          />
        )}
        {error == null && !loading && items.length > 0 && (
          <LoadMore
            hasMore={hasMore}
            loading={loadingMore}
            onLoadMore={loadMore}
            shown={items.length}
            noun="việc"
          />
        )}
      </Flex>
      <WorkItemDrawer
        itemId={openItem}
        holderName={holderName}
        onClose={() => setParams({ item: null })}
      />
    </div>
  );
}

function WorkItemDrawer({
  itemId,
  holderName,
  onClose,
}: {
  itemId: string | null;
  holderName: (item: WorkItem) => string;
  onClose: () => void;
}) {
  const screens = Grid.useBreakpoint();
  return (
    <Drawer
      open={itemId !== null}
      onClose={onClose}
      title="Việc"
      placement={screens.lg ? "right" : "bottom"}
      size={screens.lg ? 560 : "80%"}
      destroyOnHidden
    >
      {itemId !== null && (
        <WorkItemDetail itemId={itemId} holderName={holderName} />
      )}
    </Drawer>
  );
}

function WorkItemDetail({
  itemId,
  holderName,
}: {
  itemId: string;
  holderName: (item: WorkItem) => string;
}) {
  const found = useCachedResource<WorkItem>(
    `work-item:${itemId}`,
    useCallback(() => apiClient().getWorkItem(itemId), [itemId]),
  );
  if (found.error != null)
    return <LoadError error={found.error} onRetry={found.reload} compact />;
  if (found.data === null) return <RegionState kind="loading" compact />;
  const item = found.data;
  const shown = workStatus(item.status);
  return (
    <Flex vertical gap="large">
      <Descriptions
        column={1}
        size="small"
        items={[
          { key: "kind", label: "Loại việc", children: item.kind },
          { key: "source", label: "Nguồn", children: item.source_key },
          {
            key: "status",
            label: "Trạng thái",
            children: <Tag color={shown.color}>{shown.label}</Tag>,
          },
          { key: "holder", label: "Người giữ", children: holderName(item) },
          {
            key: "created",
            label: "Tạo lúc (giờ Việt Nam)",
            children: formatDateTime(item.created_at),
          },
          ...(item.error
            ? [{ key: "error", label: "Lỗi", children: item.error }]
            : []),
        ]}
      />
      {item.status === "handed_off" && (
        <Flex vertical gap="small">
          <Typography.Title level={5}>Gói bàn giao</Typography.Title>
          {item.handoff ? (
            <Descriptions
              column={1}
              size="small"
              bordered
              items={HANDOFF_FIELDS.map(([field, label]) => ({
                key: field,
                label,
                children: (
                  <Typography.Paragraph className="whitespace-pre-wrap">
                    {item.handoff?.[field]}
                  </Typography.Paragraph>
                ),
              }))}
            />
          ) : (
            <Typography.Text>
              Chỉ người đang giữ việc và bốn người của Digital Worker đọc được
              gói bàn giao.
            </Typography.Text>
          )}
        </Flex>
      )}
      <Flex vertical gap="small">
        <Typography.Title level={5}>Các bước đã chạy</Typography.Title>
        <Table<WorkTrailEntry>
          rowKey={(entry) => `${entry.step_id}:${entry.at}:${entry.status}`}
          size="small"
          pagination={false}
          scroll={{ x: "max-content" }}
          dataSource={item.trail ?? []}
          locale={{ emptyText: "Việc này chưa chạy bước nào." }}
          columns={[
            {
              title: "Lúc (giờ Việt Nam)",
              dataIndex: "at",
              render: (value: string) => formatDateTime(value),
            },
            {
              title: "Bước",
              dataIndex: "step_id",
              render: (value: string) => (
                <Typography.Text code>{value}</Typography.Text>
              ),
            },
            { title: "Loại", dataIndex: "type" },
            { title: "Kết quả", dataIndex: "status" },
          ]}
        />
      </Flex>
    </Flex>
  );
}
