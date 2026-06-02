"""
Interactive 6-digit PIN challenge — the **server-side**, pre-boot human gate
for Dev-Mirror mode. Python analog of the runner-side
``playwright/src/pin-challenge.ts``.

Dev-Mirror copies data out of the **live** ``(default)`` database into the
developer's ``viur-tests`` namespace *before* the real server boots. Because
that copy reads production data (read-only) on a dev-server process, every
boot demands a fresh human confirmation — same design intent as Guarded Mode
on the runner side:

- **Every boot requires confirmation.** No persisted ACK file, no env-var
  bypass — those would silently inherit an old decision. The PIN is fresh
  per boot and forces the developer to look at the screen.
- **One try, no retry.** A retry loop invites muscle-memory. A wrong PIN
  raises; restarting the server issues a new PIN.
- **No TTY → no run.** Without an interactive terminal there is no human to
  challenge, so Dev-Mirror refuses (hard abort). Do not run it in CI or
  background jobs.
- **The copy context is part of the prompt.** The project id, the LIVE
  source and the target slice are printed above the PIN, so the developer
  sees exactly what is about to be copied before typing.

The module is deliberately free of any ``viur.core`` import so it can run
at the very top of ``main.py`` — before the datastore client is bound.
"""

import secrets
import sys
import typing as t


class PinChallengeError(RuntimeError):
    """Raised when the PIN challenge fails — wrong PIN, empty input, or no TTY.

    Dev-Mirror lets this propagate out of ``activate()`` so the boot aborts
    rather than continuing without (or with) an unconfirmed copy.
    """


class PinChallengeIo(t.Protocol):
    """Injectable I/O surface so the challenge can be exercised without a TTY.

    The default implementation, :class:`_DefaultPinChallengeIo`, wires up the
    real :data:`sys.stdin` / :data:`sys.stdout`.
    """

    def is_tty(self) -> bool: ...
    def write_line(self, line: str) -> None: ...
    def read_line(self, prompt: str) -> str: ...


class _DefaultPinChallengeIo:
    """Real-terminal I/O backed by :data:`sys.stdin` / :data:`sys.stdout`."""

    def is_tty(self) -> bool:
        stream = sys.stdin
        return bool(stream is not None and stream.isatty())

    def write_line(self, line: str) -> None:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()

    def read_line(self, prompt: str) -> str:
        return input(prompt)


_YELLOW = "\033[1;33m"
"""ANSI SGR yellow-bold for the digits — stands out without looking like an
emergency. Mirrors the runner-side challenge's colouring."""

_RESET = "\033[0m"
"""ANSI SGR reset, always emitted after the coloured digits."""

_PIN_LENGTH = 6
"""Number of digits in the challenge PIN."""


def generate_pin() -> str:
    """Return a fresh, cryptographically-random 6-digit numeric PIN.

    Uses :func:`secrets.randbelow` rather than :mod:`random` so the value is
    not predictable from process state.
    """
    return "".join(str(secrets.randbelow(10)) for _ in range(_PIN_LENGTH))


def format_pin(pin: str) -> str:
    """Render the PIN space-separated (``"482193"`` → ``"4 8 2 1 9 3"``).

    Easier to read off the screen and to type without losing one's place;
    matches the runner-side challenge's formatting.
    """
    return " ".join(pin)


def run_pin_challenge(
    *,
    context_lines: t.Sequence[str],
    io: "PinChallengeIo | None" = None,
    _pin: str | None = None,
) -> None:
    """Run the interactive PIN challenge. Returns on success; raises on failure.

    :param context_lines: Lines printed under the ``DEV-MIRROR MODE`` title
        and above the PIN — typically the project id, the LIVE source and
        the target slice, so the developer sees what is about to be copied.
    :param io: I/O override (tests pass a fake; production passes ``None``,
        which selects :class:`_DefaultPinChallengeIo`).
    :param _pin: PIN override (tests pass a fixed value; production passes
        ``None``, which generates a fresh PIN).
    :raises PinChallengeError: when stdin is not a TTY, or the reply does not
        match the PIN.
    """
    io = io if io is not None else _DefaultPinChallengeIo()

    if not io.is_tty():
        raise PinChallengeError(
            "viur-testing dev-mirror: stdin is not a TTY — no human to confirm. "
            "Run from an interactive terminal (dev-mirror is for developer "
            "hands only; not for CI or background jobs)."
        )

    pin = _pin if _pin is not None else generate_pin()

    io.write_line("")
    io.write_line("⚠  DEV-MIRROR MODE")
    for line in context_lines:
        io.write_line("   " + line)
    io.write_line("")
    io.write_line(f"   Confirm by typing:   {_YELLOW}{format_pin(pin)}{_RESET}")
    io.write_line("")

    reply = "".join(io.read_line("   > ").split())
    if reply != pin:
        raise PinChallengeError(
            "viur-testing dev-mirror: PIN confirmation failed. "
            "Restart the server for a fresh PIN."
        )


__all__ = [
    "PinChallengeError",
    "PinChallengeIo",
    "format_pin",
    "generate_pin",
    "run_pin_challenge",
]
