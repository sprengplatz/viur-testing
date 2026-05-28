"""Unit and integration tests for :mod:`viur.testing.activation`."""

import sys
import types

import pytest

from viur.testing import activation
from viur.testing._test.config import ConfigModule


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeKey:
    def __init__(self, kind, name):
        self.kind = kind
        self.name = name

    def __hash__(self):
        return hash((self.kind, self.name))

    def __eq__(self, other):
        return isinstance(other, _FakeKey) and (self.kind, self.name) == (
            other.kind,
            other.name,
        )


class _FakeEntity(dict):
    def __init__(self, key=None):
        super().__init__()
        self.key = key


class _FakeClient:
    def __init__(
        self,
        database,
        project="proj-x",
        namespace=None,
        refuse_database=False,
        refuse_namespace=False,
    ):
        self.database = None if refuse_database else database
        self.namespace = None if refuse_namespace else namespace
        self.project = project
        self._store: dict = {}
        self.put_calls = 0

    def key(self, kind, name):
        return _FakeKey(kind, name)

    def put(self, entity):
        self.put_calls += 1
        self._store[entity.key] = dict(entity)

    def get(self, key):
        data = self._store.get(key)
        if data is None:
            return None
        e = _FakeEntity(key=key)
        e.update(data)
        return e


def _install_fake_datastore_module(monkeypatch, *, client: _FakeClient):
    fake_mod = types.ModuleType("google.cloud.datastore")
    fake_mod.Client = lambda **kwargs: client
    fake_mod.Entity = _FakeEntity
    monkeypatch.setitem(sys.modules, "google.cloud.datastore", fake_mod)

    google_pkg = sys.modules.get("google") or types.ModuleType("google")
    google_cloud = sys.modules.get("google.cloud") or types.ModuleType("google.cloud")
    google_cloud.datastore = fake_mod
    google_pkg.cloud = google_cloud
    monkeypatch.setitem(sys.modules, "google", google_pkg)
    monkeypatch.setitem(sys.modules, "google.cloud", google_cloud)
    return fake_mod


@pytest.fixture(autouse=True)
def _reset_test_module_state():
    ConfigModule.reset()
    yield
    ConfigModule.reset()


# ---------------------------------------------------------------------------
# Helper-level unit tests
# ---------------------------------------------------------------------------


def test_require_dev_server_passes_when_conf_says_yes(conf_instance):
    conf_instance.is_dev_server = True
    activation._require_dev_server()


def test_require_dev_server_refuses_when_conf_says_no(conf_instance):
    conf_instance.is_dev_server = False
    with pytest.raises(RuntimeError, match="local dev server"):
        activation._require_dev_server()


def test_require_transport_not_loaded_passes_when_absent():
    sys.modules.pop("viur.core.db.transport", None)
    activation._require_transport_not_loaded()


def test_require_transport_not_loaded_refuses_when_present(monkeypatch):
    monkeypatch.setitem(sys.modules, "viur.core.db.transport", types.ModuleType("x"))
    with pytest.raises(RuntimeError, match="must run BEFORE"):
        activation._require_transport_not_loaded()


def test_build_test_client_passes_when_database_honoured(monkeypatch):
    client = _FakeClient(database="viur-tests")
    _install_fake_datastore_module(monkeypatch, client=client)
    assert activation._build_test_client("viur-tests") is client


def test_build_test_client_refuses_when_database_ignored(monkeypatch):
    client = _FakeClient(database="viur-tests", refuse_database=True)
    _install_fake_datastore_module(monkeypatch, client=client)
    with pytest.raises(RuntimeError, match="did not honour database"):
        activation._build_test_client("viur-tests")


