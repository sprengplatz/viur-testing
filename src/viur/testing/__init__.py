"""
viur-testing — safe test-mode for viur-core projects.

The package implements a bilateral guarantee for end-to-end tests
(typically Playwright): the server refuses to boot unless it is wired
to a dedicated test database, and the runner refuses to start tests
unless the server confirms that state back. The session token lives
only in the test database itself — no on-disk handoff.

Server side
~~~~~~~~~~~

- :func:`activate` swaps the datastore client to the target test
  database, runs a synchronous probe roundtrip, primes the in-process
  state on :class:`~viur.testing._test.config.ConfigModule`, and installs
  the request validator. Must be called before any ``viur.core``
  import.
- :class:`~viur.testing._test.TestModule` is the host-mountable container
  under ``/_test``. It refuses to instantiate outside a local dev
  server — the structural last line of defence against an accidental
  production mount. It carries
  :class:`~viur.testing._test.config.ConfigModule` as a submodule under
  ``config``, exposing ``POST /json/_test/config/status`` and
  ``POST /json/_test/config/finish``.
- :class:`~viur.testing.validator.TokenValidator` rejects every
  non-bootstrap request that lacks the matching ``X-Viur-Test-Token``
  header.

Runner side
~~~~~~~~~~~

- :func:`require_test_mode` is the preflight check.
- :func:`finish` tells the server to drop the token entity.

Importing the heavy classes
~~~~~~~~~~~~~~~~~~~~~~~~~~~

:class:`TestModule`, :class:`ConfigModule`, :class:`TokenValidator` and
:class:`ProductionGuardValidator` all inherit from viur-core base
classes at class-definition time — importing any of them triggers the
full ``viur.core/__init__.py`` chain, which loads
``viur.core.db.transport`` and instantiates the default
``datastore.Client``. That is exactly what :func:`activate` is trying
to swap *before* it ever runs.

This top-level package therefore deliberately does **not** re-export
those classes. Import them from their concrete submodules, and only
*after* :func:`activate` has finished:

- :class:`~viur.testing._test.TestModule` →
  ``from viur.testing._test import TestModule``
- :class:`~viur.testing.validator.TokenValidator`,
  :class:`~viur.testing.validator.ProductionGuardValidator` →
  used internally by :func:`activate` / :func:`protect`; the host
  rarely needs to touch them.
"""

import os as _os

from .activation import activate
from .constants import DEFAULT_DATABASE, TOKEN_HEADER
from .mode import MODE_DEV, MODE_OFF, MODE_TEST, parse_spec, validate_spec
from .mirror import arm_tokenless_browsing
from .protection import protect
from .runner import ServerStatus, TestModePreflightError, finish, require_test_mode

__version__ = "0.4.0"

__all__ = [
    "DEFAULT_DATABASE",
    "ServerStatus",
    "TOKEN_HEADER",
    "TestModePreflightError",
    "activate",
    "arm_tokenless_browsing",
    "finish",
    "protect",
    "register_finish_hook",
    "register_modules",
    "register_status_hook",
    "register_test_submodule",
    "require_test_mode",
    "setup",
]


def register_status_hook(hook) -> None:
    """Register a project callback that runs inside ``/_test/config/status``.

    The hook is invoked after the session token has been issued and
    in-process state primed; if it returns a dict, the entries are
    merged into the response payload. Use this to inject
    project-specific configuration that the e2e runner needs to know
    about (feature flags, generated IDs, seed data references, …).

    Thin wrapper around
    :meth:`viur.testing._test.config.ConfigModule.register_status_hook`.
    Typical wiring lives in ``deploy/test/__init__.py``.

    :param hook: ``() -> dict | None`` callable.
    """
    from ._test.config import ConfigModule  # noqa: PLC0415

    ConfigModule.register_status_hook(hook)


def register_finish_hook(hook) -> None:
    """Register a project callback that runs inside ``/_test/config/finish``.

    Same shape as :func:`register_status_hook`: optional dict return
    is merged into the finish response. Useful for cleanup
    confirmation, summary info, or project-specific shutdown hooks.

    :param hook: ``() -> dict | None`` callable.
    """
    from ._test.config import ConfigModule  # noqa: PLC0415

    ConfigModule.register_finish_hook(hook)


def register_test_submodule(name: str, module_cls: type) -> None:
    """Mount a host-provided submodule under ``/_test/<name>/...``.

    Use this to attach project-specific test fixtures (setup,
    teardown, seed data, …) to the same ``/_test`` container that
    carries the built-in :class:`~viur.testing._test.config.ConfigModule`.

    Recommended convention: one submodule per e2e spec file, named
    after the spec — ``tests/auth/userLogin.spec.ts`` ↔ ``/_test/userLogin/``
    with methods ``setup`` and ``teardown``. This keeps test fixtures
    co-located with the tests that need them.

    The registration is stored on :class:`~viur.testing._test.TestModule`
    and consumed at mount time. Call this **before** ``viur.core.setup()``
    runs — typically right after ``register_modules`` in your host's
    ``modules/__init__.py``.

    Production-safe: if test mode is not armed (``VIUR_TESTING`` off /
    unset), ``TestModule`` is never mounted and the registration has
    no observable effect.

    :param name: URL segment under ``/_test/``. Must not collide with
        viur-testing's reserved names (currently ``config``).
    :param module_cls: A ``viur.core.Module`` subclass with the
        endpoints the test needs.
    :raises ValueError: when ``name`` is reserved or empty.
    """
    from ._test import TestModule  # noqa: PLC0415

    TestModule.register_submodule(name, module_cls)


