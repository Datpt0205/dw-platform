import { ApiError } from "@dw/api-client";

/**
 * The sentence to show a person when a call fails.
 *
 * `ApiError.message` is `"<code>: <sentence>"` because the code is what a
 * developer reading a stack trace needs. A seller reading a toast does not:
 * "validation_failed: hai đầu quan hệ chưa có trên bản đồ" leaks a machine
 * word into the product. The server already writes the sentence in Vietnamese
 * — take that, and keep the code for the console.
 */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.body.message;
  if (error instanceof Error) return error.message;
  return String(error);
}

/** The server's machine code, when there is one — for branching, not display. */
export function errorCode(error: unknown): string | null {
  return error instanceof ApiError ? error.body.code : null;
}

/**
 * The body fields a refusal names, keyed by JSON pointer (`"/name"`), each with
 * its machine code: a form builds its Vietnamese sentence from the code
 * (DO-57) and puts it under the field. The first error on a field wins.
 */
export function fieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError)) return {};
  const fields: Record<string, string> = {};
  for (const { pointer, code } of error.body.errors) {
    if (pointer !== undefined && !(pointer in fields)) fields[pointer] = code;
  }
  return fields;
}

/**
 * A failure, as the shared `RegionState` reads it: the server's code and
 * sentence (never `"<code>: …"`), or `"offline"` when the browser has no
 * network and `fetch` could not even start.
 */
export function toRegionError(
  error: unknown,
): { code: string; message: string; requestId?: string | null } | "offline" {
  if (error instanceof ApiError) {
    return {
      code: error.body.code,
      message: error.body.message,
      requestId: error.body.request_id,
    };
  }
  if (
    error instanceof TypeError &&
    typeof navigator !== "undefined" &&
    navigator.onLine === false
  ) {
    return "offline";
  }
  return { code: "internal", message: errorMessage(error) };
}
