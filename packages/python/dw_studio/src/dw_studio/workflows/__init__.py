"""Studio's `workflow` kind (workflow-engine ticket 01): what only Studio has
of a `dw.workflow/v1` document, its path rules, its dependency extractor, its
publish hook and the port that hook calls. The document model, the IR, the
validator and the compiler are the platform core's (`dw_agent_runtime.wflite`;
ADR-0112 Amendments 2026-11-03); nothing here is a second one. A capability
over the core envelope; the core imports none of it."""