def setup(
    *,
    env_var: str = "VIUR_TESTING",
    mode: str | None = None,
    namespace: str | None = None,
    database: str = DEFAULT_DATABASE,
    api_dir: str | None = "testing",
    tokenless_app_ids: list[str] | None = None,
) -> None:
    """One-call host-side wiring for ``main.py``.

    Must be the **first** line of code in ``main.py`` — before any
    ``from viur.core ...`` import. Internally:

    1. Resolves the mode + namespace. If ``mode`` and ``namespace`` are
       both ``None`` (the usual case), parses ``os.environ[env_var]``
       (default ``VIUR_TESTING``) via :func:`viur.testing.mode.parse_spec`.
       Otherwise the explicit kwargs win and the env var is ignored.
    2. For ``test`` / ``dev`` mode, calls :func:`activate` (datastore
       client swap to ``database`` + ``namespace``, probe, validator).
    3. For ``dev`` mode additionally calls :func:`arm_tokenless_browsing`
       (PIN-gated tokenless browsing of the seeded slice).
    4. Calls :func:`protect` unconditionally to install the production
       header guard.

    The single env var replaces the former trio
    (``VIUR_TESTING_ENABLE`` / ``_NAMESPACE`` / ``_TOKENLESS``)::

        $ VIUR_TESTING=test          # test mode, default namespace
        $ VIUR_TESTING=test:ak       # test mode, namespace ak
        $ VIUR_TESTING=dev:ak        # dev mode (test + tokenless), namespace ak

    ``1`` / ``true`` / ``on`` are accepted as aliases for ``test``;
    unset / ``""`` / ``0`` / ``off`` / ``false`` mean off. ``dev``
    requires a namespace. See :func:`viur.testing.mode.parse_spec`.

    Use the env var, **not** ``conf.instance.is_dev_server``, as the
    gate — reading ``conf.instance`` triggers the full ``viur.core``
    import chain (including ``viur.core.db.transport``), which would
    leave :func:`activate` with no chance to patch the singleton.

    Typical host wiring::

        # main.py
        import viur.testing
        viur.testing.setup()

        from viur.core import setup as core_setup
        import modules, render
        app = core_setup(modules, render)

    :param env_var: Name of the single variable to read. Default
        ``VIUR_TESTING``.
    :param mode: Explicit mode override (``"test"``/``"dev"``/``"off"``).
        When given (or ``namespace`` is given), the env var is not read.
    :param namespace: Explicit Datastore namespace override. An empty
        string is normalised to ``None`` (default slice). When several
        testers share one ``viur-tests`` database, giving each their own
        namespace keeps their entities from colliding.
    :param database: Name of the test database to swap to. Default
        ``viur-tests``.
    :param api_dir: Name of the wrapper directory (relative to the
        caller's parent dir) that contains an ``api/`` subfolder
        with the project test API package. ``setup()`` loads
        ``<api_dir>/api/__init__.py`` and registers it as the
        top-level Python package ``api`` via ``importlib`` — no
        ``sys.path`` manipulation, no sibling-directory exposure.

        Default: ``"testing"`` — resolves to
        ``<dirname(main.py)>/../testing/api/`` and matches the
        convention ``testing/api/`` (backend fixtures) +
        ``testing/e2e/`` (Playwright). Pass any other string to
        relocate the wrapper, or ``None`` to skip the project
        test API entirely.

        If the resolved ``__init__.py`` does not exist, a one-line
        info message is printed and setup continues — that helps
        spot misconfigurations early (you'd otherwise see mysterious
        ``404 /_test/<spec>/setup`` errors from the runner side).
    :param tokenless_app_ids: Whitelist of GCP project ids allowed to enable
        **tokenless browsing** of the ``viur-tests`` slice (skip the
        ``X-Viur-Test-Token`` header) in ``dev`` mode. Kept here, in
        ``main.py``, so it is reviewed in PRs rather than drifting in a
        dotfile. ``None``/empty disables tokenless even in dev mode
        (:func:`arm_tokenless_browsing` then refuses).

        Seeding the ``viur-tests`` slice with live data is a separate,
        out-of-band step — see the ``viur-mirror`` console script
        (:mod:`viur.testing.cli`; direct namespace copy from ``(default)``).
    :raises ValueError: on an unparseable / illegal ``VIUR_TESTING``
        value (unknown mode, dev without namespace, …) — aborts the boot.
    """
    if mode is None and namespace is None:
        mode, namespace = parse_spec(_os.environ.get(env_var))
    else:
        if mode is None:
            mode = MODE_TEST
        if namespace == "":
            namespace = None
        validate_spec(mode, namespace)

    if mode != MODE_OFF:
        activate(database=database, namespace=namespace)
        if mode == MODE_DEV:
            arm_tokenless_browsing(tokenless_app_ids=tokenless_app_ids)
        if api_dir is not None:
            _load_project_api(api_dir)
    protect()


