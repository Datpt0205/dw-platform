"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import dynamic from "next/dynamic";
import {
  Alert,
  App,
  Button,
  Drawer,
  Flex,
  Form,
  Grid,
  Input,
  Menu,
  Modal,
  Result,
  Segmented,
  Select,
  Skeleton,
  Tooltip,
  TreeSelect,
  Typography,
} from "antd";
import {
  ApartmentOutlined,
  RedoOutlined,
  SearchOutlined,
  UndoOutlined,
} from "@ant-design/icons";
import { CANVAS_VOCABULARY, PageHeader } from "@dw/ui";
import type { StudioDraft } from "@dw/api-client";
import { LoadError } from "../../../../../components/load-error";
import { errorCode, errorMessage } from "../../../../../lib/error-message";
import { apiClient } from "../../../../../lib/session";
import {
  addLane,
  catalogueOf,
  commit,
  deleteStep,
  emptyLaneStop,
  framesAround,
  fromTree,
  history,
  insertStep,
  isFrame,
  isInside,
  locate,
  moveStep,
  navigate,
  newStep,
  parseEmptyLaneStop,
  redo,
  removeLane,
  setOnError,
  stepAtPointer,
  stepName,
  stopsInOrder,
  toStepNode,
  toTree,
  treeIds,
  undo,
  updateStepFields,
  walk,
  type Catalogue,
  type Direction,
  type History,
  type LaneRef,
  type OnError,
  type Outcome,
  type Refusal,
  type Slot,
  type StepNode,
  type StepTypeSpec,
  type WorkflowTree,
} from "../../../../../lib/workflow-graph";
import { layoutWorkflow, metricsFor } from "../../../../../lib/workflow-layout";
import type {
  CanvasLaneHead,
  CanvasSlot,
} from "../../../../../lib/workflow-shapes";
import type { CardIssues } from "./canvas/workflow-canvas";
import {
  cardView,
  laneLabel,
  laneMenu,
  laneName,
  moveTargets,
  parseSlotValue,
  slotLabel,
  stepMenu,
  type MenuEntry,
  type MenuKey,
  type MoveTarget,
} from "./builder-model";
import { ConfigDrawer } from "./config-drawer";
import { bt, fold } from "./messages";
import { StepPalette } from "./step-palette";
import { useDraftAutosave, type SavedWarnings } from "./use-draft-autosave";
import { useFoldedFrames } from "./use-folded-frames";
import { WorkflowOutline } from "./workflow-outline";

/**
 * The workflow builder (workflow-builder-ui R1.4, R2.1-R2.11): the draft of a
 * Studio workflow, edited as one step tree that the canvas draws and the
 * outline lists, saved as it changes. Every edit is one tree operation of
 * `lib/workflow-graph.ts`; nothing positional reaches the document. The page
 * never decides who may edit: the routes answer, and a refusal is drawn as
 * the server sent it.
 */

const WorkflowCanvas = dynamic(() => import("./canvas/workflow-canvas"), {
  ssr: false,
  loading: () => <Skeleton active />,
});

const METRICS = metricsFor(CANVAS_VOCABULARY.card);
const DELETED_KEY = "workflow-builder-deleted";
const ARROWS: Record<string, Direction> = {
  ArrowUp: "up",
  ArrowDown: "down",
  ArrowLeft: "left",
  ArrowRight: "right",
};

function isEditable(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return (
    target.isContentEditable ||
    ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) ||
    target.closest("[role=combobox]") !== null
  );
}

type Drag = { kind: "new"; type: string } | { kind: "move"; id: string };

/** The save's warnings on the cards they point at, and how many lie inside
 * each step, which its card shows while it is a folded frame (R1.7, R3.4). */
function issuesOf(
  tree: WorkflowTree,
  warnings: SavedWarnings | null,
): Map<string, CardIssues> {
  const own = new Map<string, string[]>();
  for (const item of warnings?.items ?? []) {
    const id = stepAtPointer(warnings!.document, item.pointer);
    if (id === null) continue;
    own.set(id, [...(own.get(id) ?? []), item.detail]);
  }
  const out = new Map<string, CardIssues>();
  if (own.size === 0) return out;
  const count = (node: StepNode): number => {
    let inside = 0;
    for (const lane of node.lanes)
      for (const step of lane.steps) inside += count(step);
    const mine = own.get(node.id) ?? [];
    if (mine.length + inside > 0) out.set(node.id, { own: mine, inside });
    return mine.length + inside;
  };
  for (const step of tree.steps) count(step);
  return out;
}

