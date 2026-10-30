import pytest

from dw_observability.metrics import ALL_METRICS
from dw_observability.redaction import REDACTED, is_sensitive_key, redact_mapping, redact_text

pytestmark = pytest.mark.unit


def test_sensitive_keys_detected() -> None:
    for key in ["password", "API_KEY", "client_secret", "Authorization", "access_key_id"]:
        assert is_sensitive_key(key), key
    for key in ["tenant_id", "meeting_title", "worker_version"]:
        assert not is_sensitive_key(key), key


def test_redact_mapping_recurses() -> None:
    cleaned = redact_mapping(
        {
            "tenant_id": "t-1",
            "api_key": "sk-live-123",
            "nested": {"password": "hunter2", "note": "ok"},
        }
    )
    assert cleaned["api_key"] == REDACTED
    nested = cleaned["nested"]
    assert isinstance(nested, dict)
    assert nested["password"] == REDACTED
    assert nested["note"] == "ok"
    assert cleaned["tenant_id"] == "t-1"


def test_redact_bearer_tokens_in_text() -> None:
    text = "header was Authorization: Bearer abc.def-ghi_jkl123 and more"
    assert "abc.def" not in redact_text(text)
    assert REDACTED in redact_text(text)


def test_metric_names_follow_dw_prefix() -> None:
    assert all(name.startswith("dw_") for name in ALL_METRICS)
    assert len(set(ALL_METRICS)) == len(ALL_METRICS)


def test_redact_mapping_walks_lists_and_tuples_at_any_depth() -> None:
    """runtime-hardening R6.5: a key in a list used to come out verbatim."""
    cleaned = redact_mapping(
        {
            "items": [{"api_key": "sk-123", "name": "a"}],
            "pairs": ({"token": "t-1"}, "Bearer abcdefgh.ijk"),
            "deep": [[{"nested": {"client_secret": "s-1"}}]],
        }
    )
    assert cleaned["items"] == [{"api_key": REDACTED, "name": "a"}]
    assert cleaned["pairs"] == [{"token": REDACTED}, f"Bearer {REDACTED}"]
    assert cleaned["deep"] == [[{"nested": {"client_secret": REDACTED}}]]
    assert "sk-123" not in str(cleaned) and "s-1" not in str(cleaned)
