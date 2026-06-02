"""
Dev-Mirror — tokenless browsing for the seeded test slice.

The actual seeding is done **out-of-band** by ``scripts/dev_mirror_import.py``
(managed ``gcloud firestore export``/``import``: ``(default)`` → ``viur-tests``,
default namespace, keys preserved 1:1). Managed import cannot remap namespaces,
so the test slice is the **shared default namespace** of ``viur-tests`` — there
is no per-developer namespace isolation in this mode (a deliberate trade-off).

This module provides the two pieces that live in the package:

- :class:`ReadOnlyClient` — the read-only wrapper the seed script uses on the
  live ``(default)`` database (for the ``__kind__`` enumeration), so an
  export-side bug can never write to production.
- :func:`arm_tokenless_browsing` — boot-time, PIN-gated arming of tokenless
  browsing: on a whitelisted dev server, requests may then skip the
  ``X-Viur-Test-Token`` header so the developer can open the seeded slice in a
  browser. See
  :meth:`viur.testing._test.config.ConfigModule.tokenless_allowed`.

The module imports no ``viur.core`` and no ``google.cloud`` at top level, so it
is safe to import at the very top of ``main.py`` before the datastore client is
bound; those imports are done lazily inside the functions that need them.
"""

import typing as t

from .pin import run_pin_challenge

if t.TYPE_CHECKING:  # pragma: no cover
    from google.cloud import datastore


_BLOCKED_WRITES: frozenset[str] = frozenset({
    "put",
    "put_multi",
    "delete",
    "delete_multi",
    "allocate_ids",
    "mutation",
    "transaction",
})
"""Client methods the read-only source wrapper refuses to forward."""


class ReadOnlyClient:
    """Wrap a datastore client so reads pass through but any write raises.

    Used by the managed seed script on the live ``(default)`` database: the
    source can be queried and fetched, never mutated. A bug that tried to
    write to production fails loudly instead of corrupting live data.
    """

    def __init__(self, client: "datastore.Client") -> None:
        self._client = client

    def __getattr__(self, name: str) -> t.Any:
        if name in _BLOCKED_WRITES:
            raise RuntimeError(
                f"viur-testing dev-mirror: refusing to call {name}() on the LIVE "
                "(default) database — the mirror source is strictly read-only."
            )
        return getattr(self._client, name)


def _is_dev_server() -> bool:
    from viur.core.config import conf  # noqa: PLC0415

    return bool(getattr(conf.instance, "is_dev_server", False))


def arm_tokenless_browsing(
    *,
    tokenless_app_ids: "t.Iterable[str] | None",
    io: t.Any = None,
    _pin: str | None = None,
    _project_id: "str | None" = None,
) -> None:
    """Boot-time: PIN-gate, then arm tokenless browsing for this process.

    Intended to run inside :func:`viur.testing.setup` after
    :func:`viur.testing.activate`, when ``VIUR_TESTING_TOKENLESS`` is set.
    Once armed, :class:`~viur.testing.validator.TokenValidator` lets requests
    on this (whitelisted) dev server through without the token header — only
    ever exposing the ``viur-tests`` slice, never ``(default)``, and only while
    ``conf.instance.is_dev_server`` holds (re-checked per request).

    Raises (aborting the boot) on an unwhitelisted project, outside a dev
    server, or on a missing TTY / wrong PIN — the developer opted in via the
    env var, so a silent fallback would hide a misconfiguration.

    :param tokenless_app_ids: Whitelist of GCP project ids allowed to enable
        tokenless browsing (kept in ``main.py``).
    :param io: PIN-challenge I/O override (tests only).
    :param _pin: PIN override (tests only).
    :param _project_id: Project-id override (tests only); defaults to the
        active project recorded by :func:`activate`.
    :raises RuntimeError: on an unwhitelisted project or outside a dev server.
    :raises ~viur.testing.pin.PinChallengeError: on no TTY / wrong PIN.
    """
    from ._test.config import ConfigModule  # noqa: PLC0415

    project_id = (
        _project_id if _project_id is not None else ConfigModule.current_project_id()
    )
    allow = tuple(tokenless_app_ids or ())

    if project_id not in allow:
        raise RuntimeError(
            f"viur-testing tokenless: refusing — project {project_id!r} is not in "
            f"the whitelist {list(allow)!r}. Pass the project id via "
            "viur.testing.setup(tokenless_app_ids=[...]) in main.py."
        )
    if not _is_dev_server():
        raise RuntimeError(
            "viur-testing tokenless: refusing outside a local dev server."
        )

    run_pin_challenge(
        context_lines=[
            f"project = {project_id}",
            "enables TOKENLESS browsing of the viur-tests slice (no token header).",
            "the slice is a SHARED copy seeded out-of-band (scripts/dev_mirror_import.py).",
        ],
        io=io,
        _pin=_pin,
    )

    ConfigModule.arm_tokenless(allow)
    print(
        f"[viur-testing] tokenless browsing ENABLED for project {project_id!r} "
        "(viur-tests slice, dev server only)."
    )


__all__ = [
    "ReadOnlyClient",
    "arm_tokenless_browsing",
]
