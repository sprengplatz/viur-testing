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
        "register_finish_hook",
        "register_modules",
        "register_status_hook",
        "register_test_submodule",
        "require_test_mode",
        "setup",
    }
    assert set(viur.testing.__all__) == expected
    for name in expected:
        assert hasattr(viur.testing, name), name


def test_register_test_submodule_delegates_to_testmodule(monkeypatch):
    """The top-level ``register_test_submodule`` is a thin wrapper around
    ``TestModule.register_submodule``."""
    from viur.testing._test import TestModule

    calls: list = []
    monkeypatch.setattr(
        TestModule, "register_submodule",
        classmethod(lambda cls, name, mcls: calls.append((name, mcls))),
    )
    viur.testing.register_test_submodule("userLogin", object)
    assert calls == [("userLogin", object)]


def test_register_status_hook_delegates_to_configmodule(monkeypatch):
    """Top-level wrapper around
    :meth:`ConfigModule.register_status_hook`."""
    from viur.testing._test.config import ConfigModule

    calls: list = []
    monkeypatch.setattr(
        ConfigModule, "register_status_hook",
        classmethod(lambda cls, hook: calls.append(hook)),
    )
    sentinel = lambda: {"x": 1}  # noqa: E731 — clearer than def in a test
    viur.testing.register_status_hook(sentinel)
    assert calls == [sentinel]


def test_register_finish_hook_delegates_to_configmodule(monkeypatch):
    """Top-level wrapper around
    :meth:`ConfigModule.register_finish_hook`."""
    from viur.testing._test.config import ConfigModule

    calls: list = []
    monkeypatch.setattr(
        ConfigModule, "register_finish_hook",
        classmethod(lambda cls, hook: calls.append(hook)),
    )
    sentinel = lambda: None  # noqa: E731
    viur.testing.register_finish_hook(sentinel)
    assert calls == [sentinel]


# ---------------------------------------------------------------------------
# setup(api_dir=...) — project test API loading
# ---------------------------------------------------------------------------


def test_load_api_package_registers_module_when_init_exists(tmp_path):
    """Given a real `__init__.py`, `_load_api_package` registers the
    package in sys.modules and executes its body."""
    from viur.testing import _load_api_package

    pkg_dir = tmp_path / "api"
    pkg_dir.mkdir()
    api_init = pkg_dir / "__init__.py"
    api_init.write_text("MARKER = 'loaded'\n")

    import sys
    sys.modules.pop("api", None)
    try:
        _load_api_package(str(api_init))
        assert "api" in sys.modules
        assert sys.modules["api"].MARKER == "loaded"
    finally:
        sys.modules.pop("api", None)


def test_load_api_package_prints_info_when_missing(tmp_path, capsys):
    """Missing `__init__.py` → info line, no crash."""
    from viur.testing import _load_api_package

    missing = tmp_path / "nope" / "__init__.py"
    _load_api_package(str(missing))

    out = capsys.readouterr().out
    assert "no api package found" in out
    assert str(missing) in out


def test_load_project_api_resolves_path_relative_to_caller(tmp_path):
    """``_load_project_api(api_dir, caller_file)`` builds
    ``<caller_parent>/<api_dir>/api/__init__.py`` and loads it."""
    from viur.testing import _load_project_api

    # Layout:
    #   tmp_path/deploy/host.py  (the "caller")
    #   tmp_path/testing/api/__init__.py
    deploy_dir = tmp_path / "deploy"
    deploy_dir.mkdir()
    host_file = deploy_dir / "host.py"
    host_file.write_text("# stand-in main.py\n")

    api_pkg = tmp_path / "testing" / "api"
    api_pkg.mkdir(parents=True)
    (api_pkg / "__init__.py").write_text("MARKER = 'via-caller'\n")

    import sys
    sys.modules.pop("api", None)
    try:
        _load_project_api("testing", caller_file=str(host_file))
        assert sys.modules["api"].MARKER == "via-caller"
    finally:
        sys.modules.pop("api", None)


def test_load_project_api_walks_stack_when_caller_file_is_none(monkeypatch, tmp_path):
    """Without explicit `caller_file`, the function walks the call
    stack via inspect.stack to find the original caller of `setup`."""
    import inspect
    from viur.testing import _load_project_api

    deploy_dir = tmp_path / "deploy"
    deploy_dir.mkdir()
    fake_main = deploy_dir / "main.py"
    fake_main.write_text("# stub\n")

    api_pkg = tmp_path / "testing" / "api"
    api_pkg.mkdir(parents=True)
    (api_pkg / "__init__.py").write_text("MARKER = 'via-stack'\n")

    # Fake stack[2] (caller-of-setup) to point at our temp main.py.
    class _Frame:
        def __init__(self, filename: str) -> None:
            self.filename = filename

    monkeypatch.setattr(
        inspect, "stack",
        lambda: [_Frame("_load_project_api"), _Frame("setup"), _Frame(str(fake_main))],
    )

    import sys
    sys.modules.pop("api", None)
    try:
        _load_project_api("testing")  # caller_file=None → uses stack
        assert sys.modules["api"].MARKER == "via-stack"
    finally:
        sys.modules.pop("api", None)


