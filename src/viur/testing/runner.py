"""
Runner-side preflight + cleanup helpers.

Two functions cover the runner side of the bilateral handshake:

- :func:`require_test_mode` is the preflight. It calls
  ``POST <base_url>/_test/config/status`` and verifies the response.
  The server's reply both proves the server is wired to the expected
  test database *and* hands the session token back to the runner.
  POST (not GET) so the server-side endpoint stays drive-by-resistant
  against random browser tabs on the same machine.
- :func:`finish` (call at end-of-session) hits
  ``POST <base_url>/_test/config/finish`` to delete the token from the
  test database. After that, the server's request validator goes back
  to rejecting every non-bootstrap request.

There is no on-disk state — the token lives only in the test database
and in the runner's memory.
"""

import dataclasses
import hashlib
import http.client
import json
import socket
import typing as t
import urllib.error
import urllib.request

from .constants import DEFAULT_DATABASE, TOKEN_HEADER


class TestModePreflightError(RuntimeError):
    """Raised when the runner cannot confirm the server is in test mode."""


_UNSET: t.Final = object()
"""Sentinel that distinguishes "namespace check omitted" from
``expected_namespace=None`` (which means "expect the default namespace")."""


@dataclasses.dataclass(frozen=True)
class ServerStatus:
    """Validated server-side snapshot returned by ``/_test/config/status``."""

    database: str
    namespace: str | None
    project_id: str
    token: str
    token_hash: str
    version: str


def _do_request(
    request: urllib.request.Request,
    timeout: float,
    opener: t.Callable[[urllib.request.Request, float], t.Any] | None,
) -> dict:
    do_open = opener or (lambda req, to: urllib.request.urlopen(req, timeout=to))
    try:
        response = do_open(request, timeout)
    except urllib.error.HTTPError as exc:
        raise TestModePreflightError(
            f"Server returned HTTP {exc.code} {exc.reason} for {request.full_url}. "
            "The server is likely not in test mode, or activation refused."
        ) from exc
    except (urllib.error.URLError, http.client.HTTPException, socket.timeout, OSError) as exc:
        raise TestModePreflightError(
            f"Could not reach {request.full_url}: {exc}"
        ) from exc

    body = response.read().decode("utf-8")
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise TestModePreflightError(
            f"Endpoint returned non-JSON body: {body[:200]!r}"
        ) from exc
    if not isinstance(parsed, dict):
        raise TestModePreflightError(
            f"Endpoint returned a {type(parsed).__name__}, expected object."
        )
    return parsed


def _build_status_request(base_url: str) -> urllib.request.Request:
    return urllib.request.Request(
        base_url.rstrip("/") + "/json/_test/config/status",
        headers={"Accept": "application/json"},
        method="POST",
        data=b"",
    )


def _build_finish_request(base_url: str, token: str) -> urllib.request.Request:
    return urllib.request.Request(
        base_url.rstrip("/") + "/json/_test/config/finish",
        headers={
            "Accept": "application/json",
            TOKEN_HEADER: token,
        },
        method="POST",
        data=b"",
    )


def require_test_mode(
    base_url: str,
    *,
    expected_database: str = DEFAULT_DATABASE,
    expected_namespace: str | None | t.Any = _UNSET,
    expected_project_id: str | None = None,
    timeout: float = 5.0,
    _opener: t.Callable[[urllib.request.Request, float], t.Any] | None = None,
) -> ServerStatus:
    """Block until the running server confirms it is in test mode.

    :param base_url: Origin of the server under test,
        e.g. ``http://localhost:8080``.
    :param expected_database: Database name we expect the server to be on.
        Default ``viur-tests``.
    :param expected_namespace: When supplied, the server's ``namespace``
        must match exactly. Pass ``None`` to assert the server is on the
        default namespace; omit the argument entirely to skip the check.
    :param expected_project_id: If set, the server's ``project_id`` must
        match. Use this when your CI knows which GCP project the dev
        server is bound to.
    :param timeout: HTTP timeout in seconds.
    :param _opener: Injection seam for tests.
    :raises TestModePreflightError: if any check fails. The caller must
        treat this as a hard stop and not run any test.
    :returns: A :class:`ServerStatus` snapshot, including the session token.
    """
    server = _do_request(_build_status_request(base_url), timeout, _opener)

    if server.get("test_mode") is not True:
        raise TestModePreflightError(
            f"Server reports test_mode={server.get('test_mode')!r}; "
            "refusing to run tests against a non-test instance."
        )
    if server.get("is_dev_server") is not True:
        raise TestModePreflightError(
            f"Server reports is_dev_server={server.get('is_dev_server')!r}; "
            "refusing to run tests against anything that is not a local dev server."
        )
    if server.get("database") != expected_database:
        raise TestModePreflightError(
            f"Server reports database={server.get('database')!r}, "
            f"expected {expected_database!r}."
        )
    if expected_namespace is not _UNSET and server.get("namespace") != expected_namespace:
        raise TestModePreflightError(
            f"Server reports namespace={server.get('namespace')!r}, "
            f"expected {expected_namespace!r}."
        )
    if expected_project_id is not None and server.get("project_id") != expected_project_id:
        raise TestModePreflightError(
            f"Server reports project_id={server.get('project_id')!r}, "
            f"expected {expected_project_id!r}."
        )

    token = server.get("token")
    if not isinstance(token, str) or not token:
        raise TestModePreflightError(
            "Server response is missing a non-empty 'token' string."
        )

    reported_hash = server.get("token_hash")
    expected_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    if reported_hash != expected_hash:
        raise TestModePreflightError(
            "Server's token_hash does not match the sha256 of the returned token."
        )

    return ServerStatus(
        database=server["database"],
        namespace=server.get("namespace"),
        project_id=server["project_id"],
        token=token,
        token_hash=reported_hash,
        version=server.get("version", "unknown"),
    )


def finish(
    base_url: str,
    token: str,
    *,
    timeout: float = 5.0,
    _opener: t.Callable[[urllib.request.Request, float], t.Any] | None = None,
) -> dict:
    """End the session: tell the server to delete the token entity.

    :param base_url: Origin of the server under test.
    :param token: Session token as returned by :func:`require_test_mode`.
    :param timeout: HTTP timeout in seconds.
    :param _opener: Injection seam for tests.
    :returns: The parsed JSON response
        (``{"finished": True, "had_token": ...}``).
    :raises TestModePreflightError: on transport errors or non-2xx responses.
    """
    return _do_request(_build_finish_request(base_url, token), timeout, _opener)
