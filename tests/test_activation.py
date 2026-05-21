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
    def __init__(self, database, project="proj-x", refuse_database=False):
        self.database = None if refuse_database else database
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
    fake_mod.Client = lambda database, **kwargs: client
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
        # Concrete and wildcard variants both appear — see _BOOTSTRAP_OPEN_PATHS.
        assert "_test/config/status" in paths
        assert "_test/config/finish" in paths
        assert "_test/config/*" in paths
        assert "*/_test/config/*" in paths
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
        assert paths.count("_test/config/status") == 1
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


def test_patch_key_factory_no_op_when_client_has_no_database(monkeypatch):
    """A default-DB client (database=None) leaves Key.__init__ alone."""
    captured: list = []
    Key = _install_fake_db_types_module(monkeypatch, captured)

    class _DefaultClient:
        database = None

    activation._patch_key_factory(_DefaultClient())

    Key("kind", "id")
    assert captured == [{"path": ("kind", "id"), "project": None, "kwargs": {}}]


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


def test_activate_uses_default_database_name(monkeypatch):
    client = _FakeClient(database="viur-tests")
    _install_fake_datastore_module(monkeypatch, client=client)
    _stub_patch_transport(monkeypatch, [])
    _stub_patch_key_factory(monkeypatch, [])
    _stub_open_bootstrap_paths(monkeypatch, [])

    activation.activate()
    assert ConfigModule.current_database() == "viur-tests"
