"""Tests for the top-level :mod:`viur.testing` package surface."""

import pytest

import viur.testing


def test_top_level_exports():
    """The package exports only the small, viur-core-free surface."""
    expected = {
        "DEFAULT_DATABASE",
        "ServerStatus",
        "TOKEN_COOKIE",
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
    stack and anchors at the first frame whose file lives *outside*
    ``viur.testing`` — that is the host-side ``main.py`` (or the
    closest host-side wrapper that called ``setup``).

    A previous implementation used a hard-coded ``stack()[2]`` offset
    which silently broke as soon as any frame slipped in between
    (decorator, helper, conditional re-entry). This test exercises
    the new walk: ``stack[1]`` mimics ``setup()`` (file inside our
    package — must be skipped), ``stack[2]`` mimics the host's
    ``main.py`` (must be picked).
    """
    import inspect
    import os
    from viur.testing import _PACKAGE_DIR, _load_project_api

    deploy_dir = tmp_path / "deploy"
    deploy_dir.mkdir()
    fake_main = deploy_dir / "main.py"
    fake_main.write_text("# stub\n")

    api_pkg = tmp_path / "testing" / "api"
    api_pkg.mkdir(parents=True)
    (api_pkg / "__init__.py").write_text("MARKER = 'via-stack'\n")

    inside_pkg = os.path.join(_PACKAGE_DIR, "__init__.py")

    class _Frame:
        def __init__(self, filename: str) -> None:
            self.filename = filename

    monkeypatch.setattr(
        inspect, "stack",
        lambda: [
            _Frame(inside_pkg),       # stack[0]: _load_project_api itself
            _Frame(inside_pkg),       # stack[1]: setup() — skipped by the walk
            _Frame(str(fake_main)),   # stack[2]: host main.py — picked
        ],
    )

    import sys
    sys.modules.pop("api", None)
    try:
        _load_project_api("testing")  # caller_file=None → uses stack
        assert sys.modules["api"].MARKER == "via-stack"
    finally:
        sys.modules.pop("api", None)


def test_load_project_api_skips_extra_internal_frames(monkeypatch, tmp_path):
    """The walk must skip *every* viur.testing frame, not just one.
    Future internal helpers between :func:`setup` and
    :func:`_load_project_api` (decorators, validation steps, ...) must
    not change the resolved anchor."""
    import inspect
    import os
    from viur.testing import _PACKAGE_DIR, _load_project_api

    deploy_dir = tmp_path / "deploy"
    deploy_dir.mkdir()
    fake_main = deploy_dir / "main.py"
    fake_main.write_text("# stub\n")

    api_pkg = tmp_path / "testing" / "api"
    api_pkg.mkdir(parents=True)
    (api_pkg / "__init__.py").write_text("MARKER = 'via-deep-stack'\n")

    inside_pkg = os.path.join(_PACKAGE_DIR, "__init__.py")

    class _Frame:
        def __init__(self, filename: str) -> None:
            self.filename = filename

    monkeypatch.setattr(
        inspect, "stack",
        lambda: [
            _Frame(inside_pkg),       # _load_project_api
            _Frame(inside_pkg),       # internal helper #1
            _Frame(inside_pkg),       # internal helper #2
            _Frame(inside_pkg),       # setup()
            _Frame(str(fake_main)),   # host main.py — must still be picked
        ],
    )

    import sys
    sys.modules.pop("api", None)
    try:
        _load_project_api("testing")
        assert sys.modules["api"].MARKER == "via-deep-stack"
    finally:
        sys.modules.pop("api", None)


def test_load_project_api_raises_when_no_host_frame(monkeypatch):
    """Pathological: every frame on the stack is inside ``viur.testing``.
    Shouldn't happen in practice — :func:`setup` is always called from
    the host's ``main.py`` — but if it ever does, fail loudly with a
    pointer to the explicit-override escape hatch."""
    import inspect
    import os
    from viur.testing import _PACKAGE_DIR, _load_project_api

    inside_pkg = os.path.join(_PACKAGE_DIR, "__init__.py")

    class _Frame:
        def __init__(self, filename: str) -> None:
            self.filename = filename

    monkeypatch.setattr(
        inspect, "stack",
        lambda: [_Frame(inside_pkg), _Frame(inside_pkg)],
    )

    with pytest.raises(RuntimeError, match="host-side frame"):
        _load_project_api("testing")


def test_setup_skips_api_loading_when_test_mode_off(monkeypatch, tmp_path):
    """Without test mode, `api_dir` is ignored entirely — even
    a valid wrapper is left untouched."""
    api_pkg = tmp_path / "testing" / "api"
    api_pkg.mkdir(parents=True)
    (api_pkg / "__init__.py").write_text("MARKER = 'should-not-load'\n")

    monkeypatch.delenv("VIUR_TESTING", raising=False)
    monkeypatch.setattr(viur.testing, "protect", lambda: None)

    import sys
    sys.modules.pop("api", None)
    viur.testing.setup(api_dir="testing")
    assert "api" not in sys.modules


def test_setup_skips_api_loading_when_api_dir_is_none(monkeypatch):
    """`api_dir=None` is the explicit opt-out: never touch sys.modules['api']."""
    monkeypatch.setenv("VIUR_TESTING", "test")
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


def test_setup_treats_bare_value_as_namespace(monkeypatch):
    """A non-boolean value is the namespace verbatim — the former mode
    keyword ``test`` is now just a namespace name."""
    calls: list = []
    monkeypatch.setenv("VIUR_TESTING", "test")
    monkeypatch.setattr(
        viur.testing, "activate", lambda **kw: calls.append(("activate", kw))
    )
    monkeypatch.setattr(viur.testing, "protect", lambda: calls.append(("protect",)))
    viur.testing.setup(api_dir=None)
    assert calls == [
        ("activate", {"database": "viur-tests", "namespace": "test"}),
        ("protect",),
    ]


def test_setup_accepts_numeric_alias(monkeypatch):
    """VIUR_TESTING=1 is an alias for test mode."""
    calls: list = []
    monkeypatch.setenv("VIUR_TESTING", "1")
    monkeypatch.setattr(
        viur.testing, "activate", lambda **kw: calls.append(("activate", kw))
    )
    monkeypatch.setattr(viur.testing, "protect", lambda: calls.append(("protect",)))
    viur.testing.setup(api_dir=None)
    assert calls[0] == ("activate", {"database": "viur-tests", "namespace": None})


def test_setup_skips_activate_when_off(monkeypatch):
    calls: list = []
    monkeypatch.delenv("VIUR_TESTING", raising=False)
    monkeypatch.setattr(
        viur.testing, "activate", lambda **kw: calls.append(("activate", kw))
    )
    monkeypatch.setattr(viur.testing, "protect", lambda: calls.append(("protect",)))
    viur.testing.setup(api_dir=None)
    assert calls == [("protect",)]


def test_setup_skips_activate_when_empty_string(monkeypatch):
    calls: list = []
    monkeypatch.setenv("VIUR_TESTING", "")
    monkeypatch.setattr(
        viur.testing, "activate", lambda **kw: calls.append(("activate", kw))
    )
    monkeypatch.setattr(viur.testing, "protect", lambda: calls.append(("protect",)))
    viur.testing.setup(api_dir=None)
    assert calls == [("protect",)]


def test_setup_honours_custom_env_var_and_database(monkeypatch):
    calls: list = []
    monkeypatch.setenv("MY_TEST_FLAG", "1")
    monkeypatch.setattr(
        viur.testing, "activate", lambda **kw: calls.append(("activate", kw))
    )
    monkeypatch.setattr(viur.testing, "protect", lambda: calls.append(("protect",)))
    viur.testing.setup(env_var="MY_TEST_FLAG", database="alt-tests", api_dir=None)
    assert calls == [
        ("activate", {"database": "alt-tests", "namespace": None}),
        ("protect",),
    ]


def test_setup_reads_namespace_from_env_var(monkeypatch):
    """VIUR_TESTING=alice feeds the namespace into activate()."""
    calls: list = []
    monkeypatch.setenv("VIUR_TESTING", "alice")
    monkeypatch.setattr(
        viur.testing, "activate", lambda **kw: calls.append(("activate", kw))
    )
    monkeypatch.setattr(viur.testing, "protect", lambda: calls.append(("protect",)))
    viur.testing.setup(api_dir=None)
    assert calls[0] == ("activate", {"database": "viur-tests", "namespace": "alice"})


def test_setup_explicit_kwargs_override_env_var(monkeypatch):
    """An explicit namespace kwarg wins over the env var (and forces on)."""
    calls: list = []
    monkeypatch.setenv("VIUR_TESTING", "from-env")
    monkeypatch.setattr(
        viur.testing, "activate", lambda **kw: calls.append(("activate", kw))
    )
    monkeypatch.setattr(viur.testing, "protect", lambda: calls.append(("protect",)))
    viur.testing.setup(namespace="from-call", api_dir=None)
    assert calls[0] == ("activate", {"database": "viur-tests", "namespace": "from-call"})


def test_setup_explicit_empty_namespace_means_default(monkeypatch):
    """An explicit namespace="" is normalised to the default slice."""
    calls: list = []
    monkeypatch.delenv("VIUR_TESTING", raising=False)
    monkeypatch.setattr(
        viur.testing, "activate", lambda **kw: calls.append(("activate", kw))
    )
    monkeypatch.setattr(viur.testing, "protect", lambda: calls.append(("protect",)))
    viur.testing.setup(namespace="", api_dir=None)
    assert calls[0] == ("activate", {"database": "viur-tests", "namespace": None})


def test_setup_explicit_namespace_forces_on_ignoring_off_env(monkeypatch):
    """An explicit namespace kwarg forces test mode on even when the env
    var says off (the env var is not read when namespace is given)."""
    calls: list = []
    monkeypatch.setenv("VIUR_TESTING", "off")
    monkeypatch.setattr(
        viur.testing, "activate", lambda **kw: calls.append(("activate", kw))
    )
    monkeypatch.setattr(viur.testing, "protect", lambda: calls.append(("protect",)))
    viur.testing.setup(namespace="ak", api_dir=None)
    assert calls[0] == ("activate", {"database": "viur-tests", "namespace": "ak"})


def test_setup_loads_api_when_mode_on(monkeypatch):
    """With test mode on and api_dir set, setup() loads the project API."""
    calls: list = []
    monkeypatch.setenv("VIUR_TESTING", "test")
    monkeypatch.setattr(viur.testing, "activate", lambda **kw: None)
    monkeypatch.setattr(viur.testing, "protect", lambda: None)
    monkeypatch.setattr(
        viur.testing, "_load_project_api", lambda api_dir: calls.append(api_dir)
    )
    viur.testing.setup(api_dir="testing")
    assert calls == ["testing"]


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
