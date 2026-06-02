"""Unit tests for :mod:`viur.testing.validator`."""

import types

import pytest

from viur.testing.constants import TOKEN_HEADER
from viur.testing._test.config import ConfigModule
from viur.testing.validator import ProductionGuardValidator, TokenValidator


def _make_request(headers: dict | None = None, path: str = "/some/route"):
    return types.SimpleNamespace(
        request=types.SimpleNamespace(
            headers=headers or {},
            path=path,
        ),
    )


@pytest.fixture(autouse=True)
def _reset_test_module_state():
    ConfigModule.reset()
    yield
    ConfigModule.reset()


def test_token_header_constant_is_renamed():
    """Header name must no longer carry 'E2E'."""
    assert TOKEN_HEADER == "X-Viur-Test-Token"


def test_validate_returns_403_when_state_inactive():
    result = TokenValidator.validate(_make_request())
    assert result is not None
    assert result[0] == 403
    assert "not in test mode" in result[2]


def test_validate_returns_403_when_no_token_issued_yet():
    ConfigModule.set_active(database="viur-tests", project_id="p")
    result = TokenValidator.validate(
        _make_request(headers={TOKEN_HEADER: "anything"})
    )
    assert result is not None
    assert result[0] == 403
    assert "no session token" in result[2]


def test_validate_returns_403_when_header_missing():
    ConfigModule.set_active(database="viur-tests", project_id="p")
    ConfigModule.set_token("secret")
    result = TokenValidator.validate(_make_request(headers={}))
    assert result is not None
    assert result[0] == 403
    assert "missing" in result[2].lower()


def test_validate_returns_403_when_token_wrong():
    ConfigModule.set_active(database="viur-tests", project_id="p")
    ConfigModule.set_token("secret")
    result = TokenValidator.validate(
        _make_request(headers={TOKEN_HEADER: "nope"})
    )
    assert result is not None
    assert result[0] == 403
    assert "invalid" in result[2].lower()


def test_validate_passes_with_correct_token():
    ConfigModule.set_active(database="viur-tests", project_id="p")
    ConfigModule.set_token("secret")
    result = TokenValidator.validate(
        _make_request(headers={TOKEN_HEADER: "secret"})
    )
    assert result is None


def test_validate_tokenless_allows_without_token_in_dev(conf_instance):
    """Dev-Mirror tokenless: armed + whitelisted + namespaced + dev server →
    any request passes without a token header."""
    conf_instance.is_dev_server = True
    ConfigModule.set_active(database="viur-tests", project_id="p", namespace="ak")
    ConfigModule.arm_tokenless(["p"])
    result = TokenValidator.validate(_make_request(headers={}))
    assert result is None


def test_validate_tokenless_still_requires_token_outside_dev(conf_instance):
    """Even when tokenless is armed, a non-dev process must NOT open up — the
    validator re-checks is_dev_server and falls back to the token path."""
    conf_instance.is_dev_server = False
    ConfigModule.set_active(database="viur-tests", project_id="p", namespace="ak")
    ConfigModule.set_token("secret")
    ConfigModule.arm_tokenless(["p"])
    result = TokenValidator.validate(_make_request(headers={}))
    assert result is not None
    assert result[0] == 403  # missing token — tokenless bypass did not fire


@pytest.mark.parametrize(
    "path",
    [
        "/_test/config/status",
        "/_test/config/finish",
        "/json/_test/config/status",
        "/html/_test/config/finish",
    ],
)
def test_validate_bypasses_bootstrap_paths_without_token(path):
    """Status + finish must be reachable even before a token exists."""
    ConfigModule.set_active(database="viur-tests", project_id="p")
    result = TokenValidator.validate(_make_request(headers={}, path=path))
    assert result is None


def test_validate_bypasses_status_when_state_active_and_no_token():
    """Bootstrap bypass kicks in *before* the token check.

    Crucial because /_test/config/status is what *creates* the token in the
    first place; without this branch the runner could never bootstrap.
    """
    ConfigModule.set_active(database="viur-tests", project_id="p")
    result = TokenValidator.validate(
        _make_request(headers={}, path="/_test/config/status")
    )
    assert result is None


