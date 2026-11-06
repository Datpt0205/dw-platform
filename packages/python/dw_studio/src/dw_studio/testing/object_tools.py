"""An object version and its live definition without a database, for the
object tools' unit tests and graders (tools-and-skills ticket 03).

`applied_of` is a `dw.object/v1` document as `applied_object` would read it
once published: what the document decides, each filterable field in a slot of
its family, `name`, `owner` and `workspace` as system columns. `pinned_of` is
the version row a run manifest holds for it. Neither decides anything: the
real path (a publish through the hook, a manifest, RecordService) is the
integration suite's.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from dw_agent_runtime.model.copy import load_copy_codes
from dw_agent_runtime.ports import PinnedEntry, PinnedVersion
from dw_studio.records.application.object_tools import ObjectToolCopy
from dw_studio.records.application.ports import AppliedObject, FieldStorage
from dw_studio.records.domain.document import (
    NAME,
    OBJECT_DOCUMENT_SCHEMA,
    OWNER,
    WORKSPACE,
    definition_of,
)

COPY_FILE: Final = Path("configs") / "copy" / "studio_object_tools.yaml"
_FAMILY: Final[Mapping[str, str]] = {
    "number": "i",
    "currency": "i",
    "boolean": "b",
    "date": "d",
    "datetime": "z",
}


def object_tool_copy(repo_root: Path) -> ObjectToolCopy:
    return ObjectToolCopy.of(load_copy_codes(repo_root / COPY_FILE))


def applied_of(
    document: Mapping[str, Any],
    *,
    api_name: str,
    object_id: uuid.UUID,
    version_no: int = 1,
) -> AppliedObject:
    decided = definition_of(document)
    storage: dict[str, FieldStorage] = {}
    used: dict[str, int] = {}
    for number, (name, field) in enumerate(sorted(decided.fields.items()), start=1):
        field_id = uuid.uuid5(object_id, name)
        if name == NAME:
            storage[name] = FieldStorage(field_id, "system", None, None)
        elif field.indexed or field.is_unique:
            family = _FAMILY.get(field.type, "t")
            used[family] = used.get(family, 0) + 1
            storage[name] = FieldStorage(field_id, "slot", f"{family}{used[family]:02d}", number)
        else:
            storage[name] = FieldStorage(field_id, "data", None, number)
    for name in (OWNER, WORKSPACE):
        storage[name] = FieldStorage(uuid.uuid5(object_id, name), "system", None, None)
    return AppliedObject(
        object_id=object_id,
        api_name=api_name,
        applied_version_id=uuid.uuid5(object_id, f"v{version_no}"),
        schema_version=version_no,
        definition=decided,
        storage=storage,
    )


def pinned_of(
    document: Mapping[str, Any], *, object_id: uuid.UUID, version_no: int = 1
) -> PinnedEntry:
    """The manifest's entry for the object at ``version_no``, its row read."""
    version_id = uuid.uuid5(object_id, f"v{version_no}")
    content_hash = "sha256:" + version_id.hex * 2
    row = PinnedVersion(
        id=version_id,
        artifact_id=object_id,
        version_no=version_no,
        stage="live",
        content_hash=content_hash,
        definition_hash=content_hash,
        document_schema=OBJECT_DOCUMENT_SCHEMA,
        document=dict(document),
        current_hash=None,
    )
    return PinnedEntry("artifact", str(object_id), version_no, content_hash, row)
