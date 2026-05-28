"""Unit tests for :class:`viur.testing._test.config.ConfigModule` — state + endpoints."""

import hashlib
import sys
import types

import pytest

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
    def __init__(self, database="viur-tests", project="proj-x"):
        self.database = database
        self.project = project
        self._store: dict = {}

    def key(self, kind, name):
        return _FakeKey(kind, name)

    def get(self, key):
        data = self._store.get(key)
        if data is None:
            return None
        e = _FakeEntity(key=key)
        e.update(data)
        return e

    def put(self, entity):
        self._store[entity.key] = dict(entity)

    def delete(self, key):
        self._store.pop(key, None)


@pytest.fixture(autouse=True)
def _reset_module_state():
    ConfigModule.reset()
    yield
    ConfigModule.reset()


@pytest.fixture
def client_active(install_transport_stub, monkeypatch):
    """Common setup: state active, transport stubbed, google.cloud mocked."""
    client = _FakeClient()
    install_transport_stub(client)

    fake_ds = types.ModuleType("google.cloud.datastore")
    fake_ds.Entity = _FakeEntity
    monkeypatch.setitem(sys.modules, "google.cloud.datastore", fake_ds)

    google_pkg = sys.modules.get("google") or types.ModuleType("google")
    google_cloud = sys.modules.get("google.cloud") or types.ModuleType("google.cloud")
    google_cloud.datastore = fake_ds
    google_pkg.cloud = google_cloud
    monkeypatch.setitem(sys.modules, "google", google_pkg)
    monkeypatch.setitem(sys.modules, "google.cloud", google_cloud)

    ConfigModule.set_active(database="viur-tests", project_id="proj-x")
    return client


# ---------------------------------------------------------------------------
# Mount guards (defense in depth — ConfigModule may be mounted directly,
# bypassing the TestModule container; the same checks must fire here too)
# ---------------------------------------------------------------------------


def test_config_module_refuses_when_not_dev_server(conf_instance):
    ConfigModule.set_active(database="viur-tests", project_id="p")
    conf_instance.is_dev_server = False
    with pytest.raises(RuntimeError, match="local dev server"):
        ConfigModule(moduleName="config", modulePath="_test/config")


def test_config_module_refuses_when_not_activated():
    # State is reset by the autouse fixture — not active.
    with pytest.raises(RuntimeError, match="activate"):
        ConfigModule(moduleName="config", modulePath="_test/config")


def test_config_module_mounts_when_dev_and_activated(conf_instance):
    conf_instance.is_dev_server = True
    ConfigModule.set_active(database="viur-tests", project_id="p")
    module = ConfigModule(moduleName="config", modulePath="_test/config")
    assert module.moduleName == "config"
    assert module.modulePath == "_test/config"


# ---------------------------------------------------------------------------
# State (class methods)
# ---------------------------------------------------------------------------


def test_is_active_false_initially():
    assert ConfigModule.is_active() is False
    assert ConfigModule.has_token() is False
    assert ConfigModule.current_database() is None
    assert ConfigModule.current_namespace() is None
    assert ConfigModule.current_project_id() is None
    assert ConfigModule.current_token() is None
    assert ConfigModule.current_token_hash() is None


def test_set_active_initialises_class_state():
    ConfigModule.set_active(database="viur-tests", project_id="p")
    assert ConfigModule.is_active() is True
    assert ConfigModule.current_database() == "viur-tests"
    assert ConfigModule.current_project_id() == "p"
    assert ConfigModule.current_token() is None


def test_set_active_idempotent_for_matching_args():
    ConfigModule.set_active(database="viur-tests", project_id="p")
    ConfigModule.set_active(database="viur-tests", project_id="p")  # no raise


def test_set_active_refuses_different_database():
    ConfigModule.set_active(database="viur-tests", project_id="p")
    with pytest.raises(RuntimeError, match="refusing"):
        ConfigModule.set_active(database="other", project_id="p")


