"""Inject a ``database = ...`` line into viur-core's dev-server boot banner.

When the host's ``main.py`` calls ``viur.core.setup()`` it prints a
five-line ASCII banner under ``#`` fill chars to signal that the local
dev server is up. With test mode active, the most important piece of
information at that moment is *which* datastore the process is wired to
— prod-default vs. ``viur-tests`` — so we extend the banner with an
extra ``database = <name>`` line in matching style.

The extension is implemented as a thin wrapper around
``viur.core.setup``: while the wrapped call runs, ``builtins.print`` is
replaced with a sniffer that detects the banner's title and trailer
lines and injects the database line immediately before the trailer.
The original ``print`` is restored as soon as ``setup()`` returns, so
nothing outside the banner window is affected.

The patch is installed only by :func:`viur.testing.activate`, which
runs exclusively in a local dev server, so production processes never
see it.
"""

import builtins
import sys
import typing as t

_BANNER_TITLE_MARKER = "LOCAL DEVELOPMENT SERVER IS UP AND RUNNING"
"""Substring that appears in viur-core's banner title line."""

_BANNER_WIDTH = 80
"""Total visible width of the banner, matching viur-core's ``WIDTH``."""

_BANNER_FILL = "#"
"""Fill character used by viur-core for the banner frame."""

_ANSI_ESCAPE_PAD = 11
"""Width correction for ANSI escapes in coloured content lines.

viur-core wraps each content value with ``\\033[1;3Xm…\\033[0m`` (7 + 4
chars) which do not occupy visible columns but do count toward
``format``'s width — hence the +11 in the format spec.
"""

_PATCH_SENTINEL_ATTR = "_viur_testing_banner_patched"
"""Attribute set on the wrapped ``viur.core.setup`` to make the install
idempotent across re-entrant activate() calls (tests, repeated boots)."""


def _format_content_line(label: str, value: str) -> str:
    """Render one injected line in viur-core's content-line style.

    The format mirrors how viur-core renders the ``project``/``python``/
    ``viur`` lines: outer ``#`` frame, space-padded centre, and
    ``\\033[1;33m…\\033[0m`` (yellow) for the value to make test
    settings visually stand out from prod-coloured fields.
    """
    content = f"{label} = \033[1;33m{value}\033[0m"
    return (
        f"\033[0m{_BANNER_FILL}"
        f"{content:^{(_BANNER_WIDTH - 2) + _ANSI_ESCAPE_PAD}}"
        f"{_BANNER_FILL}"
    )


def _format_db_line(database: str) -> str:
    """Backward-compatible alias for the ``database = …`` line."""
    return _format_content_line("database", database)


def _looks_like_banner_tail(line: str) -> bool:
    """Return True if *line* matches viur-core's banner trailer.

    The trailer is the empty content line padded with ``#`` to full
    width — i.e. the entire visible content is fill char. We strip the
    leading ``\\033[0m`` reset, then require the result to start with a
    run of fill chars and contain at least ``WIDTH - 2`` of them (the
    title line also starts with ``#`` chars but breaks that run with
    the title text, so it does not match).
    """
    stripped = line.replace("\033[0m", "")
    return (
        stripped.startswith(_BANNER_FILL * 10)
        and stripped.count(_BANNER_FILL) >= _BANNER_WIDTH - 2
    )


_DEFAULT_NAMESPACE_LABEL = "(default)"
"""Banner placeholder for ``namespace=None`` so testers see at a glance
that test mode is armed but no namespace isolation is in effect."""


def install_banner_patch(database: str, *, namespace: str | None = None) -> None:
    """Wrap ``viur.core.setup`` to inject the test-mode lines into its banner.

    Always injects ``database = <name>`` followed by
    ``namespace = <name or "(default)">``. The namespace line is
    rendered unconditionally so a tester can never overlook the
    distinction between "test mode armed with namespace isolation"
    and "test mode armed but everybody writes to the same slice".

    Idempotent: if a previous call has already wrapped ``viur.core.setup``
    the second call is a no-op, so re-entry through activate() (e.g. in
    tests) does not stack wrappers.

    :param database: Name of the active test database — rendered verbatim
        into the injected line.
    :param namespace: Datastore namespace, or ``None`` for the default
        namespace; rendered as the second injected line.
    """
    # Pull viur.core via sys.modules instead of `import viur.core` so
    # the lookup also works in test setups where viur.core was injected
    # into sys.modules without being attached as an attribute on `viur`
    # (viur-light-mock does this).
    import viur.core  # noqa: F401, PLC0415  # ensure the module is in sys.modules
    viur_core = sys.modules["viur.core"]

    if getattr(viur_core.setup, _PATCH_SENTINEL_ATTR, False):
        return

    _orig_setup = viur_core.setup
    namespace_label = namespace if namespace else _DEFAULT_NAMESPACE_LABEL

    def _wrapped_setup(*args: t.Any, **kwargs: t.Any) -> t.Any:
        state = {"in_banner": False}
        _orig_print = builtins.print

        def _patched_print(*pa: t.Any, **pk: t.Any) -> None:
            if pa and isinstance(pa[0], str):
                line = pa[0]
                if not state["in_banner"]:
                    if _BANNER_TITLE_MARKER in line:
                        state["in_banner"] = True
                elif _looks_like_banner_tail(line):
                    _orig_print(_format_content_line("database", database), **pk)
                    _orig_print(_format_content_line("namespace", namespace_label), **pk)
                    state["in_banner"] = False
            _orig_print(*pa, **pk)

        builtins.print = _patched_print
        try:
            return _orig_setup(*args, **kwargs)
        finally:
            builtins.print = _orig_print

    setattr(_wrapped_setup, _PATCH_SENTINEL_ATTR, True)
    viur_core.setup = _wrapped_setup
