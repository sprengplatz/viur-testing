"""
``viur.testing._test`` — top-level viur module that aggregates *all* test
infrastructure endpoints.

The leading underscore in the URL prefix (``/_test/...``) signals
"system-internal, not for production callers". The :class:`TestModule`
container refuses to instantiate under two conditions:

- ``conf.instance.is_dev_server`` is False — even if a host project
  forgets the mount-guard, the test endpoints cannot accidentally end
  up on a cloud deployment.
- :func:`viur.testing.activate` has not been called yet — fail loudly
  on mount-without-activation instead of silently returning 403 from
  every request later.

Today the only submodule shipped here is
:class:`~viur.testing._test.config.ConfigModule`, mounted under ``config``;
future test flavours (load test, integration helpers, …) are added as
additional sibling submodules in this package.

Host wiring::

    # modules/__init__.py
    from viur.core.config import conf
    from viur.testing._test import TestModule

    if conf.instance.is_dev_server:
        _test = TestModule()  # mounts under /_test
"""

import typing as t

from viur.core import Module

from .config import ConfigModule


class TestModule(Module):
    """Container module aggregating local-only test endpoints under ``/_test``.

    Refuses to instantiate outside a local dev server — this is the
    structural last line of defence against a host project that
    accidentally mounts the test endpoints in production. Also refuses
    when :func:`viur.testing.activate` has not run yet, so a forgotten
    activate-call fails loudly at boot rather than silently 403-ing
    every later request.
    """

    handler = "test"
    accessRights = None

    # Opt the module into the JSON renderer. viur-core's __build_app skips
    # any module class where ``getattr(module_cls, render_name, False)``
    # is falsy for the active render — without this flag the routes would
    # silently not be registered for /json/_test/config/*.
    json = True

    # Tell pytest not to collect this class as a test suite: it happens to
    # start with "Test" but it is a viur module, not a unittest container.
    __test__ = False

    def __init__(
        self,
        moduleName: str = "_test",
        modulePath: str = "_test",
        *args: t.Any,
        **kwargs: t.Any,
    ) -> None:
        from viur.core.config import conf  # noqa: PLC0415 — fresh lookup on each instantiation

        if not getattr(conf.instance, "is_dev_server", False):
            raise RuntimeError(
                "viur-testing: TestModule refuses to instantiate outside a local dev "
                "server. conf.instance.is_dev_server is False. Guard the mount "
                "in your host's modules/__init__.py with "
                "`if conf.instance.is_dev_server:`."
            )
        if not ConfigModule.is_active():
            raise RuntimeError(
                "viur-testing: TestModule cannot mount because viur.testing.activate() "
                "has not been called yet. Move the activate() call to the very top "
                "of main.py, before the modules package is imported."
            )
        super().__init__(moduleName, modulePath, *args, **kwargs)
        self.config = ConfigModule(
            moduleName="config",
            modulePath=f"{modulePath}/config",
        )
        # Re-scan attributes — the base __init__ already ran one scan
        # before ``self.config`` was attached.
        self._update_methods()


__all__ = ["TestModule", "ConfigModule"]
