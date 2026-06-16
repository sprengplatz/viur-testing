"""Parse the single ``VIUR_TESTING`` env var into ``(enabled, namespace)``.

There is exactly one test mode now (the former ``test``/``dev`` split was
removed in 0.5.0 — manual browsing is handled by the cookie transport, not
by a separate tokenless mode). The env var therefore only carries
"on/off + optional namespace":

- off (unset / ``""`` / ``0`` / ``off`` / ``false``) → ``(False, None)``
- on, default namespace (``1`` / ``true`` / ``on``) → ``(True, None)``
- any other value → ``(True, <value verbatim>)`` — the value is a Datastore
  **namespace** name, e.g. ``VIUR_TESTING=ak`` → ``(True, "ak")``.

On/off keywords are case-insensitive; a namespace is kept verbatim
(Datastore namespaces are case-sensitive). Note there is no separator and
no reserved namespace names — ``VIUR_TESTING=test`` simply means "on,
namespace ``test``".

This module imports nothing from ``viur.core`` or ``google.cloud`` so it is
safe to import at the very top of ``main.py``.
"""

_OFF_VALUES = frozenset({"", "0", "off", "false"})
"""Case-insensitive values that mean "test mode off"."""

_ON_VALUES = frozenset({"1", "true", "on"})
"""Case-insensitive values that mean "on, default namespace"."""


def parse_spec(value: str | None) -> tuple[bool, str | None]:
    """Parse a ``VIUR_TESTING`` value into ``(enabled, namespace)``.

    :param value: the raw env-var string, or ``None`` when unset.
    :returns: ``(enabled, namespace)`` — ``namespace`` is ``None`` for the
        default namespace, otherwise the verbatim value.
    """
    if value is None:
        return False, None
    raw = value.strip()
    lowered = raw.lower()
    if lowered in _OFF_VALUES:
        return False, None
    if lowered in _ON_VALUES:
        return True, None
    return True, raw


__all__ = ["parse_spec"]
