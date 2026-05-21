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
  ``config``, exposing ``GET /_test/config/status`` and
  ``POST /_test/config/finish``.
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
from .protection import protect
from .runner import ServerStatus, TestModePreflightError, finish, require_test_mode

__version__ = "0.1.0"

__all__ = [
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
]


def setup(
    *,
    enable_env_var: str = "VIUR_TESTING_ENABLE",
    database: str = DEFAULT_DATABASE,
) -> None:
    """One-call host-side wiring for ``main.py``.

    Must be the **first** line of code in ``main.py`` — before any
    ``from viur.core ...`` import. Internally:

    1. Reads ``os.environ[enable_env_var]`` (default
       ``VIUR_TESTING_ENABLE``). If truthy, calls :func:`activate`
       which swaps the datastore client to ``database`` (default
       ``viur-tests``), runs the probe and installs the request
       validator.
    2. Calls :func:`protect` unconditionally to install the
       production header guard.

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

    :param enable_env_var: Name of the env var that gates
        :func:`activate`. Default ``VIUR_TESTING_ENABLE``.
    :param database: Name of the test database to swap to. Default
        ``viur-tests``.
    """
    if _os.environ.get(enable_env_var):
        activate(database=database)
    protect()


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
