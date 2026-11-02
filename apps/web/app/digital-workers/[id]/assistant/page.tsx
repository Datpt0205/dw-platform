"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Flex,
  Input,
  List,
  Row,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import {
  ExperimentOutlined,
  RobotOutlined,
  RollbackOutlined,
  SaveOutlined,
  SendOutlined,
} from "@ant-design/icons";
import type {
  AssistantAnswer,
  AssistantTurn,
  DigitalWorker,
  WorkflowDraft,
} from "@dw/api-client";
import { PageHeader, RegionState } from "@dw/ui";
import { LoadError } from "../../../../components/load-error";
import { WorkflowTree } from "../../../../components/digital-workers/workflow-tree";
import {
  SimulationResult,
  WorkflowDiff,
  WorkflowProblems,
} from "../../../../components/digital-workers/workflow-review";
import { errorMessage, reasonCode } from "../../../../lib/error-message";
import { useIdempotencyKeys } from "../../../../lib/idempotency";
import { apiClient } from "../../../../lib/session";
import { useCachedResource } from "../../../../lib/use-cached-resource";

/** The API keeps no conversation; the page sends the last turns back (R1.4). */
const MAX_HISTORY = 10;

type Turn = { id: number } & (
  | { role: "user"; text: string }
  | { role: "assistant"; answer: AssistantAnswer }
);

const DRAFT_STATE: Record<
  WorkflowDraft["state"],
  { label: string; color: string }
> = {
  draft: { label: "Bản nháp", color: "default" },
  submitted: { label: "Chờ duyệt", color: "warning" },
};

/** Why a decided draft came back (wf-ai R6.6). */
const RETURNED: Record<string, string> = {
  base_changed:
    "Quy trình đang chạy đã đổi từ khi gửi duyệt nên bản này chưa được phát hành. Lưu lại một đề xuất mới.",
  content_changed:
    "Nội dung bản nháp đã đổi sau khi gửi duyệt nên chưa được phát hành. Chạy mô phỏng rồi gửi duyệt lại.",
};

function asHistory(turns: Turn[]): AssistantTurn[] {
  return turns
    .map((turn): AssistantTurn =>
      turn.role === "user"
        ? { role: "user", text: turn.text }
        : {
            role: "assistant",
            text:
              turn.answer.kind === "question"
                ? (turn.answer.question ?? "")
                : turn.answer.plan.join("\n"),
          },
    )
    .slice(-MAX_HISTORY);
}

/**
 * The workflow assistant of one DW (wf-ai R7.1): the owner says what to
 * change, the assistant asks back or proposes a step tree with its plan, its
 * diff against the pinned workflow and the platform's problems with it. A
 * proposal without problems is saved as the DW's draft, simulated, and sent
 * to a second person to publish; each button says why it is not yet open.
 * The server decides all of it anyway.
 */
export default function WorkflowAssistantPage() {
  const { id } = useParams<{ id: string }>();
  const worker = useCachedResource<DigitalWorker>(
    `digital-worker:${id}`,
    useCallback(() => apiClient().getDigitalWorker(id), [id]),
  );
  const breadcrumb = [
    { title: <Link href="/digital-workers">Digital Worker</Link> },
    {
      title: (
        <Link href={`/digital-workers/${id}`}>
          {worker.data?.name ?? "Digital Worker"}
        </Link>
      ),
    },
  ];
  if (worker.error != null) {
    return (
      <div className="mx-auto max-w-6xl">
        <PageHeader breadcrumb={breadcrumb} title="Trợ lý quy trình" />
        <LoadError error={worker.error} onRetry={worker.reload} />
      </div>
    );
  }
  if (worker.data === null) {
    return (
      <div className="mx-auto max-w-6xl">
        <PageHeader breadcrumb={breadcrumb} title="Trợ lý quy trình" />
        <RegionState kind="loading" />
      </div>
    );
  }
  return <Assistant worker={worker.data} breadcrumb={breadcrumb} />;
}

