"use client";

import { useCallback, useRef } from "react";

/**
 * One `Idempotency-Key` per press (ui-quality §3): the same action with the
 * same payload reuses its key until it succeeds, so a retry after a dropped
 * response is one write, and a new payload or a later press gets a new key,
 * which the API requires (it refuses a key reused with another payload).
 */
export function useIdempotencyKeys(): {
  keyFor: (action: string, payload?: unknown) => string;
  settled: (action: string) => void;
} {
  const keys = useRef(new Map<string, { payload: string; key: string }>());
  const keyFor = useCallback((action: string, payload: unknown = null) => {
    const body = JSON.stringify(payload);
    const held = keys.current.get(action);
    if (held && held.payload === body) return held.key;
    const key = crypto.randomUUID();
    keys.current.set(action, { payload: body, key });
    return key;
  }, []);
  const settled = useCallback((action: string) => {
    keys.current.delete(action);
  }, []);
  return { keyFor, settled };
}
