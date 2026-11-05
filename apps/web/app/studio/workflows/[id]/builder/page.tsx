"use client";

import { useParams } from "next/navigation";
import { useAuth } from "../../../../../lib/auth/auth-context";
import { WorkflowBuilder } from "./workflow-builder";

/** `/studio/workflows/[id]/builder`, `[id]` the workflow's artifact id
 * (workflow-builder-ui R2.1). The viewer is `GET /api/v1/me`'s principal,
 * whose folded frames the page keeps (R1.7). */
export default function WorkflowBuilderPage() {
  const { id } = useParams<{ id: string }>();
  const { principalId } = useAuth();
  return <WorkflowBuilder artifactId={id} viewerId={principalId} />;
}
