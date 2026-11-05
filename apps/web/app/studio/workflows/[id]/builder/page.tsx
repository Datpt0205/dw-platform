"use client";

import { useParams } from "next/navigation";
import { WorkflowBuilder } from "./workflow-builder";

/** `/studio/workflows/[id]/builder`, `[id]` the workflow's artifact id
 * (workflow-builder-ui R2.1). */
export default function WorkflowBuilderPage() {
  const { id } = useParams<{ id: string }>();
  return <WorkflowBuilder artifactId={id} />;
}
