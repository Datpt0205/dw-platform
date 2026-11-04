/**
 * What the workflow canvas draws, as plain shapes (workflow-builder-ui R1.3,
 * ADR-0101 (Accepted) decision 3): a card at a position and a connection
 * between two cards. `lib/workflow-layout.ts` (workflow-builder-ui/02) returns
 * exactly this, computing every position from the step tree, and widens these
 * types in place when it needs more; the canvas under
 * `app/studio/**\/canvas/**` maps them to the library's nodes and edges and
 * never positions anything itself. Outside the canvas glob and importing
 * nothing, so the library stays behind one path.
 */

/** A step's card: its top-left corner in canvas pixels and the builder's name
 * for the step (the step's `description`). */
export interface CanvasCard {
  id: string;
  x: number;
  y: number;
  description: string;
}

/** A connection from one card to another, by card id. */
export interface CanvasConnection {
  id: string;
  from: string;
  to: string;
}

export interface CanvasShapes {
  cards: CanvasCard[];
  connections: CanvasConnection[];
}
