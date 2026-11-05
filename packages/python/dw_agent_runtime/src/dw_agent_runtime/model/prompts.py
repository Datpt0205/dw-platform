"""Versioned prompt bundles loaded from configs/prompts.

A prompt artifact is immutable: changing wording means a new version file.
Rendering is strict — missing or unknown variables fail fast.

**Every variable is untrusted unless the template says otherwise.** The registry
wraps each value it interpolates in ``<input name="...">`` with ``&``, ``<`` and
``>`` escaped, so a value cannot close its block and continue as the prompt's
own words. Containment used to be each template's job: a template that forgot
the block, or a document carrying ``</input>``, was enough. A template opts a
variable out, by name and with the reason, only for a value code builds (a
date, an identifier); ``raw_variables`` is that list.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, NamedTuple
from uuid import UUID

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from dw_agent_runtime.contracts import (
    MAX_OUTPUT_BYTES,
    MODEL_TOOL_NAME,
    ToolDefinition,
    model_facing_name,
)
from dw_agent_runtime.registry import ConfigError
from dw_kernel.errors import DomainError, NotFoundError
from dw_kernel.overlay import TenantOverlay

_VARIABLE_PATTERN = re.compile(r"\{([a-z_][a-z0-9_]*)\}")
UNTRUSTED_TAG = "input"
TOOL_OUTPUT_TAG = "tool_output"
# Ends a tool output the model-facing view cut, inside its ceilings (R5.1).
TRUNCATED_MARK: Final = "[đã cắt]"


def escape_untrusted(value: str) -> str:
    """ADR-0010's one escape: `&`, `<` and `>`, so a value can neither close
    its block nor open another. Every untrusted block a model reads goes
    through it exactly once."""
    return html.escape(value, quote=False)


def contain_untrusted(name: str, value: str) -> str:
    """The one form an untrusted value takes inside a prompt.

    Escaped rather than stripped: the model still reads what the document said,
    and nothing in it can open or close a block. ``name`` is a template
    placeholder, which the pattern above limits to ``[a-z0-9_]``.
    """
    escaped = escape_untrusted(value)
    return f'<{UNTRUSTED_TAG} name="{name}">\n{escaped}\n</{UNTRUSTED_TAG}>'


# An opening or closing untrusted block, in any case: `<input>`, `</INPUT`,
# `<input name=...`; never `<inputs` or `<input_x`, which open no block.
_UNTRUSTED_TAG_PATTERN = re.compile(rf"(?i)</?{UNTRUSTED_TAG}\b")


def writes_untrusted_tag(text: str) -> bool:
    """Whether instruction text writes an untrusted block's tag itself.

    The platform wraps every value; text that writes the tag too nests one
    block in another and teaches the next author that containment is theirs
    to do (ADR-0010). The one check for a platform prompt's `template` and a
    tenant's prompt template (workflow-nodes R4.2)."""
    return _UNTRUSTED_TAG_PATTERN.search(text) is not None


# ---- a tenant's instructions (ADR-0117 decision 4) ------------------------------
#
# A Studio agent's instructions, and a workflow `ai.llm` step's (workflow-nodes
# 05), are a company's text, never a template: the frame around them is the
# platform's, rendered at the platform layer only, and the text follows it in a
# `<tenant_instructions>` block it cannot close. The rules below are the one
# lint both callers run, each with one code (agent-builder R2.1-R2.4).

TENANT_INSTRUCTIONS_TAG: Final = "tenant_instructions"
# The platform variables a frame may name, a closed set (ADR-0117 decision 4):
# a frame or a caller naming another is refused before any prompt exists.
SYSTEM_VARIABLES: Final = frozenset(
    {"current_date", "current_time", "user_display_name", "workspace_name", "agent_name", "locale"}
)
# The two of them code builds, which a frame may interpolate raw (ADR-0010);
# a person's name or a workspace's is never one.
CODE_BUILT_VARIABLES: Final = frozenset({"current_date", "current_time"})
MAX_INSTRUCTION_CHARS: Final = 16_000
# Each interpolated value, cut at a character (16 KiB of UTF-8).
MAX_SYSTEM_VALUE_BYTES: Final = 16_384

# An opening or closing of any block the platform writes, in any case and with
# any space after `<` or `/`: `</tenant_instructions>`, `< /input`, `<TOOL_OUTPUT`.
_CONTAINMENT_DELIMITER = re.compile(
    rf"<\s*/?\s*(?:{TENANT_INSTRUCTIONS_TAG}|{UNTRUSTED_TAG}|{TOOL_OUTPUT_TAG})", re.IGNORECASE
)
# `{{`, or `{name}` with a dotted or indexed path: what `str.format` or a
# template engine would read as a placeholder. `{"a": 1}` is not one.
_TEMPLATE_SYNTAX = re.compile(r"\{\{|\{[A-Za-z_][A-Za-z0-9_.\[\]]*\}")
# C0 controls but the tab and the newline.
_CONTROL_CHAR = re.compile(r"[\x00-\x08\x0b-\x1f]")


