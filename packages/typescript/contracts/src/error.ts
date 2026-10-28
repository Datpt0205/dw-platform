import { z } from "zod";

/**
 * The four members every API error has carried since before problem+json:
 * what a client may rely on whatever answered (an older server, a proxy-era
 * body, a replay of a stored response).
 */
export const errorResponseSchema = z.object({
  code: z.string(),
  message: z.string(),
  details: z.record(z.string(), z.unknown()).default({}),
  request_id: z.string().nullable().optional(),
});

export type ErrorResponse = z.infer<typeof errorResponseSchema>;

export const PROBLEM_MEDIA_TYPE = "application/problem+json";

/** One thing wrong with the request: exactly one of `pointer`, `parameter`, `header`. */
export const problemErrorSchema = z.object({
  pointer: z.string().optional(),
  parameter: z.string().optional(),
  header: z.string().optional(),
  code: z.string(),
  detail: z.string(),
});

export type ProblemError = z.infer<typeof problemErrorSchema>;

/**
 * Mirrors `dw_api.errors.Problem`, the one error description every endpoint
 * returns (RFC 9457 plus extension members, ADR 0108). Not strict, and every
 * member past the four above optional, so a member the server adds later
 * breaks no client.
 */
export const problemSchema = errorResponseSchema.extend({
  type: z.string().optional(),
  title: z.string().optional(),
  status: z.number().int().optional(),
  detail: z.string().optional(),
  instance: z.string().nullable().optional(),
  trace_id: z.string().nullable().optional(),
  errors: z.array(problemErrorSchema).default([]),
});

export type Problem = z.infer<typeof problemSchema>;

/** Stable error codes shared with the backend taxonomy. */
export const ErrorCode = {
  ValidationFailed: "validation_failed",
  NotFound: "not_found",
  MethodNotAllowed: "method_not_allowed",
  Conflict: "conflict",
  PreconditionFailed: "precondition_failed",
  PreconditionRequired: "precondition_required",
  Unauthenticated: "unauthenticated",
  PermissionDenied: "permission_denied",
  EntitlementDenied: "entitlement_denied",
  ApprovalRequired: "approval_required",
  TenantContextMissing: "tenant_context_missing",
  IdempotencyConflict: "idempotency_conflict",
  RateLimited: "rate_limited",
  PayloadTooLarge: "payload_too_large",
  UnsupportedMediaType: "unsupported_media_type",
  Timeout: "timeout",
  UpstreamUnavailable: "upstream_unavailable",
  Internal: "internal",
} as const;

export type ErrorCodeValue = (typeof ErrorCode)[keyof typeof ErrorCode];