def _install_fake_datastore_capturing(monkeypatch, *, client: _FakeClient, captured: dict):
    """Variant of :func:`_install_fake_datastore_module` whose Client
    factory records the kwargs it was called with."""
    def _capture(**kwargs):
        captured.update(kwargs)
        return client

    fake_mod = types.ModuleType("google.cloud.datastore")
    fake_mod.Client = _capture
    fake_mod.Entity = _FakeEntity
    monkeypatch.setitem(sys.modules, "google.cloud.datastore", fake_mod)

    google_pkg = sys.modules.get("google") or types.ModuleType("google")
    google_cloud = sys.modules.get("google.cloud") or types.ModuleType("google.cloud")
    google_cloud.datastore = fake_mod
    google_pkg.cloud = google_cloud
    monkeypatch.setitem(sys.modules, "google", google_pkg)
    monkeypatch.setitem(sys.modules, "google.cloud", google_cloud)


def test_build_test_client_passes_namespace_when_given(monkeypatch):
    """When ``namespace`` is given, the datastore.Client constructor must
    receive the ``namespace=`` kwarg and the returned client's
    ``namespace`` attribute is checked for consistency."""
    captured: dict = {}
    client = _FakeClient(database="viur-tests", namespace="alice")
    _install_fake_datastore_capturing(monkeypatch, client=client, captured=captured)

    result = activation._build_test_client("viur-tests", namespace="alice")
    assert result is client
    assert captured == {"database": "viur-tests", "namespace": "alice"}


def test_build_test_client_omits_namespace_when_none(monkeypatch):
    """Without a namespace, the kwarg must NOT be passed at all so the
    client falls back to the Datastore default namespace."""
    captured: dict = {}
    client = _FakeClient(database="viur-tests")
    _install_fake_datastore_capturing(monkeypatch, client=client, captured=captured)

    activation._build_test_client("viur-tests")
    assert "namespace" not in captured


def test_build_test_client_refuses_when_namespace_ignored(monkeypatch):
    client = _FakeClient(database="viur-tests", namespace="alice", refuse_namespace=True)
    _install_fake_datastore_module(monkeypatch, client=client)
    with pytest.raises(RuntimeError, match="did not honour namespace"):
        activation._build_test_client("viur-tests", namespace="alice")


def test_probe_roundtrip_writes_and_reads(monkeypatch):
    client = _FakeClient(database="viur-tests")
    _install_fake_datastore_module(monkeypatch, client=client)
    activation._probe_roundtrip(client, "viur-tests")
    assert client.put_calls == 1


def test_probe_roundtrip_raises_if_read_returns_none(monkeypatch):
    client = _FakeClient(database="viur-tests")
    _install_fake_datastore_module(monkeypatch, client=client)
    client.get = lambda key: None
    with pytest.raises(RuntimeError, match="did not return on read-back"):
        activation._probe_roundtrip(client, "viur-tests")


def test_probe_roundtrip_raises_if_database_property_mismatches(monkeypatch):
    client = _FakeClient(database="viur-tests")
    _install_fake_datastore_module(monkeypatch, client=client)
    original_get = client.get

    def evil_get(key):
        e = original_get(key)
        if e is not None:
            e["database"] = "(default)"
        return e

    client.get = evil_get
    with pytest.raises(RuntimeError, match="not addressing the test DB"):
        activation._probe_roundtrip(client, "viur-tests")


def test_install_request_validator_appends_once(router_validators):
    activation._install_request_validator()
    activation._install_request_validator()
    from viur.testing.validator import TokenValidator

    assert router_validators.count(TokenValidator) == 1


def test_patch_transport_client_replaces_singleton(monkeypatch):
    transport = types.ModuleType("viur.core.db.transport")
    transport.__client__ = "default-sentinel"
    monkeypatch.setitem(sys.modules, "viur.core.db.transport", transport)
    activation._patch_transport_client("test-client")
    assert transport.__client__ == "test-client"


# ---------------------------------------------------------------------------
# _patch_key_factory
# ---------------------------------------------------------------------------


