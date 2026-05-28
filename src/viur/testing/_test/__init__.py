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

import re
import typing as t

from viur.core import Module

from .config import ConfigModule

_SUBMODULE_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
"""Allowed shape for a host-registered submodule name.

Starts with a lowercase ASCII letter, then any mix of lowercase letters,
digits, ``_`` and ``-``. Rejects:

- empty/None (caught separately for a better message),
- leading underscores (would clash with module-internal attributes
  like ``_methods``, ``_modules``),
- dunders (``__init__``, ``__test__``, ...),
- mixed case (URL routing lowercases anyway, so accepting uppercase
  would only invite confusion),
- non-ASCII characters and special chars like ``/``, ``.``, spaces
  that would either break ``setattr`` or invent ambiguous routes.
"""


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

    # Host-provided test submodules registered via
    # :func:`viur.testing.register_test_submodule`. Read at mount time
    # by :meth:`__init__` and attached as instance attributes so the
    # router sees them as ``/_test/<name>/...``.
    _user_submodules: t.ClassVar[dict[str, type]] = {}

    _RESERVED_SUBMODULE_NAMES: t.ClassVar[frozenset[str]] = frozenset({"config"})

    @classmethod
    def register_submodule(cls, name: str, module_cls: type) -> None:
        """Add a host-provided submodule that will be mounted under
        ``/_test/<name>/...`` whenever TestModule itself mounts.

        Must be called **before** ``viur.core.setup()`` runs — the
        list is consumed in :meth:`__init__` when the router builds
        the application.

        The ``name`` is normalised to lowercase because viur-core
        lower-cases every URL path segment at request time
        (``viur.core.request.BrowseHandler``). Without normalisation
        a registration of ``userLogin`` would land in the resolver
        as mixed-case while the request looks up ``userlogin`` — and
        the lookup would silently fail.

        Three layered checks gate the name:

        1. Empty/non-string rejected for a clear error.
        2. After lower-casing, must match :data:`_SUBMODULE_NAME_RE`
           (ASCII letter prefix + letters/digits/_-) so the name is
           safely usable as a Python attribute and a URL segment.
        3. Must not collide with any attribute already present on
           ``TestModule`` (reserved submodules, renderer flags like
           ``json``, inherited :class:`viur.core.Module` internals
           like ``handler``/``accessRights``/``_methods``). The
           ``hasattr`` check is intentionally permissive — a future
           viur-core Module addition is caught automatically.

        :param name: URL segment under ``/_test/``. Lower-cased
            internally.
        :param module_cls: Subclass of ``viur.core.Module`` to mount.
        :raises ValueError: when ``name`` is empty, malformed,
            reserved, or would shadow an existing TestModule attribute.
        """
        if not name:
            raise ValueError("Submodule name must be a non-empty string.")
        name = name.lower()
        if not _SUBMODULE_NAME_RE.fullmatch(name):
            raise ValueError(
                f"Submodule name {name!r} must match {_SUBMODULE_NAME_RE.pattern!r}: "
                "start with a lowercase ASCII letter, then ASCII letters, digits, "
                "underscore or dash. Names with leading underscores, dunders, dots "
                "or other special characters would clash with module-internal "
                "attributes or break URL routing."
            )
        if name in cls._RESERVED_SUBMODULE_NAMES:
            raise ValueError(
                f"Submodule name {name!r} is reserved by viur-testing "
                f"(reserved: {sorted(cls._RESERVED_SUBMODULE_NAMES)})."
            )
        # Previously-registered submodule names live in ``_user_submodules``
        # (dict keys), not as class attributes — so ``hasattr`` does not
        # catch them. The original overwrite-last-wins behaviour is
        # preserved here intentionally; only attribute *collisions* are
        # refused.
        if hasattr(cls, name):
            raise ValueError(
                f"Submodule name {name!r} would shadow an existing attribute "
                f"on {cls.__name__} (renderer flag, inherited Module attribute, "
                "or class-level state). Pick a different name."
            )
        cls._user_submodules[name] = module_cls

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
        # Mount host-registered submodules (see :meth:`register_submodule`).
        # These typically correspond 1:1 to e2e spec files — name of the
        # submodule matches the spec name, so /_test/<spec>/setup +
        # /_test/<spec>/teardown is the convention.
        for sub_name, sub_cls in type(self)._user_submodules.items():
            instance = sub_cls(
                moduleName=sub_name,
                modulePath=f"{modulePath}/{sub_name}",
            )
            setattr(self, sub_name, instance)
        # Re-scan attributes — the base __init__ already ran one scan
        # before ``self.config`` / host submodules were attached.
        self._update_methods()


__all__ = ["TestModule", "ConfigModule"]
