"""Parse the single ``VIUR_TESTING`` env var into ``(mode, namespace)``.

Grammar: ``<mode>[:<namespace>]``.

- off-values (unset / ``""`` / ``0`` / ``off`` / ``false``) → ``("off", None)``
- ``1`` / ``true`` / ``on`` / ``test`` → ``("test", None)``
- ``test:<ns>`` → ``("test", "<ns>")``
- ``dev:<ns>`` → ``("dev", "<ns>")``  (dev requires a namespace)

Mode keywords are case-insensitive; the namespace is kept verbatim
(Datastore namespaces are case-sensitive). Any other value — unknown
mode, empty mode before ``:``, empty namespace after ``:``, ``dev``
without a namespace — raises :class:`ValueError`, which aborts the boot.

This module imports nothing from ``viur.core`` or ``google.cloud`` so it
is safe to import at the very top of ``main.py``.
"""

MODE_OFF = "off"
MODE_TEST = "test"
MODE_DEV = "dev"

_OFF_VALUES = frozenset({"", "0", "off", "false"})
"""Case-insensitive values (with no ``:`` part) that mean "test mode off"."""

_TEST_ALIASES = frozenset({"1", "true", "on", "test"})
"""Case-insensitive aliases that all resolve to :data:`MODE_TEST`."""


def validate_spec(mode: str, namespace: str | None) -> None:
    """Raise :class:`ValueError` if *mode*/*namespace* is an illegal combo.

    Currently the only rule: ``dev`` mode requires a namespace, because a
    seeded Dev-Mirror slice always lives in a named namespace
    (``viur-mirror`` forces ``--target-namespace``); ``dev`` without one
    would point at an empty slice.
    """
    if mode == MODE_DEV and namespace is None:
        raise ValueError(
            "viur-testing: dev mode requires a namespace — "
            "use VIUR_TESTING=dev:<ns>."
        )


def parse_spec(value: str | None) -> tuple[str, str | None]:
    """Parse a ``VIUR_TESTING`` value into ``(mode, namespace)``.

    :param value: the raw env-var string, or ``None`` when unset.
    :returns: ``(mode, namespace)`` where ``mode`` is one of
        :data:`MODE_OFF` / :data:`MODE_TEST` / :data:`MODE_DEV` and
        ``namespace`` is the string after ``:`` or ``None``.
    :raises ValueError: on an unknown mode, an empty mode before ``:``,
        an empty namespace after ``:``, or ``dev`` without a namespace.
    """
    if value is None:
        return MODE_OFF, None
    raw = value.strip()
    if raw.lower() in _OFF_VALUES:
        return MODE_OFF, None

    head, sep, tail = raw.partition(":")
    head = head.strip().lower()
    namespace = tail.strip() if sep else None

    if head == "":
        raise ValueError(
            f"viur-testing: empty mode in VIUR_TESTING={value!r} — "
            "use VIUR_TESTING=<mode>[:<namespace>] (mode = test or dev)."
        )
    if head in _TEST_ALIASES:
        mode = MODE_TEST
    elif head == MODE_DEV:
        mode = MODE_DEV
    else:
        raise ValueError(
            f"viur-testing: unknown mode {head!r} in VIUR_TESTING={value!r} — "
            "expected 'test' (or 1/true/on) or 'dev'."
        )
    if sep and not namespace:
        raise ValueError(
            f"viur-testing: empty namespace after ':' in VIUR_TESTING={value!r}."
        )

    validate_spec(mode, namespace)
    return mode, namespace


__all__ = ["MODE_OFF", "MODE_TEST", "MODE_DEV", "parse_spec", "validate_spec"]
