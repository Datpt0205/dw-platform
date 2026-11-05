"use client";

import { useMemo, useState, type KeyboardEvent, type ReactNode } from "react";
import { Button, Dropdown, Flex, Tree, Typography } from "antd";
import type { DataNode } from "antd/es/tree";
import { MoreOutlined } from "@ant-design/icons";
import {
  emptyLaneStop,
  parseEmptyLaneStop,
  type Catalogue,
  type LaneRef,
  type StepNode,
  type WorkflowTree,
} from "../../../../../lib/workflow-graph";
import {
  cardView,
  laneLabel,
  stepMenu,
  type MenuEntry,
  type MenuKey,
} from "./builder-model";
import { bt } from "./messages";

/**
 * The outline (workflow-builder-ui R2.6, BU11): an antd `Tree` built from the
 * same tree the canvas draws, never a copy of the document. Each step is a
 * node, each of its lanes a node under it (named by the catalogue's label),
 * the lane's steps under that; an empty lane is a lane node with no children
 * whose menu has "Thêm Bước". Every node carries `aria-level`,
 * `aria-posinset` and `aria-setsize` (antd 6.6.5 emits none of them itself).
 * It is the editor below `md` and at 320 px, with the canvas's menu: Enter
 * opens a step's configuration, Shift+F10 its menu, Delete removes it,
 * Ctrl+Z and Ctrl+Shift+Z undo and redo.
 */

export const OUTLINE_LANE_PREFIX = "lane:";

interface OutlineNode extends DataNode {
  "aria-level": number;
  "aria-posinset": number;
  "aria-setsize": number;
  children?: OutlineNode[];
}

interface WorkflowOutlineProps {
  tree: WorkflowTree;
  catalogue: Catalogue;
  activeKey: string | null;
  onActiveChange: (key: string | null) => void;
  openMenu: string | null;
  /** On a phone the menu is a bottom Drawer the page draws, not a Dropdown. */
  menuInDropdown: boolean;
  onOpenMenu: (id: string | null) => void;
  onMenu: (id: string, key: MenuKey) => void;
  onAddToLane: (lane: LaneRef) => void;
  onOpenStep: (id: string) => void;
  onDelete: (id: string) => void;
  onUndo: () => void;
  onRedo: () => void;
}

