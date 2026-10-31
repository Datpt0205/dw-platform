"use client";

import { useCallback } from "react";
import Link from "next/link";
import { Button, Flex, Table, Tag, Typography } from "antd";
import { ReloadOutlined, RobotOutlined } from "@ant-design/icons";
import type { DigitalWorkerListItem } from "@dw/api-client";
import { PageHeader, RegionState } from "@dw/ui";
import { LoadError } from "../../components/load-error";
import { LoadMore } from "../../components/load-more";
import { dwState } from "../../lib/digital-workers/labels";
import { apiClient } from "../../lib/session";
import { useCachedPages } from "../../lib/use-cached-pages";

/** The workspace's Digital Workers (digital-worker R9.1). */
export default function DigitalWorkersPage() {
  const { items, loading, loadingMore, error, hasMore, loadMore, reload } =
    useCachedPages(
      "digital-workers",
      useCallback(
        (cursor: string | null) => apiClient().listDigitalWorkers({ cursor }),
        [],
      ),
    );

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        icon={<RobotOutlined />}
        title="Digital Worker"
        subtitle="Mỗi Digital Worker giữ một hàng việc trong khung nhiệm vụ của nó; việc vượt quyền thì hỏi người, việc ngoài công cụ được phép thì bị chặn."
        actions={
          <Button
            icon={<ReloadOutlined aria-hidden />}
            aria-label="Tải lại"
            onClick={reload}
          />
        }
      />
      <Flex vertical gap="middle">
        {error != null && <LoadError error={error} onRetry={reload} />}
        {error == null && !loading && items.length === 0 && (
          <RegionState
            kind="empty"
            title="Workspace này chưa có Digital Worker nào"
            description="Một Digital Worker được tạo từ gói quy trình đã cài, rồi chạy khi người thứ hai cho phép."
          />
        )}
        {error == null && (loading || items.length > 0) && (
          <Table<DigitalWorkerListItem>
            rowKey="id"
            loading={loading}
            pagination={false}
            sticky
            // A fixed width, not max-content: the table lays out fixed, so a
            // long mandate is cut with its full text on hover, not pushing the
            // open-item count off the screen.
            scroll={{ x: 760 }}
            dataSource={items}
            locale={{ emptyText: " " }}
            columns={[
              {
                title: "Tên",
                dataIndex: "name",
                width: 260,
                render: (name: string, worker) => (
                  <Link href={`/digital-workers/${worker.id}`}>{name}</Link>
                ),
              },
              {
                title: "Trạng thái",
                dataIndex: "state",
                width: 130,
                render: (state: string) => {
                  const shown = dwState(state);
                  return <Tag color={shown.color}>{shown.label}</Tag>;
                },
              },
              {
                title: "Nhiệm vụ",
                dataIndex: "mandate",
                ellipsis: { showTitle: true },
              },
              {
                title: "Việc đang mở",
                dataIndex: "open_items",
                align: "right",
                width: 130,
                render: (count: number) => (
                  <Typography.Text className="tabular-nums">
                    {count}
                  </Typography.Text>
                ),
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
            noun="Digital Worker"
          />
        )}
      </Flex>
    </div>
  );
}
