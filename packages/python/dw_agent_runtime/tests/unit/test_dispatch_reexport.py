"""The runtime's three dispatch errors are the kernel's own classes
(connections-and-vault R3.13): what the egress client in `dw_connectors`
raises is what the ToolExecutor reads, with no mapping between them."""

from __future__ import annotations

import pytest

from dw_agent_runtime import dispatch as runtime_dispatch
from dw_kernel import dispatch as kernel_dispatch

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("name", ["NotDispatchedError", "RejectedError", "OutcomeUnknownError"])
def test_the_runtime_re_exports_the_kernels_class(name: str) -> None:
    assert getattr(runtime_dispatch, name) is getattr(kernel_dispatch, name)