def test_set_active_refuses_different_project_id():
    ConfigModule.set_active(database="viur-tests", project_id="p")
    with pytest.raises(RuntimeError, match="refusing"):
        ConfigModule.set_active(database="viur-tests", project_id="other")


def test_set_active_records_namespace():
    ConfigModule.set_active(database="viur-tests", project_id="p", namespace="alice")
    assert ConfigModule.current_namespace() == "alice"


def test_set_active_idempotent_for_matching_namespace():
    ConfigModule.set_active(database="viur-tests", project_id="p", namespace="alice")
    ConfigModule.set_active(database="viur-tests", project_id="p", namespace="alice")


def test_set_active_refuses_different_namespace():
    ConfigModule.set_active(database="viur-tests", project_id="p", namespace="alice")
    with pytest.raises(RuntimeError, match="refusing"):
        ConfigModule.set_active(database="viur-tests", project_id="p", namespace="bob")


def test_set_active_default_namespace_is_none():
    ConfigModule.set_active(database="viur-tests", project_id="p")
    assert ConfigModule.current_namespace() is None


def test_set_active_normalises_empty_namespace_to_none():
    """``set_active(namespace="")`` must be treated the same as
    ``namespace=None`` — otherwise a direct empty-string call followed
    by an :func:`activate`-driven ``None`` call (which is how the
    env-var path arrives) would falsely report a mismatch."""
    ConfigModule.set_active(database="viur-tests", project_id="p", namespace="")
    assert ConfigModule.current_namespace() is None

    # And matches a subsequent None call without raising.
    ConfigModule.set_active(database="viur-tests", project_id="p", namespace=None)
    assert ConfigModule.current_namespace() is None


def test_set_token_requires_active_state():
    with pytest.raises(RuntimeError, match="not active"):
        ConfigModule.set_token("x")


def test_set_token_and_hash():
    ConfigModule.set_active(database="viur-tests", project_id="p")
    ConfigModule.set_token("secret")
    assert ConfigModule.current_token() == "secret"
    assert ConfigModule.has_token() is True
    assert ConfigModule.current_token_hash() == hashlib.sha256(b"secret").hexdigest()


def test_clear_token_leaves_state_active():
    ConfigModule.set_active(database="viur-tests", project_id="p")
    ConfigModule.set_token("secret")
    ConfigModule.clear_token()
    assert ConfigModule.has_token() is False
    assert ConfigModule.is_active() is True


def test_reset_clears_everything():
    ConfigModule.set_active(database="viur-tests", project_id="p")
    ConfigModule.set_token("secret")
    ConfigModule.reset()
    assert ConfigModule.is_active() is False


# ---------------------------------------------------------------------------
# status()
# ---------------------------------------------------------------------------


def test_status_creates_token_on_first_call(client_active):
    import json
    import viur.testing

    module = ConfigModule(moduleName="config", modulePath="_test/config")
    raw = module.status()
    assert isinstance(raw, str), "status() must return a JSON string, not a dict"
    result = json.loads(raw)

    assert result["test_mode"] is True
    assert result["is_dev_server"] is True
    assert result["database"] == "viur-tests"
    assert result["namespace"] is None
    assert result["project_id"] == "proj-x"
    assert isinstance(result["token"], str) and len(result["token"]) >= 40
    assert result["version"] == viur.testing.__version__
    assert (
        result["token_hash"]
        == hashlib.sha256(result["token"].encode("utf-8")).hexdigest()
    )

    key = _FakeKey("viur-tests", "auth-token")
    assert client_active._store[key]["token"] == result["token"]
    assert ConfigModule.current_token() == result["token"]


