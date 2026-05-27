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


def _build_test_client(database: str, namespace: str | None = None) -> "datastore.Client":
    """Construct a datastore client targeting the requested database.

    The ``database`` kwarg is supported by ``google-cloud-datastore >= 2.18``,
    which is what viur-core 3.7+ already depends on. The optional
    ``namespace`` argument partitions writes within the database so
    several concurrent test runners can share one ``viur-tests`` database
    without colliding on each other's entities — see README's
    "Concurrency" section.
    """
    from google.cloud import datastore  # noqa: PLC0415

    kwargs: dict[str, str] = {"database": database}
    if namespace is not None:
        kwargs["namespace"] = namespace

    client = datastore.Client(**kwargs)
    if getattr(client, "database", None) != database:
        raise RuntimeError(
            f"google.cloud.datastore.Client did not honour database={database!r}; "
            f"got client.database={getattr(client, 'database', None)!r}. "
            "Upgrade google-cloud-datastore to a version that supports named databases."
        )
    if namespace is not None and getattr(client, "namespace", None) != namespace:
        raise RuntimeError(
            f"google.cloud.datastore.Client did not honour namespace={namespace!r}; "
            f"got client.namespace={getattr(client, 'namespace', None)!r}."
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
    """Make ``viur.core.db.types.Key`` carry the client's ``database=`` and ``namespace=``.

    viur-core's ``Key`` class forwards only ``project=`` to
    ``google.cloud.datastore.Key`` — never ``database=`` or
    ``namespace=``. With a named-database client that mismatch causes
    every Datastore call to fail with ``InvalidArgument: 400 mismatched
    databases within request: …~project#viur-tests vs. …~project`` (the
    Key was built for the default database, the client targets the
    named one). The same applies to namespaces: without alignment,
    writes go to the default namespace while the client reads from the
    test namespace, and tests would see an empty database.

    Fix: wrap ``Key.__init__`` so the default ``database`` and
    ``namespace`` kwargs are the patched client's database/namespace.
    Explicit kwargs from the caller still win. The patch is
    intentionally only applied when test mode is active — no effect on
    production processes, where :func:`activate` refuses to run anyway.
    """
    target_db = getattr(client, "database", None)
    target_ns = getattr(client, "namespace", None)
    if target_db is None and target_ns is None:
        return  # default-DB client without namespace — nothing to align

    from viur.core.db.types import Key as ViurKey  # noqa: PLC0415

    _orig_init = ViurKey.__init__

    def _patched_init(self, *path_args, project=None, **kwargs):
        if target_db is not None:
            kwargs.setdefault("database", target_db)
        if target_ns is not None:
            kwargs.setdefault("namespace", target_ns)
        _orig_init(self, *path_args, project=project, **kwargs)

    _patched_init.__name__ = _orig_init.__name__
    ViurKey.__init__ = _patched_init


def _patch_legacy_urlsafe() -> None:
    """Make ``google.cloud.datastore.Key.to_legacy_urlsafe()`` tolerate
    named databases.

    The underlying Google method raises
    ``ValueError("to_legacy_urlsafe only supports the default
    database")`` on any key whose ``database`` attribute is set.
    viur-core hits this on hot paths — ``Key.__str__`` (used in
    session save and JSON renders of ``login_success``), CSRF token
    encoding, and elsewhere — so without this patch every successful
    login in a named database crashes with a 500.

    Patching the Google method directly (instead of viur-core's
    ``Key.__str__`` wrapper) is more robust:

    - Survives changes in viur-core's ``Key.__str__`` implementation.
    - Covers any call site that uses ``to_legacy_urlsafe`` directly,
      not only the ``str(key)`` path.
    - Patches the root cause; viur-core stays untouched.

    Workaround: temporarily clear ``self._database`` around the
    original call. The resulting urlsafe string covers project +
    namespace + path — the database id is dropped. Safe in a test
    process: every Key targets the same database (the one
    :func:`activate` wired up), so the patched ``Key.__init__``
    default fills the database back in when the urlsafe string is
    parsed into a new Key.
    """
    from google.cloud.datastore.key import Key as GCDSKey  # noqa: PLC0415

    _orig = GCDSKey.to_legacy_urlsafe

    def _patched(self, location_prefix=None):
        if self._database is None:
            return _orig(self, location_prefix=location_prefix)
        saved = self._database
        self._database = None
        try:
            return _orig(self, location_prefix=location_prefix)
        finally:
            self._database = saved

    _patched.__name__ = _orig.__name__
    GCDSKey.to_legacy_urlsafe = _patched


def _install_request_validator() -> None:
    """Add :class:`viur.testing.validator.TokenValidator` to the Router chain."""
    from viur.core.request import Router  # noqa: PLC0415
    from .validator import TokenValidator  # noqa: PLC0415

    if TokenValidator not in Router.requestValidators:
        Router.requestValidators.append(TokenValidator)


_BOOTSTRAP_OPEN_PATHS: tuple[str, ...] = (
    # Wildcard variants — viur-core uses fnmatch on these, so we err on
    # the side of accepting any render prefix the host may have
    # configured (json/, vi/, html/, or none). The actual security
    # comes from the TokenValidator that runs before the closed-system
    # gate (plus the per-endpoint _require_runtime_consistency check on
    # the built-in config endpoints).
    #
    # The broad ``_test/*`` / ``*/_test/*`` patterns cover host-
    # registered fixture submodules too (see
    # :func:`viur.testing.register_test_submodule`). Without them,
    # ``closed_system=True`` would reject the fixture POSTs with 401
    # even when the token header is correct.
    "json/_test/*",

)
"""Paths that must be reachable without a logged-in user.

viur-core's ``conf.security.closed_system`` (if true) blocks every request
that does not match one of ``conf.security.closed_system_allowed_paths``.
The broad ``_test/*`` wildcards cover both the built-in config bootstrap
and any host-registered fixture submodule. Security on those is still
enforced by the :class:`~viur.testing.validator.TokenValidator`.
"""


def _open_bootstrap_paths_in_closed_system() -> None:
    """Add the bootstrap paths to ``conf.security.closed_system_allowed_paths``."""
    from viur.core.config import conf  # noqa: PLC0415

    existing = list(conf.security.closed_system_allowed_paths)
    for path in _BOOTSTRAP_OPEN_PATHS:
        if path not in existing:
            existing.append(path)
    conf.security.closed_system_allowed_paths = existing


def activate(*, database: str = DEFAULT_DATABASE, namespace: str | None = None) -> None:
    """Switch the running process into test mode.

    Must be called before any ``viur.core`` import. Performs:

    1. ``viur.core.db.transport`` not-yet-imported precondition check.
    2. ``conf.instance.is_dev_server`` precondition check.
    3. Construction of a datastore client targeting ``database`` (and
       ``namespace``, if given).
    4. Synchronous probe roundtrip in that database/namespace.
    5. Patching of ``viur.core.db.transport.__client__``.
    6. Patching of ``viur.core.db.types.Key.__init__`` to default
       ``database=`` and ``namespace=`` to the client's values — without
       this every Key viur-core constructs goes to the wrong database/
       namespace and Datastore rejects the request (or, worse, silently
       returns empty results).
    7. Patching of ``google.cloud.datastore.Key.to_legacy_urlsafe`` so
       it tolerates named databases — the original raises on them and
       viur-core's ``str(key)`` cascade goes through it on hot paths
       (session save, JSON render of login_success).
       See :func:`_patch_legacy_urlsafe`.
    8. Activation of the in-process state on
       :class:`~viur.testing._test.config.ConfigModule`.
    9. Installation of the request validator.
    10. Wrap of ``viur.core.setup`` so the dev-server boot banner gains
       a ``database = <name>`` (and, when set, ``namespace = <name>``)
       line — see :mod:`viur.testing.banner`.

    No token is created here — the session token is created and stored
    by ``/_test/config/status`` directly in the test database, and
    released by ``/_test/config/finish``.

    :param database: Name of the target test database. Default ``viur-tests``.
    :param namespace: Optional Datastore namespace to scope every read
        and write to. When several testers share one ``viur-tests``
        database, giving each their own namespace (e.g. ``ak``, ``mb``,
        ``ci-pr-42``) keeps their entities from colliding without
        needing to provision separate databases.
    :raises RuntimeError: if any of the precondition checks or the probe
        fail. The process must abort rather than continue with a
        half-applied swap.
    """
    _require_transport_not_loaded()
    _require_dev_server()

    client = _build_test_client(database, namespace=namespace)
    _probe_roundtrip(client, database)

    _patch_transport_client(client)
    _patch_key_factory(client)
    _patch_legacy_urlsafe()

    # Safe to import ConfigModule now: transport has been patched, so
    # any transitive viur-core import that touches ``__client__`` will
    # find our test client.
    from ._test.config import ConfigModule  # noqa: PLC0415
    ConfigModule.set_active(
        database=database, project_id=client.project, namespace=namespace,
    )

    _install_request_validator()
    _open_bootstrap_paths_in_closed_system()

    from .banner import install_banner_patch  # noqa: PLC0415
    install_banner_patch(database, namespace=namespace)