def test_bootstrap_open_paths_cover_every_renderer_prefix():
    """The closed-system allow-list must accept ``/_test/...`` under any
    renderer prefix (json/, vi/, html/, ...) plus the no-prefix variant.

    Regression guard: an earlier version only listed ``json/_test/*``,
    so hosts using ``vi/`` or ``html/`` renderers got 401 from
    ``closed_system`` before the request even reached the TokenValidator.
    """
    from viur.testing.activation import _BOOTSTRAP_OPEN_PATHS

    assert "*/_test/*" in _BOOTSTRAP_OPEN_PATHS, (
        "renderer-agnostic wildcard missing — hosts on vi/ or html/ "
        "would be 401'd by closed_system"
    )
    assert "_test/*" in _BOOTSTRAP_OPEN_PATHS, (
        "no-prefix variant missing — renderer-less mounts would 401"
    )


def test_open_bootstrap_paths_in_closed_system_appends_paths(conf_instance):
    """activate() must extend conf.security.closed_system_allowed_paths so
    /_test/config/status + /_test/config/finish stay reachable for the runner."""
    class _Security:
        closed_system = True
        closed_system_allowed_paths = ["index"]

    conf_instance_module = sys.modules["viur.core.config"]
    original_security = getattr(conf_instance_module.conf, "security", None)
    conf_instance_module.conf.security = _Security()
    try:
        from viur.testing.activation import _open_bootstrap_paths_in_closed_system

        _open_bootstrap_paths_in_closed_system()

        paths = list(conf_instance_module.conf.security.closed_system_allowed_paths)
        # Every entry from _BOOTSTRAP_OPEN_PATHS must end up in the
        # allow-list — this covers both the built-in config bootstrap
        # and any host-registered fixture submodule under /_test/.
        from viur.testing.activation import _BOOTSTRAP_OPEN_PATHS

        for pattern in _BOOTSTRAP_OPEN_PATHS:
            assert pattern in paths, f"expected {pattern!r} in allow-list, got {paths!r}"
        # existing entries are preserved
        assert "index" in paths
    finally:
        if original_security is None:
            del conf_instance_module.conf.security
        else:
            conf_instance_module.conf.security = original_security


def test_open_bootstrap_paths_in_closed_system_is_idempotent(conf_instance):
    class _Security:
        closed_system = True
        closed_system_allowed_paths = []

    conf_instance_module = sys.modules["viur.core.config"]
    original_security = getattr(conf_instance_module.conf, "security", None)
    conf_instance_module.conf.security = _Security()
    try:
        from viur.testing.activation import _open_bootstrap_paths_in_closed_system

        _open_bootstrap_paths_in_closed_system()
        _open_bootstrap_paths_in_closed_system()  # second call no-ops
        paths = list(conf_instance_module.conf.security.closed_system_allowed_paths)
        from viur.testing.activation import _BOOTSTRAP_OPEN_PATHS

        # Every bootstrap pattern appears exactly once even after two calls.
        for pattern in _BOOTSTRAP_OPEN_PATHS:
            assert paths.count(pattern) == 1, (
                f"{pattern!r} appears {paths.count(pattern)} times, expected exactly 1"
            )
    finally:
        if original_security is None:
            del conf_instance_module.conf.security
        else:
            conf_instance_module.conf.security = original_security


def _install_fake_db_types_module(monkeypatch, capture: list):
    """Install a fake ``viur.core.db.types`` with a ``Key`` class that
    records every ``__init__`` call into *capture*."""
    mod = types.ModuleType("viur.core.db.types")

    class Key:
        def __init__(self, *path_args, project=None, **kwargs):
            capture.append({"path": path_args, "project": project, "kwargs": dict(kwargs)})

    mod.Key = Key
    monkeypatch.setitem(sys.modules, "viur.core.db.types", mod)
    return Key


def test_patch_key_factory_no_op_when_client_has_no_database_and_namespace(monkeypatch):
    """A default-DB client with no namespace (both None) leaves Key.__init__ alone."""
    captured: list = []
    Key = _install_fake_db_types_module(monkeypatch, captured)

    class _DefaultClient:
        database = None
        namespace = None

    activation._patch_key_factory(_DefaultClient())

    Key("kind", "id")
    assert captured == [{"path": ("kind", "id"), "project": None, "kwargs": {}}]


