"""Parsers that call an API instead of running a model locally.

Three routes behind one ``DocumentParserPort``, chosen by extension:

- plaintext decodes in process, no call and no cost;
- documents and images go to the OpenAI-compatible gateway as ``input_file`` /
  ``input_image``, which reads pdf/docx/xlsx/pptx server-side;
- audio goes to Deepgram, which is not an OpenAI dialect and needs its own call.

Both gateway routes were measured before being written against - see
docs/architecture/model-gateway-findings.md. This replaced a local ML parser,
and with it the torch stack in the worker image.
"""

from __future__ import annotations

import base64
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from dw_kernel.errors import InfrastructureError
from dw_kernel.residency import Destination, ResidencyGate, TenantRouteScope
from dw_knowledge.attachment_policy import AttachmentKind, AttachmentPolicy
from dw_knowledge.ports import ParsedDocument

DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"

# A document is one request. Generous because the model reads the whole file
# before it answers, and a scanned contract is slow.
_EXTRACTION_TIMEOUT = 300.0

# One request too, and it carries the whole recording in its body. Sized for the
# longest real input rather than the average one: a four-hour customer meeting is
# ~230MB at 128kbps stereo, which is minutes to send before Deepgram starts, and
# it transcribes at roughly 30x realtime - so about ten minutes of work on top.
# Thirty minutes covers that on a modest uplink; ten did not cover it at all,
# which is what made a long meeting unprocessable rather than slow.
_TRANSCRIPTION_TIMEOUT = 1800.0


def _mime_for(filename: str) -> str:
    """Only what the two APIs need to distinguish; not a general mime table."""
    suffix = filename.rsplit(".", 1)[-1].lower()
    return {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "gif": "image/gif",
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "m4a": "audio/mp4",
        "aac": "audio/aac",
        "ogg": "audio/ogg",
        "opus": "audio/opus",
        "flac": "audio/flac",
        "webm": "audio/webm",
        "mp4": "audio/mp4",
    }.get(suffix, "application/octet-stream")