_PACKAGE_DIR = _os.path.dirname(_os.path.abspath(__file__))
"""Absolute directory of the ``viur.testing`` package on disk. The
stack walk in :func:`_load_project_api` uses this as the boundary
between "still inside our own helpers" and "back in host code"."""


def _load_project_api(api_dir: str, caller_file: str | None = None) -> None:
    """Resolve ``<caller_parent>/<api_dir>/api/__init__.py`` and
    register it as top-level Python package ``api``.

    The relative path is anchored at the **first host-side frame** on
    the call stack — i.e. the closest frame whose file is *not* inside
    :data:`_PACKAGE_DIR`. The previous implementation used a hard-coded
    ``inspect.stack()[2]`` offset which silently broke as soon as any
    wrapper (test helper, decorator, host-side convenience function)
    sat between ``main.py`` and :func:`setup`.

    Tests can pass ``caller_file`` directly to bypass the stack walk.

    :param api_dir: Wrapper directory name (e.g. ``"testing"``).
    :param caller_file: Override for the host file used to anchor the
        relative path. When ``None``, walks the call stack until it
        finds a frame outside the ``viur.testing`` package.
    :raises RuntimeError: when the stack walk cannot find a host frame
        (e.g. every frame is inside ``viur.testing`` — should not
        happen in practice, but fail loudly rather than guess).
    """
    if caller_file is None:
        import inspect  # noqa: PLC0415
        for frame_info in inspect.stack()[1:]:
            frame_file = _os.path.abspath(frame_info.filename)
            if not frame_file.startswith(_PACKAGE_DIR + _os.sep):
                caller_file = frame_file
                break
        if caller_file is None:
            raise RuntimeError(
                "viur.testing.setup(): could not find a host-side frame on "
                "the call stack — pass `api_dir=None` to skip the project "
                "API lookup, or call viur.testing._load_project_api(...) "
                "with an explicit `caller_file=` argument."
            )
    api_init = _os.path.abspath(_os.path.join(
        _os.path.dirname(caller_file), "..", api_dir, "api", "__init__.py",
    ))
    _load_api_package(api_init)


def _load_api_package(api_init: str) -> None:
    """Register the package at ``api_init`` as the top-level Python
    package ``api``.

    ``api_init`` is the absolute path to an ``__init__.py``. Uses
    ``importlib.util.spec_from_file_location`` so only the one
    package is exposed — ``sys.path`` is left untouched. If the file
    is missing, prints a clear info line and returns; the rest of
    test-mode setup keeps running.
    """
    import importlib.util  # noqa: PLC0415
    import sys  # noqa: PLC0415

    if not _os.path.isfile(api_init):
        print(
            f"[viur-testing] no api package found at {api_init!r} — "
            "project-specific test fixtures will not be loaded. "
            "Pass `api_dir=<wrapper>` to viur.testing.setup() pointing "
            "at a wrapper directory that contains an api/ subfolder.",
        )
        return

    spec = importlib.util.spec_from_file_location(
        "api", api_init,
        submodule_search_locations=[_os.path.dirname(api_init)],
    )
    if spec is None or spec.loader is None:  # pragma: no cover — only happens on a corrupted file system
        print(f"[viur-testing] could not build import spec for {api_init!r}")
        return

    module = importlib.util.module_from_spec(spec)
    sys.modules["api"] = module
    spec.loader.exec_module(module)
    print(f"[viur-testing] loaded project api package from {api_init!r}")


def register_modules(target: dict) -> None:
    """Inject :class:`~viur.testing._test.TestModule` into the host's
    ``modules/`` namespace if test mode is active.

    Call from ``modules/__init__.py`` after the auto-discovery loop —
    typically::

        # modules/__init__.py
        from viur.testing import register_modules
        register_modules(globals())

    Idempotent: if :func:`activate` has not run (test mode not armed)
    this is a no-op, so the same line stays in place for both dev and
    production deployments.

    ``TestModule`` is registered as a **class**, not an instance, so
    viur-core's ``__build_app`` (which scans ``vars(modules)`` for
    Module subclasses) picks it up and routes ``/_test/config/*``
    through it.

    :param target: The ``modules/__init__.py`` global namespace dict,
        typically ``globals()``.
    """
    from ._test.config import ConfigModule  # noqa: PLC0415

    if not ConfigModule.is_active():
        return  # test mode not armed — nothing to mount

    from ._test import TestModule  # noqa: PLC0415

    target["_test"] = TestModule