export function WorkflowOutline({
  tree,
  catalogue,
  activeKey,
  onActiveChange,
  openMenu,
  menuInDropdown,
  onOpenMenu,
  onMenu,
  onAddToLane,
  onOpenStep,
  onDelete,
  onUndo,
  onRedo,
}: WorkflowOutlineProps) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const { treeData, keys, steps } = useMemo(() => {
    const keys: string[] = [];
    const steps = new Map<string, StepNode>();
    const menuButton = (key: string, name: string, entries: ReactNode) => (
      <Flex align="center" gap={4} className="min-w-0">
        {entries}
        <Button
          type="text"
          size="small"
          tabIndex={-1}
          aria-label={`${bt("card.menu")} «${name}»`}
          icon={<MoreOutlined aria-hidden />}
          onClick={(event) => {
            event.stopPropagation();
            onOpenMenu(key);
          }}
        />
      </Flex>
    );
    const withMenu = (
      key: string,
      name: string,
      items: MenuEntry[],
      title: ReactNode,
    ) => {
      const body = menuButton(key, name, title);
      if (!menuInDropdown) return body;
      return (
        <Dropdown
          trigger={["contextMenu"]}
          autoFocus
          open={openMenu === key}
          onOpenChange={(open) => onOpenMenu(open ? key : null)}
          menu={{
            items: items.map(({ key: k, label, danger }) => ({
              key: k,
              label,
              danger,
            })),
            onClick: ({ key: picked, domEvent }) => {
              domEvent.stopPropagation();
              onOpenMenu(null);
              if (picked === "addStep") {
                const lane = parseEmptyLaneStop(key);
                if (lane) onAddToLane(lane);
              } else onMenu(key, picked as MenuKey);
            },
          }}
        >
          {body}
        </Dropdown>
      );
    };
    const stepNodes = (list: StepNode[], level: number): OutlineNode[] =>
      list.map((node, index) => {
        keys.push(node.id);
        steps.set(node.id, node);
        const view = cardView(node, catalogue);
        const title = (
          <Typography.Text ellipsis={{ tooltip: view.name }}>
            {view.name}
            <Typography.Text type="secondary">
              {" · "}
              {view.known ? view.typeLabel : bt("card.unknown")}
            </Typography.Text>
          </Typography.Text>
        );
        const children = node.lanes.map((lane, laneIndex): OutlineNode => {
          const ref = { parent: node.id, port: lane.port };
          const key = emptyLaneStop(ref);
          keys.push(key);
          const label = laneLabel(lane);
          const empty = lane.steps.length === 0;
          return {
            key,
            title: empty
              ? withMenu(
                  key,
                  label,
                  [{ key: "addStep" as MenuKey, label: bt("menu.addStep") }],
                  <Typography.Text>{label}</Typography.Text>,
                )
              : label,
            "aria-level": level + 1,
            "aria-posinset": laneIndex + 1,
            "aria-setsize": node.lanes.length,
            children: stepNodes(lane.steps, level + 2),
          };
        });
        return {
          key: node.id,
          title: withMenu(node.id, view.name, stepMenu(node, catalogue), title),
          "aria-level": level,
          "aria-posinset": index + 1,
          "aria-setsize": list.length,
          children: children.length > 0 ? children : undefined,
        };
      });
    const root = stepNodes(tree.steps, 1);
    return { treeData: root, keys, steps };
    // The callbacks are stable enough for a list; the tree is what changes.
  }, [
    tree,
    catalogue,
    openMenu,
    menuInDropdown,
    onOpenMenu,
    onMenu,
    onAddToLane,
  ]);

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.nativeEvent.isComposing) return;
    const ctrl = event.ctrlKey || event.metaKey;
    const key = event.key.toLowerCase();
    if (ctrl && key === "z") {
      event.preventDefault();
      if (event.shiftKey) onRedo();
      else onUndo();
      return;
    }
    if (ctrl && key === "y") {
      event.preventDefault();
      onRedo();
      return;
    }
    if (activeKey === null) return;
    if (
      (event.key === "F10" && event.shiftKey) ||
      event.key === "ContextMenu"
    ) {
      event.preventDefault();
      onOpenMenu(activeKey);
      return;
    }
    if (event.key === "Delete" && steps.has(activeKey)) {
      event.preventDefault();
      onDelete(activeKey);
    }
  };

  return (
    <div className="overflow-x-auto">
      <Tree<OutlineNode>
        aria-label={bt("outline.label")}
        blockNode
        showLine
        treeData={treeData}
        expandedKeys={keys.filter((k) => !collapsed.has(k))}
        onExpand={(expanded) => {
          const open = new Set(expanded.map(String));
          setCollapsed(new Set(keys.filter((k) => !open.has(k))));
        }}
        activeKey={activeKey ?? undefined}
        onActiveChange={(key) =>
          onActiveChange(key === null ? null : String(key))
        }
        selectedKeys={activeKey ? [activeKey] : []}
        onSelect={(selected, info) => {
          const key = String(info.node.key);
          onActiveChange(key);
          if (steps.has(key)) onOpenStep(key);
          else if (selected.length > 0) {
            const lane = parseEmptyLaneStop(key);
            const holder = lane?.parent ? steps.get(lane.parent) : undefined;
            if (
              lane &&
              holder?.lanes.find((l) => l.port === lane.port)?.steps.length ===
                0
            ) {
              onAddToLane(lane);
            }
          }
        }}
        onKeyDown={onKeyDown}
      />
    </div>
  );
}
