"""The tenant-wide scope's registry a test hands the offboarding lane.

The worker's composition root builds the real one (`build_tenant_wide_scopes`
in `dw_worker.main`); a test builds its own here rather than importing the
worker, and `test_session_setting_scan.py` allows a registry to be built in
tests and at that root only (record-access ticket 03, gate (f)).
"""

from __future__ import annotations

from dw_platform.adapters.persistence.offboarding import OFFBOARDING_LANE
from dw_platform.adapters.persistence.tenant_session import (
    TenantWideLane,
    TenantWideScopeRegistry,
)

OFFBOARDING_SCOPES = TenantWideScopeRegistry(
    TenantWideLane(
        lane=OFFBOARDING_LANE,
        reason="the offboarding lane under test",
        reads_private_tables=True,
    )
)
