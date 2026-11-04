"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  App,
  Button,
  Card,
  Checkbox,
  Flex,
  Select,
  Tag,
  Tooltip,
  Typography,
  theme,
} from "antd";
import {
  DeleteOutlined,
  LockOutlined,
  SafetyCertificateOutlined,
  SaveOutlined,
  UserAddOutlined,
} from "@ant-design/icons";
import type {
  AdminRole,
  PlatformUserRef,
  WorkspaceMember,
} from "@dw/api-client";
import { RegionState } from "@dw/ui";
import { apiClient } from "../../lib/session";
import { useAuth } from "../../lib/auth/auth-context";
import { errorMessage } from "../../lib/error-message";
import { roleLabel } from "../../lib/nav/roles";
import { EmailPicker } from "../email-picker";
import {
  LOCKED_ROLE_REASON,
  SECOND_PERSON_PENDING,
  assignableOf,
  keepLocked,
  lockedOf,
  membershipsBody,
} from "./role-assignment";

// The member nobody assigned anything else to starts as, when the caller may
// assign it; otherwise the first role they may.
const DEFAULT_ROLE = "member";

/**
 * The workspace's members and the roles each holds there. The roles are the
 * company's own (`GET /api/v1/admin/roles`): a role the caller may not assign
 * (`assignable_by_me = false`) is shown locked with the reason and sent back
 * as it is, and a role added waits for a second person (202 `proposals`).
 * The server decides either way; the lock only says so before the click.
 */
