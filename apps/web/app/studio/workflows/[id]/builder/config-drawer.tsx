"use client";

import { useMemo } from "react";
import {
  Alert,
  Drawer,
  Form,
  Input,
  InputNumber,
  Select,
  Switch,
  Tabs,
} from "antd";
import {
  formConfig,
  laneKeys,
  stepName,
  type Catalogue,
  type JsonObject,
  type OnError,
  type StepNode,
  type StepTypeSpec,
} from "../../../../../lib/workflow-graph";
import { bt } from "./messages";

/**
 * A step's configuration in an antd Drawer (workflow-builder-ui R2.1): a Form
 * generated from the type's `config_schema` without the keys that hold lanes
 * (a lane is edited on the canvas only), the step's name, and a "Khi lỗi" tab
 * for `on_error`, `retry` and `timeout_s`. No widget of its own: a value the
 * schema does not type plainly is JSON in a text area. The Form checks
 * nothing but what it must to build a value; the server's validator warns at
 * save and refuses at submit (ADR-0112 (Accepted) decision 3).
 */

type FieldKind = "text" | "integer" | "number" | "boolean" | "enum" | "json";

interface FieldSpec {
  key: string;
  label: string;
  kind: FieldKind;
  required: boolean;
  options: string[];
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** The Form's fields: every property of the schema but the lane keys. */
export function schemaFields(spec: StepTypeSpec): FieldSpec[] {
  const properties = isObject(spec.config_schema.properties)
    ? spec.config_schema.properties
    : {};
  const required = Array.isArray(spec.config_schema.required)
    ? (spec.config_schema.required as unknown[])
    : [];
  const lanes = new Set(laneKeys(spec));
  return Object.entries(properties)
    .filter(([key]) => !lanes.has(key))
    .map(([key, schema]) => {
      const s = isObject(schema) ? schema : {};
      const label = typeof s.title === "string" ? s.title : key;
      let kind: FieldKind = "json";
      let options: string[] = [];
      if (Array.isArray(s.enum) && s.enum.every((v) => typeof v === "string")) {
        kind = "enum";
        options = s.enum as string[];
      } else if (s.type === "string") kind = "text";
      else if (s.type === "integer") kind = "integer";
      else if (s.type === "number") kind = "number";
      else if (s.type === "boolean") kind = "boolean";
      return { key, label, kind, required: required.includes(key), options };
    });
}

/** A config value as its field holds it. */
function toField(field: FieldSpec, value: unknown): unknown {
  if (value === undefined) return undefined;
  return field.kind === "json" ? JSON.stringify(value, null, 2) : value;
}

/** A field's value back in the config; `undefined` removes the key, and JSON
 * that does not parse keeps the value the step had. */
function fromField(
  field: FieldSpec,
  value: unknown,
  previous: unknown,
): unknown {
  if (value === null || value === undefined || value === "") return undefined;
  if (field.kind !== "json") return value;
  try {
    return JSON.parse(String(value));
  } catch {
    return previous;
  }
}

interface ConfigDrawerProps {
  node: StepNode | null;
  catalogue: Catalogue;
  /** Bumped by undo and redo, so the Form reads the restored values. */
  epoch: number;
  placement: "right" | "bottom";
  onClose: () => void;
  afterClose?: () => void;
  onFields: (
    fields: {
      config?: JsonObject;
      retry?: unknown;
      timeout_s?: unknown;
      description?: unknown;
    },
    tag: string,
  ) => void;
  onOnError: (value: OnError) => void;
}

export function ConfigDrawer({
  node,
  catalogue,
  epoch,
  placement,
  onClose,
  afterClose,
  onFields,
  onOnError,
}: ConfigDrawerProps) {
  const spec = node ? catalogue.get(node.type) : undefined;
  const fields = useMemo(() => (spec ? schemaFields(spec) : []), [spec]);
  const config = node && spec ? formConfig(node, catalogue) : {};
  const initial = Object.fromEntries(
    fields.map((f) => [f.key, toField(f, config[f.key])]),
  );
  const retry = isObject(node?.rest.retry) ? node.rest.retry : {};

  const fieldsTab = (
    <Form
      key={`${node?.id}:${epoch}:fields`}
      layout="vertical"
      validateTrigger="onBlur"
      initialValues={{
        ...initial,
        __description: node?.rest.description ?? "",
      }}
      onValuesChange={(_, all: Record<string, unknown>) => {
        if (!node) return;
        const next: JsonObject = {};
        for (const field of fields) {
          const value = fromField(field, all[field.key], config[field.key]);
          if (value !== undefined) next[field.key] = value;
        }
        const description = String(all.__description ?? "").trim();
        onFields(
          {
            config: next,
            description: description === "" ? undefined : description,
          },
          `config:${node.id}`,
        );
      }}
    >
      <Form.Item
        name="__description"
        label={bt("config.name")}
        extra={bt("config.name.help")}
      >
        <Input />
      </Form.Item>
      {fields.map((field) => (
        <Form.Item
          key={field.key}
          name={field.key}
          label={field.label}
          required={field.required}
          valuePropName={field.kind === "boolean" ? "checked" : "value"}
          rules={
            field.kind === "json"
              ? [
                  {
                    validator: async (_, value: unknown) => {
                      if (value === undefined || value === "") return;
                      JSON.parse(String(value));
                    },
                    message: bt("config.json.invalid"),
                  },
                ]
              : []
          }
        >
          {field.kind === "text" ? (
            <Input />
          ) : field.kind === "integer" ? (
            <InputNumber precision={0} className="w-full" />
          ) : field.kind === "number" ? (
            <InputNumber className="w-full" />
          ) : field.kind === "boolean" ? (
            <Switch />
          ) : field.kind === "enum" ? (
            <Select
              allowClear
              options={field.options.map((o) => ({ value: o, label: o }))}
            />
          ) : (
            <Input.TextArea autoSize={{ minRows: 2, maxRows: 10 }} />
          )}
        </Form.Item>
      ))}
    </Form>
  );

  const errorTab = (
    <Form
      key={`${node?.id}:${epoch}:error`}
      layout="vertical"
      initialValues={{
        on_error: node?.rest.on_error ?? "fail",
        max_attempts: retry.max_attempts,
        backoff: retry.backoff,
        timeout_s: node?.rest.timeout_s,
      }}
      onValuesChange={(
        changed: Record<string, unknown>,
        all: Record<string, unknown>,
      ) => {
        if (!node) return;
        if ("on_error" in changed) {
          onOnError(changed.on_error as OnError);
          return;
        }
        const attempts = all.max_attempts;
        onFields(
          {
            retry:
              typeof attempts === "number"
                ? { max_attempts: attempts, backoff: all.backoff ?? "fixed" }
                : undefined,
            timeout_s:
              typeof all.timeout_s === "number" ? all.timeout_s : undefined,
          },
          `error:${node.id}`,
        );
      }}
    >
      <Form.Item name="on_error" label={bt("config.onError")}>
        <Select
          options={(["fail", "continue", "route"] as const).map((value) => ({
            value,
            label: bt(`onError.${value}`),
          }))}
        />
      </Form.Item>
      <Form.Item name="max_attempts" label={bt("config.retry")}>
        <InputNumber min={1} max={5} precision={0} className="w-full" />
      </Form.Item>
      <Form.Item name="backoff" label={bt("config.backoff")}>
        <Select
          allowClear
          options={[
            { value: "fixed", label: bt("config.backoff.fixed") },
            { value: "exponential", label: bt("config.backoff.exponential") },
          ]}
        />
      </Form.Item>
      <Form.Item name="timeout_s" label={bt("config.timeout")}>
        <InputNumber min={1} max={900} precision={0} className="w-full" />
      </Form.Item>
    </Form>
  );

  return (
    <Drawer
      open={node !== null}
      onClose={onClose}
      afterOpenChange={(open) => {
        if (!open) afterClose?.();
      }}
      placement={placement}
      size={placement === "bottom" ? "large" : "default"}
      title={
        node ? bt("config.title", { name: stepName(node, catalogue) }) : ""
      }
      destroyOnHidden
    >
      {node && !node.known ? (
        <Alert type="warning" showIcon message={bt("config.unknown")} />
      ) : (
        <Tabs
          items={[
            {
              key: "fields",
              label: bt("config.tab.fields"),
              children: fieldsTab,
            },
            {
              key: "error",
              label: bt("config.tab.onError"),
              children: errorTab,
            },
          ]}
        />
      )}
    </Drawer>
  );
}
