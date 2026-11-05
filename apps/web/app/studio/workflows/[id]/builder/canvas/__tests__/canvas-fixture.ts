import {
  catalogueOf,
  toTree,
  walk,
} from "../../../../../../../lib/workflow-graph";
import {
  layoutWorkflow,
  metricsFor,
} from "../../../../../../../lib/workflow-layout";
import { NODE_TYPES } from "../../../../../../../lib/__tests__/workflow-catalogue";
import { cardView, type CardView } from "../../builder-model";

/** Two plain steps, as the layout lays them out and the builder names them:
 * what the canvas tests draw. */
export const catalogue = catalogueOf(NODE_TYPES);

export const TREE = toTree(
  {
    schema: "dw.workflow/v1",
    triggers: [],
    steps: [
      {
        id: "chuan_hoa",
        type: "data.transform@1",
        description: "Chuẩn hóa số điện thoại",
        config: {},
      },
      {
        id: "luu_lead",
        type: "data.object.upsert@1",
        description: "Lưu hoặc cập nhật Lead",
        config: {},
        retry: { max_attempts: 3, backoff: "fixed" },
        timeout_s: 30,
        on_error: "continue",
      },
    ],
  },
  catalogue,
);

export const SHAPES = layoutWorkflow(
  TREE,
  metricsFor({ width: 256, height: 120 }),
);

export const VIEWS: Map<string, CardView> = (() => {
  const out = new Map<string, CardView>();
  walk(TREE, (node) => out.set(node.id, cardView(node, catalogue)));
  return out;
})();
