"""
Test-mode activation for a viur-core based project.

Call :func:`activate` at the very top of ``main.py`` — **before** any
``viur.core`` import — to swap the default datastore client out for a
client that targets a dedicated test database (default: ``viur-tests``).
The function performs a synchronous roundtrip probe to prove the test
database is actually reachable and refuses to return otherwise, so the
application cannot finish booting against the wrong database.

Activation has four mandatory checks that must *all* pass before the swap
is applied. The order matters: the ``transport-not-loaded`` check runs
*before* the dev-server check, because the dev-server check itself reaches
into ``viur.core.config`` and therefore triggers the full ``viur.core``
import chain (which loads ``viur.core.db.transport``). Doing
transport-check first lets activate() differentiate between "host already
loaded viur.core" (refuse) and "we are about to load it ourselves"
(allowed).

1. ``viur.core.db.transport`` must not yet be imported. If it is, the
   ``__client__`` singleton has already been bound to the default database
   and any later swap would be racing — refuse.
2. ``conf.instance.is_dev_server`` must be true. Refuses in any cloud
   environment.
3. A roundtrip write+read against the target database must succeed.
4. The constructed client's ``database`` attribute must match the
   requested database name (defense against API surface drift in
   google-cloud-datastore).

The :class:`~viur.testing._test.config.ConfigModule` (which carries the
in-process state and the status/finish endpoints) is imported only
**after** the transport patch, because importing it would otherwise
trigger the full ``viur.core`` import chain — including
``viur.core.db.transport`` and its default ``datastore.Client()`` —
too early.
"""

import secrets
import sys
import typing as t

from .constants import DEFAULT_DATABASE, PROBE_KIND

if t.TYPE_CHECKING:
    from google.cloud import datastore


def _require_dev_server() -> None:
    """Refuse activation outside of a local dev server."""
    from viur.core.config import conf  # noqa: PLC0415

    if not getattr(conf.instance, "is_dev_server", False):
        raise RuntimeError(
            "viur.testing.activate() refuses to run outside a local dev server. "
            "conf.instance.is_dev_server is False (set GAE_ENV=localdev to opt in)."
        )


def _require_transport_not_loaded() -> None:
    """Refuse if ``viur.core.db.transport`` is already imported."""
    if "viur.core.db.transport" in sys.modules:
        raise RuntimeError(
            "viur.testing.activate() must run BEFORE viur.core.db is imported. "
            "Currently sys.modules already contains 'viur.core.db.transport', "
            "meaning a datastore.Client() bound to the default database has "
            "been created. Move the activate() call to the very top of main.py, "
            "before any 'from viur.core ...' import."
        )


def _build_test_client(database: str) -> "datastore.Client":
    """Construct a datastore client targeting the requested database.

    The ``database`` kwarg is supported by ``google-cloud-datastore >= 2.18``,
    which is what viur-core 3.7+ already depends on.
    """
    from google.cloud import datastore  # noqa: PLC0415

    client = datastore.Client(database=database)
    if getattr(client, "database", None) != database:
        raise RuntimeError(
            f"google.cloud.datastore.Client did not honour database={database!r}; "
            f"got client.database={getattr(client, 'database', None)!r}. "
            "Upgrade google-cloud-datastore to a version that supports named databases."
        )
    return client


def _probe_roundtrip(client: "datastore.Client", database: str) -> None:
    """Write+read a marker entity to prove the client really hits the test DB."""
    from google.cloud import datastore  # noqa: PLC0415

    key = client.key(PROBE_KIND, "viur-test-activation-probe")
    entity = datastore.Entity(key=key)
    entity["database"] = database
    entity["probed_at"] = secrets.token_hex(8)
    client.put(entity)

    read_back = client.get(key)
    if read_back is None:
        raise RuntimeError(
            f"Probe write to database={database!r} did not return on read-back. "
            "The test database may not exist, or the client is misconfigured."
        )
    if read_back.get("database") != database:
        raise RuntimeError(
            f"Probe read-back returned database={read_back.get('database')!r}, "
            f"expected {database!r}. The client is not addressing the test DB."
        )


def _patch_transport_client(client: "datastore.Client") -> None:
    """Import ``viur.core.db.transport`` and replace its module-level client.

    Done as soon as the probe passes so that any later step which imports
    viur-core finds the swapped client already in place.
    """
    from viur.core.db import transport  # noqa: PLC0415
    transport.__client__ = client


