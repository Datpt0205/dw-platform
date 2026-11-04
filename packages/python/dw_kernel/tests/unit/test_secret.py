"""A `Secret` prints, formats and serialises as a mask (connections-and-vault R1.2, CV4)."""

from __future__ import annotations

import copy
import json
import logging
import pickle

import pytest
from pydantic import BaseModel, ConfigDict
from pydantic_core import PydanticSerializationError

from dw_kernel.secret import Secret

pytestmark = pytest.mark.unit

CANARY = "canary-7f3a9c1e-không-được-lộ"


class _Holder(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    password: Secret


def test_the_value_comes_out_only_through_reveal() -> None:
    secret = Secret(CANARY)
    assert secret.reveal() == CANARY
    percent = "%s" % secret  # noqa: UP031 - the formatting `logging` uses
    for shown in (repr(secret), str(secret), f"{secret}", f"{secret!r}", f"{secret:>40}", percent):
        assert CANARY not in shown
    assert "***" in str(secret)


def test_json_pickle_and_copy_refuse_it() -> None:
    secret = Secret(CANARY)
    with pytest.raises(TypeError):
        json.dumps({"password": secret})
    with pytest.raises(TypeError, match="not serialised"):
        pickle.dumps(secret)
    with pytest.raises(TypeError, match="not serialised"):
        copy.deepcopy(secret)


def test_a_model_holding_one_dumps_no_value() -> None:
    holder = _Holder(password=Secret(CANARY))
    assert CANARY not in str(holder.model_dump())
    assert CANARY not in repr(holder)
    with pytest.raises(PydanticSerializationError):
        holder.model_dump_json()


def test_a_log_line_that_picks_one_up_carries_the_mask(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        logging.getLogger("probe").info("connecting with %s", Secret(CANARY))
    assert CANARY not in caplog.text
    assert "***" in caplog.text


def test_only_text_is_held() -> None:
    with pytest.raises(TypeError):
        Secret(b"bytes")  # type: ignore[arg-type]
