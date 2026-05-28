"""Tests for :mod:`viur.testing.banner`."""

import builtins
import sys
import types

import pytest

from viur.testing import banner


# ---------------------------------------------------------------------------
# _format_db_line
# ---------------------------------------------------------------------------


def test_format_db_line_contains_database_name():
    line = banner._format_db_line("viur-tests")
    assert "viur-tests" in line


def test_format_db_line_visible_width_matches_banner():
    """Strip ANSI escapes — the remaining visible string must be exactly
    BANNER_WIDTH columns wide so it lines up with viur-core's frame."""
    line = banner._format_db_line("viur-tests")
    visible = (
        line.replace("\033[0m", "").replace("\033[1;33m", "")
    )
    assert len(visible) == banner._BANNER_WIDTH


def test_format_db_line_uses_hash_frame():
    line = banner._format_db_line("viur-tests")
    # Strip the leading reset escape — the first visible char is the
    # left frame, the last visible char is the right frame.
    visible = line.replace("\033[0m", "").replace("\033[1;33m", "")
    assert visible[0] == banner._BANNER_FILL
    assert visible[-1] == banner._BANNER_FILL


# ---------------------------------------------------------------------------
# _looks_like_banner_tail
# ---------------------------------------------------------------------------


def test_banner_tail_detected_on_pure_fill_line():
    tail = "\033[0m" + banner._BANNER_FILL * banner._BANNER_WIDTH
    assert banner._looks_like_banner_tail(tail) is True


def test_banner_tail_rejects_title_line():
    """The title line starts with ``#`` chars but breaks the run with
    text — must NOT match the trailer detector."""
    title = (
        "\033[0m"
        + banner._BANNER_FILL * 18
        + " LOCAL DEVELOPMENT SERVER IS UP AND RUNNING "
        + banner._BANNER_FILL * 18
    )
    assert banner._looks_like_banner_tail(title) is False


def test_banner_tail_rejects_content_line():
    """A regular ``project = …`` line uses space padding — no match."""
    content = (
        "\033[0m"
        + banner._BANNER_FILL
        + "       project = \033[1;31mfoo\033[0m       "
        + banner._BANNER_FILL
    )
    assert banner._looks_like_banner_tail(content) is False


def test_banner_tail_rejects_plain_text():
    assert banner._looks_like_banner_tail("hello world") is False


def test_banner_tail_rejects_short_fill_run():
    """Fewer than ten leading fill chars → not a banner trailer."""
    assert banner._looks_like_banner_tail("###") is False


# ---------------------------------------------------------------------------
# install_banner_patch — wraps viur.core.setup
# ---------------------------------------------------------------------------


@pytest.fixture
def viur_core_with_setup():
    """Install a minimal ``viur.core.setup`` stub on the test viur.core
    module and yield (module, recorded_prints). Restores the original
    setup attribute (or removes it) on teardown."""
    viur_core = sys.modules["viur.core"]
    had_setup = hasattr(viur_core, "setup")
    original = getattr(viur_core, "setup", None)

    recorded: list[str] = []

    def _stub_setup():
        # Emit a five-line banner matching viur-core's exact format.
        WIDTH = banner._BANNER_WIDTH
        FILL = banner._BANNER_FILL
        lines = (
            " LOCAL DEVELOPMENT SERVER IS UP AND RUNNING ",
            "project = \033[1;31mproj-x\033[0m",
            "python = \033[1;32m3.13.0\033[0m",
            "viur = \033[1;32m3.8.25\033[0m",
            "",
        )
        first_last = (0, len(lines) - 1)
        for i, line in enumerate(lines):
            print(
                f"\033[0m{FILL}{line:{FILL if i in first_last else ' '}^{(WIDTH - 2) + (11 if i not in first_last else 0)}}{FILL}"
            )
        return "setup-return-value"

    viur_core.setup = _stub_setup

    # Capture prints during the wrapped setup call.
    _orig_print = builtins.print

    def _capture(*args, **kwargs):
        if args and isinstance(args[0], str):
            recorded.append(args[0])
        # Do NOT pass through — keeps test output clean.

    yield viur_core, recorded, _capture, _orig_print

    if had_setup:
        viur_core.setup = original
    else:
        delattr(viur_core, "setup")


