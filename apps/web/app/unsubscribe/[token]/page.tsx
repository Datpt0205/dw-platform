"use client";

import { Button, Card, Result, Spin } from "antd";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { API_BASE_URL } from "../../../lib/auth/config";

/**
 * The one-address opt-out page (ADR-0124 decision 5; compliance-pdpl R3.4).
 *
 * Public: whoever clicks has no account. Opening the page only checks the
 * link (`GET`), so a mailbox's link scanner opts nobody out; the button sends
 * the opt-out (`POST`), which holds at once for every message of the company.
 */
type State = "checking" | "ready" | "sending" | "done" | "invalid" | "failed";

export default function UnsubscribePage() {
  const { token } = useParams<{ token: string }>();
  const [state, setState] = useState<State>("checking");
  const url = `${API_BASE_URL}/api/v1/public/unsubscribe/${encodeURIComponent(token)}`;

  useEffect(() => {
    let live = true;
    fetch(url, { method: "GET", credentials: "omit" })
      .then((response) => {
        if (live)
          setState(
            response.ok
              ? "ready"
              : response.status === 404
                ? "invalid"
                : "failed",
          );
      })
      .catch(() => live && setState("failed"));
    return () => {
      live = false;
    };
  }, [url]);

  const confirm = () => {
    setState("sending");
    fetch(url, { method: "POST", credentials: "omit" })
      .then((response) =>
        setState(
          response.ok ? "done" : response.status === 404 ? "invalid" : "failed",
        ),
      )
      .catch(() => setState("failed"));
  };

  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <Card className="w-full max-w-lg">
        {state === "checking" && (
          <Spin tip="Đang kiểm tra liên kết…" fullscreen={false} />
        )}
        {(state === "ready" || state === "sending") && (
          <Result
            title="Hủy nhận thư"
            subTitle="Bạn sẽ không nhận thêm thư giới thiệu từ công ty này nữa."
            extra={
              <Button
                type="primary"
                loading={state === "sending"}
                onClick={confirm}
              >
                Xác nhận hủy nhận
              </Button>
            }
          />
        )}
        {state === "done" && (
          <Result
            status="success"
            title="Đã hủy nhận"
            subTitle="Từ giờ bạn không nhận thư giới thiệu từ công ty này nữa."
          />
        )}
        {state === "invalid" && (
          <Result
            status="404"
            title="Liên kết không còn dùng được"
            subTitle="Liên kết hủy nhận này sai hoặc đã hết hạn."
          />
        )}
        {state === "failed" && (
          <Result
            status="warning"
            title="Chưa hủy nhận được"
            subTitle="Có lỗi khi liên hệ máy chủ. Hãy thử lại sau."
          />
        )}
      </Card>
    </div>
  );
}
