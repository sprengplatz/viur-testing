"""
Per-request token validator.

Once :func:`viur.testing.activate` has run, :class:`TokenValidator` is appended
to ``viur.core.request.Router.requestValidators``. From that point on,
every incoming request must either:

- target one of the bootstrap endpoints whose path ends in
  ``/_test/config/status`` or ``/_test/config/finish`` (they need to be
  reachable before a token exists and they re-verify the runtime
  themselves), or
- carry a matching ``X-Viur-Test-Token`` header.

Anything else is rejected with 403 before any module code runs.

This is the second leg of the bilateral check: the activation probe wires
the server to the test database, and the validator ensures the server
answers any subsequent request only to a caller who can prove they also
mean to talk to the test instance.

Imports are kept lazy: :class:`TokenValidator` itself only imports the
viur-core ``RequestValidator`` base class at module load (which is
unavoidable for the subclass relation), while the per-request state and
constant lookups happen inside :meth:`validate` so the path used by
:mod:`viur.testing.activation` to install this validator stays free of any
top-level reference to :mod:`viur.testing._test.config`.
"""

import hmac
import typing as t

from viur.core.request import RequestValidator

if t.TYPE_CHECKING:
    from viur.core.request import BrowseHandler


def _is_bootstrap_path(path: str | None, suffixes: tuple[str, ...]) -> bool:
    """True if ``path`` targets one of the un-tokened bootstrap endpoints.

    Suffix match works regardless of the render prefix viur-core folds in
    (``/json/_test/config/status``, ``/html/_test/config/status``, plain
    ``/_test/config/status`` …). The leading slash on the suffix prevents
    accidental prefix collision (``/foo_test/config/status`` would not match).
    """
    if not path:
        return False
    return any(path.endswith(suffix) for suffix in suffixes)


class ProductionGuardValidator(RequestValidator):
    """Reject any request that carries a test-token header outside dev.

    Defense in depth: the full :class:`TokenValidator` is only installed
    inside :func:`viur.testing.activate`, which itself refuses to run outside
    a local dev server. A cloud deployment therefore normally has *no*
    e2e validator at all — which means the ``X-Viur-Test-Token`` header
    would be ignored rather than rejected.

    This validator closes that gap. The host installs it explicitly via
    :func:`viur.testing.protect` in **every** environment. In a dev process
    it is effectively a no-op (the full :class:`TokenValidator` handles
    the header logic). In a cloud process it raises 403 the moment a
    test-token header shows up at all, regardless of its value.
    """

    name = "ProductionGuardValidator"

    @staticmethod
    def validate(request: "BrowseHandler") -> tuple[int, str, str] | None:
        from viur.core.config import conf  # noqa: PLC0415
        from .constants import TOKEN_HEADER  # noqa: PLC0415

        if not request.request.headers.get(TOKEN_HEADER):
            return None  # no test-token header — nothing to guard against

        if getattr(conf.instance, "is_dev_server", False):
            return None  # in dev the TokenValidator owns this header

        return (
            403,
            "Forbidden",
            f"viur-test: {TOKEN_HEADER} is not accepted on this server",
        )


class TokenValidator(RequestValidator):
    """Reject every request that does not carry a matching test token header."""

    name = "TokenValidator"

    @staticmethod
    def validate(request: "BrowseHandler") -> tuple[int, str, str] | None:
        from .constants import BOOTSTRAP_PATH_SUFFIXES, TOKEN_HEADER  # noqa: PLC0415
        from ._test.config import ConfigModule  # noqa: PLC0415

        if not ConfigModule.is_active():
            # Shouldn't happen — activate() registers this validator and
            # primes state in lockstep — but if it does, fail closed.
            return 403, "Forbidden", "viur-test: server is not in test mode"

        path = getattr(request.request, "path", None)
        if _is_bootstrap_path(path, BOOTSTRAP_PATH_SUFFIXES):
            return None

        active_token = ConfigModule.current_token()
        if active_token is None:
            return (
                403,
                "Forbidden",
                "viur-test: no session token issued yet — call /_test/config/status first",
            )

        provided = request.request.headers.get(TOKEN_HEADER)
        if not provided:
            return 403, "Forbidden", f"viur-test: missing {TOKEN_HEADER} header"

        if not hmac.compare_digest(provided, active_token):
            return 403, "Forbidden", f"viur-test: invalid {TOKEN_HEADER}"

        return None
