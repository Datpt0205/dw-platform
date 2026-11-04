"use client";

import { useCallback } from "react";
import { Button, Card, Flex, Table, Typography } from "antd";
import { AppstoreOutlined, ReloadOutlined } from "@ant-design/icons";
import type { StudioArtifact } from "@dw/api-client";
import { PageHeader, RegionState } from "@dw/ui";
import { LoadError } from "../../components/load-error";
import { LoadMore } from "../../components/load-more";
import { formatDateTime } from "../../lib/dates";
import { apiClient } from "../../lib/session";
import { useCachedPages } from "../../lib/use-cached-pages";
import { kindLabel, t } from "./_meta/messages";
import { STUDIO_SECTIONS } from "./_meta/sections";

/**
 * Every Studio artifact the viewer may read (R7.3): what
 * `GET /api/v1/studio/artifacts` returns, which filters each kind by its own
 * read key across the workspaces the viewer reaches. Keyset pages, appended
 * with "Tải thêm"; a refusal is the shared forbidden state, never an empty
 * table.
 */
export default function StudioPage() {
  const { items, loading, loadingMore, error, hasMore, loadMore, reload } =
    useCachedPages(
      "studio:artifacts",
      useCallback(
        (cursor: string | null) => apiClient().listStudioArtifacts({ cursor }),
        [],
      ),
    );

  return (
    <div>
      <PageHeader
        icon={<AppstoreOutlined />}
        title={t("list.title")}
        subtitle={t("list.subtitle")}
        actions={
          <Button
            icon={<ReloadOutlined aria-hidden />}
            aria-label={t("list.reload")}
            onClick={reload}
          />
        }
      />
      <Flex vertical gap="middle">
        {error != null && <LoadError error={error} onRetry={reload} />}
        {loading && error == null && <RegionState kind="loading" />}
        {!loading && error == null && items.length === 0 && !hasMore && (
          <RegionState
            kind="empty"
            title={t("list.empty.title")}
            description={t("list.empty.description")}
          />
        )}
        {error == null && items.length > 0 && (
          <Card>
            <Table<StudioArtifact>
              rowKey="id"
              size="small"
              pagination={false}
              scroll={{ x: "max-content" }}
              dataSource={items}
              columns={[
                {
                  title: t("list.column.apiName"),
                  dataIndex: "api_name",
                  render: (value: string) => (
                    <Typography.Text code>{value}</Typography.Text>
                  ),
                },
                {
                  title: t("list.column.kind"),
                  dataIndex: "kind",
                  render: (value: string) => kindLabel(value, STUDIO_SECTIONS),
                },
                {
                  title: t("list.column.version"),
                  dataIndex: "last_version_no",
                  align: "right",
                },
                {
                  title: t("list.column.updatedAt"),
                  dataIndex: "updated_at",
                  render: (value: string) => formatDateTime(value),
                },
              ]}
            />
          </Card>
        )}
        {!loading && error == null && (items.length > 0 || hasMore) && (
          <LoadMore
            hasMore={hasMore}
            loading={loadingMore}
            onLoadMore={loadMore}
            shown={items.length}
            noun={t("list.noun")}
          />
        )}
      </Flex>
    </div>
  );
}
