"use client";

import { useCallback, useEffect, useState } from "react";

/**
 * Which frames a viewer has folded on a workflow (workflow-builder-ui R1.7,
 * BU8): the one owner the canvas, the keyboard order and the outline's
 * `expandedKeys` all read. Kept per viewer in this browser's `localStorage`
 * under `wbui.collapsed.<user_id>.<artifact_id>`, a list of step ids, and
 * never in the document, whose content hash a fold must not move.
 *
 * `viewerId` is the signed-in user (`GET /api/v1/me`'s `principal_id`), so a
 * second person on the same browser starts with every frame open. Without
 * it, or where storage cannot be read or written (a private window, blocked
 * site data), every frame starts open and a fold lasts as long as the page:
 * every access is guarded, and the page draws in full either way. A
 * read-only canvas (the run screen, the publish review) never calls this:
 * it opens every frame, so a reviewer misses nothing folded away.
 */

export function foldKey(viewerId: string, artifactId: string): string {
  return `wbui.collapsed.${viewerId}.${artifactId}`;
}

function read(key: string | null): Set<string> {
  if (key === null) return new Set();
  try {
    const raw = window.localStorage.getItem(key);
    const parsed: unknown = raw === null ? [] : JSON.parse(raw);
    return new Set(
      Array.isArray(parsed)
        ? parsed.filter((id): id is string => typeof id === "string")
        : [],
    );
  } catch {
    return new Set();
  }
}

function write(key: string | null, folded: ReadonlySet<string>) {
  if (key === null) return;
  try {
    if (folded.size === 0) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, JSON.stringify([...folded].sort()));
  } catch {
    // Storage unavailable: the fold holds for this page only.
  }
}

export interface FoldedFrames {
  folded: ReadonlySet<string>;
  setFolded: (next: ReadonlySet<string>) => void;
}

export function useFoldedFrames(
  viewerId: string | null | undefined,
  artifactId: string,
): FoldedFrames {
  const key = viewerId ? foldKey(viewerId, artifactId) : null;
  const [state, setState] = useState<{
    key: string | null;
    folded: ReadonlySet<string>;
  }>(() => ({ key, folded: read(key) }));

  // The viewer becomes known after the page (or changes): read theirs.
  useEffect(() => {
    if (state.key !== key) setState({ key, folded: read(key) });
  }, [key, state.key]);

  const setFolded = useCallback(
    (next: ReadonlySet<string>) => {
      write(key, next);
      setState({ key, folded: new Set(next) });
    },
    [key],
  );

  return { folded: state.key === key ? state.folded : NONE, setFolded };
}

const NONE: ReadonlySet<string> = new Set();
