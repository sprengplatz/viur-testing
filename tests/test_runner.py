"""Unit tests for :mod:`viur.testing.runner`."""

import hashlib
import io
import json
import urllib.error

import pytest

from viur.testing import runner


def _fake_response(payload):
    if isinstance(payload, dict):
        payload = json.dumps(payload)
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return io.BytesIO(payload)


def _stub_opener(payload):
    captured = {}

    def opener(req, timeout):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["headers"] = dict(req.header_items())
        captured["data"] = req.data
        captured["timeout"] = timeout
        if isinstance(payload, Exception):
            raise payload
        return _fake_response(payload)

    return opener, captured


def _server_payload(token, database="viur-tests", project_id="proj", namespace=None):
    return {
        "test_mode": True,
        "is_dev_server": True,
        "database": database,
        "namespace": namespace,
        "project_id": project_id,
        "token": token,
        "token_hash": hashlib.sha256(token.encode("utf-8")).hexdigest(),
        "version": "0.1.0",
    }


# ---------------------------------------------------------------------------
# require_test_mode()
# ---------------------------------------------------------------------------


def test_require_test_mode_happy_path():
    opener, captured = _stub_opener(_server_payload("tok"))
    status = runner.require_test_mode("http://localhost:8080", _opener=opener)
    assert status.token == "tok"
    assert status.database == "viur-tests"
    assert status.namespace is None
    assert status.project_id == "proj"
    assert captured["url"] == "http://localhost:8080/json/_test/config/status"
    assert captured["method"] == "POST"


def test_require_test_mode_returns_namespace_from_response():
    opener, _ = _stub_opener(_server_payload("tok", namespace="alice"))
    status = runner.require_test_mode("http://localhost", _opener=opener)
    assert status.namespace == "alice"


def test_expected_namespace_check_skipped_by_default():
    """Without ``expected_namespace``, the runner accepts any namespace
    (including the default ``None``)."""
    opener, _ = _stub_opener(_server_payload("tok", namespace="anything"))
    status = runner.require_test_mode("http://localhost", _opener=opener)
    assert status.namespace == "anything"


def test_expected_namespace_match_passes():
    opener, _ = _stub_opener(_server_payload("tok", namespace="alice"))
    status = runner.require_test_mode(
        "http://localhost", expected_namespace="alice", _opener=opener,
    )
    assert status.namespace == "alice"


def test_expected_namespace_mismatch_raises():
    opener, _ = _stub_opener(_server_payload("tok", namespace="bob"))
    with pytest.raises(runner.TestModePreflightError, match="namespace="):
        runner.require_test_mode(
            "http://localhost", expected_namespace="alice", _opener=opener,
        )


def test_expected_namespace_none_asserts_default_namespace():
    """``expected_namespace=None`` is an explicit assertion: the server
    must be on the Datastore default namespace."""
    opener, _ = _stub_opener(_server_payload("tok", namespace="alice"))
    with pytest.raises(runner.TestModePreflightError, match="namespace="):
        runner.require_test_mode(
            "http://localhost", expected_namespace=None, _opener=opener,
        )


def test_require_test_mode_strips_trailing_slash():
    opener, captured = _stub_opener(_server_payload("tok"))
    runner.require_test_mode("http://localhost:8080/", _opener=opener)
    assert captured["url"] == "http://localhost:8080/json/_test/config/status"


def test_test_mode_false_raises():
    payload = _server_payload("tok")
    payload["test_mode"] = False
    opener, _ = _stub_opener(payload)
    with pytest.raises(runner.TestModePreflightError, match="test_mode=False"):
        runner.require_test_mode("http://localhost", _opener=opener)


def test_is_dev_server_false_raises():
    payload = _server_payload("tok")
    payload["is_dev_server"] = False
    opener, _ = _stub_opener(payload)
    with pytest.raises(runner.TestModePreflightError, match="is_dev_server"):
        runner.require_test_mode("http://localhost", _opener=opener)


def test_database_mismatch_raises():
    opener, _ = _stub_opener(_server_payload("tok", database="other"))
    with pytest.raises(runner.TestModePreflightError, match="database="):
        runner.require_test_mode("http://localhost", _opener=opener)