def test_status_reports_namespace_when_set(install_transport_stub, monkeypatch):
    """When ConfigModule is activated with a namespace, the status
    endpoint must echo it back so runners can preflight against it."""
    import json

    client = _FakeClient()
    install_transport_stub(client)

    fake_ds = types.ModuleType("google.cloud.datastore")
    fake_ds.Entity = _FakeEntity
    monkeypatch.setitem(sys.modules, "google.cloud.datastore", fake_ds)
    google_pkg = sys.modules.get("google") or types.ModuleType("google")
    google_cloud = sys.modules.get("google.cloud") or types.ModuleType("google.cloud")
    google_cloud.datastore = fake_ds
    google_pkg.cloud = google_cloud
    monkeypatch.setitem(sys.modules, "google", google_pkg)
    monkeypatch.setitem(sys.modules, "google.cloud", google_cloud)

    ConfigModule.set_active(database="viur-tests", project_id="proj-x", namespace="alice")

    module = ConfigModule(moduleName="config", modulePath="_test/config")
    result = json.loads(module.status())
    assert result["namespace"] == "alice"


def test_status_sets_content_type_to_json(client_active):
    import sys

    module = ConfigModule(moduleName="config", modulePath="_test/config")
    module.status()
    request = sys.modules["viur.core.current"].request.get()
    assert request.response.headers["Content-Type"] == "application/json"


def test_status_is_idempotent(client_active):
    import json

    module = ConfigModule(moduleName="config", modulePath="_test/config")
    first = json.loads(module.status())
    second = json.loads(module.status())
    assert first["token"] == second["token"]


def test_status_reuses_existing_db_entity(client_active):
    import json

    entity = _FakeEntity(key=_FakeKey("viur-tests", "auth-token"))
    entity["token"] = "from-db"
    client_active.put(entity)

    module = ConfigModule(moduleName="config", modulePath="_test/config")
    result = json.loads(module.status())
    assert result["token"] == "from-db"


def test_status_refuses_when_dev_server_is_false(client_active, conf_instance):
    # Instantiate first (guard passes), then flip is_dev_server to simulate
    # a runtime change between mount and request.
    module = ConfigModule(moduleName="config", modulePath="_test/config")
    conf_instance.is_dev_server = False
    from viur.core.errors import Forbidden

    with pytest.raises(Forbidden, match="dev mode"):
        module.status()


def test_status_refuses_when_state_inactive(client_active):
    # Instantiate first (guard passes), then reset state to simulate
    # a runtime change between mount and request.
    module = ConfigModule(moduleName="config", modulePath="_test/config")
    ConfigModule.reset()
    from viur.core.errors import Forbidden

    with pytest.raises(Forbidden, match="activate"):
        module.status()


def test_status_refuses_when_client_on_wrong_database(install_transport_stub):
    ConfigModule.set_active(database="viur-tests", project_id="p")
    install_transport_stub(_FakeClient(database="(default)"))
    from viur.core.errors import Forbidden

    module = ConfigModule(moduleName="config", modulePath="_test/config")
    with pytest.raises(Forbidden, match="datastore client"):
        module.status()


def test_status_treats_malformed_entity_as_missing(client_active):
    import json

    key = _FakeKey("viur-tests", "auth-token")
    client_active._store[key] = {"token": 12345}  # wrong type
    module = ConfigModule(moduleName="config", modulePath="_test/config")
    result = json.loads(module.status())
    assert isinstance(result["token"], str)
    assert isinstance(client_active._store[key]["token"], str)


def test_status_is_marked_exposed_and_post_only():
    assert getattr(ConfigModule.status, "exposed", False) is True
    assert getattr(ConfigModule.status, "force_post", False) is True


# ---------------------------------------------------------------------------
# status() — project-supplied hooks
# ---------------------------------------------------------------------------


def test_status_hook_dict_is_merged_into_response(client_active):
    import json

    ConfigModule.register_status_hook(lambda: {"project_config": {"feature_x": True}})

    module = ConfigModule(moduleName="config", modulePath="_test/config")
    result = json.loads(module.status())
    assert result["project_config"] == {"feature_x": True}
    # Built-in fields are preserved alongside the hook's output.
    assert result["test_mode"] is True
    assert isinstance(result["token"], str)


