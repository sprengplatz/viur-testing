"""Unit tests for :class:`viur.testing._test.TestModule` — the container."""

import pytest

from viur.core import Module

from viur.testing._test import TestModule
from viur.testing._test.config import ConfigModule


@pytest.fixture(autouse=True)
def _reset_user_submodules():
    """Class-level ``TestModule._user_submodules`` would otherwise leak
    registrations between tests. Snapshot and restore it per test."""
    saved = dict(TestModule._user_submodules)
    yield
    TestModule._user_submodules.clear()
    TestModule._user_submodules.update(saved)


@pytest.fixture
def activated():
    """Simulate a successful ``activate()`` by priming ConfigModule's state.

    The autouse conftest fixture already resets ConfigModule between tests,
    so we only need to set it active here.
    """
    ConfigModule.set_active(database="viur-tests", project_id="proj-x")


# ---------------------------------------------------------------------------
# Submodule wiring
# ---------------------------------------------------------------------------


def test_container_mounts_config_submodule(activated):
    """``self.config`` must be a ConfigModule and picked up by viur-core."""
    container = TestModule(moduleName="_test", modulePath="_test")
    assert isinstance(container.config, ConfigModule)
    assert "config" in container._modules
    assert container._modules["config"] is container.config


def test_container_uses_default_names(activated):
    container = TestModule()
    assert container.moduleName == "_test"
    assert container.modulePath == "_test"
    assert container.config.modulePath == "_test/config"


def test_container_propagates_custom_paths(activated):
    container = TestModule(moduleName="_test", modulePath="json/_test")
    assert container.config.modulePath == "json/_test/config"


def test_handler_is_test():
    assert TestModule.handler == "test"


def test_module_opts_into_json_renderer():
    """viur-core's __build_app skips module classes whose render-name attr
    is falsy. Without ``json = True`` the routes would silently not appear
    under ``/json/_test/config/*``."""
    assert TestModule.json is True


# ---------------------------------------------------------------------------
# Dev-server guard
# ---------------------------------------------------------------------------


def test_container_refuses_to_instantiate_when_not_dev_server(activated, conf_instance):
    """Structural last line of defence against an accidental prod mount."""
    conf_instance.is_dev_server = False
    with pytest.raises(RuntimeError, match="local dev server"):
        TestModule()


def test_container_refuses_with_custom_args_too(activated, conf_instance):
    conf_instance.is_dev_server = False
    with pytest.raises(RuntimeError, match="local dev server"):
        TestModule(moduleName="_test", modulePath="_test")


# ---------------------------------------------------------------------------
# Activate-required guard
# ---------------------------------------------------------------------------


def test_container_refuses_when_activate_was_not_called():
    """Mount without prior ``activate()`` must fail loudly.

    Without this guard the host would see a successful mount but every
    request to ``/_test/config/...`` would 403 from ``_require_runtime_consistency``
    — a stealthy "kind of working" state. Better to fail at boot.
    """
    # ConfigModule state has been reset by the autouse fixture; not active.
    with pytest.raises(RuntimeError, match="activate"):
        TestModule()


def test_container_refuses_when_activate_was_not_called_even_with_args():
    with pytest.raises(RuntimeError, match="activate"):
        TestModule(moduleName="_test", modulePath="_test")


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------


def test_container_is_excluded_from_pytest_collection():
    """``__test__ = False`` is the pytest-recommended opt-out."""
    assert TestModule.__test__ is False


# ---------------------------------------------------------------------------
# Host-provided submodules (register_submodule)
# ---------------------------------------------------------------------------


class _DummyTestSpec(Module):
    """A bare-bones viur Module — stand-in for project-specific test
    fixtures (setup/teardown endpoints)."""
    json = True


def test_register_submodule_attaches_at_mount(activated):
    """Names are normalised to lowercase so the mount key matches the
    lower-cased URL segment that viur-core's router will look up."""
    TestModule.register_submodule("userLogin", _DummyTestSpec)
    container = TestModule()
    assert "userlogin" in container._modules
    assert isinstance(container.userlogin, _DummyTestSpec)
    assert container.userlogin.modulePath == "_test/userlogin"


