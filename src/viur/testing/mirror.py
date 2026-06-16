"""
Dev-Mirror — read-only source client for seeding the test slice.

The seeding is done **out-of-band** by the ``viur-mirror`` console script
(:mod:`viur.testing.cli`): a direct, entity-by-entity copy from the live
``(default)`` database into a developer-chosen **namespace** of the
``viur-tests`` database. Each developer copies into their own namespace, so the
slices are isolated.

This module provides the read-only wrapper the copy uses on the live
``(default)`` database (for the ``__kind__`` enumeration and the reads), so a
copy-side bug can never write to production. Browsing the seeded slice no longer
needs a special server mode — boot ``VIUR_TESTING=<namespace>`` and use the
cookie transport (``/_test/config/enter``) like any other test session.

The module imports no ``viur.core`` and no ``google.cloud`` at top level, so it
is safe to import at the very top of ``main.py``; those imports are done lazily.
"""

import typing as t

if t.TYPE_CHECKING:  # pragma: no cover
    from google.cloud import datastore


_BLOCKED_WRITES: frozenset[str] = frozenset({
    "put",
    "put_multi",
    "delete",
    "delete_multi",
    "allocate_ids",
    "mutation",
    "transaction",
})
"""Client methods the read-only source wrapper refuses to forward."""


class ReadOnlyClient:
    """Wrap a datastore client so reads pass through but any write raises.

    Used by the ``viur-mirror`` copy on the live ``(default)`` database: the
    source can be queried and fetched, never mutated. A bug that tried to
    write to production fails loudly instead of corrupting live data.
    """

    def __init__(self, client: "datastore.Client") -> None:
        self._client = client

    def __getattr__(self, name: str) -> t.Any:
        if name in _BLOCKED_WRITES:
            raise RuntimeError(
                f"viur-testing dev-mirror: refusing to call {name}() on the LIVE "
                "(default) database — the mirror source is strictly read-only."
            )
        return getattr(self._client, name)


__all__ = [
    "ReadOnlyClient",
]
