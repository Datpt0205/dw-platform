"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@dw/api-client";
import { sameJson, type JsonObject } from "../../../../../lib/workflow-graph";
import { apiClient } from "../../../../../lib/session";

/**
 * The draft saved as the builder edits it (workflow-builder-ui R2.3, R2.4,
 * BU4), through tenant-config/02's route: `PUT .../draft` with `If-Match` the
 * version the page last read or saved, and the version the answer carries for
 * the next save. Debounced, and nothing is sent while the document equals the
 * one last saved (each save writes an audit row, ticket 02 MEDIUM (b)).
 *
 * A 412 stops autosave: what is on the page stays as it is, no further `PUT`
 * goes out, and only `reload` (the "Tải bản mới nhất" button) brings the
 * server's draft and version back. Any other refusal is "Lưu thất bại" with
 * the server's sentence; the next edit, or `retry`, tries again. The server
 * decides who may save: the page never asks first.
 */

export type SaveState = "idle" | "saving" | "saved" | "failed" | "conflict";

/** What the kind's check found in the last draft saved, with the document
 * its pointers point into (a warning never blocks a save). */
export interface SavedWarnings {
  document: JsonObject;
  items: { pointer: string; code: string; detail: string }[];
}

export interface DraftAutosave {
  state: SaveState;
  error: unknown;
  warnings: SavedWarnings | null;
  retry: () => void;
  /** The server's draft, after which autosave runs again from its version. */
  reload: () => Promise<JsonObject>;
}

export function useDraftAutosave(
  artifactId: string,
  document: JsonObject,
  initial: { version: number; document: JsonObject },
  delayMs: number,
): DraftAutosave {
  const version = useRef(initial.version);
  const saved = useRef<JsonObject>(initial.document);
  const latest = useRef(document);
  latest.current = document;
  const stopped = useRef(false);
  const busy = useRef(false);
  const again = useRef(false);
  const [state, setState] = useState<SaveState>("idle");
  const [error, setError] = useState<unknown>(null);
  const [warnings, setWarnings] = useState<SavedWarnings | null>(null);

  const save = useCallback(async (): Promise<void> => {
    if (stopped.current) return;
    if (busy.current) {
      again.current = true;
      return;
    }
    const doc = latest.current;
    if (sameJson(doc, saved.current)) return;
    busy.current = true;
    setState("saving");
    try {
      const out = await apiClient().saveStudioDraft(
        artifactId,
        version.current,
        doc,
      );
      version.current = out.version;
      saved.current = doc;
      setWarnings({ document: doc, items: out.warnings ?? [] });
      setError(null);
      setState("saved");
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 412) {
        stopped.current = true;
        setState("conflict");
      } else {
        setError(caught);
        setState("failed");
      }
    } finally {
      busy.current = false;
    }
    if (again.current && !stopped.current) {
      again.current = false;
      await save();
    }
  }, [artifactId]);

  useEffect(() => {
    if (stopped.current || sameJson(document, saved.current)) return;
    const timer = window.setTimeout(() => void save(), delayMs);
    return () => window.clearTimeout(timer);
  }, [document, delayMs, save]);

  const retry = useCallback(() => void save(), [save]);

  const reload = useCallback(async () => {
    const draft = await apiClient().getStudioDraft(artifactId);
    version.current = draft.version;
    saved.current = draft.document;
    latest.current = draft.document;
    stopped.current = false;
    again.current = false;
    setError(null);
    setWarnings(null);
    setState("saved");
    return draft.document;
  }, [artifactId]);

  return { state, error, warnings, retry, reload };
}