def _patch_key_factory(client: "datastore.Client") -> None:
    """Make ``viur.core.db.types.Key`` carry the client's ``database=``.

    viur-core's ``Key`` class forwards only ``project=`` to
    ``google.cloud.datastore.Key`` — never ``database=``. With a named-
    database client that mismatch causes every Datastore call to fail
    with ``InvalidArgument: 400 mismatched databases within request:
    …~project#viur-tests vs. …~project`` (the Key was built for the
    default database, the client targets the named one).

    Fix: wrap ``Key.__init__`` so the default ``database`` kwarg is the
    patched client's database. Explicit ``database=`` from the caller
    still wins. The patch is intentionally only applied when test mode
    is active — no effect on production processes, where
    :func:`activate` refuses to run anyway.
    """
    target_db = getattr(client, "database", None)
    if target_db is None:
        return  # default-DB client — nothing to align

    from viur.core.db.types import Key as ViurKey  # noqa: PLC0415

    _orig_init = ViurKey.__init__

    def _patched_init(self, *path_args, project=None, **kwargs):
        kwargs.setdefault("database", target_db)
        _orig_init(self, *path_args, project=project, **kwargs)

    _patched_init.__name__ = _orig_init.__name__
    ViurKey.__init__ = _patched_init


def _install_request_validator() -> None:
    """Add :class:`viur.testing.validator.TokenValidator` to the Router chain."""
    from viur.core.request import Router  # noqa: PLC0415
    from .validator import TokenValidator  # noqa: PLC0415

    if TokenValidator not in Router.requestValidators:
        Router.requestValidators.append(TokenValidator)


_BOOTSTRAP_OPEN_PATHS: tuple[str, ...] = (
    # Plain + wildcard variants — viur-core uses fnmatch on these, so we
    # err on the side of accepting any render prefix the host may have
    # configured (json/, vi/, html/, or none). The actual security comes
    # from the per-endpoint _require_runtime_consistency check + the
    # TokenValidator that runs before the closed-system gate.
    "_test/config/*",
    "*/_test/config/*",
    "_test/config/status",
    "_test/config/finish",
)
"""Paths that must be reachable without a logged-in user.

viur-core's ``conf.security.closed_system`` (if true) blocks every request
that does not match one of ``conf.security.closed_system_allowed_paths``.
The bootstrap endpoints have to issue / release the token before the
runner can authenticate at all, so they must be in the allow-list.

The :class:`~viur.testing.validator.TokenValidator` and the per-endpoint
``_require_runtime_consistency`` check remain the actual access controls
for these paths.
"""


def _open_bootstrap_paths_in_closed_system() -> None:
    """Add the bootstrap paths to ``conf.security.closed_system_allowed_paths``."""
    from viur.core.config import conf  # noqa: PLC0415

    existing = list(conf.security.closed_system_allowed_paths)
    for path in _BOOTSTRAP_OPEN_PATHS:
        if path not in existing:
            existing.append(path)
    conf.security.closed_system_allowed_paths = existing


def activate(*, database: str = DEFAULT_DATABASE) -> None:
    """Switch the running process into test mode.

    Must be called before any ``viur.core`` import. Performs:

    1. ``viur.core.db.transport`` not-yet-imported precondition check.
    2. ``conf.instance.is_dev_server`` precondition check.
    3. Construction of a datastore client targeting ``database``.
    4. Synchronous probe roundtrip in that database.
    5. Patching of ``viur.core.db.transport.__client__``.
    6. Patching of ``viur.core.db.types.Key.__init__`` to default
       ``database=`` to the client's database — without this every
       Key viur-core constructs goes to the wrong (default) database
       and Datastore rejects the request.
    7. Activation of the in-process state on
       :class:`~viur.testing._test.config.ConfigModule`.
    8. Installation of the request validator.

    No token is created here — the session token is created and stored
    by ``/_test/config/status`` directly in the test database, and
    released by ``/_test/config/finish``.

    :param database: Name of the target test database. Default ``viur-tests``.
    :raises RuntimeError: if any of the precondition checks or the probe
        fail. The process must abort rather than continue with a
        half-applied swap.
    """
    _require_transport_not_loaded()
    _require_dev_server()

    client = _build_test_client(database)
    _probe_roundtrip(client, database)

    _patch_transport_client(client)
    _patch_key_factory(client)

    # Safe to import ConfigModule now: transport has been patched, so
    # any transitive viur-core import that touches ``__client__`` will
    # find our test client.
    from ._test.config import ConfigModule  # noqa: PLC0415
    ConfigModule.set_active(database=database, project_id=client.project)

    _install_request_validator()
    _open_bootstrap_paths_in_closed_system()
