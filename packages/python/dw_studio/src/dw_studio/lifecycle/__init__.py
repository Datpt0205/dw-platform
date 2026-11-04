"""The stage machine of a Studio version (agent-lifecycle; ADR-0120): submit,
withdraw and retire through `LifecycleService`, with `studio.guard_version_stage()`
as the backstop. A capability over the core envelope; the core imports none of it."""