def test_patch_key_factory_sets_default_namespace(monkeypatch):
    captured: list = []
    Key = _install_fake_db_types_module(monkeypatch, captured)

    class _Client:
        database = "viur-tests"
        namespace = "alice"

    activation._patch_key_factory(_Client())

    Key("kind", "id")
    assert captured[-1]["kwargs"]["database"] == "viur-tests"
    assert captured[-1]["kwargs"]["namespace"] == "alice"


def test_patch_key_factory_preserves_explicit_namespace(monkeypatch):
    captured: list = []
    Key = _install_fake_db_types_module(monkeypatch, captured)

    class _Client:
        database = "viur-tests"
        namespace = "alice"

    activation._patch_key_factory(_Client())

    Key("kind", "id", namespace="other")
    assert captured[-1]["kwargs"]["namespace"] == "other"


def test_patch_key_factory_skips_database_when_client_has_only_namespace(monkeypatch):
    """A client with only a namespace (no database) must still patch the
    namespace default — but must NOT inject a ``database=None`` kwarg."""
    captured: list = []
    Key = _install_fake_db_types_module(monkeypatch, captured)

    class _NamespaceOnlyClient:
        database = None
        namespace = "alice"

    activation._patch_key_factory(_NamespaceOnlyClient())

    Key("kind", "id")
    assert "database" not in captured[-1]["kwargs"]
    assert captured[-1]["kwargs"]["namespace"] == "alice"


def test_patch_key_factory_omits_namespace_when_client_has_none(monkeypatch):
    """If the client has no namespace, the patch must not synthesise one
    — otherwise plain ``datastore.Key("kind", "id")`` would land in the
    default namespace explicitly, which behaves differently from the
    implicit default in some Datastore client versions."""
    captured: list = []
    Key = _install_fake_db_types_module(monkeypatch, captured)

    class _Client:
        database = "viur-tests"
        namespace = None

    activation._patch_key_factory(_Client())

    Key("kind", "id")
    assert "namespace" not in captured[-1]["kwargs"]


def test_patch_key_factory_sets_default_database(monkeypatch):
    """The patch injects ``database=`` matching the client."""
    captured: list = []
    Key = _install_fake_db_types_module(monkeypatch, captured)

    class _Client:
        database = "viur-tests"

    activation._patch_key_factory(_Client())

    Key("kind", "id")
    assert captured[-1]["kwargs"]["database"] == "viur-tests"


def test_patch_key_factory_preserves_explicit_database(monkeypatch):
    """Callers can still override the default by passing ``database=``."""
    captured: list = []
    Key = _install_fake_db_types_module(monkeypatch, captured)

    class _Client:
        database = "viur-tests"

    activation._patch_key_factory(_Client())

    Key("kind", "id", database="other")
    assert captured[-1]["kwargs"]["database"] == "other"


def _install_fake_gcds_key(monkeypatch):
    """Install a fake ``google.cloud.datastore.key`` module whose Key's
    ``to_legacy_urlsafe`` simulates the real one: raises if
    ``self._database`` is set."""
    mod = types.ModuleType("google.cloud.datastore.key")

    class Key:
        def __init__(self, *path_args, project=None, **kwargs):
            self._project = project
            self._database = kwargs.get("database")
            self._namespace = kwargs.get("namespace")
            self._path = path_args

        def to_legacy_urlsafe(self, location_prefix=None):
            if self._database:
                raise ValueError("to_legacy_urlsafe only supports the default database")
            return f"<urlsafe:{self._project}:{self._namespace}:{self._path}>".encode()

    mod.Key = Key
    monkeypatch.setitem(sys.modules, "google.cloud.datastore.key", mod)
    return Key