def test_custom_expected_database_passes():
    opener, _ = _stub_opener(_server_payload("tok", database="custom"))
    status = runner.require_test_mode(
        "http://localhost", expected_database="custom", _opener=opener
    )
    assert status.database == "custom"


def test_project_id_check_skipped_by_default():
    opener, _ = _stub_opener(_server_payload("tok", project_id="anything"))
    status = runner.require_test_mode("http://localhost", _opener=opener)
    assert status.project_id == "anything"


def test_project_id_mismatch_raises_when_expected():
    opener, _ = _stub_opener(_server_payload("tok", project_id="other"))
    with pytest.raises(runner.TestModePreflightError, match="project_id="):
        runner.require_test_mode(
            "http://localhost",
            expected_project_id="expected",
            _opener=opener,
        )


def test_missing_token_raises():
    payload = _server_payload("tok")
    del payload["token"]
    opener, _ = _stub_opener(payload)
    with pytest.raises(runner.TestModePreflightError, match="non-empty 'token'"):
        runner.require_test_mode("http://localhost", _opener=opener)


def test_empty_token_raises():
    payload = _server_payload("tok")
    payload["token"] = ""
    opener, _ = _stub_opener(payload)
    with pytest.raises(runner.TestModePreflightError, match="non-empty 'token'"):
        runner.require_test_mode("http://localhost", _opener=opener)


def test_non_string_token_raises():
    payload = _server_payload("tok")
    payload["token"] = 123
    opener, _ = _stub_opener(payload)
    with pytest.raises(runner.TestModePreflightError, match="non-empty 'token'"):
        runner.require_test_mode("http://localhost", _opener=opener)


def test_token_hash_mismatch_raises():
    payload = _server_payload("tok")
    payload["token_hash"] = "deadbeef"
    opener, _ = _stub_opener(payload)
    with pytest.raises(runner.TestModePreflightError, match="token_hash"):
        runner.require_test_mode("http://localhost", _opener=opener)


def test_http_error_raises():
    err = urllib.error.HTTPError(
        url="http://localhost/_e2e/status",
        code=403,
        msg="Forbidden",
        hdrs=None,
        fp=None,
    )
    opener, _ = _stub_opener(err)
    with pytest.raises(runner.TestModePreflightError, match="HTTP 403"):
        runner.require_test_mode("http://localhost", _opener=opener)


def test_connection_error_raises():
    err = urllib.error.URLError("connection refused")
    opener, _ = _stub_opener(err)
    with pytest.raises(runner.TestModePreflightError, match="Could not reach"):
        runner.require_test_mode("http://localhost", _opener=opener)


def test_non_json_body_raises():
    opener, _ = _stub_opener("not json")
    with pytest.raises(runner.TestModePreflightError, match="non-JSON"):
        runner.require_test_mode("http://localhost", _opener=opener)


def test_non_object_body_raises():
    opener, _ = _stub_opener("[1, 2, 3]")
    with pytest.raises(runner.TestModePreflightError, match="expected object"):
        runner.require_test_mode("http://localhost", _opener=opener)


def test_version_defaults_to_unknown():
    payload = _server_payload("tok")
    del payload["version"]
    opener, _ = _stub_opener(payload)
    status = runner.require_test_mode("http://localhost", _opener=opener)
    assert status.version == "unknown"


# ---------------------------------------------------------------------------
# finish()
# ---------------------------------------------------------------------------


def test_finish_posts_with_token_header():
    opener, captured = _stub_opener({"finished": True, "had_token": True})
    result = runner.finish("http://localhost:8080", "tok", _opener=opener)
    assert result == {"finished": True, "had_token": True}
    assert captured["url"] == "http://localhost:8080/json/_test/config/finish"
    assert captured["method"] == "POST"
    headers = {k.lower(): v for k, v in captured["headers"].items()}
    assert headers["x-viur-test-token"] == "tok"


def test_finish_propagates_http_errors():
    err = urllib.error.HTTPError(
        url="http://localhost/_e2e/finish",
        code=403,
        msg="Forbidden",
        hdrs=None,
        fp=None,
    )
    opener, _ = _stub_opener(err)
    with pytest.raises(runner.TestModePreflightError, match="HTTP 403"):
        runner.finish("http://localhost", "tok", _opener=opener)