function Assistant({
  worker,
  breadcrumb,
}: {
  worker: DigitalWorker;
  breadcrumb: { title: ReactNode }[];
}) {
  const { message } = App.useApp();
  const { keyFor, settled } = useIdempotencyKeys();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [instruction, setInstruction] = useState("");
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // undefined while it loads, null when the DW has none.
  const [draft, setDraft] = useState<WorkflowDraft | null | undefined>(
    undefined,
  );
  const [notOwner, setNotOwner] = useState(false);
  const [busy, setBusy] = useState<
    "save" | "simulate" | "submit" | "withdraw" | null
  >(null);

  useEffect(() => {
    let cancelled = false;
    apiClient()
      .getWorkflowDraft(worker.id)
      .then((found) => !cancelled && setDraft(found))
      .catch((e: unknown) => {
        if (cancelled) return;
        const reason = reasonCode(e);
        if (reason === "draft_not_found") setDraft(null);
        else if (reason === "not_dw_owner") {
          setNotOwner(true);
          setDraft(null);
        } else {
          setDraft(null);
          setError(errorMessage(e));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [worker.id]);

  const proposal = [...turns]
    .reverse()
    .map((turn) => (turn.role === "assistant" ? turn.answer : null))
    .find((answer) => answer?.kind === "proposal");

  async function ask() {
    const text = instruction.trim();
    if (!text) return;
    setAsking(true);
    try {
      const answer = await apiClient().askWorkflowAssistant(worker.id, {
        instruction: text,
        history: asHistory(turns),
      });
      setTurns((current) => [
        ...current,
        { id: current.length, role: "user", text },
        { id: current.length + 1, role: "assistant", answer },
      ]);
      setInstruction("");
      setError(null);
    } catch (e) {
      if (reasonCode(e) === "not_dw_owner") setNotOwner(true);
      setError(errorMessage(e));
    } finally {
      setAsking(false);
    }
  }

  async function act(
    kind: "save" | "simulate" | "submit" | "withdraw",
    run: () => Promise<WorkflowDraft>,
    done: string,
  ) {
    setBusy(kind);
    try {
      setDraft(await run());
      settled(kind);
      setError(null);
      message.success(done);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  const client = apiClient();
  const save = () => {
    const steps = proposal?.steps ?? [];
    return act(
      "save",
      () => client.saveWorkflowDraft(worker.id, steps, keyFor("save", steps)),
      "Đã lưu bản nháp",
    );
  };
  const simulate = () =>
    act(
      "simulate",
      async () => {
        const simulation = await client.simulateWorkflowDraft(
          worker.id,
          keyFor("simulate", draft?.content_sha256 ?? null),
        );
        return { ...(draft as WorkflowDraft), simulation };
      },
      "Đã chạy mô phỏng",
    );
  const submit = () =>
    act(
      "submit",
      () =>
        client.submitWorkflowDraft(
          worker.id,
          keyFor("submit", draft?.content_sha256 ?? null),
        ),
      "Đã gửi duyệt",
    );
  const withdraw = () =>
    act(
      "withdraw",
      () =>
        client.withdrawWorkflowDraft(
          worker.id,
          keyFor("withdraw", draft?.approval_id ?? null),
        ),
      "Đã rút lại bản gửi duyệt",
    );

  const submitted = draft?.state === "submitted";
  const saveReason = !proposal
    ? "Chưa có đề xuất nào để lưu."
    : !proposal.publishable
      ? "Đề xuất còn lỗi nên chưa lưu được; nhờ trợ lý sửa tiếp."
      : submitted
        ? "Bản nháp đang chờ duyệt; rút lại để thay bằng đề xuất này."
        : null;
  const simulateReason = !draft
    ? "Lưu bản nháp trước khi chạy mô phỏng."
    : submitted
      ? "Bản nháp đang chờ duyệt; rút lại để chạy lại."
      : null;
  const simulatedThis =
    draft?.simulation != null &&
    draft.simulation.outcome === "passed" &&
    draft.simulation.content_sha256 === draft.content_sha256;
  const submitReason = !draft
    ? "Lưu bản nháp trước khi gửi duyệt."
    : submitted
      ? "Bản nháp đã được gửi duyệt."
      : !simulatedThis
        ? "Chạy mô phỏng bản này và thấy qua trước khi gửi duyệt."
        : null;

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        breadcrumb={breadcrumb}
        icon={<RobotOutlined />}
        title="Trợ lý quy trình"
        subtitle={`Nói điều bạn muốn đổi trong quy trình của ${worker.name}. Trợ lý chỉ đổi các bước, từ những công cụ và prompt quy trình đã dùng; bản sửa chỉ chạy thật khi một người khác duyệt.`}
      />
      <Flex vertical gap="middle">
        {error !== null && <Alert type="error" showIcon title={error} />}
        {notOwner && (
          <Alert
            type="info"
            showIcon
            title="Chỉ Business Owner hay Technical Owner của Digital Worker này dùng trợ lý và sửa bản nháp."
          />
        )}
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={10}>
            <Card title="Trao đổi">
              <Flex vertical gap="middle">
                <Conversation turns={turns} />
                <label htmlFor="assistant-instruction">
                  <Typography.Text strong>Bạn muốn đổi gì?</Typography.Text>
                </label>
                <Input.TextArea
                  id="assistant-instruction"
                  rows={3}
                  maxLength={4000}
                  showCount
                  value={instruction}
                  disabled={notOwner}
                  onChange={(event) => setInstruction(event.target.value)}
                  placeholder="Ví dụ: chờ thêm một ngày trước khi nhắc lại"
                />
                <Flex>
                  <Button
                    type="primary"
                    icon={<SendOutlined aria-hidden />}
                    loading={asking}
                    disabled={notOwner || !instruction.trim()}
                    onClick={() => void ask()}
                  >
                    Gửi cho trợ lý
                  </Button>
                </Flex>
              </Flex>
            </Card>
          </Col>
          <Col xs={24} lg={14}>
            <Flex vertical gap="middle">
              <Card title="Đề xuất">
                {proposal ? (
                  <Flex vertical gap="middle">
                    <Plan plan={proposal.plan} />
                    <Typography.Text strong>Thay đổi</Typography.Text>
                    <WorkflowDiff changes={proposal.diff} />
                    <WorkflowProblems problems={proposal.problems} />
                    {proposal.outline.length > 0 && (
                      <>
                        <Typography.Text strong>
                          Quy trình đề xuất
                        </Typography.Text>
                        <WorkflowTree steps={proposal.outline} />
                      </>
                    )}
                    <Locked reason={saveReason}>
                      <Button
                        type="primary"
                        icon={<SaveOutlined aria-hidden />}
                        loading={busy === "save"}
                        disabled={saveReason !== null || busy !== null}
                        onClick={() => void save()}
                      >
                        Lưu bản nháp
                      </Button>
                    </Locked>
                  </Flex>
                ) : (
                  <Typography.Text>
                    Chưa có đề xuất. Trợ lý trả lời bằng một câu hỏi khi chưa
                    rõ, hay bằng một đề xuất gồm kế hoạch và các bước.
                  </Typography.Text>
                )}
              </Card>
              <DraftCard
                draft={draft}
                busy={busy}
                simulateReason={simulateReason}
                submitReason={submitReason}
                onSimulate={() => void simulate()}
                onSubmit={() => void submit()}
                onWithdraw={() => void withdraw()}
              />
            </Flex>
          </Col>
        </Row>
      </Flex>
    </div>
  );
}

function Conversation({ turns }: { turns: Turn[] }) {
  if (turns.length === 0) {
    return (
      <Typography.Text>
        Chưa có lượt nào. Lịch sử chỉ giữ trên trang này, tối đa {MAX_HISTORY}{" "}
        lượt gần nhất được gửi lại cho trợ lý.
      </Typography.Text>
    );
  }
  return (
    <List
      size="small"
      dataSource={turns}
      rowKey={(turn) => turn.id}
      renderItem={(turn) => (
        <List.Item>
          <Flex vertical gap={4} className="w-full">
            <Typography.Text strong>
              {turn.role === "user" ? "Bạn" : "Trợ lý"}
            </Typography.Text>
            {turn.role === "user" ? (
              <Typography.Paragraph className="m-0 whitespace-pre-wrap">
                {turn.text}
              </Typography.Paragraph>
            ) : turn.answer.kind === "question" ? (
              <Typography.Paragraph className="m-0 whitespace-pre-wrap">
                {turn.answer.question}
              </Typography.Paragraph>
            ) : (
              <Typography.Text>
                Đề xuất {turn.answer.diff.length} thay đổi
                {turn.answer.publishable
                  ? ", không lỗi."
                  : `, còn ${turn.answer.problems.length} lỗi.`}
              </Typography.Text>
            )}
          </Flex>
        </List.Item>
      )}
    />
  );
}

function Plan({ plan }: { plan: string[] }) {
  if (plan.length === 0) return null;
  return (
    <Flex vertical gap="small">
      <Typography.Text strong>Kế hoạch</Typography.Text>
      <ol className="m-0 pl-4">
        {plan.map((line, index) => (
          <li key={index}>{line}</li>
        ))}
      </ol>
    </Flex>
  );
}

/** A button that is not yet open, with the reason beside it and on hover. */
function Locked({
  reason,
  children,
}: {
  reason: string | null;
  children: ReactNode;
}) {
  if (reason === null) return <Flex>{children}</Flex>;
  return (
    <Flex wrap gap="small" align="center">
      <Tooltip title={reason}>
        <span className="inline-flex">{children}</span>
      </Tooltip>
      <Typography.Text>{reason}</Typography.Text>
    </Flex>
  );
}

function DraftCard({
  draft,
  busy,
  simulateReason,
  submitReason,
  onSimulate,
  onSubmit,
  onWithdraw,
}: {
  draft: WorkflowDraft | null | undefined;
  busy: string | null;
  simulateReason: string | null;
  submitReason: string | null;
  onSimulate: () => void;
  onSubmit: () => void;
  onWithdraw: () => void;
}) {
  if (draft === undefined) {
    return (
      <Card title="Bản nháp">
        <RegionState kind="loading" compact />
      </Card>
    );
  }
  const state = draft ? DRAFT_STATE[draft.state] : null;
  return (
    <Card
      title="Bản nháp"
      extra={state && <Tag color={state.color}>{state.label}</Tag>}
    >
      <Flex vertical gap="middle">
        {draft === null ? (
          <Typography.Text>
            Digital Worker này chưa có bản nháp. Lưu một đề xuất không lỗi để
            chạy mô phỏng và gửi duyệt.
          </Typography.Text>
        ) : (
          <>
            {draft.reason && RETURNED[draft.reason] && (
              <Alert type="warning" showIcon title={RETURNED[draft.reason]} />
            )}
            <Typography.Text>
              Mã nội dung{" "}
              <Typography.Text code>
                {draft.content_sha256.slice(0, 12)}
              </Typography.Text>
              , {draft.author_ids.length} người đã soạn. Không ai trong số họ
              duyệt được bản này.
            </Typography.Text>
            {draft.simulation ? (
              <Flex vertical gap="small">
                <Typography.Text strong>Mô phỏng gần nhất</Typography.Text>
                {draft.simulation.content_sha256 !== draft.content_sha256 && (
                  <Alert
                    type="warning"
                    showIcon
                    title="Kết quả này của một bản nháp trước; chạy lại cho bản hiện tại."
                  />
                )}
                <SimulationResult simulation={draft.simulation} />
              </Flex>
            ) : (
              <Typography.Text>Chưa chạy mô phỏng.</Typography.Text>
            )}
            {draft.state === "submitted" && (
              <Typography.Text>
                Đang chờ Validator hay Technical Owner duyệt ở trang{" "}
                <Link href="/approvals">Duyệt</Link>.
              </Typography.Text>
            )}
          </>
        )}
        <Flex wrap gap="small">
          <Locked reason={simulateReason}>
            <Button
              icon={<ExperimentOutlined aria-hidden />}
              loading={busy === "simulate"}
              disabled={simulateReason !== null || busy !== null}
              onClick={onSimulate}
            >
              Chạy mô phỏng
            </Button>
          </Locked>
          <Locked reason={submitReason}>
            <Button
              type="primary"
              icon={<SendOutlined aria-hidden />}
              loading={busy === "submit"}
              disabled={submitReason !== null || busy !== null}
              onClick={onSubmit}
            >
              Gửi duyệt
            </Button>
          </Locked>
          {draft?.state === "submitted" && (
            <Button
              icon={<RollbackOutlined aria-hidden />}
              loading={busy === "withdraw"}
              disabled={busy !== null}
              onClick={onWithdraw}
            >
              Rút lại
            </Button>
          )}
        </Flex>
      </Flex>
    </Card>
  );
}