class InstructionFinding(NamedTuple):
    """One rule a company's instructions break: its code and a fixed sentence,
    never the text itself."""

    code: str
    detail: str


INSTRUCTION_RULES: Final[Mapping[str, str]] = {
    "instructions.too_long": f"instructions are at most {MAX_INSTRUCTION_CHARS} characters",
    "instructions.control_char": "a control character other than a newline or a tab",
    "instructions.template_syntax": "text shaped like a template placeholder, {{ or {name}",
    "instructions.delimiter": "the opening or closing of a block the platform writes",
}


def lint_instructions(text: str) -> list[InstructionFinding]:
    """Every rule `text` breaks, each once, in `INSTRUCTION_RULES`' order.

    The assembler does not depend on it: text that reaches it unchecked is
    still contained (a draft run, a step built before the rule). NFC is the
    envelope's repair at save (`canonical_document`), not a rule here."""
    broken = {
        "instructions.too_long": len(text) > MAX_INSTRUCTION_CHARS,
        "instructions.control_char": _CONTROL_CHAR.search(text) is not None,
        "instructions.template_syntax": _TEMPLATE_SYNTAX.search(text) is not None,
        "instructions.delimiter": _CONTAINMENT_DELIMITER.search(text) is not None,
    }
    return [
        InstructionFinding(code, detail)
        for code, detail in INSTRUCTION_RULES.items()
        if broken[code]
    ]


def escape_delimiters(text: str) -> str:
    """`text` with the `<` of each block delimiter written `&lt;`, and every
    other character as it was: `a < b` stays, `</tenant_instructions>` cannot
    close its block (R2.2)."""
    return _CONTAINMENT_DELIMITER.sub(lambda found: "&lt;" + found.group(0)[1:], text)


def cut_utf8(value: str, max_bytes: int) -> str:
    """At most `max_bytes` of UTF-8, a character cut in half dropped whole."""
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


class ContainedOutput(NamedTuple):
    """A tool's answer as the model reads it, and what stays beside it: a
    `content_and_artifact` pair whose artifact is never sent to the model."""

    content: str
    artifact: dict[str, object]


_ABSENT: Final = object()


def _at(document: object, pointer: str) -> object:
    """The value a JSON Pointer (RFC 6901) names, or `_ABSENT`."""
    node = document
    for raw in pointer.split("/")[1:]:
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, Mapping) and token in node:
            node = node[token]
        elif isinstance(node, list) and token.isdigit() and int(token) < len(node):
            node = node[int(token)]
        else:
            return _ABSENT
    return node


def _projected(payload: object, fields: Sequence[str]) -> object:
    """The whole output; the value one pointer names (null when absent); or
    an object keyed by pointer holding each value present."""
    if not fields:
        return payload
    if len(fields) == 1:
        found = _at(payload, fields[0])
        return None if found is _ABSENT else found
    picked = {pointer: _at(payload, pointer) for pointer in fields}
    return {pointer: value for pointer, value in picked.items() if value is not _ABSENT}


def _capped(escaped: str, max_chars: int) -> tuple[str, bool]:
    """At most `max_chars` characters and `MAX_OUTPUT_BYTES` bytes of UTF-8,
    both counted on the escaped text plus the mark that ends a cut one; cut
    at a character, never inside an entity such as `&lt;`."""
    if len(escaped) <= max_chars and len(escaped.encode("utf-8")) <= MAX_OUTPUT_BYTES:
        return escaped, False
    room = max_chars - len(TRUNCATED_MARK)
    if room <= 0:
        return TRUNCATED_MARK[:max_chars], True
    kept = escaped[:room]
    room_bytes = MAX_OUTPUT_BYTES - len(TRUNCATED_MARK.encode("utf-8"))
    encoded = kept.encode("utf-8")
    if len(encoded) > room_bytes:
        # A character cut in half at the end is dropped whole.
        kept = encoded[:room_bytes].decode("utf-8", errors="ignore")
    # The escape writes `&` only to open an entity, so an `&` with no `;`
    # after it is an entity cut in half.
    opened = kept.rfind("&")
    if opened != -1 and ";" not in kept[opened:]:
        kept = kept[:opened]
    return kept + TRUNCATED_MARK, True


