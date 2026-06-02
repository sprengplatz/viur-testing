"""Unit tests for :mod:`viur.testing.pin`."""

import types

import pytest

from viur.testing import pin as pin_mod
from viur.testing.pin import (
    PinChallengeError,
    format_pin,
    generate_pin,
    run_pin_challenge,
)


class FakeIo:
    """In-memory :class:`~viur.testing.pin.PinChallengeIo` for tests."""

    def __init__(self, *, tty: bool, reply: str) -> None:
        self._tty = tty
        self._reply = reply
        self.lines: list[str] = []
        self.prompts: list[str] = []

    def is_tty(self) -> bool:
        return self._tty

    def write_line(self, line: str) -> None:
        self.lines.append(line)

    def read_line(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self._reply


# ---------------------------------------------------------------------------
# generate_pin / format_pin
# ---------------------------------------------------------------------------


def test_generate_pin_is_six_digits():
    for _ in range(50):
        pin = generate_pin()
        assert len(pin) == 6
        assert pin.isdigit()


def test_format_pin_spaces_digits():
    assert format_pin("482193") == "4 8 2 1 9 3"


# ---------------------------------------------------------------------------
# run_pin_challenge — happy path
# ---------------------------------------------------------------------------


def test_correct_pin_passes_and_prints_context():
    fake = FakeIo(tty=True, reply="482193")
    run_pin_challenge(
        context_lines=["project = demo", "source = LIVE (default)"],
        _pin="482193",
        io=fake,
    )
    joined = "\n".join(fake.lines)
    assert "DEV-MIRROR MODE" in joined
    assert "project = demo" in joined
    assert "source = LIVE (default)" in joined
    assert "4 8 2 1 9 3" in joined
    assert fake.prompts == ["   > "]


def test_whitespace_in_reply_is_ignored():
    fake = FakeIo(tty=True, reply="  4 8 2 1 9 3 \t")
    run_pin_challenge(context_lines=[], _pin="482193", io=fake)  # no raise


# ---------------------------------------------------------------------------
# run_pin_challenge — failure paths
# ---------------------------------------------------------------------------


def test_wrong_pin_raises():
    fake = FakeIo(tty=True, reply="000000")
    with pytest.raises(PinChallengeError, match="confirmation failed"):
        run_pin_challenge(context_lines=[], _pin="482193", io=fake)


def test_empty_reply_raises():
    fake = FakeIo(tty=True, reply="")
    with pytest.raises(PinChallengeError, match="confirmation failed"):
        run_pin_challenge(context_lines=[], _pin="482193", io=fake)


def test_no_tty_raises_before_any_output():
    fake = FakeIo(tty=False, reply="482193")
    with pytest.raises(PinChallengeError, match="not a TTY"):
        run_pin_challenge(context_lines=["x"], _pin="482193", io=fake)
    assert fake.lines == []  # nothing printed
    assert fake.prompts == []  # never prompted


# ---------------------------------------------------------------------------
# _DefaultPinChallengeIo (selected when io=None)
# ---------------------------------------------------------------------------


def test_default_io_selected_when_none(monkeypatch):
    """``io=None`` constructs the real default IO; a non-TTY stdin makes the
    challenge abort there, proving the default path is taken without needing
    a real terminal."""
    monkeypatch.setattr(
        pin_mod.sys, "stdin", types.SimpleNamespace(isatty=lambda: False)
    )
    with pytest.raises(PinChallengeError, match="not a TTY"):
        run_pin_challenge(context_lines=[], _pin="482193", io=None)


def test_default_io_full_pass_and_generates_pin(monkeypatch):
    """``_pin=None`` path drives :func:`generate_pin`, and the real default
    IO's write_line / read_line / is_tty are exercised against a TTY stdin,
    a stubbed stdout and a stubbed ``input``."""
    monkeypatch.setattr(
        pin_mod.sys, "stdin", types.SimpleNamespace(isatty=lambda: True)
    )
    written: list[str] = []
    monkeypatch.setattr(
        pin_mod.sys,
        "stdout",
        types.SimpleNamespace(write=written.append, flush=lambda: None),
    )
    monkeypatch.setattr(pin_mod, "generate_pin", lambda: "135790")
    monkeypatch.setattr("builtins.input", lambda prompt="": "135790")

    run_pin_challenge(context_lines=["ctx"], io=None)  # _pin=None → generate_pin

    out = "".join(written)
    assert "1 3 5 7 9 0" in out
    assert "ctx" in out


def test_default_io_is_tty_handles_none_stdin(monkeypatch):
    """``_DefaultPinChallengeIo.is_tty()``: stdin is ``None`` → ``False``."""
    monkeypatch.setattr(pin_mod.sys, "stdin", None)
    assert pin_mod._DefaultPinChallengeIo().is_tty() is False