def test_install_banner_patch_wraps_setup(viur_core_with_setup):
    viur_core, _, _, _ = viur_core_with_setup
    assert not getattr(viur_core.setup, banner._PATCH_SENTINEL_ATTR, False)
    banner.install_banner_patch("viur-tests")
    assert getattr(viur_core.setup, banner._PATCH_SENTINEL_ATTR, False) is True


def test_install_banner_patch_is_idempotent(viur_core_with_setup):
    viur_core, _, _, _ = viur_core_with_setup
    banner.install_banner_patch("viur-tests")
    first_wrap = viur_core.setup
    banner.install_banner_patch("viur-tests")
    assert viur_core.setup is first_wrap


def test_wrapped_setup_injects_database_and_namespace_lines(viur_core_with_setup, monkeypatch):
    viur_core, recorded, capture, _orig_print = viur_core_with_setup
    banner.install_banner_patch("viur-tests")

    monkeypatch.setattr(builtins, "print", capture)
    result = viur_core.setup()

    # Stub returns its sentinel — wrapping must not swallow the return.
    assert result == "setup-return-value"

    # Banner had 5 lines; wrapped produces 7 — database + namespace
    # are both injected immediately before the trailer, always.
    assert len(recorded) == 7
    assert "database = " in recorded[4]
    assert "viur-tests" in recorded[4]
    assert "namespace = " in recorded[5]
    assert banner._DEFAULT_NAMESPACE_LABEL in recorded[5]
    assert banner._looks_like_banner_tail(recorded[6])


def test_wrapped_setup_restores_print_on_return(viur_core_with_setup):
    viur_core, _, _, _ = viur_core_with_setup
    banner.install_banner_patch("viur-tests")

    _orig_print = builtins.print
    try:
        viur_core.setup()
    finally:
        # Confirm the wrap left builtins.print as it found it,
        # regardless of any monkeypatching above.
        assert builtins.print is _orig_print


def test_wrapped_setup_restores_print_on_exception(viur_core_with_setup):
    viur_core, _, _, _ = viur_core_with_setup

    def _boom():
        raise RuntimeError("setup crashed")

    viur_core.setup = _boom
    banner.install_banner_patch("viur-tests")

    _orig_print = builtins.print
    with pytest.raises(RuntimeError, match="setup crashed"):
        viur_core.setup()
    assert builtins.print is _orig_print


def test_wrapped_setup_passes_through_non_banner_prints(viur_core_with_setup, monkeypatch):
    """Prints that have nothing to do with the banner must flow through
    unchanged and not trigger injection."""
    viur_core, recorded, capture, _ = viur_core_with_setup

    def _noisy_setup():
        print("some unrelated log line")
        print("another one — no banner here")

    viur_core.setup = _noisy_setup
    banner.install_banner_patch("viur-tests")

    monkeypatch.setattr(builtins, "print", capture)
    viur_core.setup()

    assert recorded == [
        "some unrelated log line",
        "another one — no banner here",
    ]


def test_wrapped_setup_ignores_non_string_prints(viur_core_with_setup, monkeypatch):
    """``print(123)`` inside setup must not crash the sniffer."""
    viur_core, recorded, _, _ = viur_core_with_setup

    captured: list = []

    def _capture_any(*args, **kwargs):
        captured.append(args)

    def _setup_with_numbers():
        print(42)
        print("plain string")

    viur_core.setup = _setup_with_numbers
    banner.install_banner_patch("viur-tests")

    monkeypatch.setattr(builtins, "print", _capture_any)
    viur_core.setup()

    assert (42,) in captured
    assert ("plain string",) in captured


def test_format_content_line_renders_label_and_value():
    line = banner._format_content_line("namespace", "alice")
    assert "namespace = " in line
    assert "alice" in line


def test_format_content_line_visible_width_matches_banner():
    """The ANSI-stripped line must be exactly BANNER_WIDTH columns wide."""
    line = banner._format_content_line("namespace", "alice")
    visible = line.replace("\033[0m", "").replace("\033[1;33m", "")
    assert len(visible) == banner._BANNER_WIDTH


def test_wrapped_setup_renders_explicit_namespace_value(viur_core_with_setup, monkeypatch):
    """When ``install_banner_patch(database, namespace=…)`` is called
    with a namespace, the namespace line carries that exact value
    instead of the default-namespace placeholder."""
    viur_core, recorded, capture, _ = viur_core_with_setup
    banner.install_banner_patch("viur-tests", namespace="alice")

    monkeypatch.setattr(builtins, "print", capture)
    viur_core.setup()

    assert len(recorded) == 7
    assert "alice" in recorded[5]
    assert banner._DEFAULT_NAMESPACE_LABEL not in recorded[5]


