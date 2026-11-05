"""Plaintext / Markdown document parser.

Richer formats are read by the API parsers in ``api_parsers.py`` behind the same
``DocumentParserPort``.
"""

from __future__ import annotations

from dw_kernel.residency import TenantRouteScope
from dw_knowledge.ports import ParsedDocument

_TEXT_TYPES = ("text/plain", "text/markdown")
_TEXT_SUFFIXES = (".txt", ".md", ".markdown")


class PlaintextParser:
    """Implements ``DocumentParserPort`` for UTF-8 text and Markdown."""

    def supports(self, content_type: str, filename: str) -> bool:
        ct = (content_type or "").split(";", 1)[0].strip().lower()
        name = (filename or "").lower()
        return ct in _TEXT_TYPES or name.endswith(_TEXT_SUFFIXES)

    async def parse(
        self, data: bytes, content_type: str, filename: str, *, scope: TenantRouteScope
    ) -> ParsedDocument:
        del scope  # decoded in process: nothing leaves
        warnings: list[str] = []
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("utf-8", errors="replace")
            warnings.append("decoded_with_replacement")
        title: str | None = None
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            title = stripped.lstrip("#").strip()[:200]
            break
        return ParsedDocument(text=text, detected_title=title, warnings=tuple(warnings))
