"""`RuntimeSeam` hands a bounded context metered model doors only
(usage-and-limits R6.1, UL4; ADR-0121 decision 7).

Read from the dataclass's own annotations: a field typed as a bare door (the
routing gateway, a chat factory that builds unguarded models, an embedding or
rerank port, a provider adapter) fails here, whatever the composition root
happens to pass today. What the root builds is `test_wf_ai_wiring.py`'s.
"""

from __future__ import annotations

import types
import typing
from typing import Any

import pytest
from langchain_core.language_models import BaseChatModel

from dw_agent_runtime.adapters.chat_model import (
    ChatModelFactory,
    LimitedChatModelFactory,
    MockChatModelFactory,
    OpenAICompatibleChatModelFactory,
)
from dw_agent_runtime.model.gateway import ModelProviderAdapter
from dw_agent_runtime.model.routing import RoutingModelGateway
from dw_agent_runtime.model.single_call import SingleCallModelGateway
from dw_agent_runtime.ports import MeteredModelGateway, ModelGateway, TracedModelGateway
from dw_api.bootstrap.container import RuntimeSeam
from dw_knowledge.ports import EmbeddingPort, RerankPort

pytestmark = pytest.mark.unit

# Every type through which a model is reached without a lease's say.
_BARE: frozenset[Any] = frozenset(
    {
        RoutingModelGateway,
        SingleCallModelGateway,
        ModelGateway,
        TracedModelGateway,
        ModelProviderAdapter,
        ChatModelFactory,
        OpenAICompatibleChatModelFactory,
        MockChatModelFactory,
        BaseChatModel,
        EmbeddingPort,
        RerankPort,
    }
)
# The doors of the seam and the one type each must have.
_METERED: dict[str, Any] = {
    "gateway": MeteredModelGateway,
    "chat_models": LimitedChatModelFactory | None,
}


def _parts(hint: Any) -> set[Any]:
    """A field's type and every type it is a union of."""
    if isinstance(hint, types.UnionType) or typing.get_origin(hint) is typing.Union:
        return {part for arg in typing.get_args(hint) for part in _parts(arg)}
    return {hint}


def test_no_field_of_the_seam_is_a_bare_model_door() -> None:
    hints = typing.get_type_hints(RuntimeSeam)
    bare = {name: hint for name, hint in hints.items() if _parts(hint) & _BARE}
    assert bare == {}


def test_each_model_door_of_the_seam_is_its_metered_type() -> None:
    hints = typing.get_type_hints(RuntimeSeam)
    assert {name: hints[name] for name in _METERED} == _METERED
