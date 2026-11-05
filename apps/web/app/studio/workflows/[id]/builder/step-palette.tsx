"use client";

import { useMemo, useState } from "react";
import { Button, Empty, Flex, Input, Typography } from "antd";
import { HolderOutlined, SearchOutlined } from "@ant-design/icons";
import {
  isTriggerType,
  stepGroup,
  type StepGroup,
  type StepTypeSpec,
} from "../../../../../lib/workflow-graph";
import { bt, fold } from "./messages";

/**
 * The step-type catalogue as a builder picks from it (workflow-builder-ui
 * R2.1): grouped, searchable by name without diacritics, never a `trigger.*`
 * type (`triggers[]` is not edited in W1). In a "+"'s Popover a choice goes
 * into that slot; in the side panel (from `lg`) an entry is dragged onto a
 * slot. The route names no lock yet (its lock reasons join the first type
 * that declares one, workflow-nodes R1.2), so none is drawn.
 */

const ORDER: StepGroup[] = ["ai", "data", "logic", "human", "tool", "trigger"];

export function paletteTypes(types: readonly StepTypeSpec[]): StepTypeSpec[] {
  return types.filter((t) => !isTriggerType(t.type));
}

interface StepPaletteProps {
  types: readonly StepTypeSpec[];
  mode: "pick" | "drag";
  onPick?: (type: string) => void;
  onDragStart?: (type: string) => void;
}

export function StepPalette({
  types,
  mode,
  onPick,
  onDragStart,
}: StepPaletteProps) {
  const [query, setQuery] = useState("");
  const groups = useMemo(() => {
    const wanted = fold(query.trim());
    const shown = paletteTypes(types).filter(
      (t) =>
        wanted === "" ||
        fold(t.label_vi).includes(wanted) ||
        t.type.includes(wanted),
    );
    return ORDER.map((group) => ({
      group,
      items: shown
        .filter((t) => stepGroup(t.type) === group)
        .sort((a, b) => a.label_vi.localeCompare(b.label_vi, "vi")),
    })).filter((g) => g.items.length > 0);
  }, [types, query]);

  return (
    <Flex vertical gap="small" className="min-w-0">
      <Input
        allowClear
        autoFocus={mode === "pick"}
        prefix={<SearchOutlined aria-hidden />}
        aria-label={bt("palette.search")}
        placeholder={bt("palette.search")}
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />
      {mode === "drag" && (
        <Typography.Text>{bt("palette.dragHint")}</Typography.Text>
      )}
      {groups.length === 0 && (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={bt("palette.empty")}
        />
      )}
      <div className="max-h-80 overflow-y-auto" role="list">
        {groups.map(({ group, items }) => (
          <div key={group} role="listitem">
            <Typography.Text strong>{bt(`group.${group}`)}</Typography.Text>
            <Flex vertical>
              {items.map((spec) =>
                mode === "pick" ? (
                  <Button
                    key={spec.type}
                    type="text"
                    className="justify-start"
                    onClick={() => onPick?.(spec.type)}
                  >
                    {spec.label_vi}
                  </Button>
                ) : (
                  <Button
                    key={spec.type}
                    type="text"
                    className="cursor-grab justify-start"
                    icon={<HolderOutlined aria-hidden />}
                    aria-label={bt("palette.drag", { name: spec.label_vi })}
                    onPointerDown={(event) => {
                      event.preventDefault();
                      onDragStart?.(spec.type);
                    }}
                  >
                    {spec.label_vi}
                  </Button>
                ),
              )}
            </Flex>
          </div>
        ))}
      </div>
    </Flex>
  );
}