def test_patch_legacy_urlsafe_works_around_check_on_named_db(monkeypatch):
    """``key.to_legacy_urlsafe()`` on a Key with ``_database`` set must not crash."""
    Key = _install_fake_gcds_key(monkeypatch)
    activation._patch_legacy_urlsafe()

    k = Key("user", "abc", database="viur-tests", namespace="alice")
    # Before the patch this would raise; after the patch we get the urlsafe form.
    result = k.to_legacy_urlsafe()
    assert b"viur-tests" not in result  # database is stripped during serialisation
    assert k._database == "viur-tests"  # but restored on the live key


def test_patch_legacy_urlsafe_passes_through_for_default_db(monkeypatch):
    """A Key without ``_database`` is serialised unchanged."""
    Key = _install_fake_gcds_key(monkeypatch)
    activation._patch_legacy_urlsafe()

    k = Key("user", "abc")
    assert k._database is None
    result = k.to_legacy_urlsafe()
    assert k._database is None
    assert result == b"<urlsafe:None:None:('user', 'abc')>"


def test_patch_legacy_urlsafe_restores_database_on_exception(monkeypatch):
    """If the underlying to_legacy_urlsafe raises after we cleared
    _database, the finally block must put it back so the key is not
    corrupted."""
    Key = _install_fake_gcds_key(monkeypatch)

    def _explode(_self, location_prefix=None):
        raise RuntimeError("boom")

    Key.to_legacy_urlsafe = _explode
    activation._patch_legacy_urlsafe()

    k = Key("user", "abc", database="viur-tests")
    with pytest.raises(RuntimeError, match="boom"):
        k.to_legacy_urlsafe()
    assert k._database == "viur-tests"  # restored


def test_patch_key_factory_preserves_other_kwargs(monkeypatch):
    """Project and other kwargs flow through untouched."""
    captured: list = []
    Key = _install_fake_db_types_module(monkeypatch, captured)

    class _Client:
        database = "viur-tests"

    activation._patch_key_factory(_Client())

    Key("kind", "id", project="proj-x", namespace="ns-1")
    last = captured[-1]
    assert last["project"] == "proj-x"
    assert last["kwargs"] == {"database": "viur-tests", "namespace": "ns-1"}


def test_patch_key_factory_is_idempotent(monkeypatch):
    """Re-entering _patch_key_factory (e.g. test re-activation after the
    transport stub is popped) must not stack wrapper layers — the
    second wrapper rebuilds on top of the original __init__, not on
    top of the previous wrapper.

    Stacking would be observationally OK with identical params (the
    inner setdefault is a no-op), but the wrapper chain would grow
    unboundedly across test re-entries.
    """
    captured: list = []
    Key = _install_fake_db_types_module(monkeypatch, captured)
    original_init = Key.__init__

    class _Client:
        database = "viur-tests"
        namespace = "alice"

    activation._patch_key_factory(_Client())
    first_wrapper = Key.__init__
    assert first_wrapper is not original_init

    # Re-patch with the same client — the wrapper must reference the
    # ORIGINAL init, not the first wrapper.
    activation._patch_key_factory(_Client())
    second_wrapper = Key.__init__
    assert second_wrapper is not first_wrapper
    assert getattr(second_wrapper, activation._KEY_FACTORY_ORIG_ATTR) is original_init

    # Behaviour still correct.
    Key("kind", "id")
    assert captured[-1]["kwargs"]["database"] == "viur-tests"
    assert captured[-1]["kwargs"]["namespace"] == "alice"


def test_patch_legacy_urlsafe_is_idempotent(monkeypatch):
    """Same idempotency contract for the to_legacy_urlsafe patch."""
    Key = _install_fake_gcds_key(monkeypatch)
    original = Key.to_legacy_urlsafe

    activation._patch_legacy_urlsafe()
    first = Key.to_legacy_urlsafe
    assert first is not original

    activation._patch_legacy_urlsafe()
    second = Key.to_legacy_urlsafe
    assert second is not first
    assert getattr(second, activation._LEGACY_URLSAFE_ORIG_ATTR) is original

    # Behaviour still correct.
    k = Key("user", "abc", database="viur-tests")
    result = k.to_legacy_urlsafe()
    assert b"viur-tests" not in result
    assert k._database == "viur-tests"


