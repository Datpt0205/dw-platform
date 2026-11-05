"""Test doubles and contract checks of Studio's `workflow` kind
(workflow-engine/03): the record doors' fakes, their contract, and the golden
traces of the W1 core."""

from dw_studio.workflows.testing.fakes import FakeRecordAssignPort, FakeRecordsPort

__all__ = ["FakeRecordAssignPort", "FakeRecordsPort"]