/** Whether a stop (a step, or an empty lane's slot) lies inside step `id`. */
function stopInside(tree: WorkflowTree, stop: string, id: string): boolean {
  const lane = parseEmptyLaneStop(stop);
  const holder = lane ? lane.parent : stop;
  if (holder === null) return false;
  if (lane && holder === id) return true;
  return locate(tree, holder)?.ancestors.includes(id) ?? false;
}

interface EditorProps {
  artifactId: string;
  catalogue: Catalogue;
  types: StepTypeSpec[];
  draft: StudioDraft;
  saveDelayMs: number;
  viewerId: string | null;
}

function Editor({
  artifactId,
  catalogue,
  types,
  draft,
  saveDelayMs,
  viewerId,
}: EditorProps) {
  const { message, notification } = App.useApp();
  const screens = Grid.useBreakpoint();
  const wide = screens.md === true;
  const large = screens.lg === true;
  const [hist, setHist] = useState<History<WorkflowTree>>(() =>
    history(toTree(draft.document, catalogue)),
  );
  const tree = hist.present;
  const document = useMemo(() => fromTree(tree), [tree]);
  const autosave = useDraftAutosave(
    artifactId,
    document,
    { version: draft.version, document: draft.document },
    saveDelayMs,
  );

  const [view, setView] = useState<"canvas" | "outline">("canvas");
  const showCanvas = wide && view === "canvas";
  const [live, setLive] = useState({ text: "", n: 0 });
  const [active, setActive] = useState<string | null>(null);
  const [outlineKey, setOutlineKey] = useState<string | null>(null);
  const [focusRequest, setFocusRequest] = useState<{
    stop: string;
    seq: number;
  } | null>(null);
  const [configFor, setConfigFor] = useState<string | null>(null);
  const [epoch, setEpoch] = useState(0);
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const [openSlot, setOpenSlot] = useState<string | null>(null);
  const [picker, setPicker] = useState<Slot | null>(null);
  const [moving, setMoving] = useState<string | null>(null);
  const [laneFor, setLaneFor] = useState<{
    id: string;
    mode: "add" | "remove";
  } | null>(null);
  const [gotoOpen, setGotoOpen] = useState(false);
  const [drag, setDrag] = useState<Drag | null>(null);
  const treeRef = useRef(tree);
  treeRef.current = tree;
  const { folded, setFolded } = useFoldedFrames(viewerId, artifactId);

  const stops = useMemo(() => stopsInOrder(tree, folded), [tree, folded]);
  const activeStop =
    active !== null && stops.includes(active) ? active : (stops[0] ?? null);

  const announce = useCallback(
    (text: string) => setLive((l) => ({ text, n: l.n + 1 })),
    [],
  );

  const focusStop = useCallback((stop: string) => {
    setActive(stop);
    setFocusRequest((r) => ({ stop, seq: (r?.seq ?? 0) + 1 }));
  }, []);

  /** Fold or open a frame (R1.7): kept for this viewer, never in the
   * document. Folding the frame focus is inside brings focus to its card. */
  const toggleFrame = useCallback(
    (id: string) => {
      const node = locate(tree, id)?.node;
      if (!node || !isFrame(node)) return;
      const next = new Set(folded);
      const folding = !next.has(id);
      if (folding) next.add(id);
      else next.delete(id);
      setFolded(next);
      announce(
        bt(folding ? "announce.folded" : "announce.unfolded", {
          name: stepName(node, catalogue),
        }),
      );
      if (folding && active !== null && stopInside(tree, active, id)) {
        focusStop(id);
      }
    },
    [active, announce, catalogue, focusStop, folded, setFolded, tree],
  );

  /** Open every folded frame around a step, as a manual open would, before
   * going to it (R1.7: Ctrl+K, a problem pointing inside a folded frame). */
  const reveal = useCallback(
    (id: string) => {
      const around = framesAround(tree, id).filter((f) => folded.has(f));
      if (around.length === 0) return;
      const next = new Set(folded);
      for (const f of around) next.delete(f);
      setFolded(next);
    },
    [folded, setFolded, tree],
  );

  /** Every change goes through here: one history entry (or the top one
   * replaced, for a field typed into), and the delete notice closes, so its
   * Hoàn tác is always the top of the stack (R2.11). */
  const apply = useCallback(
    (next: WorkflowTree, text: string | null, tag: string | null = null) => {
      setHist((h) => commit(h, next, tag));
      notification.destroy(DELETED_KEY);
      if (text) announce(text);
    },
    [notification, announce],
  );

  const doUndo = useCallback(() => {
    notification.destroy(DELETED_KEY);
    setHist((h) => undo(h));
    setEpoch((e) => e + 1);
    announce(bt("announce.undo"));
  }, [notification, announce]);

  const doRedo = useCallback(() => {
    notification.destroy(DELETED_KEY);
    setHist((h) => redo(h));
    setEpoch((e) => e + 1);
    announce(bt("announce.redo"));
  }, [notification, announce]);

  const refuse = useCallback(
    (reason: Refusal) => {
      void message.error(
        reason === "into_itself" || reason === "unknown_type"
          ? bt(`refused.${reason}`)
          : bt("refused.other"),
      );
    },
    [message],
  );

  /** A deletion: announced, and undone from the notice (R2.10, R2.11). */
  const deleted = useCallback(
    (out: Extract<Outcome, { ok: true }>, lane: LaneRef) => {
      const names = out.removed
        .map((n) => `«${stepName(n, catalogue)}»`)
        .join(", ");
      apply(
        out.tree,
        bt("announce.deleted", {
          names,
          lane: laneName(tree, catalogue, lane),
        }),
      );
      notification.open({
        key: DELETED_KEY,
        message: bt("deleted.title", { names }),
        duration: 10,
        actions: (
          <Button type="primary" size="small" onClick={doUndo}>
            {bt("deleted.undo")}
          </Button>
        ),
      });
    },
    [apply, catalogue, doUndo, notification, tree],
  );

  const insertNew = useCallback(
    (type: string, slot: Slot) => {
      const spec = catalogue.get(type);
      if (!spec) return;
      const node = toStepNode(newStep(spec, treeIds(tree)), catalogue);
      const out = insertStep(tree, slot, node);
      if (!out.ok) return refuse(out.reason);
      apply(
        out.tree,
        bt("announce.added", {
          name: stepName(node, catalogue),
          lane: laneName(out.tree, catalogue, slot.lane),
          n: slot.index + 1,
        }),
      );
      focusStop(node.id);
    },
    [apply, catalogue, focusStop, refuse, tree],
  );

  const move = useCallback(
    (id: string, slot: Slot) => {
      const out = moveStep(tree, id, slot);
      if (!out.ok) return refuse(out.reason);
      if (out.tree === tree) return;
      const at = locate(out.tree, id)!;
      apply(
        out.tree,
        bt("announce.moved", {
          name: stepName(at.node, catalogue),
          lane: laneName(out.tree, catalogue, at.lane),
          n: at.index + 1,
        }),
      );
      focusStop(id);
    },
    [apply, catalogue, focusStop, refuse, tree],
  );

  const remove = useCallback(
    (id: string) => {
      const at = locate(tree, id);
      const out = deleteStep(tree, id);
      if (!out.ok || !at) return refuse(out.ok ? "not_found" : out.reason);
      deleted(out, at.lane);
      const lane =
        at.lane.parent === null
          ? out.tree.steps
          : locate(out.tree, at.lane.parent)?.node.lanes.find(
              (l) => l.port === at.lane.port,
            )?.steps;
      const next =
        lane?.[at.index]?.id ??
        lane?.[at.index - 1]?.id ??
        (lane && lane.length === 0 ? emptyLaneStop(at.lane) : at.lane.parent);
      if (next) focusStop(next);
    },
    [deleted, focusStop, refuse, tree],
  );

  /** Remove a lane: with steps, a deletion with its Hoàn tác notice (R2.11);
   * empty, a change announced. */
  const removeLaneOf = useCallback(
    (id: string, port: string) => {
      const node = locate(tree, id)?.node;
      const lane = node?.lanes.find((l) => l.port === port);
      const out = removeLane(tree, id, port);
      if (!out.ok) return refuse(out.reason);
      if (!node || !lane) return;
      if (out.removed.length > 0) deleted(out, { parent: id, port });
      else
        apply(
          out.tree,
          bt("announce.laneRemoved", {
            lane: laneLabel(lane),
            name: stepName(node, catalogue),
          }),
        );
    },
    [apply, catalogue, deleted, refuse, tree],
  );

  const addLaneOf = useCallback(
    (id: string, name: string): Refusal | null => {
      const out = addLane(tree, id, name, catalogue);
      if (!out.ok) return out.reason;
      const before = new Set(locate(tree, id)!.node.lanes.map((l) => l.port));
      const node = locate(out.tree, id)!.node;
      const lane = node.lanes.find((l) => !before.has(l.port));
      apply(
        out.tree,
        bt("announce.laneAdded", {
          lane: lane ? laneLabel(lane) : name,
          name: stepName(node, catalogue),
        }),
      );
      return null;
    },
    [apply, catalogue, tree],
  );

  const onMenu = useCallback(
    (id: string, key: MenuKey) => {
      const at = locate(tree, id);
      if (!at) return;
      if (key.startsWith("addPort:")) {
        const refusal = addLaneOf(id, key.slice("addPort:".length));
        if (refusal) refuse(refusal);
        return;
      }
      if (key.startsWith("removePort:")) {
        removeLaneOf(id, key.slice("removePort:".length));
        return;
      }
      switch (key) {
        case "addBefore":
          setPicker({ lane: at.lane, index: at.index });
          break;
        case "addAfter":
          setPicker({ lane: at.lane, index: at.index + 1 });
          break;
        case "move":
          setMoving(id);
          break;
        case "addLane":
          setLaneFor({ id, mode: "add" });
          break;
        case "removeLane":
          setLaneFor({ id, mode: "remove" });
          break;
        case "fold":
        case "unfold":
          toggleFrame(id);
          break;
        case "delete":
          remove(id);
          break;
        case "copyRef": {
          const ref = `steps.${id}`;
          void navigator.clipboard?.writeText(ref);
          void message.success(bt("copied", { ref }));
          break;
        }
      }
    },
    [addLaneOf, message, refuse, remove, removeLaneOf, toggleFrame, tree],
  );

  const onLaneMenu = useCallback(
    (head: CanvasLaneHead, key: MenuKey) => {
      if (key === "removeBranch") removeLaneOf(head.parent, head.port);
    },
    [removeLaneOf],
  );
  const laneMenus = useCallback((head: CanvasLaneHead): MenuEntry[] => {
    const lane = locate(treeRef.current, head.parent)?.node.lanes.find(
      (l) => l.port === head.port,
    );
    return lane ? laneMenu(lane) : [];
  }, []);

  const onOnError = useCallback(
    (id: string, value: OnError) => {
      const at = locate(tree, id);
      const out = setOnError(tree, id, value);
      if (!out.ok || !at) return;
      if (out.removed.length > 0)
        deleted(out, { parent: id, port: "error_lane" });
      else apply(out.tree, null);
    },
    [apply, deleted, tree],
  );

  // Ctrl+K "Đi tới Bước", from anywhere on the page; never mid-composition.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.isComposing) return;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setGotoOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  /** Keys while focus is on the canvas only (R2.5, R2.7, R2.8). */
  const onCanvasKey = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.nativeEvent.isComposing || isEditable(event.target)) return;
    const ctrl = event.ctrlKey || event.metaKey;
    const key = event.key.toLowerCase();
    if (ctrl && (key === "z" || key === "y")) {
      event.preventDefault();
      if (key === "y" || event.shiftKey) doRedo();
      else doUndo();
      return;
    }
    const stop =
      event.target instanceof HTMLElement
        ? (event.target.closest<HTMLElement>("[data-stop]")?.dataset.stop ??
          null)
        : null;
    if (stop === null) return;
    const direction = ARROWS[event.key];
    if (direction && !ctrl && !event.altKey && !event.shiftKey) {
      event.preventDefault();
      event.stopPropagation();
      const next = navigate(tree, stop, direction, folded);
      if (next) focusStop(next);
      return;
    }
    const isStep = locate(tree, stop) !== null;
    if (
      isStep &&
      ((event.key === "F10" && event.shiftKey) || event.key === "ContextMenu")
    ) {
      event.preventDefault();
      setOpenMenu(stop);
      return;
    }
    if (isStep && event.key === "Delete") {
      event.preventDefault();
      if (locate(tree, stop)?.node.known) remove(stop);
      else refuse("unknown_type");
    }
  };

  const shapes = useMemo(
    () => (showCanvas ? layoutWorkflow(tree, METRICS, folded) : null),
    [showCanvas, tree, folded],
  );
  const issues = useMemo(
    () => issuesOf(tree, autosave.warnings),
    [tree, autosave.warnings],
  );
  const views = useMemo(() => {
    const out = new Map<string, ReturnType<typeof cardView>>();
    walk(tree, (node) => out.set(node.id, cardView(node, catalogue)));
    return out;
  }, [tree, catalogue]);
  const laneLabels = useMemo(() => {
    const out = new Map<string, string>();
    walk(tree, (node) => {
      for (const lane of node.lanes)
        out.set(`head:${node.id}:${lane.port}`, laneLabel(lane));
    });
    return out;
  }, [tree]);
  const slotLabels = useMemo(
    () =>
      new Map(
        (shapes?.slots ?? []).map((s) => [s.id, slotLabel(s, tree, catalogue)]),
      ),
    [shapes, tree, catalogue],
  );
  const menus = useCallback(
    (id: string): MenuEntry[] => {
      const node = locate(treeRef.current, id)?.node;
      return node ? stepMenu(node, catalogue, folded.has(id)) : [];
    },
    [catalogue, folded],
  );
  const slotOf = (id: string | null): CanvasSlot | undefined =>
    id === null ? undefined : shapes?.slots.find((s) => s.id === id);

  const acceptSlot = useCallback(
    (slot: CanvasSlot) =>
      drag?.kind !== "move" ||
      !isInside(treeRef.current, drag.id, {
        parent: slot.parent,
        port: slot.port,
      }),
    [drag],
  );
  const onDrop = useCallback(
    (slot: CanvasSlot | null) => {
      const current = drag;
      setDrag(null);
      if (!slot || !current) return;
      const target = {
        lane: { parent: slot.parent, port: slot.port },
        index: slot.index,
      };
      if (current.kind === "new") insertNew(current.type, target);
      else move(current.id, target);
    },
    [drag, insertNew, move],
  );

  const configNode = configFor ? (locate(tree, configFor)?.node ?? null) : null;
  const saveText =
    autosave.state === "saving"
      ? bt("save.saving")
      : autosave.state === "saved"
        ? bt("save.saved")
        : autosave.state === "failed"
          ? bt("save.failed")
          : autosave.state === "conflict"
            ? bt("conflict.title")
            : bt("save.idle");

  const reloadLatest = async () => {
    try {
      const doc = await autosave.reload();
      setHist(history(toTree(doc, catalogue)));
      notification.destroy(DELETED_KEY);
      setEpoch((e) => e + 1);
    } catch (caught) {
      void message.error(errorMessage(caught));
    }
  };

  const phoneMenu = !wide && openMenu !== null ? openMenu : null;
  const phoneMenuItems: MenuEntry[] | null = phoneMenu
    ? phoneMenu.startsWith("lane:")
      ? [{ key: "addLane" as MenuKey, label: bt("menu.addStep") }]
      : menus(phoneMenu)
    : null;

  return (
    <div className="min-w-0">
      <PageHeader
        icon={<ApartmentOutlined />}
        title={bt("page.title")}
        actions={
          <Flex wrap gap="small" align="center">
            <span role="status" aria-live="polite">
              <Typography.Text>{saveText}</Typography.Text>
            </span>
            <Tooltip title={bt("undo")}>
              <Button
                icon={<UndoOutlined aria-hidden />}
                aria-label={bt("undo")}
                disabled={hist.past.length === 0}
                onClick={doUndo}
              />
            </Tooltip>
            <Tooltip title={bt("redo")}>
              <Button
                icon={<RedoOutlined aria-hidden />}
                aria-label={bt("redo")}
                disabled={hist.future.length === 0}
                onClick={doRedo}
              />
            </Tooltip>
            <Button
              icon={<SearchOutlined aria-hidden />}
              onClick={() => setGotoOpen(true)}
            >
              {bt("goto.title")} ({bt("goto.hint")})
            </Button>
            {wide && (
              <Segmented
                aria-label={bt("view.label")}
                value={view}
                onChange={(value) => setView(value as "canvas" | "outline")}
                options={[
                  { value: "canvas", label: bt("view.canvas") },
                  { value: "outline", label: bt("view.outline") },
                ]}
              />
            )}
          </Flex>
        }
      />
      <Flex vertical gap="middle">
        {autosave.state === "conflict" && (
          <Alert
            type="warning"
            showIcon
            message={bt("conflict.title")}
            description={bt("conflict.description")}
            action={
              <Button type="primary" onClick={() => void reloadLatest()}>
                {bt("conflict.reload")}
              </Button>
            }
          />
        )}
        {autosave.state === "failed" && (
          <Alert
            type="error"
            showIcon
            message={bt("save.failed")}
            description={failureText(autosave.error)}
            action={
              <Button onClick={autosave.retry}>{bt("save.retry")}</Button>
            }
          />
        )}
        <Typography.Text>{bt("keys.hint")}</Typography.Text>
        <div aria-live="polite" className="sr-only" data-testid="builder-live">
          {live.text}
        </div>
        {showCanvas && shapes ? (
          <Flex gap="middle" className="min-w-0">
            {large && (
              <aside className="w-64 shrink-0" aria-label={bt("palette.side")}>
                <Typography.Title level={5}>
                  {bt("palette.side")}
                </Typography.Title>
                <StepPalette
                  types={types}
                  mode="drag"
                  onDragStart={(type) => setDrag({ kind: "new", type })}
                />
              </aside>
            )}
            <div className="h-[70vh] min-w-0 flex-1" onKeyDown={onCanvasKey}>
              <WorkflowCanvas
                shapes={shapes}
                views={views}
                laneLabels={laneLabels}
                laneMenus={laneMenus}
                onLaneMenu={onLaneMenu}
                issues={issues}
                onToggleFrame={toggleFrame}
                slotLabels={slotLabels}
                menus={menus}
                activeStop={activeStop}
                focusRequest={focusRequest}
                onStopFocus={setActive}
                onOpenStep={setConfigFor}
                openMenu={openMenu}
                onOpenMenu={setOpenMenu}
                onMenu={onMenu}
                openSlot={openSlot}
                onOpenSlot={setOpenSlot}
                palette={
                  <StepPalette
                    types={types}
                    mode="pick"
                    onPick={(type) => {
                      const slot = slotOf(openSlot);
                      setOpenSlot(null);
                      if (slot) {
                        insertNew(type, {
                          lane: { parent: slot.parent, port: slot.port },
                          index: slot.index,
                        });
                      }
                    }}
                  />
                }
                dragging={drag !== null}
                acceptSlot={acceptSlot}
                onDrop={onDrop}
                onStartMove={(id) => setDrag({ kind: "move", id })}
              />
            </div>
          </Flex>
        ) : (
          <WorkflowOutline
            tree={tree}
            catalogue={catalogue}
            folded={folded}
            onFoldedChange={setFolded}
            activeKey={outlineKey}
            onActiveChange={setOutlineKey}
            openMenu={openMenu}
            menuInDropdown={wide}
            onOpenMenu={setOpenMenu}
            onMenu={onMenu}
            onAddToLane={(lane) => setPicker({ lane, index: 0 })}
            onOpenStep={setConfigFor}
            onDelete={remove}
            onUndo={doUndo}
            onRedo={doRedo}
          />
        )}
      </Flex>

      <ConfigDrawer
        node={configNode}
        catalogue={catalogue}
        epoch={epoch}
        placement={wide ? "right" : "bottom"}
        onClose={() => setConfigFor(null)}
        afterClose={() => {
          if (configFor === null && active && showCanvas) focusStop(active);
        }}
        onFields={(fields, tag) => {
          if (!configFor) return;
          const out = updateStepFields(tree, configFor, fields, catalogue);
          if (out.ok) apply(out.tree, null, tag);
        }}
        onOnError={(value) => configFor && onOnError(configFor, value)}
      />

      <Drawer
        open={phoneMenu !== null}
        placement="bottom"
        size="default"
        title={bt("card.menu")}
        onClose={() => setOpenMenu(null)}
      >
        <Menu
          items={(phoneMenuItems ?? []).map(({ key, label, danger }) => ({
            key,
            label,
            danger,
          }))}
          onClick={({ key }) => {
            const target = phoneMenu;
            setOpenMenu(null);
            if (!target) return;
            const lane = parseEmptyLaneStop(target);
            if (lane) setPicker({ lane, index: 0 });
            else onMenu(target, key as MenuKey);
          }}
        />
      </Drawer>

      <Modal
        open={picker !== null}
        title={bt("palette.title")}
        footer={null}
        onCancel={() => setPicker(null)}
        destroyOnHidden
      >
        <StepPalette
          types={types}
          mode="pick"
          onPick={(type) => {
            const slot = picker;
            setPicker(null);
            if (slot) insertNew(type, slot);
          }}
        />
      </Modal>

      <MoveModal
        tree={tree}
        catalogue={catalogue}
        moving={moving}
        onCancel={() => setMoving(null)}
        onMove={(slot) => {
          const id = moving;
          setMoving(null);
          if (id) move(id, slot);
        }}
      />

      <LaneModal
        tree={tree}
        catalogue={catalogue}
        target={laneFor}
        onCancel={() => setLaneFor(null)}
        onAdd={(id, name) => {
          const refusal = addLaneOf(id, name);
          if (refusal === null) setLaneFor(null);
          return refusal;
        }}
        onRemove={(id, port) => {
          setLaneFor(null);
          removeLaneOf(id, port);
        }}
      />

      <GotoModal
        open={gotoOpen}
        tree={tree}
        catalogue={catalogue}
        onClose={() => setGotoOpen(false)}
        onGo={(id) => {
          setGotoOpen(false);
          reveal(id);
          if (showCanvas) focusStop(id);
          else setOutlineKey(id);
        }}
      />
    </div>
  );
}

