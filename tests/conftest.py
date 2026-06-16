"""
Conftest for viur-testing tests.

The bulk of the test infrastructure (``viur.core`` stand-ins, fixtures,
in-memory datastore) lives in the ``viur-light-mock`` package and is loaded
automatically via its pytest plugin. viur-testing additionally reaches into:

- ``viur.core.request.{RequestValidator, Router}`` — request validator,
- ``viur.core.Module`` and ``viur.core.decorators.{exposed, force_post}`` —
  status/finish endpoints,
- ``viur.core.db.transport.__client__`` — for the datastore client swap,
- ``viur.core.config.conf.instance.is_dev_server`` — for the dev-server check.

This conftest installs the additional stand-ins on top of light-mock's,
both at import time (so test collection succeeds) and again in
``pytest_configure`` with ``trylast=True`` (so light-mock's own
``pytest_configure`` cannot clobber them). It also resets
:mod:`viur.testing.state` between tests so each test starts clean.
"""

import sys
import types
import typing as t
from abc import ABC, abstractmethod

import pytest


def _install_request_stub() -> types.ModuleType:
    mod = types.ModuleType("viur.core.request")

    class RequestValidator(ABC):
        name = "RequestValidator"

        @staticmethod
        @abstractmethod
        def validate(request: t.Any) -> tuple[int, str, str] | None:
            raise NotImplementedError()

    class Router:
        requestValidators: list[type[RequestValidator]] = []

    class BrowseHandler:
        """Placeholder; tests build duck-typed request objects directly."""

    mod.RequestValidator = RequestValidator
    mod.Router = Router
    mod.BrowseHandler = BrowseHandler
    sys.modules["viur.core.request"] = mod
    return mod


def _install_setup_stub() -> None:
    """Install a no-op ``viur.core.setup`` so :func:`viur.testing.banner.
    install_banner_patch` has something to wrap. Tests that exercise the
    banner replace ``viur.core.setup`` with a banner-emitting stub.
    """
    viur_core = sys.modules["viur.core"]
    viur_core.setup = lambda *_a, **_kw: None


def _install_module_stub() -> None:
    viur_core = sys.modules["viur.core"]

    class Module:
        handler: str | None = None
        accessRights: t.Any = None

        def __init__(self, moduleName: str = "", modulePath: str = "", *args, **kwargs):
            self.moduleName = moduleName
            self.modulePath = modulePath
            self._methods: dict = {}
            self._modules: dict = {}
            self._update_methods()

        def _update_methods(self) -> None:
            """Scan instance attributes for Method/Module children.

            Mirrors viur-core's behaviour just enough that TestModule's
            submodule mount can be observed in tests.
            """
            self._methods.clear()
            self._modules.clear()
            for key in dir(self):
                if key.startswith("_"):
                    continue
                try:
                    prop = getattr(self, key)
                except AttributeError:
                    continue
                if isinstance(prop, Module):
                    self._modules[key] = prop
                elif callable(prop) and getattr(prop, "exposed", False):
                    self._methods[key] = prop

    viur_core.Module = Module


def _install_decorators_stub() -> None:
    mod = types.ModuleType("viur.core.decorators")

    def exposed(fn):
        fn.exposed = True
        return fn

    def force_post(fn):
        fn.force_post = True
        return fn

    mod.exposed = exposed
    mod.force_post = force_post
    sys.modules["viur.core.decorators"] = mod


def _install_config_stub() -> None:
    """Install ``viur.core.config`` with a ``conf.instance`` attribute.

    activate() reaches via ``from viur.core.config import conf``, so the
    canonical viur-core entry point needs to exist as its own module.
    """
    viur_core = sys.modules["viur.core"]

    class _Instance:
        is_dev_server = True
        project_id = "viur-testing-tests"

    class _Conf:
        instance = _Instance()

    conf = _Conf()
    viur_core.conf = conf

    config_mod = types.ModuleType("viur.core.config")
    config_mod.conf = conf
    sys.modules["viur.core.config"] = config_mod


def _install_current_request_stub() -> None:
    """Extend light-mock's ``viur.core.current`` so ``current.request.get()``
    returns an object with a ``.response.headers`` dict.

    Needed by ``ConfigModule._json_response`` which sets the
    ``Content-Type`` header before serialising the payload.
    """
    current_mod = sys.modules.get("viur.core.current")
    if current_mod is None:
        return

    class _Response:
        def __init__(self) -> None:
            self.headers: dict[str, str] = {}
            self.cookies_set: list[tuple[str, str, dict]] = []
            self.cookies_deleted: list[tuple[str, dict]] = []

        def set_cookie(self, name: str, value: str, **kwargs) -> None:
            self.cookies_set.append((name, value, kwargs))

        def delete_cookie(self, name: str, **kwargs) -> None:
            self.cookies_deleted.append((name, kwargs))

    class _Handler:
        def __init__(self) -> None:
            self.response = _Response()
            # Mirrors viur-core's BrowseHandler.request (a webob Request):
            # ConfigModule._set_token_cookie reads ``.scheme`` to decide Secure.
            self.request = types.SimpleNamespace(scheme="http")

    # light-mock's `_Slot` exposes get()/set(); pre-populate it.
    if hasattr(current_mod, "request") and hasattr(current_mod.request, "set"):
        current_mod.request.set(_Handler())


def _install_transport_stub() -> None:
    """Install an empty ``viur.core.db.transport`` so module.py can patch it."""
    transport = types.ModuleType("viur.core.db.transport")
    transport.__client__ = None
    sys.modules["viur.core.db.transport"] = transport


def _install_all_stubs() -> None:
    _install_request_stub()
    _install_module_stub()
    _install_setup_stub()
    _install_decorators_stub()
    _install_config_stub()
    _install_current_request_stub()


_install_all_stubs()


@pytest.hookimpl(trylast=True)
def pytest_configure(config) -> None:  # noqa: ARG001
    _install_all_stubs()


def _ensure_transport_unloaded() -> None:
    """Remove ``viur.core.db.transport`` from sys.modules if present.

    activate() refuses if it is already imported. Tests that exercise the
    "transport already imported" guard install a sentinel themselves; the
    happy-path tests rely on the runtime swap going through cleanly.
    """
    sys.modules.pop("viur.core.db.transport", None)


@pytest.fixture(autouse=True)
def _viur_testing_test_environment():
    """Per-test setup: re-install stubs, reset ConfigModule class-level state."""
    _install_all_stubs()
    _ensure_transport_unloaded()

    from viur.testing._test.config import ConfigModule

    ConfigModule.reset()
    yield
    ConfigModule.reset()
    sys.modules["viur.core.request"].Router.requestValidators.clear()


@pytest.fixture
def router_validators():
    """Direct handle to the patched Router's validator list."""
    return sys.modules["viur.core.request"].Router.requestValidators


@pytest.fixture
def conf_instance():
    """Direct handle to ``viur.core.config.conf.instance`` for toggling."""
    return sys.modules["viur.core.config"].conf.instance


@pytest.fixture
def install_transport_stub():
    """Install a ``viur.core.db.transport`` with the given client.

    Returns a callable: ``install(client)`` registers ``transport.__client__
    = client`` and returns the module.
    """
    def _install(client) -> types.ModuleType:
        transport = types.ModuleType("viur.core.db.transport")
        transport.__client__ = client
        sys.modules["viur.core.db.transport"] = transport
        return transport

    return _install