def test_setup_skips_api_loading_when_test_mode_off(monkeypatch, tmp_path):
    """Without the gate env var, `api_dir` is ignored entirely — even
    a valid wrapper is left untouched."""
    api_pkg = tmp_path / "testing" / "api"
    api_pkg.mkdir(parents=True)
    (api_pkg / "__init__.py").write_text("MARKER = 'should-not-load'\n")

    monkeypatch.delenv("VIUR_TESTING_ENABLE", raising=False)
    monkeypatch.setattr(viur.testing, "protect", lambda: None)

    import sys
    sys.modules.pop("api", None)
    viur.testing.setup(api_dir="testing")
    assert "api" not in sys.modules


def test_setup_skips_api_loading_when_api_dir_is_none(monkeypatch):
    """`api_dir=None` is the explicit opt-out: never touch sys.modules['api']."""
    monkeypatch.setenv("VIUR_TESTING_ENABLE", "1")
    monkeypatch.delenv("VIUR_TESTING_NAMESPACE", raising=False)
    monkeypatch.setattr(viur.testing, "activate", lambda **kw: None)
    monkeypatch.setattr(viur.testing, "protect", lambda: None)

    import sys
    sys.modules.pop("api", None)
    viur.testing.setup(api_dir=None)
    assert "api" not in sys.modules


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
    monkeypatch.delenv("VIUR_TESTING_NAMESPACE", raising=False)
    monkeypatch.setattr(
        viur.testing, "activate", lambda **kw: calls.append(("activate", kw))
    )
    monkeypatch.setattr(viur.testing, "protect", lambda: calls.append(("protect",)))
    viur.testing.setup()
    assert calls == [
        ("activate", {"database": "viur-tests", "namespace": None}),
        ("protect",),
    ]


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
    monkeypatch.delenv("VIUR_TESTING_NAMESPACE", raising=False)
    monkeypatch.setattr(
        viur.testing, "activate", lambda **kw: calls.append(("activate", kw))
    )
    monkeypatch.setattr(viur.testing, "protect", lambda: calls.append(("protect",)))
    viur.testing.setup(enable_env_var="MY_TEST_FLAG", database="alt-tests")
    assert calls == [
        ("activate", {"database": "alt-tests", "namespace": None}),
        ("protect",),
    ]


def test_setup_reads_namespace_from_env_var(monkeypatch):
    """``VIUR_TESTING_NAMESPACE`` env var feeds into activate()."""
    calls: list = []
    monkeypatch.setenv("VIUR_TESTING_ENABLE", "1")
    monkeypatch.setenv("VIUR_TESTING_NAMESPACE", "alice")
    monkeypatch.setattr(
        viur.testing, "activate", lambda **kw: calls.append(("activate", kw))
    )
    monkeypatch.setattr(viur.testing, "protect", lambda: calls.append(("protect",)))
    viur.testing.setup()
    assert calls[0] == ("activate", {"database": "viur-tests", "namespace": "alice"})


def test_setup_explicit_namespace_overrides_env_var(monkeypatch):
    """Explicit ``namespace=`` kwarg wins over the env var."""
    calls: list = []
    monkeypatch.setenv("VIUR_TESTING_ENABLE", "1")
    monkeypatch.setenv("VIUR_TESTING_NAMESPACE", "from-env")
    monkeypatch.setattr(
        viur.testing, "activate", lambda **kw: calls.append(("activate", kw))
    )
    monkeypatch.setattr(viur.testing, "protect", lambda: calls.append(("protect",)))
    viur.testing.setup(namespace="from-call")
    assert calls[0] == ("activate", {"database": "viur-tests", "namespace": "from-call"})


def test_setup_empty_namespace_env_var_means_default(monkeypatch):
    """An empty ``VIUR_TESTING_NAMESPACE`` is treated as "no namespace"."""
    calls: list = []
    monkeypatch.setenv("VIUR_TESTING_ENABLE", "1")
    monkeypatch.setenv("VIUR_TESTING_NAMESPACE", "")
    monkeypatch.setattr(
        viur.testing, "activate", lambda **kw: calls.append(("activate", kw))
    )
    monkeypatch.setattr(viur.testing, "protect", lambda: calls.append(("protect",)))
    viur.testing.setup()
    assert calls[0] == ("activate", {"database": "viur-tests", "namespace": None})


def test_setup_honours_custom_namespace_env_var(monkeypatch):
    """Caller can override the env var name."""
    calls: list = []
    monkeypatch.setenv("VIUR_TESTING_ENABLE", "1")
    monkeypatch.setenv("MY_NS", "bob")
    monkeypatch.setattr(
        viur.testing, "activate", lambda **kw: calls.append(("activate", kw))
    )
    monkeypatch.setattr(viur.testing, "protect", lambda: calls.append(("protect",)))
    viur.testing.setup(namespace_env_var="MY_NS")
    assert calls[0] == ("activate", {"database": "viur-tests", "namespace": "bob"})


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