def _strip_code_fence(text: str) -> str:
    """Models wrap "give me markdown" in a markdown fence. Chunking should not
    inherit ```markdown as the document's first line."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return text
    lines = stripped.splitlines()
    if len(lines) >= 2 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1])
    return text


def _response_text(body: Any) -> str:
    """Flatten a /responses body; gateways differ on the convenience field."""
    if not isinstance(body, dict):
        return ""
    direct = body.get("output_text")
    if isinstance(direct, str):
        return direct
    parts: list[str] = []
    for item in body.get("output") or []:
        if not isinstance(item, dict):
            continue
        for block in item.get("content") or []:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
    return "".join(parts)


@dataclass
class PlaintextAttachmentParser:
    """UTF-8 in, UTF-8 out. No API, so no cost and no failure mode worth retrying."""

    policy: AttachmentPolicy

    def supports(self, content_type: str, filename: str) -> bool:
        return self.policy.kind_of(filename) is AttachmentKind.PLAINTEXT

    async def parse(
        self, data: bytes, content_type: str, filename: str, *, scope: TenantRouteScope
    ) -> ParsedDocument:
        del scope  # decoded in process: nothing leaves
        warnings: tuple[str, ...] = ()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("utf-8", errors="replace")
            warnings = ("decoded_with_replacement",)
        return ParsedDocument(text=text, detected_title=filename, warnings=warnings)


@dataclass
class GatewayFileParser:
    """Documents and images, read by the model behind the configured gateway."""

    base_url: str
    api_key: str
    model: str
    policy: AttachmentPolicy
    # The gate, and where the extraction endpoint processes, declared in the
    # worker's settings beside its URL (compliance-pdpl R2.3).
    residency: ResidencyGate
    destination: Destination
    timeout: float = _EXTRACTION_TIMEOUT

    def supports(self, content_type: str, filename: str) -> bool:
        return self.policy.kind_of(filename) in (
            AttachmentKind.DOCUMENT,
            AttachmentKind.IMAGE,
        )

    async def parse(
        self, data: bytes, content_type: str, filename: str, *, scope: TenantRouteScope
    ) -> ParsedDocument:
        # Before the file is read into a request: a refused scope sends nothing.
        await self.residency.check(scope, self.destination)
        kind = self.policy.kind_of(filename)
        encoded = base64.b64encode(data).decode("ascii")
        mime = _mime_for(filename)
        if kind is AttachmentKind.IMAGE:
            instruction = self.policy.image_instruction
            block: dict[str, Any] = {
                "type": "input_image",
                "image_url": f"data:{mime};base64,{encoded}",
            }
        else:
            instruction = self.policy.document_instruction
            block = {
                "type": "input_file",
                "filename": filename,
                "file_data": f"data:{mime};base64,{encoded}",
            }

        body = await self._post(
            {
                "model": self.model,
                "input": [
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": instruction}, block],
                    }
                ],
            }
        )
        text = _strip_code_fence(_response_text(body))
        if self.policy.empty_marker in text:
            # Nothing readable. Returned empty so the consumer fails the job
            # rather than indexing the marker as if it were the document.
            #
            # Matched anywhere rather than as the whole reply: the instruction
            # asks for the marker alone, and a model that prefixes it with a
            # sentence of apology is saying the same thing. Requiring an exact
            # match let that reply through as content, and a file nobody could
            # read was indexed, shown as read, and quoted back as evidence.
            text = ""
        warnings: tuple[str, ...] = ()
        # A truncated extraction is worse than a failed one: it indexes a
        # document that silently stops halfway, and every later answer about the
        # missing part is "not in the file".
        if (body.get("status") if isinstance(body, dict) else None) == "incomplete":
            warnings = ("extraction_incomplete",)
        return ParsedDocument(text=text, detected_title=filename, warnings=warnings)

    async def _post(self, payload: dict[str, Any]) -> Any:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url.rstrip("/"),
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout,
            ) as client:
                response = await client.post("/responses", json=payload)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as exc:
            raise InfrastructureError(
                "document extraction request failed",
                details={"model": self.model, "error": type(exc).__name__},
            ) from exc


@dataclass
class DeepgramTranscriptParser:
    """Recordings, transcribed by Deepgram.

    The transcript is emitted with speaker headings so `structure_aware_chunks`
    keeps a turn together and a citation can name who was speaking.
    """

    api_key: str
    policy: AttachmentPolicy
    # The gate, and where `DEEPGRAM_URL` processes, declared in the worker's
    # settings with no default: undeclared is foreign (compliance-pdpl R2.3).
    residency: ResidencyGate
    destination: Destination
    timeout: float = _TRANSCRIPTION_TIMEOUT

    def supports(self, content_type: str, filename: str) -> bool:
        return self.policy.kind_of(filename) is AttachmentKind.AUDIO

    async def parse(
        self, data: bytes, content_type: str, filename: str, *, scope: TenantRouteScope
    ) -> ParsedDocument:
        await self.residency.check(scope, self.destination)
        params = {
            "model": self.policy.transcription_model,
            "language": self.policy.transcription_language,
            "smart_format": "true",
            "diarize": "true",
            "punctuate": "true",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    DEEPGRAM_URL,
                    params=params,
                    content=data,
                    headers={
                        "Authorization": f"Token {self.api_key}",
                        "Content-Type": _mime_for(filename),
                    },
                )
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPError as exc:
            raise InfrastructureError(
                "transcription request failed",
                details={"error": type(exc).__name__},
            ) from exc

        alternative = _first_alternative(body)
        text = _as_speaker_markdown(alternative) or str(alternative.get("transcript") or "")
        return ParsedDocument(text=text, detected_title=filename)


def _first_alternative(body: Any) -> dict[str, Any]:
    channels = ((body or {}).get("results") or {}).get("channels") or []
    if not channels:
        return {}
    alternatives = channels[0].get("alternatives") or []
    return alternatives[0] if alternatives else {}


def _as_speaker_markdown(alternative: dict[str, Any]) -> str:
    """Group the transcript into "## Người nói N" sections, each stamped.

    Without headings the whole recording is one wall of text that the chunker
    splits on character count alone, which cuts through the middle of answers.

    The timestamp is what makes a transcript quotable. Spec 001 section 6.1 asks a
    citation to say "phút 12:30", and a chunk that reached the scorer without
    one could only be cited as "somewhere in the recording" — which is not a
    citation a person can check.
    """
    paragraphs = ((alternative.get("paragraphs") or {}).get("paragraphs")) or []
    if not paragraphs:
        return ""
    lines: list[str] = []
    speaker: object = object()
    for paragraph in paragraphs:
        if paragraph.get("speaker") != speaker:
            speaker = paragraph.get("speaker")
            lines.append(f"\n## Người nói {speaker if speaker is not None else '?'}\n")
        stamp = _timestamp(paragraph.get("start"))
        body = _sentences(paragraph.get("sentences") or [])
        lines.append(f"[{stamp}] {body}" if stamp and body else body)
    return "\n".join(line for line in lines if line).strip()


def _timestamp(start: Any) -> str:
    """`mm:ss` from Deepgram's seconds-since-start float, or "" if it is absent."""
    if not isinstance(start, (int, float)):
        return ""
    seconds = int(start)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _sentences(sentences: Sequence[dict[str, Any]]) -> str:
    """The words of one paragraph, joined.

    The recogniser also returns a per-sentence confidence, and this used to mark
    the low ones and count them towards a rejection threshold. Removed on
    2026-08-25: nobody - not a person, not the agent - can say what that number
    means for a given recording, so the only thing it reliably produced was an
    audible meeting thrown away because a vendor scored it low. Judging the
    evidence is the scorer's job, and it already has to do it for notes and
    documents that carry no confidence at all.
    """
    parts = [str(sentence.get("text") or "") for sentence in sentences]
    return " ".join(part for part in parts if part).strip()