/** "Lưu thất bại" with the server's sentence and, for a document the server
 * refused (422), the JSON pointer it names (ticket 02 MEDIUM (a)). */
function failureText(error: unknown): string {
  const sentence = errorMessage(error);
  const pointers =
    error && typeof error === "object" && "body" in error
      ? (
          (error as { body: { errors?: { pointer?: string }[] } }).body
            .errors ?? []
        )
          .map((e) => e.pointer)
          .filter(Boolean)
      : [];
  return pointers.length > 0
    ? `${sentence} (${pointers.join(", ")})`
    : sentence;
}

function toTreeSelect(targets: MoveTarget[]): object[] {
  return targets.map((t) => ({
    title: t.title,
    value: t.value,
    selectable: t.selectable,
    children: toTreeSelect(t.children),
  }));
}

function MoveModal({
  tree,
  catalogue,
  moving,
  onCancel,
  onMove,
}: {
  tree: WorkflowTree;
  catalogue: Catalogue;
  moving: string | null;
  onCancel: () => void;
  onMove: (slot: Slot) => void;
}) {
  const [value, setValue] = useState<string | null>(null);
  const node = moving ? locate(tree, moving)?.node : undefined;
  const data = useMemo(
    () => (moving ? toTreeSelect(moveTargets(tree, catalogue, moving)) : []),
    [tree, catalogue, moving],
  );
  return (
    <Modal
      open={moving !== null}
      title={node ? bt("move.title", { name: stepName(node, catalogue) }) : ""}
      okText={bt("move.ok")}
      cancelText={bt("cancel")}
      okButtonProps={{ disabled: value === null }}
      onCancel={() => {
        setValue(null);
        onCancel();
      }}
      onOk={() => {
        if (value) onMove(parseSlotValue(value));
        setValue(null);
      }}
      destroyOnHidden
    >
      <Form layout="vertical">
        <Form.Item label={bt("move.target")} htmlFor="move-target">
          <TreeSelect
            id="move-target"
            className="w-full"
            treeData={data}
            treeDefaultExpandAll
            // Typing narrows the targets: the keyboard's way to a slot deep
            // in a frame or a lane (R2.5).
            showSearch
            treeNodeFilterProp="title"
            value={value ?? undefined}
            onChange={(v: string) => setValue(v)}
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}

function LaneModal({
  tree,
  catalogue,
  target,
  onCancel,
  onAdd,
  onRemove,
}: {
  tree: WorkflowTree;
  catalogue: Catalogue;
  target: { id: string; mode: "add" | "remove" } | null;
  onCancel: () => void;
  onAdd: (id: string, name: string) => Refusal | null;
  onRemove: (id: string, port: string) => void;
}) {
  const [value, setValue] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const node: StepNode | undefined = target
    ? locate(tree, target.id)?.node
    : undefined;
  const close = () => {
    setValue("");
    setProblem(null);
    onCancel();
  };
  if (!target || !node) return null;
  const name = stepName(node, catalogue);
  // A keyed type's entries; an optional fixed lane has menu entries of its
  // own ("Thêm làn «…»", "Bỏ làn «…»").
  const removable = node.lanes.filter((l) => l.kind === "keyed");
  return (
    <Modal
      open
      title={bt(target.mode === "add" ? "addLane.title" : "removeLane.title", {
        name,
      })}
      okText={bt(target.mode === "add" ? "addLane.ok" : "removeLane.ok")}
      okButtonProps={{
        danger: target.mode === "remove",
        disabled: value === "",
      }}
      cancelText={bt("cancel")}
      onCancel={close}
      onOk={() => {
        if (target.mode === "remove") {
          onRemove(target.id, value);
          close();
          return;
        }
        const refusal = onAdd(target.id, value);
        if (refusal === "lane_exists") setProblem(bt("addLane.exists"));
        else if (refusal) setProblem(bt("addLane.invalid"));
        else close();
      }}
      destroyOnHidden
    >
      <Form layout="vertical">
        {target.mode === "add" && (
          <Form.Item
            label={bt("addLane.key")}
            htmlFor="lane-key"
            validateStatus={problem ? "error" : undefined}
            help={problem ?? undefined}
          >
            <Input
              id="lane-key"
              value={value}
              onChange={(e) => setValue(e.target.value)}
            />
          </Form.Item>
        )}
        {target.mode === "remove" && (
          <Form.Item label={bt("removeLane.lane")} htmlFor="lane-remove">
            <Select
              id="lane-remove"
              value={value || undefined}
              onChange={(v: string) => setValue(v)}
              options={removable.map((l) => ({
                value: l.port,
                label: laneLabel(l),
              }))}
            />
          </Form.Item>
        )}
      </Form>
    </Modal>
  );
}

/** Ctrl+K "Đi tới Bước": a search by name without diacritics, ↑↓ through
 * the matches, Enter goes; every key ignored mid-composition (R2.8). */
function GotoModal({
  open,
  tree,
  catalogue,
  onClose,
  onGo,
}: {
  open: boolean;
  tree: WorkflowTree;
  catalogue: Catalogue;
  onClose: () => void;
  onGo: (id: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);
  const all = useMemo(() => {
    const out: { id: string; name: string }[] = [];
    walk(tree, (node) =>
      out.push({ id: node.id, name: stepName(node, catalogue) }),
    );
    return out;
  }, [tree, catalogue]);
  const wanted = fold(query.trim());
  const matches = all
    .filter((s) => wanted === "" || fold(s.name).includes(wanted))
    .slice(0, 50);
  const go = (id: string | undefined) => {
    setQuery("");
    setIndex(0);
    if (id) onGo(id);
  };
  return (
    <Modal
      open={open}
      title={bt("goto.title")}
      footer={null}
      onCancel={() => {
        setQuery("");
        onClose();
      }}
      destroyOnHidden
    >
      <Flex vertical gap="small">
        <Input
          autoFocus
          aria-label={bt("goto.search")}
          placeholder={bt("goto.search")}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setIndex(0);
          }}
          onKeyDown={(event) => {
            if (event.nativeEvent.isComposing) return;
            if (event.key === "ArrowDown") {
              event.preventDefault();
              setIndex((i) => Math.min(i + 1, matches.length - 1));
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              setIndex((i) => Math.max(i - 1, 0));
            } else if (event.key === "Enter") {
              event.preventDefault();
              go(matches[index]?.id);
            }
          }}
        />
        {matches.length === 0 ? (
          <Typography.Text>{bt("goto.empty")}</Typography.Text>
        ) : (
          <Flex vertical role="list">
            {matches.map((s, i) => (
              <Button
                key={s.id}
                role="listitem"
                type={i === index ? "primary" : "text"}
                ghost={i === index}
                className="justify-start"
                onClick={() => go(s.id)}
              >
                <Typography.Text ellipsis style={{ color: "inherit" }}>
                  {s.name}
                </Typography.Text>
              </Button>
            ))}
          </Flex>
        )}
      </Flex>
    </Modal>
  );
}

