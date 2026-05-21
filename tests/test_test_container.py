"""Unit tests for :class:`viur.testing._test.TestModule` — the container."""

import pytest

from viur.testing._test import TestModule
from viur.testing._test.config import ConfigModule


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