export function MembersManager() {
  const { active } = useAuth();
  const { message, modal } = App.useApp();
  const { token } = theme.useToken();
  const workspaceId = active?.workspaceId ?? null;

  const [members, setMembers] = useState<WorkspaceMember[] | null>(null);
  const [roles, setRoles] = useState<AdminRole[] | null>(null);
  const [rolesError, setRolesError] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<PlatformUserRef[]>([]);
  // The picker is a convenience (the email box works without it), so a load
  // failure shows a small note here rather than being swallowed silently.
  const [candidatesError, setCandidatesError] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // What the last write left waiting for a second person, until dismissed.
  const [pending, setPending] = useState<string | null>(null);
  // Per-row choices among the roles the caller may assign, keyed by user id;
  // a row falls back to what it holds until it is touched.
  const [roleEdits, setRoleEdits] = useState<Record<string, string[]>>({});
  const [savingId, setSavingId] = useState<string | null>(null);
  // Per-row permission-set edits, keyed by user id.
  const [setEdits, setSetEdits] = useState<Record<string, string[]>>({});
  const [savingSetsId, setSavingSetsId] = useState<string | null>(null);
  // Permission sets are the exception, not the rule, so the editor stays folded
  // per member and opens only when an admin asks for it. One open at a time.
  const [expandedSetsId, setExpandedSetsId] = useState<string | null>(null);

  const rolesByKey = useMemo(
    () => new Map((roles ?? []).map((r) => [r.key, r])),
    [roles],
  );
  const roleCatalog = useMemo(
    () => (roles ?? []).filter((r) => r.kind === "role"),
    [roles],
  );
  const setCatalog = useMemo(
    () => (roles ?? []).filter((r) => r.kind === "permission_set"),
    [roles],
  );
  const roleOptions = useMemo(
    () => roleCatalog.map(lockableOption),
    [roleCatalog],
  );
  const grantable = roleCatalog.filter((r) => r.assignable_by_me);
  const defaultRole =
    grantable.find((r) => r.key === DEFAULT_ROLE)?.key ??
    grantable[0]?.key ??
    null;
  const grantRole = role ?? defaultRole;

  function nameOf(key: string): string {
    return rolesByKey.get(key)?.name ?? roleLabel(key);
  }

  // Re-read the pick list on its own so it can refresh when the picker opens:
  // somebody who signs in after this page loaded must appear without a reload.
  const loadCandidates = useCallback(async () => {
    try {
      setCandidates(await apiClient().listGrantCandidates());
      setCandidatesError(null);
    } catch (e) {
      setCandidates([]);
      setCandidatesError(`${errorMessage(e)} Gõ email để cấp trực tiếp.`);
    }
  }, []);

  const refresh = useCallback(async () => {
    try {
      setMembers(await apiClient().listWorkspaceMembers());
      // Clear pending per-row edits so freshly loaded members show stored state.
      setSetEdits({});
      setRoleEdits({});
      await loadCandidates();
    } catch (e) {
      setMembers([]);
      setError(errorMessage(e));
    }
    // Without the company's roles nothing can be assigned, but the roster
    // still shows: a failure here locks the role controls, not the page.
    try {
      setRoles(await apiClient().listAdminRoles());
      setRolesError(null);
    } catch (e) {
      setRoles(null);
      setRolesError(errorMessage(e));
    }
  }, [loadCandidates]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  /** Say what a write left waiting, or that it is done. */
  function announce(who: string, proposals: readonly string[], done: string) {
    if (proposals.length > 0) {
      setPending(
        `Đã gửi ${proposals.length} đề xuất vai trò cho ${who}. Vai trò có` +
          " hiệu lực khi một người khác có quyền giao vai trò xác nhận.",
      );
    } else {
      message.success(done);
    }
  }

  async function grant() {
    if (!workspaceId || !email.trim() || !grantRole) return;
    setBusy(true);
    setError(null);
    try {
      const placed = await apiClient().grantMember({
        email: email.trim(),
        workspaceId,
        roleKeys: [grantRole],
      });
      announce(
        placed.display_name,
        placed.proposals,
        `Đã cấp quyền cho ${email.trim()}.`,
      );
      setEmail("");
      await refresh();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  function chosenRoles(m: WorkspaceMember): string[] {
    return roleEdits[m.user_id] ?? assignableOf(m.role_keys, rolesByKey);
  }

  /** Why a row's roles cannot be saved, or null when they can. */
  function saveBlocked(m: WorkspaceMember): string | null {
    if (roles === null) return "Chưa đọc được danh sách vai trò.";
    if (keepLocked(m.role_keys, chosenRoles(m), rolesByKey).length === 0) {
      return "Chọn ít nhất một vai. Để gỡ người này khỏi workspace, dùng nút Gỡ.";
    }
    return null;
  }

  // The route replaces a person's roles in every workspace at once, so the
  // other workspaces are read fresh and sent back as they are.
  async function saveRoles(m: WorkspaceMember) {
    if (!workspaceId) return;
    setSavingId(m.user_id);
    setError(null);
    try {
      const person = (await apiClient().listTenantMembers()).find(
        (t) => t.user_id === m.user_id,
      );
      if (!person) {
        setError(`${m.display_name} không còn trong công ty.`);
        await refresh();
        return;
      }
      const result = await apiClient().setMemberships(
        m.user_id,
        membershipsBody(person, workspaceId, chosenRoles(m), rolesByKey),
      );
      announce(
        m.display_name,
        result.proposals,
        `Đã lưu vai trò của ${m.display_name}.`,
      );
      await refresh();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSavingId(null);
    }
  }

  function checkedSets(m: WorkspaceMember): string[] {
    return setEdits[m.user_id] ?? m.permission_set_keys;
  }

  async function savePermissionSets(m: WorkspaceMember) {
    setSavingSetsId(m.user_id);
    setError(null);
    try {
      const result = await apiClient().setMemberPermissionSets(
        m.user_id,
        keepLocked(m.permission_set_keys, checkedSets(m), rolesByKey),
      );
      announce(
        m.display_name,
        result.proposals,
        `Đã lưu bộ quyền của ${m.display_name}.`,
      );
      await refresh();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSavingSetsId(null);
    }
  }

  function revoke(m: WorkspaceMember) {
    if (!workspaceId) return;
    modal.confirm({
      title: `Gỡ ${m.display_name} khỏi workspace?`,
      content: "Người này sẽ mất mọi vai trong workspace hiện tại.",
      okText: "Gỡ",
      okButtonProps: { danger: true },
      cancelText: "Hủy",
      autoFocusButton: "cancel",
      onOk: async () => {
        setError(null);
        try {
          await apiClient().revokeMember(m.user_id, workspaceId);
          await refresh();
        } catch (e) {
          setError(errorMessage(e));
        }
      },
    });
  }

  const grantBlocked =
    roles === null
      ? "Chưa đọc được danh sách vai trò."
      : grantRole === null
        ? "Bạn không giao được vai trò nào."
        : null;

  return (
    <Card title="Thành viên">
      <Flex vertical gap="middle">
        <Typography.Text type="secondary">
          Cấp quyền cho người đã đăng nhập ít nhất một lần. Người mới phải tự
          đăng nhập trước khi được giao vai. Vai trò thêm mới có hiệu lực khi
          người thứ hai xác nhận.
        </Typography.Text>
        <Flex wrap align="end" gap="small">
          <Flex vertical gap={4} className="min-w-[12rem] flex-1">
            <label htmlFor="grant-email">Email</label>
            <EmailPicker
              id="grant-email"
              value={email}
              onChange={setEmail}
              onOpen={() => void loadCandidates()}
              options={candidates.map((c) => ({
                email: c.email ?? "",
                display_name: c.display_name,
              }))}
              placeholder="Chọn hoặc gõ email…"
            />
            {candidatesError && (
              <Typography.Text type="secondary" className="text-xs">
                {candidatesError}
              </Typography.Text>
            )}
          </Flex>
          <Flex vertical gap={4}>
            <label htmlFor="grant-role">Vai</label>
            <Select
              id="grant-role"
              className="w-44"
              value={grantRole}
              onChange={setRole}
              options={roleOptions}
              disabled={roles === null}
            />
          </Flex>
          <Tooltip title={grantBlocked}>
            <Button
              type="primary"
              icon={<UserAddOutlined aria-hidden />}
              loading={busy}
              disabled={!email.trim() || grantBlocked !== null}
              onClick={() => void grant()}
            >
              Cấp quyền
            </Button>
          </Tooltip>
        </Flex>

        {rolesError && (
          <Alert
            type="warning"
            showIcon
            title="Không đọc được danh sách vai trò, nên chưa giao được vai."
            description={rolesError}
          />
        )}
        {pending && (
          <Alert
            type="info"
            showIcon
            role="status"
            title={SECOND_PERSON_PENDING}
            description={pending}
            closable={{
              onClose: () => setPending(null),
              "aria-label": "Đóng",
            }}
          />
        )}
        {error && <Alert type="error" showIcon title={error} />}

        {members === null ? (
          <RegionState kind="loading" compact />
        ) : members.length === 0 ? (
          <RegionState kind="empty" compact title="Chưa có thành viên" />
        ) : (
          <ul className="m-0 list-none p-0">
            {members.map((m) => {
              const locked = lockedOf(m.role_keys, rolesByKey);
              const blocked = saveBlocked(m);
              return (
                <li
                  key={m.user_id}
                  className="py-2.5"
                  style={{
                    borderBottom: `1px solid ${token.colorBorderSecondary}`,
                  }}
                >
                  <Flex wrap justify="space-between" align="center" gap="small">
                    <div className="min-w-0">
                      <Typography.Text strong ellipsis className="block">
                        {m.display_name}
                      </Typography.Text>
                      <Typography.Text type="secondary" className="text-xs">
                        {m.email ?? "—"} · {m.department}
                      </Typography.Text>
                    </div>
                    <Flex
                      align="center"
                      gap="small"
                      wrap
                      className="max-w-full"
                    >
                      {locked.map((key) => (
                        <Tag key={key} icon={<LockOutlined aria-hidden />}>
                          {nameOf(key)}
                        </Tag>
                      ))}
                      <Select
                        mode="multiple"
                        aria-label={`Vai của ${m.display_name}`}
                        className="min-w-[10rem]"
                        value={chosenRoles(m)}
                        onChange={(value: string[]) =>
                          setRoleEdits((prev) => ({
                            ...prev,
                            [m.user_id]: value,
                          }))
                        }
                        options={roleOptions}
                        disabled={roles === null}
                        placeholder="Chọn vai"
                      />
                      <Tooltip title={blocked}>
                        <Button
                          icon={<SaveOutlined aria-hidden />}
                          loading={savingId === m.user_id}
                          disabled={blocked !== null}
                          onClick={() => void saveRoles(m)}
                        >
                          Lưu
                        </Button>
                      </Tooltip>
                      <Button
                        type="text"
                        danger
                        icon={<DeleteOutlined aria-hidden />}
                        aria-label={`Gỡ ${m.display_name}`}
                        onClick={() => revoke(m)}
                      />
                    </Flex>
                  </Flex>
                  {locked.length > 0 && (
                    <Typography.Text className="mt-1 block">
                      <LockOutlined aria-hidden /> {LOCKED_ROLE_REASON}:{" "}
                      {locked.map(nameOf).join(", ")}. Vai này được giữ nguyên
                      khi lưu.
                    </Typography.Text>
                  )}

                  {setCatalog.length > 0 && (
                    <div className="mt-1.5">
                      <Button
                        type="link"
                        size="small"
                        className="!px-0"
                        icon={<SafetyCertificateOutlined aria-hidden />}
                        aria-expanded={expandedSetsId === m.user_id}
                        onClick={() =>
                          setExpandedSetsId(
                            expandedSetsId === m.user_id ? null : m.user_id,
                          )
                        }
                      >
                        Bộ quyền bổ sung
                        {checkedSets(m).length > 0 && (
                          <Tag className="!ms-1">{checkedSets(m).length}</Tag>
                        )}
                      </Button>
                      {expandedSetsId === m.user_id && (
                        <Flex vertical gap="small" className="mt-2">
                          <Checkbox.Group
                            value={checkedSets(m)}
                            onChange={(next) =>
                              setSetEdits((prev) => ({
                                ...prev,
                                [m.user_id]: next as string[],
                              }))
                            }
                            options={setCatalog.map(lockableOption)}
                          />
                          <div>
                            <Button
                              size="small"
                              icon={<SaveOutlined aria-hidden />}
                              loading={savingSetsId === m.user_id}
                              onClick={() => void savePermissionSets(m)}
                            >
                              Lưu bộ quyền
                            </Button>
                          </div>
                        </Flex>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </Flex>
    </Card>
  );
}

/** A role as an option: its name, and when the caller may not assign it,
 * disabled behind a lock with the reason. */
function lockableOption(r: AdminRole) {
  return r.assignable_by_me
    ? { value: r.key, label: r.name, title: r.description ?? r.name }
    : {
        value: r.key,
        label: (
          <span>
            <LockOutlined aria-hidden /> {r.name}
          </span>
        ),
        title: `${r.name}: ${LOCKED_ROLE_REASON}`,
        disabled: true,
      };
}
