"""
``viur.testing._test.config`` — the ``ConfigModule`` viur module + per-process state.

Carries:

- the **class-level state** that marks the running process as a test-mode
  process and stores the session token (``_database``, ``_project_id``,
  ``_token`` on :class:`ConfigModule`),
- the **bootstrap endpoints** ``status`` (provisions the token in the
  test database and hands it to the runner) and ``finish`` (deletes the
  token entity, ending the session),
- the **private helpers** that consult ``viur.core`` to verify runtime
  consistency, build the datastore key, and read/write/delete the token
  entity.

State lives on the class — there is exactly one logical test session
per process. :mod:`viur.testing.activation` sets the active state by
calling :meth:`ConfigModule.set_active` after the datastore client
swap; the request validator reads :meth:`ConfigModule.current_token`
to decide whether to let a request through.
"""

import base64
import datetime
import hashlib
import json
import typing as t

from viur.core import Module, current
from viur.core.decorators import exposed, force_post
from viur.core.errors import Forbidden

from ..constants import (
    TOKEN_COOKIE,
    TOKEN_ENTITY_NAME,
    TOKEN_KIND,
    TOKEN_PROPERTY,
)


class ConfigModule(Module):
    """Bootstrap configuration module mounted under ``/_test/config``.

    Holds the per-process session state as class attributes and exposes
    two endpoints:

    - ``POST /json/_test/config/status`` — verify the runtime is consistent
      (dev server + correct datastore database), then read or create
      the session token entity in the test database and return it.
      POST-only to block drive-by GETs from another browser tab on
      the same machine (CORS preflight stops the cross-origin call).
    - ``POST /json/_test/config/finish`` — verify the runtime, delete the
      token entity, clear the in-process token.
    """

    handler = "config"
    accessRights = None

    # ----- mount guards -----------------------------------------------------

    def __init__(
        self,
        moduleName: str = "config",
        modulePath: str = "_test/config",
        *args: t.Any,
        **kwargs: t.Any,
    ) -> None:
        """Refuse to instantiate unless the runtime is in test mode.

        Defense in depth: :class:`~viur.testing._test.TestModule` already
        checks both conditions before constructing the container, but a
        host project might bypass the container and mount ConfigModule
        directly. The same two guards are repeated here so that a direct
        mount cannot accidentally end up in production or run before
        :func:`viur.testing.activate` has wired the datastore client.
        """
        from viur.core.config import conf  # noqa: PLC0415 — fresh lookup on each instantiation

        if not getattr(conf.instance, "is_dev_server", False):
            raise RuntimeError(
                "viur-testing: ConfigModule refuses to instantiate outside a local "
                "dev server. conf.instance.is_dev_server is False."
            )
        if type(self)._database is None:
            raise RuntimeError(
                "viur-testing: ConfigModule cannot mount because viur.testing.activate() "
                "has not been called yet. Move the activate() call to the very top "
                "of main.py, before the modules package is imported."
            )
        super().__init__(moduleName, modulePath, *args, **kwargs)

    # ----- per-process state ------------------------------------------------

    _database: t.ClassVar[str | None] = None
    _namespace: t.ClassVar[str | None] = None
    _project_id: t.ClassVar[str | None] = None
    _token: t.ClassVar[str | None] = None

    # Project-supplied hooks. Each hook returns an optional dict whose
    # entries get merged into the JSON response of /_test/config/status
    # or /_test/config/finish. See :meth:`register_status_hook` and
    # :meth:`register_finish_hook`.
    _status_hooks: t.ClassVar[list[t.Callable[[], dict | None]]] = []
    _finish_hooks: t.ClassVar[list[t.Callable[[], dict | None]]] = []

    @classmethod
    def is_active(cls) -> bool:
        """Whether :func:`viur.testing.activate` has wired the process."""
        return cls._database is not None

    @classmethod
    def has_token(cls) -> bool:
        """Whether a session is currently established (a token is issued)."""
        return cls._token is not None

    @classmethod
    def current_database(cls) -> str | None:
        return cls._database

    @classmethod
    def current_project_id(cls) -> str | None:
        return cls._project_id

    @classmethod
    def current_namespace(cls) -> str | None:
        """Datastore namespace this process is scoped to, or ``None`` for
        the default namespace.
        """
        return cls._namespace

    @classmethod
    def current_token(cls) -> str | None:
        return cls._token

    @classmethod
    def current_token_hash(cls) -> str | None:
        if cls._token is None:
            return None
        return hashlib.sha256(cls._token.encode("utf-8")).hexdigest()

    @classmethod
    def set_active(
        cls, *, database: str, project_id: str, namespace: str | None = None,
    ) -> None:
        """Mark the process as test-mode active.

        Idempotent for matching ``(database, project_id, namespace)``;
        refuses to silently overwrite a mismatching prior activation.

        ``namespace=""`` is normalised to ``None`` — same convention as
        :func:`viur.testing.activate` and the ``VIUR_TESTING`` namespace
        part. Without this normalisation a direct call with the
        empty string followed by an :func:`activate`-driven call with
        ``None`` (or vice-versa) would falsely report a mismatch.
        """
        if namespace == "":
            namespace = None
        if cls._database is None:
            cls._database = database
            cls._project_id = project_id
            cls._namespace = namespace
            return
        if (
            cls._database != database
            or cls._project_id != project_id
            or cls._namespace != namespace
        ):
            raise RuntimeError(
                f"ConfigModule is already active for "
                f"(database={cls._database!r}, namespace={cls._namespace!r}, "
                f"project_id={cls._project_id!r}); refusing to switch to "
                f"(database={database!r}, namespace={namespace!r}, "
                f"project_id={project_id!r})."
            )

    @classmethod
    def set_token(cls, token: str) -> None:
        """Record the current session token. Requires prior :meth:`set_active`."""
        if cls._database is None:
            raise RuntimeError("ConfigModule is not active; cannot set token.")
        cls._token = token

    @classmethod
    def clear_token(cls) -> None:
        """Drop the session token. Test-mode itself stays active."""
        cls._token = None

    @classmethod
    def register_status_hook(cls, hook: t.Callable[[], dict | None]) -> None:
        """Register a project-side callback that fires inside ``/_test/config/status``.

        The hook is invoked after the token has been issued and the
        in-process state primed, but **before** the JSON response is
        serialised. If it returns a dict, the entries are merged into
        the response payload (later hooks win on conflicting keys).
        Side effects on ``viur.core.conf`` are allowed — useful for
        seeding project-specific config that every test relies on.

        Registrations survive across calls to :meth:`reset` only if
        the host re-runs the registration; ``reset()`` clears the
        hook list along with the rest of the state.

        :param hook: A zero-argument callable returning ``dict | None``.
        """
        cls._status_hooks.append(hook)

    @classmethod
    def register_finish_hook(cls, hook: t.Callable[[], dict | None]) -> None:
        """Register a project-side callback that fires inside ``/_test/config/finish``.

        Same shape as :meth:`register_status_hook`: optional dict
        return value is merged into the ``finish`` response.
        """
        cls._finish_hooks.append(hook)

    @classmethod
    def reset(cls) -> None:
        """Clear all state. Intended for tests only."""
        cls._database = None
        cls._namespace = None
        cls._project_id = None
        cls._token = None
        cls._status_hooks = []
        cls._finish_hooks = []

    # ----- private helpers --------------------------------------------------

    @classmethod
    def _require_runtime_consistency(cls) -> None:
        """Re-verify dev-server + datastore database before any DB op.

        Defense in depth: the endpoints are reachable without the token
        header (whitelisted in the validator), so they must re-check
        the environment themselves. A mismatch means the host has been
        misconfigured or the activation step never ran.
        """
        from viur.core.config import conf  # noqa: PLC0415

        if not getattr(conf.instance, "is_dev_server", False):
            raise Forbidden("viur-test: server is not in dev mode")

        if cls._database is None:
            raise Forbidden("viur-test: activate() has not been called")

        from viur.core.db import transport  # noqa: PLC0415

        actual_db = getattr(transport.__client__, "database", None)
        if actual_db != cls._database:
            raise Forbidden(
                f"viur-test: datastore client is on database={actual_db!r}, "
                f"expected {cls._database!r}"
            )

    @classmethod
    def _token_key(cls):
        from viur.core.db import transport  # noqa: PLC0415
        return transport.__client__.key(TOKEN_KIND, TOKEN_ENTITY_NAME)

    @classmethod
    def _current_day(cls) -> str:
        """UTC calendar day as ``YYYY-MM-DD``. Isolated so tests can pin it."""
        return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    @classmethod
    def _compute_daily_token(cls) -> str:
        """Deterministic per-day session token.

        Identical for the whole UTC day and stable across server restarts,
        :meth:`finish` calls and re-issues — so a cookie armed once via
        ``/_test/config/enter`` keeps working all day; it rotates at UTC
        midnight. Derived from the session identity (database, namespace,
        project id) plus the day, so distinct slices and distinct days never
        share a token.

        Not a secret: ``/_test/config/status`` already hands the token to any
        local caller, and the production guard + dev-server gate remain the
        real protection. Determinism is the point — see :meth:`_read_or_create_token`.
        """
        material = "\0".join([
            "viur-testing-daily-token-v1",
            cls._database or "",
            cls._namespace or "",
            cls._project_id or "",
            cls._current_day(),
        ])
        digest = hashlib.sha256(material.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    @classmethod
    def _read_or_create_token(cls) -> str:
        """Return today's deterministic token, persisting it in the test DB.

        The stored entity is (re)written whenever it is missing or holds a
        different value — e.g. on the first call of a new day, or after a
        stale entity from a previous day — so the DB always mirrors the
        active token and :meth:`finish` can report ``had_token`` correctly.
        """
        from google.cloud import datastore as gcds  # noqa: PLC0415
        from viur.core.db import transport  # noqa: PLC0415

        token = cls._compute_daily_token()
        key = cls._token_key()
        existing = transport.__client__.get(key)
        if existing is None or existing.get(TOKEN_PROPERTY) != token:
            entity = gcds.Entity(key=key)
            entity[TOKEN_PROPERTY] = token
            transport.__client__.put(entity)
        return token

    @classmethod
    def _delete_token(cls) -> bool:
        """Delete the token entity from the DB. ``True`` if one was present."""
        from viur.core.db import transport  # noqa: PLC0415

        key = cls._token_key()
        existed = transport.__client__.get(key) is not None
        transport.__client__.delete(key)
        return existed

    # ----- HTTP endpoints ---------------------------------------------------

    @staticmethod
    def _json_response(payload: dict) -> str:
        """Serialise ``payload`` to JSON and set the response Content-Type.

        viur-core endpoints return the response body as a *string* — a raw
        ``dict`` would be coerced to ``str(payload)`` which is Python repr,
        not JSON. Mirroring what
        :class:`viur.core.render.json.default.DefaultRender` does: dump
        explicitly and announce ``application/json``.
        """
        current.request.get().response.headers["Content-Type"] = "application/json"
        return json.dumps(payload)

    @staticmethod
    def _set_token_cookie(token: str) -> None:
        """Set the session token as a ``viur-test-token`` cookie.

        ``SameSite=Strict; HttpOnly; Path=/`` — ``Secure`` only on HTTPS so
        it still works on a plain-HTTP ``http://localhost`` dev server. The
        cookie is the canonical transport: once set, the browser attaches it
        to every request, including hard navigations.
        """
        handler = current.request.get()
        secure = getattr(handler.request, "scheme", "http") == "https"
        handler.response.set_cookie(
            TOKEN_COOKIE,
            token,
            path="/",
            secure=secure,
            httponly=True,
            samesite="Strict",
        )

    @staticmethod
    def _clear_token_cookie() -> None:
        """Expire the ``viur-test-token`` cookie (used by ``finish``)."""
        handler = current.request.get()
        handler.response.delete_cookie(TOKEN_COOKIE, path="/")

    @staticmethod
    def _enter_confirmation_html() -> str:
        """Minimal HTML body for the ``enter`` GET navigation."""
        current.request.get().response.headers["Content-Type"] = "text/html; charset=utf-8"
        return (
            "<!doctype html><meta charset=utf-8><title>viur-testing</title>"
            "<p>Test session armed — the <code>viur-test-token</code> cookie is set. "
            "You can now browse the test instance directly.</p>"
        )

    @exposed
    @force_post
    def status(self) -> str:
        """Begin (or resume) a test session.

        Reads the token entity from the test database; creates it on
        first call. Updates the in-process state so the request
        validator starts accepting the token. Returns the full session
        info, including the token, to the runner.

        POST-only on purpose: a third-party browser tab on the same
        machine cannot issue a cross-origin POST without CORS preflight,
        so it cannot drive-by trigger a session through this endpoint.
        """
        cls = type(self)
        cls._require_runtime_consistency()
        token = cls._read_or_create_token()
        cls.set_token(token)

        from viur.testing import __version__  # noqa: PLC0415

        payload: dict = {
            "test_mode": True,
            "is_dev_server": True,
            "database": cls._database,
            "namespace": cls._namespace,
            "project_id": cls._project_id,
            "token": token,
            "token_hash": cls.current_token_hash(),
            "version": __version__,
        }
        for hook in cls._status_hooks:
            extra = hook()
            if extra:
                payload.update(extra)
        return self._json_response(payload)

    @exposed
    def enter(self) -> str:
        """Arm a manual browsing session by setting the token cookie.

        Reached by a plain **GET** navigation (address bar, link, reload)
        before any cookie exists — hence a bootstrap path. Reads/creates the
        session token, primes the in-process state, and sets the
        ``viur-test-token`` cookie. Afterwards every request the browser makes
        — including hard navigations and server-rendered pages — carries the
        cookie, so the developer can browse the test instance directly without
        a header-injecting proxy or browser extension.

        GET (not POST) on purpose: you navigate to it. A cross-site drive-by
        could trigger it, but the resulting cookie is ``SameSite=Strict`` and
        scoped to this (dev-only, localhost) host, so it cannot be used from
        another site — see the security note in the README.
        """
        cls = type(self)
        cls._require_runtime_consistency()
        token = cls._read_or_create_token()
        cls.set_token(token)
        cls._set_token_cookie(token)
        return self._enter_confirmation_html()

    @exposed
    @force_post
    def finish(self) -> str:
        """End the current test session.

        Deletes the token entity from the test database, clears the
        in-process token and expires the cookie. Test-mode itself stays
        armed — the next call to :meth:`status`/:meth:`enter` will provision
        a fresh token.
        """
        cls = type(self)
        cls._require_runtime_consistency()
        existed = cls._delete_token()
        cls.clear_token()
        cls._clear_token_cookie()

        payload: dict = {"finished": True, "had_token": existed}
        for hook in cls._finish_hooks:
            extra = hook()
            if extra:
                payload.update(extra)
        return self._json_response(payload)


__all__ = ["ConfigModule"]