# ---------------------------------------------------------------------------
# activate() integration
# ---------------------------------------------------------------------------


def _stub_patch_transport(monkeypatch, sink):
    monkeypatch.setattr(
        activation, "_patch_transport_client", lambda client: sink.append(client)
    )


def _stub_patch_key_factory(monkeypatch, sink):
    monkeypatch.setattr(
        activation, "_patch_key_factory", lambda client: sink.append(client)
    )


def _stub_patch_legacy_urlsafe(monkeypatch, sink):
    monkeypatch.setattr(
        activation, "_patch_legacy_urlsafe", lambda: sink.append("called")
    )


def _stub_open_bootstrap_paths(monkeypatch, sink):
    monkeypatch.setattr(
        activation,
        "_open_bootstrap_paths_in_closed_system",
        lambda: sink.append("called"),
    )


def test_activate_happy_path(monkeypatch, router_validators):
    client = _FakeClient(database="viur-tests", project="proj-z")
    _install_fake_datastore_module(monkeypatch, client=client)

    sink: list = []
    _stub_patch_transport(monkeypatch, sink)
    key_sink: list = []
    _stub_patch_key_factory(monkeypatch, key_sink)
    _stub_patch_legacy_urlsafe(monkeypatch, [])
    open_paths_sink: list = []
    _stub_open_bootstrap_paths(monkeypatch, open_paths_sink)

    activation.activate(database="viur-tests")

    assert ConfigModule.is_active()
    assert ConfigModule.has_token() is False
    assert ConfigModule.current_database() == "viur-tests"
    assert ConfigModule.current_project_id() == "proj-z"
    assert sink == [client]
    assert key_sink == [client]  # key-factory patch also reached
    assert open_paths_sink == ["called"]  # closed-system whitelist also extended

    from viur.testing.validator import TokenValidator

    assert TokenValidator in router_validators


def test_activate_refuses_when_not_dev_server(conf_instance):
    conf_instance.is_dev_server = False
    with pytest.raises(RuntimeError, match="local dev server"):
        activation.activate(database="viur-tests")
    assert not ConfigModule.is_active()


def test_activate_refuses_when_transport_already_loaded(monkeypatch):
    monkeypatch.setitem(
        sys.modules, "viur.core.db.transport", types.ModuleType("transport")
    )
    with pytest.raises(RuntimeError, match="must run BEFORE"):
        activation.activate(database="viur-tests")
    assert not ConfigModule.is_active()


def test_activate_propagates_probe_failure(monkeypatch):
    client = _FakeClient(database="viur-tests")
    _install_fake_datastore_module(monkeypatch, client=client)
    client.get = lambda key: None

    sink: list = []
    _stub_patch_transport(monkeypatch, sink)

    with pytest.raises(RuntimeError, match="did not return on read-back"):
        activation.activate(database="viur-tests")
    assert not ConfigModule.is_active()
    assert sink == []  # transport patch never reached


def test_activate_propagates_database_mismatch(monkeypatch):
    client = _FakeClient(database="viur-tests", refuse_database=True)
    _install_fake_datastore_module(monkeypatch, client=client)

    with pytest.raises(RuntimeError, match="did not honour database"):
        activation.activate(database="viur-tests")
    assert not ConfigModule.is_active()