def contain_tool_output(
    output: BaseModel | Mapping[str, Any],
    definition: ToolDefinition,
    execution_id: UUID | None,
    *,
    tool_version_id: str,
) -> ContainedOutput:
    """The one place a tool's output is wrapped and cut for the model, for
    every tool the Studio assembler builds (ADR-0116 decision 5; R5.1-R5.3).

    Projected by `definition.response.fields`, written as compact JSON,
    escaped once by ADR-0010's escape, cut on the escaped text, and wrapped as
    `<tool_output source="<tool>" trust="untrusted">`. A handler returns its
    output raw: one that wrapped it too would only be escaped here, never
    trusted. The artifact names the execution row holding the full output,
    the pinned version and whether the content was cut; it never reaches the
    model."""
    source = model_facing_name(definition.name)
    if MODEL_TOOL_NAME.fullmatch(source) is None:
        raise ConfigError(
            "a tool's model-facing name is outside what a provider accepts",
            details={"tool": definition.name},
        )
    payload = output.model_dump(mode="json") if isinstance(output, BaseModel) else output
    text = json.dumps(
        _projected(payload, definition.response.fields),
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    content, truncated = _capped(escape_untrusted(text), definition.response.max_output_chars)
    return ContainedOutput(
        f'<{TOOL_OUTPUT_TAG} source="{source}" trust="untrusted">\n{content}\n</{TOOL_OUTPUT_TAG}>',
        {
            "execution_id": None if execution_id is None else str(execution_id),
            "tool_version_id": tool_version_id,
            "truncated": truncated,
        },
    )


class PromptArtifact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(pattern=r"^1\.0$")
    prompt_id: str
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    description: str = ""
    system: str
    template: str
    variables: frozenset[str] = frozenset()
    # Variables interpolated as written, each with the reason it is safe to:
    # a value code builds, never one a request, a document or a model wrote.
    raw_variables: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _raw_is_declared_and_justified(self) -> PromptArtifact:
        unknown = set(self.raw_variables) - set(self.variables)
        if unknown:
            raise ValueError(f"raw_variables not among variables: {sorted(unknown)}")
        unjustified = [name for name, why in self.raw_variables.items() if not why.strip()]
        if unjustified:
            raise ValueError(f"raw variable without a reason: {sorted(unjustified)}")
        # The registry wraps. A template doing it too nests one block in another
        # and teaches the next author that containment is the template's job.
        if writes_untrusted_tag(self.template):
            raise ValueError(f"template must not write <{UNTRUSTED_TAG}> itself")
        return self

    def declared_placeholders(self) -> frozenset[str]:
        return frozenset(_VARIABLE_PATTERN.findall(self.template))


@dataclass(frozen=True)
class RenderedPrompt:
    prompt_id: str
    version: str
    system: str
    user: str
    checksum: str


@dataclass
class PromptRegistry:
    # Platform prompts plus per-tenant overrides: a customer whose wording,
    # rules or examples differ gets its own artifact, not a branch.
    _prompts: TenantOverlay[tuple[str, str], tuple[PromptArtifact, str]] = field(
        default_factory=TenantOverlay
    )

    def load_directory(self, directory: Path, *, tenant_id: UUID | None = None) -> None:
        for path in sorted(directory.rglob("*.yaml")):
            self.load_file(path, tenant_id=tenant_id)

    def load_file(self, path: Path, *, tenant_id: UUID | None = None) -> PromptArtifact:
        raw = path.read_bytes()
        try:
            artifact = PromptArtifact.model_validate(yaml.safe_load(raw))
        except (yaml.YAMLError, ValidationError) as exc:
            raise ConfigError(f"prompt artifact {path.name} invalid: {exc}") from exc

        placeholders = artifact.declared_placeholders()
        if placeholders != artifact.variables:
            raise ConfigError(
                f"prompt {artifact.prompt_id}@{artifact.version}: declared variables "
                f"{sorted(artifact.variables)} != template placeholders {sorted(placeholders)}"
            )
        self.register(artifact, checksum=hashlib.sha256(raw).hexdigest(), tenant_id=tenant_id)
        return artifact

    def register(
        self,
        artifact: PromptArtifact,
        *,
        checksum: str | None = None,
        tenant_id: UUID | None = None,
    ) -> None:
        key = (artifact.prompt_id, artifact.version)
        # Within one layer only: a tenant overriding a platform prompt is the
        # feature; two files claiming one version inside a layer is the mistake.
        if self._prompts.existing(key, tenant_id=tenant_id) is not None:
            raise ConfigError(f"prompt already registered: {key[0]}@{key[1]}")
        digest = checksum or hashlib.sha256(artifact.model_dump_json().encode()).hexdigest()
        self._prompts.put(key, (artifact, digest), tenant_id=tenant_id)

    def has(self, prompt_id: str, version: str) -> bool:
        """Whether the platform layer holds this version.

        The platform layer only: a tenant's override is a variation of a prompt
        the platform ships, and resolution falls back to the platform, so a
        version only some tenant holds is one every other tenant cannot render.
        """
        return self._prompts.existing((prompt_id, version)) is not None

    def platform_artifact(self, prompt_id: str, version: str) -> PromptArtifact:
        """The platform layer's artifact, whatever any tenant holds: what a
        containment frame is rendered from (`assemble_system_prompt`)."""
        entry = self._prompts.existing((prompt_id, version))
        if entry is None:
            raise NotFoundError(
                "prompt version not registered",
                details={"prompt_id": prompt_id, "version": version},
            )
        return entry[0]

    def render(
        self,
        prompt_id: str,
        version: str,
        variables: dict[str, str],
        *,
        tenant_id: UUID | None = None,
    ) -> RenderedPrompt:
        entry = self._prompts.get((prompt_id, version), tenant_id=tenant_id)
        if entry is None:
            raise NotFoundError(
                "prompt version not registered",
                details={"prompt_id": prompt_id, "version": version},
            )
        artifact, checksum = entry
        provided = frozenset(variables)
        if provided != artifact.variables:
            raise DomainError(
                "prompt variables mismatch",
                details={
                    "prompt_id": prompt_id,
                    "expected": sorted(artifact.variables),
                    "provided": sorted(provided),
                },
            )
        return RenderedPrompt(
            prompt_id=prompt_id,
            version=version,
            system=artifact.system,
            user=artifact.template.format(
                **{
                    name: value
                    if name in artifact.raw_variables
                    else contain_untrusted(name, value)
                    for name, value in variables.items()
                }
            ),
            checksum=checksum,
        )


class PromptAssemblyError(DomainError):
    """A frame or a caller named a variable outside `SYSTEM_VARIABLES`, a frame
    let a value other than a code-built one through raw, or a frame's variable
    had no value: no prompt is built (agent-builder R2.3)."""

    def __init__(self, message: str, *, variable: str) -> None:
        super().__init__(f"{message}: {variable}", details={"variable": variable})
        self.variable = variable


def _refused(message: str, names: frozenset[str] | set[str]) -> None:
    if names:
        raise PromptAssemblyError(message, variable=sorted(names)[0])


def assemble_system_prompt(
    prompts: PromptRegistry,
    prompt_id: str,
    version: str,
    *,
    instructions: str,
    variables: Mapping[str, str],
) -> str:
    """The system message of a Studio agent or `ai.llm` step (ADR-0117
    decision 4; agent-builder R1.12, R2.1-R2.3).

    The frame `prompt_id@version` is rendered at the platform layer only,
    never through a company's override (`CLAUDE.md`, Per-tenant artifacts:
    a containment frame), with each value it declares cut at 16 KiB of UTF-8
    and contained by the registry unless it is one of the two code-built
    values the frame lists in `raw_variables`. The company's instructions
    follow verbatim and uncut in a `<tenant_instructions>` block, every block
    delimiter in them escaped; they never pass through `str.format`. A
    variable the frame does not declare is not interpolated."""
    frame = prompts.platform_artifact(prompt_id, version)
    if _CONTAINMENT_DELIMITER.search(frame.system + frame.template):
        # Only the code below writes the block; a frame writing one could open
        # a block the company's text then appears to sit in.
        raise ConfigError(
            "a containment frame writes a block delimiter itself",
            details={"prompt_id": prompt_id, "version": version},
        )
    _refused(
        "a variable outside the platform's set",
        (set(variables) | frame.variables) - SYSTEM_VARIABLES,
    )
    _refused(
        "the frame lets a value through raw that code does not build",
        set(frame.raw_variables) - CODE_BUILT_VARIABLES,
    )
    _refused("the frame's variable has no value", frame.variables - set(variables))
    rendered = prompts.render(
        prompt_id,
        version,
        {name: cut_utf8(variables[name], MAX_SYSTEM_VALUE_BYTES) for name in frame.variables},
        tenant_id=None,
    )
    parts = (rendered.system.strip(), rendered.user.strip())
    tag = TENANT_INSTRUCTIONS_TAG
    block = f"<{tag}>\n{escape_delimiters(instructions)}\n</{tag}>"
    return "\n\n".join([*(part for part in parts if part), block])
