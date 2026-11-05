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

/** A step's card, by the step's id; `folded`, a frame drawn as its card
 * alone (R1.7). */
export interface CanvasCard {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  folded: boolean;
}

/**
 * The frame around a step that runs every lane ("Song song") or its body
 * again ("Lặp lại khi …"), its own card at the top (R1.5). Drawn behind the
 * cards; `id` is `frame:<step>`.
 */
export interface CanvasFrame {
  id: string;
  step: string;
  kind: "parallel" | "loop";
  x: number;
  y: number;
  width: number;
  height: number;
}

/** The head of a lane: where its label goes, under the card that holds it. */
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

/**
 * Where flow meets again, of step `step`:
 * - `join`, the point a choice's lanes meet under them (`join:<step>`), and
 *   the point a loop's exit meets its "Đã đủ N lần" lane;
 * - `bar`, the Điểm nối of a parallel frame, "Chờ tất cả nhánh xong", a box
 *   across the lanes (`bar:<step>`);
 * - `exit`, the normal way out under a loop frame (`exit:<step>`), where
 *   "Thoát vòng lặp" points;
 * - `rejoin`, where the "Khi lỗi" lane meets the step's flow again
 *   (`rejoin:<step>`).
 * A point's `x`, `y` is the point itself and its size 0; a bar's is its
 * top-left corner.
 */
export interface CanvasJoin {
  id: string;
  step: string;
  kind: "join" | "bar" | "exit" | "rejoin";
  x: number;
  y: number;
  width: number;
  height: number;
}

/** A connection between two shapes, an orthogonal polyline through `points`:
 * dashed for the error lane and the loop's way back, with an arrow head where
 * it climbs back or leaves a loop, and the loop's "Lặp lại" label at
 * `labelAt`. */
export interface CanvasConnection {
  id: string;
  from: string;
  to: string;
  points: Point[];
  dashed: boolean;
  arrow: boolean;
  label: "repeat" | null;
  labelAt: Point | null;
}

export interface CanvasShapes {
  frames: CanvasFrame[];
  cards: CanvasCard[];
  laneHeads: CanvasLaneHead[];
  slots: CanvasSlot[];
  joins: CanvasJoin[];
  connections: CanvasConnection[];
}
