"""Studio: where a tenant builds its own objects, workflows, agents and tools as
versioned data (ADR 0100). Platform code, composed above the context seams.

One distribution of sub-packages, each with the layers of `CLAUDE.md`, meeting
only through `dw_studio.core` and each other's `api` modules; import-linter
holds every line (`pyproject.toml`). A sub-package arrives with its first real
module, never empty.
"""

__version__ = "0.1.0"