def test_status_hook_returning_none_is_a_noop(client_active):
    import json

    ConfigModule.register_status_hook(lambda: None)

    module = ConfigModule(moduleName="config", modulePath="_test/config")
    result = json.loads(module.status())
    # No extra keys beyond the standard payload.
    expected = {
        "test_mode", "is_dev_server", "database", "namespace",
        "project_id", "token", "token_hash", "version",
    }
    assert set(result) == expected


def test_multiple_status_hooks_later_wins_on_conflict(client_active):
    import json

    ConfigModule.register_status_hook(lambda: {"shared": "first", "from_first": 1})
    ConfigModule.register_status_hook(lambda: {"shared": "second", "from_second": 2})

    module = ConfigModule(moduleName="config", modulePath="_test/config")
    result = json.loads(module.status())
    assert result["shared"] == "second"
    assert result["from_first"] == 1
    assert result["from_second"] == 2


# ---------------------------------------------------------------------------
# finish()
# ---------------------------------------------------------------------------


def test_finish_deletes_token_from_db(client_active):
    import json

    module = ConfigModule(moduleName="config", modulePath="_test/config")
    module.status()
    key = _FakeKey("viur-tests", "auth-token")
    assert key in client_active._store

    raw = module.finish()
    assert isinstance(raw, str), "finish() must return a JSON string, not a dict"
    assert json.loads(raw) == {"finished": True, "had_token": True}
    assert key not in client_active._store
    assert ConfigModule.has_token() is False
    assert ConfigModule.is_active() is True


def test_finish_reports_no_token_when_nothing_to_delete(client_active):
    import json

    module = ConfigModule(moduleName="config", modulePath="_test/config")
    raw = module.finish()
    assert json.loads(raw) == {"finished": True, "had_token": False}


def test_finish_refuses_when_dev_server_is_false(client_active, conf_instance):
    # Instantiate first, then flip is_dev_server to simulate a runtime
    # change between mount and request.
    module = ConfigModule(moduleName="config", modulePath="_test/config")
    conf_instance.is_dev_server = False
    from viur.core.errors import Forbidden

    with pytest.raises(Forbidden, match="dev mode"):
        module.finish()


def test_finish_is_marked_exposed_and_post_only():
    assert getattr(ConfigModule.finish, "exposed", False) is True
    assert getattr(ConfigModule.finish, "force_post", False) is True


# ---------------------------------------------------------------------------
# finish() — project-supplied hooks
# ---------------------------------------------------------------------------


def test_finish_hook_dict_is_merged_into_response(client_active):
    import json

    ConfigModule.register_finish_hook(lambda: {"summary": {"users_cleaned": 3}})

    module = ConfigModule(moduleName="config", modulePath="_test/config")
    raw = module.finish()
    result = json.loads(raw)
    assert result["summary"] == {"users_cleaned": 3}
    assert result["finished"] is True


def test_finish_hook_returning_none_is_a_noop(client_active):
    import json

    ConfigModule.register_finish_hook(lambda: None)

    module = ConfigModule(moduleName="config", modulePath="_test/config")
    result = json.loads(module.finish())
    assert set(result) == {"finished", "had_token"}


# ---------------------------------------------------------------------------
# Hook registration mechanics
# ---------------------------------------------------------------------------


def test_reset_clears_status_hooks():
    ConfigModule.register_status_hook(lambda: {"x": 1})
    assert len(ConfigModule._status_hooks) == 1
    ConfigModule.reset()
    assert ConfigModule._status_hooks == []


def test_reset_clears_finish_hooks():
    ConfigModule.register_finish_hook(lambda: {"x": 1})
    assert len(ConfigModule._finish_hooks) == 1
    ConfigModule.reset()
    assert ConfigModule._finish_hooks == []
