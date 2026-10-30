"""The dev mailbox's API, Mailpit (leadcare R3.3): the latest message from one
address to another received after a moment.

`GET /api/v1/search?query=from:<a> to:<b>` lists messages newest first, each
with its `Created` time; `GET /api/v1/message/<ID>` is the one message with its
plain `Text`. Nothing is written.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import httpx


@dataclass(frozen=True)
class MailboxReply:
    text: str
    received_at: datetime


def _when(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass(frozen=True)
class MailpitMailbox:
    base_url: str
    timeout_seconds: float = 10.0
    transport: httpx.AsyncBaseTransport | None = None

    async def latest_reply(
        self, *, sender: str, recipient: str, since: datetime
    ) -> MailboxReply | None:
        async with httpx.AsyncClient(
            base_url=self.base_url.rstrip("/"),
            timeout=self.timeout_seconds,
            transport=self.transport,
        ) as client:
            listed = await client.get(
                "/api/v1/search", params={"query": f"from:{sender} to:{recipient}"}
            )
            listed.raise_for_status()
            newer = [
                m
                for m in listed.json().get("messages") or []
                if _when(str(m.get("Created", "1970-01-01T00:00:00Z"))) > since
            ]
            if not newer:
                return None
            latest = max(newer, key=lambda m: _when(str(m["Created"])))
            detail = await client.get(f"/api/v1/message/{latest['ID']}")
            detail.raise_for_status()
            return MailboxReply(
                text=str(detail.json().get("Text") or ""), received_at=_when(latest["Created"])
            )
