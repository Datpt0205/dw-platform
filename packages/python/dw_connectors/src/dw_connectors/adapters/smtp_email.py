"""One email over SMTP (leadcare R3.1, R3.7): stdlib `smtplib` in a thread.

The sender says, by the type it raises, how far the message got, so a caller
never sends twice a message that may have left:

- `SmtpNotSentError`: nothing left (the connection or the greeting failed);
- `SmtpRejectedError`: the server answered that it refused the message;
- `SmtpOutcomeUnknownError`: the message may have left (a timeout or a lost
  connection once the envelope was being sent, `DATA` included).

Which hosts it may reach is the caller's rule (the tool refuses anything but
the dev mailbox, R3.6), checked before this is called: this adapter opens a
connection to whatever it is given.
"""

from __future__ import annotations

import asyncio
import smtplib
from collections.abc import Mapping
from dataclasses import dataclass
from email.message import EmailMessage


class SmtpNotSentError(Exception):
    """Nothing left: sending again is safe."""


class SmtpRejectedError(Exception):
    """The server refused the message, with its code."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"{code} {message}")
        self.code = code


class SmtpOutcomeUnknownError(Exception):
    """The message may have left: never sent again without a person."""


@dataclass(frozen=True)
class SmtpEmailSender:
    host: str
    port: int = 25
    timeout_seconds: float = 20.0

    async def send(
        self,
        *,
        sender: str,
        to: str,
        subject: str,
        body: str,
        headers: Mapping[str, str],
    ) -> None:
        message = EmailMessage()
        message["From"] = sender
        message["To"] = to
        message["Subject"] = subject
        for name, value in headers.items():
            message[name] = value
        message.set_content(body)
        await asyncio.to_thread(self._send, message)

    def _send(self, message: EmailMessage) -> None:
        try:
            client = smtplib.SMTP(self.host, self.port, timeout=self.timeout_seconds)
        except (OSError, smtplib.SMTPException) as exc:
            raise SmtpNotSentError(str(exc)) from exc
        try:
            client.send_message(message)
        except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused) as exc:
            raise SmtpRejectedError(550, str(exc)) from exc
        except smtplib.SMTPDataError as exc:
            raise SmtpRejectedError(exc.smtp_code, str(exc.smtp_error)) from exc
        except (TimeoutError, OSError, smtplib.SMTPException) as exc:
            # The envelope was on its way: the server may have taken it.
            raise SmtpOutcomeUnknownError(str(exc)) from exc
        finally:
            try:
                client.quit()
            except (OSError, smtplib.SMTPException):
                client.close()
