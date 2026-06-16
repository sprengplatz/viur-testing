"""Unit tests for :mod:`viur.testing.mirror` (read-only source client)."""

import pytest

from viur.testing.mirror import ReadOnlyClient


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeClient:
    """Just enough of a datastore client for the read-only passthrough test."""

    def __init__(self, *, project="proj-x"):
        self.project = project
        self._kinds: dict = {}

    def key(self, *flat_path):
        return ("key", flat_path)

    def query(self, *, kind):
        return _FakeQuery(self._kinds.get(kind, []))


class _FakeQuery:
    def __init__(self, items):
        self._items = items

    def fetch(self, limit=None):
        return list(self._items)


# ---------------------------------------------------------------------------
# ReadOnlyClient
# ---------------------------------------------------------------------------


def test_readonly_client_passes_reads_through():
    inner = FakeClient(project="proj-x")
    inner._kinds["x"] = [object()]
    readonly = ReadOnlyClient(inner)

    assert readonly.project == "proj-x"
    assert readonly.key("x", 1) == ("key", ("x", 1))
    assert len(readonly.query(kind="x").fetch()) == 1


@pytest.mark.parametrize(
    "method",
    ["put", "put_multi", "delete", "delete_multi", "allocate_ids", "mutation", "transaction"],
)
def test_readonly_client_blocks_every_write(method):
    readonly = ReadOnlyClient(FakeClient())
    with pytest.raises(RuntimeError, match="read-only"):
        getattr(readonly, method)