type Loaded =
  | { status: "loading" }
  | { status: "error"; error: unknown }
  | { status: "noDraft" }
  | { status: "notWorkflow" }
  | {
      status: "ready";
      catalogue: Catalogue;
      types: StepTypeSpec[];
      draft: StudioDraft;
    };

/**
 * `/studio/workflows/[id]/builder`: the artifact (only a `workflow` is built
 * here; any other kind reads as not found), the step-type catalogue and the
 * draft. A workflow with no draft shows "Quy trình chưa có bản Nháp" and
 * calls no write route (ticket 03 replaces it).
 */
export function WorkflowBuilder({
  artifactId,
  saveDelayMs = 2000,
  viewerId = null,
}: {
  artifactId: string;
  saveDelayMs?: number;
  /** The signed-in user, whose folded frames the page keeps (R1.7). */
  viewerId?: string | null;
}) {
  const [loaded, setLoaded] = useState<Loaded>({ status: "loading" });
  const load = useCallback(async () => {
    setLoaded({ status: "loading" });
    try {
      const client = apiClient();
      const artifact = await client.getStudioArtifact(artifactId);
      if (artifact.kind !== "workflow") {
        setLoaded({ status: "notWorkflow" });
        return;
      }
      const [catalogue, draft] = await Promise.all([
        client.getStudioNodeTypes(),
        client.getStudioDraft(artifactId).catch((error: unknown) => {
          if (errorCode(error) === "not_found") return null;
          throw error;
        }),
      ]);
      if (draft === null) {
        setLoaded({ status: "noDraft" });
        return;
      }
      const types: StepTypeSpec[] = catalogue.types;
      setLoaded({
        status: "ready",
        catalogue: catalogueOf(types),
        types,
        draft,
      });
    } catch (error) {
      setLoaded({ status: "error", error });
    }
  }, [artifactId]);

  useEffect(() => {
    void load();
  }, [load]);

  switch (loaded.status) {
    case "loading":
      return <Skeleton active paragraph={{ rows: 8 }} />;
    case "error":
      return <LoadError error={loaded.error} onRetry={() => void load()} />;
    case "notWorkflow":
      return <Result status="404" title={bt("page.notWorkflow")} />;
    case "noDraft":
      return (
        <Result
          status="info"
          title={bt("page.noDraft.title")}
          subTitle={bt("page.noDraft.description")}
        />
      );
    case "ready":
      return (
        <Editor
          artifactId={artifactId}
          catalogue={loaded.catalogue}
          types={loaded.types}
          draft={loaded.draft}
          saveDelayMs={saveDelayMs}
          viewerId={viewerId}
        />
      );
  }
}
