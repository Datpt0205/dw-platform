"""What the API's composition root turns on for a configuration version
(tenant-config ticket 05, R8.8, R8.9, R3.7).

The services' own tests prove the rules hold when configured; this proves
they are configured in the container the API serves: `config.` strict, the
`config.version` guard registered, the bindings routes' services built, and a
connection's dependents answered from approved Binding sets rather than the
placeholder that counts none.
"""

import pytest

from dw_api.bootstrap import build_container
from dw_api.settings import ApiSettings
from dw_platform.application.config_versions import CONFIG_VERSION, ConfigVersionDecisions
from dw_studio.core.application.bindings import BindingConnectionDependents

pytestmark = pytest.mark.unit


def test_the_api_decides_configuration_versions_strictly_and_through_their_guard() -> None:
    container = build_container(
        ApiSettings(
            profile="test",
            database_url="postgresql+asyncpg://wiring:wiring@localhost:5432/wiring",
            dev_secret="wiring-test-secret-0123456789abcdef",
            s3_endpoint_url="http://localhost:9000",
            s3_access_key="wiring",
            s3_secret_key="wiring",
            model_provider="mock",
        )
    )
    flow = container.approval_flow
    assert flow is not None
    assert flow.is_strict(CONFIG_VERSION)
    assert isinstance(flow.decision_guards.get(CONFIG_VERSION), ConfigVersionDecisions)
    assert container.studio is not None
    assert container.studio.config_versions is not None
    assert container.connections is not None
    assert isinstance(container.connections.dependents_port, BindingConnectionDependents)
