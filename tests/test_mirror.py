"""Unit tests for :mod:`viur.testing.mirror` (read-only client + tokenless)."""

import pytest

from viur.testing._test.config import ConfigModule
from viur.testing.mirror import ReadOnlyClient, arm_tokenless_browsing
from viur.testing.pin import PinChallengeError


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


class _PinIo:
    """Minimal PinChallengeIo for the tokenless tests."""

    def __init__(self, *, tty=True, reply="123456"):
        self._tty = tty
        self._reply = reply

    def is_tty(self):
        return self._tty

    def write_line(self, line):
        pass

    def read_line(self, prompt):
        return self._reply


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


# ---------------------------------------------------------------------------
# arm_tokenless_browsing
# ---------------------------------------------------------------------------


def test_arm_tokenless_happy_path(conf_instance, capsys):
    conf_instance.is_dev_server = True
    ConfigModule.set_active(database="viur-tests", project_id="proj-x")

    arm_tokenless_browsing(
        tokenless_app_ids=["proj-x"],
        io=_PinIo(reply="123456"),
        _pin="123456",
    )

    assert ConfigModule.tokenless_allowed() is True
    out = capsys.readouterr().out
    assert "tokenless browsing ENABLED" in out


def test_arm_tokenless_reads_project_from_config_when_not_injected(conf_instance):
    """Without _project_id, the active project recorded by activate() is used."""
    conf_instance.is_dev_server = True
    ConfigModule.set_active(database="viur-tests", project_id="proj-x")

    arm_tokenless_browsing(
        tokenless_app_ids=["proj-x"], io=_PinIo(reply="123456"), _pin="123456",
    )
    assert ConfigModule.tokenless_allowed() is True


def test_arm_tokenless_refuses_unwhitelisted_project():
    with pytest.raises(RuntimeError, match="not in the whitelist"):
        arm_tokenless_browsing(tokenless_app_ids=["other"], _project_id="proj-x")


def test_arm_tokenless_refuses_when_no_whitelist():
    with pytest.raises(RuntimeError, match="not in the whitelist"):
        arm_tokenless_browsing(tokenless_app_ids=None, _project_id="proj-x")


def test_arm_tokenless_refuses_outside_dev_server(conf_instance):
    conf_instance.is_dev_server = False
    with pytest.raises(RuntimeError, match="local dev server"):
        arm_tokenless_browsing(tokenless_app_ids=["proj-x"], _project_id="proj-x")


def test_arm_tokenless_aborts_on_wrong_pin(conf_instance):
    conf_instance.is_dev_server = True
    ConfigModule.set_active(database="viur-tests", project_id="proj-x")

    with pytest.raises(PinChallengeError):
        arm_tokenless_browsing(
            tokenless_app_ids=["proj-x"],
            io=_PinIo(reply="000000"),
            _pin="123456",
            _project_id="proj-x",
        )
    # PIN failed before arming — tokenless must NOT be on.
    assert ConfigModule.tokenless_allowed() is False