def test_register_submodule_supports_multiple_specs(activated):
    class _Logout(Module):
        json = True

    TestModule.register_submodule("userLogin", _DummyTestSpec)
    TestModule.register_submodule("logout", _Logout)

    container = TestModule()
    assert isinstance(container.userlogin, _DummyTestSpec)
    assert isinstance(container.logout, _Logout)


def test_register_submodule_normalises_to_lowercase():
    """The dict key is the lowercased name regardless of caller casing."""
    TestModule.register_submodule("UserLogin", _DummyTestSpec)
    assert "userlogin" in TestModule._user_submodules
    assert "UserLogin" not in TestModule._user_submodules


def test_register_submodule_rejects_reserved_name():
    with pytest.raises(ValueError, match="reserved"):
        TestModule.register_submodule("config", _DummyTestSpec)


def test_register_submodule_rejects_empty_name():
    with pytest.raises(ValueError, match="non-empty"):
        TestModule.register_submodule("", _DummyTestSpec)


@pytest.mark.parametrize(
    "bad_name",
    [
        # Leading underscore — would collide with module-internal attrs.
        "_methods",
        "_modules",
        # Dunder.
        "__init__",
        # Dot / slash — would either break setattr or invent routes.
        "user.login",
        "user/login",
        # Whitespace / non-ASCII.
        "user login",
        "user-löschen",
        # Starts with digit — not a valid Python attribute prefix.
        "1login",
        # Empty after lowercasing-only-symbols (regex still rejects).
        "----",
    ],
)
def test_register_submodule_rejects_malformed_names(bad_name):
    """Names must be safe to use as both a Python attribute and a URL
    segment. Anything outside ``^[a-z][a-z0-9_-]*$`` is refused so
    surprising routing/attribute-collision bugs cannot sneak in."""
    with pytest.raises(ValueError, match="must match"):
        TestModule.register_submodule(bad_name, _DummyTestSpec)


@pytest.mark.parametrize(
    "shadowing_name",
    [
        # Renderer flag — overwriting this disables route registration
        # via viur-core's __build_app render-name opt-in scan.
        "json",
        # viur-core Module class attribute — overwriting it would break
        # viur-core's mounting/auth path.
        "handler",
    ],
)
def test_register_submodule_rejects_attribute_shadowing(shadowing_name):
    """Names that already exist as class attributes on ``TestModule``
    (or its bases) must be refused — they would silently break either
    viur-core mounting or test-mode internals.

    Note: this is a class-level ``hasattr`` check. Instance-only attrs
    set in ``__init__`` (``moduleName``, ``modulePath``) are not on
    the class and therefore *not* caught here — but those happen to
    also be camelCased and would be lowercased by ``register_submodule``
    before lookup, so the registered name does not actually shadow
    the camelCased instance attr."""
    with pytest.raises(ValueError, match="shadow"):
        TestModule.register_submodule(shadowing_name, _DummyTestSpec)


def test_register_submodule_overwrites_previous_for_same_name(activated):
    """Re-registering ``userLogin`` replaces the previous class — the
    last wins, no silent merge."""
    class _Replacement(Module):
        json = True

    TestModule.register_submodule("userLogin", _DummyTestSpec)
    TestModule.register_submodule("userLogin", _Replacement)
    container = TestModule()
    assert isinstance(container.userlogin, _Replacement)


def test_register_submodule_propagates_render_prefix(activated):
    """A host submodule mounted under a renderer prefix gets its
    modulePath set so viur-core's router can find it. The prefix
    flows through from the container's modulePath."""
    TestModule.register_submodule("userLogin", _DummyTestSpec)
    container = TestModule(moduleName="_test", modulePath="json/_test")
    assert container.userlogin.modulePath == "json/_test/userlogin"


def test_no_user_submodules_means_only_config(activated):
    """Without any registration, the container mounts only `config`."""
    container = TestModule()
    assert set(container._modules) == {"config"}
