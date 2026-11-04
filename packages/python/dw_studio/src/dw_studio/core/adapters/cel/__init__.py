"""The one CEL adapter (ADR-0114 decision 2): `CelCppEngine` on
`cel-expr-python`, the only package import-linter lets import the binding
("CEL binding only in dw_studio.core.adapters.cel")."""

from dw_studio.core.adapters.cel.engine import CelCppEngine

__all__ = ["CelCppEngine"]