def test_activate_propagates_namespace_to_config_module(monkeypatch, router_validators):
    """When ``activate(namespace=…)`` is called the ConfigModule's
    in-process state must reflect it so ``/_test/config/status`` can
    report it back to runners."""
    client = _FakeClient(database="viur-tests", project="proj-z", namespace="alice")
    _install_fake_datastore_module(monkeypatch, client=client)

    _stub_patch_transport(monkeypatch, [])
    _stub_patch_key_factory(monkeypatch, [])
    _stub_patch_legacy_urlsafe(monkeypatch, [])
    _stub_open_bootstrap_paths(monkeypatch, [])

    activation.activate(database="viur-tests", namespace="alice")

    assert ConfigModule.current_namespace() == "alice"


def test_activate_default_namespace_is_none(monkeypatch, router_validators):
    client = _FakeClient(database="viur-tests", project="proj-z")
    _install_fake_datastore_module(monkeypatch, client=client)
    _stub_patch_transport(monkeypatch, [])
    _stub_patch_key_factory(monkeypatch, [])
    _stub_patch_legacy_urlsafe(monkeypatch, [])
    _stub_open_bootstrap_paths(monkeypatch, [])

    activation.activate(database="viur-tests")
    assert ConfigModule.current_namespace() is None


def test_activate_normalises_empty_namespace_to_none(monkeypatch, router_validators):
    """``activate(namespace="")`` is the same as no namespace — matches
    setup()'s env-var handling so direct programmatic calls and the
    ``VIUR_TESTING_NAMESPACE=`` boot path behave identically.

    Regression guard: an earlier version passed ``namespace=""`` straight
    through, which built a datastore.Client with an empty-string
    namespace (not the default namespace) — silent data divergence
    that's painful to debug.
    """
    captured: dict = {}
    client = _FakeClient(database="viur-tests", project="proj-z")
    _install_fake_datastore_capturing(monkeypatch, client=client, captured=captured)
    _stub_patch_transport(monkeypatch, [])
    _stub_patch_key_factory(monkeypatch, [])
    _stub_patch_legacy_urlsafe(monkeypatch, [])
    _stub_open_bootstrap_paths(monkeypatch, [])

    activation.activate(database="viur-tests", namespace="")

    assert "namespace" not in captured  # client built without namespace kwarg
    assert ConfigModule.current_namespace() is None


def test_activate_installs_banner_patch(monkeypatch, router_validators):
    """A successful activate() must wrap ``viur.core.setup`` so the boot
    banner gains the ``database = ...`` line."""
    client = _FakeClient(database="viur-tests")
    _install_fake_datastore_module(monkeypatch, client=client)
    _stub_patch_transport(monkeypatch, [])
    _stub_patch_key_factory(monkeypatch, [])
    _stub_patch_legacy_urlsafe(monkeypatch, [])
    _stub_open_bootstrap_paths(monkeypatch, [])

    activation.activate(database="viur-tests")

    from viur.testing.banner import _PATCH_SENTINEL_ATTR

    viur_core = sys.modules["viur.core"]
    assert getattr(viur_core.setup, _PATCH_SENTINEL_ATTR, False) is True


def test_activate_calls_patch_legacy_urlsafe(monkeypatch, router_validators):
    """activate() must wire the to_legacy_urlsafe named-DB workaround
    so str(key) works after login."""
    client = _FakeClient(database="viur-tests")
    _install_fake_datastore_module(monkeypatch, client=client)
    _stub_patch_transport(monkeypatch, [])
    _stub_patch_key_factory(monkeypatch, [])
    called: list = []
    _stub_patch_legacy_urlsafe(monkeypatch, called)
    _stub_open_bootstrap_paths(monkeypatch, [])

    activation.activate(database="viur-tests")
    assert called == ["called"]


def test_activate_uses_default_database_name(monkeypatch):
    client = _FakeClient(database="viur-tests")
    _install_fake_datastore_module(monkeypatch, client=client)
    _stub_patch_transport(monkeypatch, [])
    _stub_patch_key_factory(monkeypatch, [])
    _stub_patch_legacy_urlsafe(monkeypatch, [])
    _stub_open_bootstrap_paths(monkeypatch, [])

    activation.activate()
    assert ConfigModule.current_database() == "viur-tests"