def test_validate_does_not_bypass_lookalike_paths():
    """Suffix match must not match a path that just happens to end in /status."""
    ConfigModule.set_active(database="viur-tests", project_id="p")
    result = TokenValidator.validate(
        _make_request(headers={}, path="/api/status")
    )
    assert result is not None
    assert result[0] == 403


@pytest.mark.parametrize(
    "path",
    [
        # Deeper than 4 segments — even though the trailing chunk
        # matches, a non-renderer first segment plus a normal
        # ``_test/config/status`` further down was previously accepted
        # by the suffix-endswith implementation. Now refused.
        "/a/b/_test/config/status",
        "/a/b/c/_test/config/finish",
        # Trailing extra segment after the action.
        "/_test/config/status/extra",
        "/json/_test/config/finish/extra",
        # Wrong action.
        "/_test/config/teardown",
        "/json/_test/config/foo",
        # Wrong middle segment.
        "/_test/configX/status",
        "/json/_test/configX/status",
        # Wrong _test segment.
        "/_testX/config/status",
    ],
)
def test_validate_does_not_bypass_oddly_shaped_paths(path):
    """The defence-in-depth contract is: only ``/_test/config/<action>``
    or ``/<renderer>/_test/config/<action>`` bypass the token. Anything
    else must take the token-checked path."""
    ConfigModule.set_active(database="viur-tests", project_id="p")
    result = TokenValidator.validate(_make_request(headers={}, path=path))
    assert result is not None
    assert result[0] == 403


@pytest.mark.parametrize("path", [None, ""])
def test_validate_does_not_bypass_falsy_path(path):
    ConfigModule.set_active(database="viur-tests", project_id="p")
    ConfigModule.set_token("secret")
    result = TokenValidator.validate(
        _make_request(headers={TOKEN_HEADER: "secret"}, path=path)
    )
    assert result is None  # token still matched, just not via bypass


def test_validate_uses_constant_time_compare(monkeypatch):
    import hmac

    ConfigModule.set_active(database="viur-tests", project_id="p")
    ConfigModule.set_token("secret")

    calls = []
    real = hmac.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr("viur.testing.validator.hmac.compare_digest", spy)
    TokenValidator.validate(_make_request(headers={TOKEN_HEADER: "secret"}))
    assert calls == [("secret", "secret")]


# ---------------------------------------------------------------------------
# ProductionGuardValidator
# ---------------------------------------------------------------------------


def test_production_guard_passes_when_header_absent_in_prod(conf_instance):
    conf_instance.is_dev_server = False
    result = ProductionGuardValidator.validate(_make_request(headers={}))
    assert result is None


def test_production_guard_passes_when_header_absent_in_dev(conf_instance):
    conf_instance.is_dev_server = True
    result = ProductionGuardValidator.validate(_make_request(headers={}))
    assert result is None


def test_production_guard_passes_in_dev_even_with_header(conf_instance):
    """In dev, the full TokenValidator handles the header — guard is no-op."""
    conf_instance.is_dev_server = True
    result = ProductionGuardValidator.validate(
        _make_request(headers={TOKEN_HEADER: "anything"})
    )
    assert result is None


def test_production_guard_rejects_header_in_prod(conf_instance):
    conf_instance.is_dev_server = False
    result = ProductionGuardValidator.validate(
        _make_request(headers={TOKEN_HEADER: "anything"})
    )
    assert result is not None
    code, _, body = result
    assert code == 403
    assert "not accepted" in body


def test_production_guard_rejects_header_regardless_of_value(conf_instance):
    """Even an empty-string value with the header present should pass through."""
    conf_instance.is_dev_server = False
    # Note: getheader("...") returns the value; "" is falsy, so absent-equivalent
    # for our `if not header` short-circuit. That's intentional — only the
    # presence of a non-empty value is suspicious enough to block.
    for value in ["x", "fake-token", "a" * 200, "../etc/passwd"]:
        result = ProductionGuardValidator.validate(
            _make_request(headers={TOKEN_HEADER: value})
        )
        assert result is not None and result[0] == 403, value


def test_production_guard_treats_empty_string_as_missing(conf_instance):
    """Empty header value should not trigger the guard — same as absent."""
    conf_instance.is_dev_server = False
    result = ProductionGuardValidator.validate(
        _make_request(headers={TOKEN_HEADER: ""})
    )
    assert result is None
