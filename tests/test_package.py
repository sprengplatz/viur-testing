"""Tests for the top-level :mod:`viur.testing` package surface."""

import pytest

import viur.testing


def test_top_level_exports():
    """The package exports only the small, viur-core-free surface."""
    expected = {
        "DEFAULT_DATABASE",
        "ServerStatus",
        "TOKEN_HEADER",
        "TestModePreflightError",
        "activate",
        "finish",
        "protect",
        "register_modules",
        "require_test_mode",
        "setup",
    }
    assert set(viur.testing.__all__) == expected
    for name in expected:
        assert hasattr(viur.testing, name), name


def test_heavy_classes_not_on_top_level():
    """TestModule/ConfigModule/TokenValidator/ProductionGuardValidator
    are intentionally NOT re-exported on the package root — they would
    trigger ``viur.core`` import at ``import viur.testing`` time, which
    must stay clean so ``activate()`` can swap the datastore client first.
    """
    for name in ("TestModule", "ConfigModule", "TokenValidator", "ProductionGuardValidator"):
        assert not hasattr(viur.testing, name), name


# ---------------------------------------------------------------------------
# setup()
# ---------------------------------------------------------------------------


def test_setup_calls_activate_when_env_var_truthy(monkeypatch):
    """When the gate env var is set, setup() must invoke activate()
    with the configured database, then protect()."""
    calls: list = []
    monkeypatch.setenv("VIUR_TESTING_ENABLE", "1")
    monkeypatch.setattr(
        viur.testing, "activate", lambda **kw: calls.append(("activate", kw))
    )
    monkeypatch.setattr(viur.testing, "protect", lambda: calls.append(("protect",)))
    viur.testing.setup()
    assert calls == [("activate", {"database": "viur-tests"}), ("protect",)]


def test_setup_skips_activate_when_env_var_unset(monkeypatch):
    calls: list = []
    monkeypatch.delenv("VIUR_TESTING_ENABLE", raising=False)
    monkeypatch.setattr(
        viur.testing, "activate", lambda **kw: calls.append(("activate", kw))
    )
    monkeypatch.setattr(viur.testing, "protect", lambda: calls.append(("protect",)))
    viur.testing.setup()
    assert calls == [("protect",)]


def test_setup_skips_activate_when_env_var_empty_string(monkeypatch):
    calls: list = []
    monkeypatch.setenv("VIUR_TESTING_ENABLE", "")
    monkeypatch.setattr(
        viur.testing, "activate", lambda **kw: calls.append(("activate", kw))
    )
    monkeypatch.setattr(viur.testing, "protect", lambda: calls.append(("protect",)))
    viur.testing.setup()
    assert calls == [("protect",)]


def test_setup_honours_custom_env_var_and_database(monkeypatch):
    calls: list = []
    monkeypatch.setenv("MY_TEST_FLAG", "yes")
    monkeypatch.setattr(
        viur.testing, "activate", lambda **kw: calls.append(("activate", kw))
    )
    monkeypatch.setattr(viur.testing, "protect", lambda: calls.append(("protect",)))
    viur.testing.setup(enable_env_var="MY_TEST_FLAG", database="alt-tests")
    assert calls == [("activate", {"database": "alt-tests"}), ("protect",)]


# ---------------------------------------------------------------------------
# register_modules()
# ---------------------------------------------------------------------------


def test_register_modules_injects_testmodule_when_active():
    from viur.testing._test.config import ConfigModule
    from viur.testing._test import TestModule

    ConfigModule.set_active(database="viur-tests", project_id="p")
    target: dict = {}
    viur.testing.register_modules(target)
    assert target.get("_test") is TestModule


def test_register_modules_is_no_op_when_inactive():
    """No activate() → no key is injected, so prod hosts stay clean."""
    target: dict = {"existing": "value"}
    viur.testing.register_modules(target)
    assert "_test" not in target
    assert target == {"existing": "value"}
