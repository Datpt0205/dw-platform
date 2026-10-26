import { describe, expect, it } from "vitest";

import { ApiClient, ApiError } from "@dw/api-client";

import { errorCode, errorMessage, fieldErrors } from "../error-message";

/**
 * A refusal reaches a form as the fields it names (ADR 0108, point 1). Before
 * the problem+json envelope, a 422 whose body the client could not read
 * became `internal` / "HTTP 422", and the person saw that instead of which
 * field was wrong.
 */

function clientAnswering(response: Response): ApiClient {
  return new ApiClient({
    baseUrl: "http://api.test",
    fetchImpl: async () => response,
  });
}

async function refusal(response: Response): Promise<ApiError> {
  const error = await clientAnswering(response)
    .getHealth()
    .catch((caught: unknown) => caught);
  if (!(error instanceof ApiError)) throw new Error("expected an ApiError");
  return error;
}

const validationProblem = {
  type: "urn:dw:problem:validation_failed",
  title: "Validation Failed",
  status: 422,
  detail: "the request does not match its schema",
  instance: "urn:dw:request:req-1",
  code: "validation_failed",
  message: "the request does not match its schema",
  details: {},
  request_id: "req-1",
  trace_id: null,
  errors: [
    { pointer: "/name", code: "string_too_short", detail: "too short" },
    { parameter: "limit", code: "int_parsing", detail: "not a number" },
  ],
};

describe("a refused call", () => {
  it("keeps the fields a 422 problem names", async () => {
    const error = await refusal(
      new Response(JSON.stringify(validationProblem), {
        status: 422,
        headers: { "Content-Type": "application/problem+json" },
      }),
    );

    expect(error.status).toBe(422);
    expect(errorCode(error)).toBe("validation_failed");
    expect(error.body.errors).toEqual(validationProblem.errors);
    expect(fieldErrors(error)).toEqual({ "/name": "string_too_short" });
  });

  it("still reads code and message from an envelope without the problem members", async () => {
    const error = await refusal(
      new Response(
        JSON.stringify({
          code: "rate_limited",
          message: "too many requests",
          details: {},
        }),
        { status: 429, headers: { "Content-Type": "application/json" } },
      ),
    );

    expect(errorCode(error)).toBe("rate_limited");
    expect(errorMessage(error)).toBe("too many requests");
    expect(error.body.errors).toEqual([]);
    expect(fieldErrors(error)).toEqual({});
  });

  it("names no field for an error that is not an API refusal", () => {
    expect(fieldErrors(new Error("offline"))).toEqual({});
  });
});
