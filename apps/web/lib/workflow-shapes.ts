/**
 * What the workflow canvas draws, as plain shapes (workflow-builder-ui R1.3,
 * R1.5; ADR-0101 (Accepted) decision 3): `lib/workflow-layout.ts` returns
 * exactly this, computing every position from the step tree, and the canvas
 * under `app/studio/**\/canvas/**` maps it to the library's nodes and edges
 * and never positions anything itself. Outside the canvas glob and importing
 * nothing, so the library stays behind one path. Coordinates are canvas
 * pixels, a shape's top-left corner.
 */

export interface Point {
  x: number;
  y: number;
}

/** A step's card, by the step's id. */
export interface CanvasCard {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

/** The head of a lane: where its label goes (ticket 04 draws its frame). */
export interface CanvasLaneHead {
  id: string;
  parent: string;
  port: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

/**
 * A place a step can go: a "+" on a connection, before the step at `index`
 * of the lane (`parent` null is the document's `steps`), or, `empty`, the
 * dashed "Thêm Bước" slot of an empty lane, whose id is that lane's keyboard
 * stop. `after` is the step the "+" follows, which names it.
 */
export interface CanvasSlot {
  id: string;
  parent: string | null;
  port: string;
  index: number;
  empty: boolean;
  after: string | null;
  x: number;
  y: number;
  width: number;
  height: number;
}

/** The point a block's lanes meet again under it. */
export interface CanvasJoin {
  id: string;
  x: number;
  y: number;
}

/** A connection between two shapes, an orthogonal polyline through `points`;
 * dashed for the error lane. */
export interface CanvasConnection {
  id: string;
  from: string;
  to: string;
  points: Point[];
  dashed: boolean;
}

export interface CanvasShapes {
  cards: CanvasCard[];
  laneHeads: CanvasLaneHead[];
  slots: CanvasSlot[];
  joins: CanvasJoin[];
  connections: CanvasConnection[];
}