def test_wrapped_setup_falls_back_to_default_label_for_empty_namespace(
    viur_core_with_setup, monkeypatch,
):
    """An empty-string namespace is treated as "no namespace" — same
    as ``None`` — and renders the ``(default)`` placeholder."""
    viur_core, recorded, capture, _ = viur_core_with_setup
    banner.install_banner_patch("viur-tests", namespace="")

    monkeypatch.setattr(builtins, "print", capture)
    viur_core.setup()

    assert banner._DEFAULT_NAMESPACE_LABEL in recorded[5]


def test_measure_visible_width_strips_ansi_escapes():
    """Visible width is the character count after every ANSI SGR escape
    is removed. Used by the wrapper to discover viur-core's actual
    banner width at runtime."""
    plain = "X" * 80
    coloured = f"\033[0m{plain[:40]}\033[1;33m{plain[40:60]}\033[0m{plain[60:]}"
    assert banner._measure_visible_width(coloured) == 80
    assert banner._measure_visible_width(plain) == 80
    assert banner._measure_visible_width("") == 0


def test_wrapped_setup_adapts_to_non_default_banner_width(viur_core_with_setup, monkeypatch):
    """If a future viur-core uses a different ``WIDTH``, the wrapper
    must follow — the injected ``database``/``namespace`` lines have
    to line up with the actual banner frame, not the constant from
    the time of writing.

    Regression guard: an earlier version hard-coded
    :data:`_BANNER_WIDTH` everywhere, so a 100-wide banner would have
    produced 80-wide injected lines (visually misaligned, framing
    broken)."""
    viur_core, recorded, capture, _ = viur_core_with_setup

    wide = 100
    fill = banner._BANNER_FILL

    def _wide_setup():
        # Real viur-core lays out title (one fill char trailing the
        # text), content lines, and a trailer that is pure fill.
        print(f"\033[0m{fill * 28} LOCAL DEVELOPMENT SERVER IS UP AND RUNNING {fill * 28}")
        print(f"\033[0m{fill}{'project = \033[1;31mproj\033[0m':^{(wide - 2) + 11}}{fill}")
        print(f"\033[0m{fill * wide}")

    viur_core.setup = _wide_setup
    banner.install_banner_patch("viur-tests")

    monkeypatch.setattr(builtins, "print", capture)
    viur_core.setup()

    # Title (1) + content (1) + database (injected) + namespace (injected)
    # + trailer (1) = 5 lines total.
    assert len(recorded) == 5
    # Injected database/namespace lines must be exactly ``wide`` columns
    # wide after ANSI strip.
    assert banner._measure_visible_width(recorded[2]) == wide
    assert banner._measure_visible_width(recorded[3]) == wide
    assert "viur-tests" in recorded[2]
    assert banner._DEFAULT_NAMESPACE_LABEL in recorded[3]


def test_wrapped_setup_injection_only_fires_once(viur_core_with_setup, monkeypatch):
    """If setup prints more banner-like trailers later, only the first one
    after the title gets a DB line — the sniffer flips back off after
    injection."""
    viur_core, recorded, capture, _ = viur_core_with_setup

    def _setup_two_trailers():
        WIDTH = banner._BANNER_WIDTH
        FILL = banner._BANNER_FILL
        print(f"\033[0m{FILL * WIDTH}".replace(FILL, FILL, 1).rstrip() + "")
        # Real banner: title, content, trailer
        print(f"\033[0m{FILL * 18} LOCAL DEVELOPMENT SERVER IS UP AND RUNNING {FILL * 18}")
        print(f"\033[0m{FILL}{'content':^89}{FILL}")
        print(f"\033[0m{FILL * WIDTH}")  # trailer → injection here
        # Spurious second trailer-looking line later: should NOT inject again
        print(f"\033[0m{FILL * WIDTH}")

    viur_core.setup = _setup_two_trailers
    banner.install_banner_patch("viur-tests")

    monkeypatch.setattr(builtins, "print", capture)
    viur_core.setup()

    db_lines = [r for r in recorded if "database = " in r]
    assert len(db_lines) == 1
