"""What the gateway route does with a file the model could not read.

The route is the only one that reads a document by asking a model, so it is the
only one where "I could not open this" arrives as *prose* rather than as an
error. Prose is text, and text is a successful parse - which is how a `.docx`
nobody could open finished as an indexed document, showed on screen as read, and
was quoted back as evidence about the company.

Both halves of the guard are pinned here: the instruction that gives the model a
way to say it, and the reading that recognises it when it does.
"""

from __future__ import annotations

import pathlib
import uuid
from typing import Any

import pytest

from dw_kernel.residency import Destination, ResidencyGate, TenantRouteScope
from dw_knowledge.adapters.api_parsers import GatewayFileParser
from dw_knowledge.attachment_policy import load_attachment_policy
from dw_platform.testing.residency import StaticRouteClasses

pytestmark = pytest.mark.unit

# A Vietnamese destination under a `vn_only` tenant: the gate admits it, so
# these tests are about the dialect (compliance-pdpl 03 tests the refusals).
_TENANT = uuid.uuid4()
SCOPE = TenantRouteScope(tenant_id=_TENANT, workspace_id=None)
GATE = ResidencyGate(classes=StaticRouteClasses({_TENANT: "vn_only"}))

REPO_ROOT = pathlib.Path(__file__).resolve().parents[5]
POLICY = load_attachment_policy(REPO_ROOT / "configs" / "policies" / "attachment_ingest@1.1.0.yaml")


class _StubbedGateway(GatewayFileParser):
    """The parser with its one network call replaced by a canned reply."""

    reply: str = ""

    async def _post(self, payload: dict[str, Any]) -> Any:
        return {"output_text": self.reply, "status": "completed"}


def _parser(reply: str) -> _StubbedGateway:
    parser = _StubbedGateway(
        base_url="https://gateway.invalid",
        api_key="unused",
        model="test-model",
        policy=POLICY,
        residency=GATE,
        destination=Destination("document_extraction", "vn", "fpt_ai_gateway"),
    )
    parser.reply = reply
    return parser


def test_the_document_prompt_tells_the_model_how_to_say_nothing_is_readable() -> None:
    """Without this line the model writes its own sentence, which is content."""
    assert POLICY.empty_marker in POLICY.document_instruction
    assert POLICY.empty_marker in POLICY.image_instruction


async def test_a_readable_document_comes_back_as_its_own_text() -> None:
    parsed = await _parser("```markdown\n# Biên bản họp\nNgân sách 18 tỷ.\n```").parse(
        b"x", "application/pdf", "bien-ban.pdf", scope=SCOPE
    )

    assert parsed.text == "# Biên bản họp\nNgân sách 18 tỷ."


@pytest.mark.parametrize(
    "reply",
    [
        "[không đọc được nội dung]",
        "  [không đọc được nội dung]\n",
        # What a model actually returns when it is being helpful: the marker
        # with a sentence around it. Read as content, that sentence became the
        # document.
        "Rất tiếc, tôi không mở được tệp này. [không đọc được nội dung]",
    ],
)
async def test_a_file_the_model_could_not_read_parses_to_nothing(reply: str) -> None:
    """Empty, not "the model said it could not read this".

    An empty parse is what makes the ingest job fail, which is what makes the
    file say "could not read this" on screen and keeps it out of the index.
    """
    parsed = await _parser(reply).parse(b"x", "application/pdf", "hong.pdf", scope=SCOPE)

    assert parsed.text == ""
