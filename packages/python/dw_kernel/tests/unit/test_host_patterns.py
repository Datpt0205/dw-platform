"""One normalizer and one matcher for Allowed hosts (connections-and-vault R3.21)."""

from __future__ import annotations

import pytest

from dw_kernel.host_patterns import normalize_host, pattern_matches

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("host", "normalized"),
    [
        ("api.acme.vn", "api.acme.vn"),
        ("API.Acme.vn.", "api.acme.vn"),
        ("bộ-công-an.vn", "xn--b-cng-an-63a1467e.vn"),
        ("xn--b-cng-an-63a1467e.vn", "xn--b-cng-an-63a1467e.vn"),
    ],
)
def test_a_host_is_lower_case_without_its_trailing_dot_and_ascii(
    host: str, normalized: str
) -> None:
    assert normalize_host(host) == normalized


@pytest.mark.parametrize("host", ["", ".", "a..b", " api.acme.vn", "x" * 64 + ".vn"])
def test_a_name_that_names_no_host_is_refused(host: str) -> None:
    with pytest.raises(ValueError):
        normalize_host(host)


@pytest.mark.parametrize(
    ("pattern", "host", "matches"),
    [
        ("*.acme.vn", "api.acme.vn", True),
        ("*.acme.vn", "acme.vn", False),
        ("*.acme.vn", "a.b.acme.vn", False),
        ("*.acme.vn", "api.acme.vn.evil.com", False),
        ("*.acme.vn", "apiacme.vn", False),
        ("*.acme.vn", ".acme.vn", False),
        ("api.acme.vn", "api.acme.vn", True),
        ("api.acme.vn", "x.api.acme.vn", False),
        ("api.acme.vn", "acme.vn", False),
    ],
)
def test_a_wildcard_matches_exactly_one_label_and_a_name_only_itself(
    pattern: str, host: str, matches: bool
) -> None:
    """R3.21 (CV19): a match on two labels, or on the domain itself, turns this red."""
    assert pattern_matches(pattern, host) is matches
