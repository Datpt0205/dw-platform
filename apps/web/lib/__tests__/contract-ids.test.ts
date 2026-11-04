import { describe, expect, it } from "vitest";
import { approvalSchema } from "@dw/contracts";

// The server's ids are PostgreSQL `uuid` values, which accept any 8-4-4-4-12
// hex string, and some fixed ids the platform ships carry version nibble 0
// (dw_evals' graders use 00000000-0000-0000-0000-0000000000c1). zod 3's
// `.uuid()` accepted those; zod 4's `.uuid()` is RFC 9562 strict and refuses
// them, so the contracts use `.guid()`. A response the server can send must
// not fail to parse in the browser.
const approval = {
  approval_type: "demo.send",
  reason: "r",
  status: "pending",
  payload: {},
  created_at: null,
  decided_at: null,
  requires_comment: false,
  required_scope: null,
  can_decide: true,
  requested_by_me: false,
};

describe("contract ids", () => {
  it.each([
    "00000000-0000-0000-0000-0000000000c1",
    "11111111-1111-1111-1111-111111111111",
    "a0000000-0000-4000-8000-0000000000a1",
  ])("parses the id %s the database can hold", (id) => {
    expect(
      approvalSchema.safeParse({ ...approval, id, run_id: id }).success,
    ).toBe(true);
  });

  it("still refuses a value that is not an id", () => {
    expect(
      approvalSchema.safeParse({ ...approval, id: "not-an-id", run_id: null })
        .success,
    ).toBe(false);
  });
});
