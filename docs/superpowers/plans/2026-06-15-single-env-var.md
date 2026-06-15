# Single `VIUR_TESTING` env var Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the three boot env vars (`VIUR_TESTING_ENABLE`, `VIUR_TESTING_NAMESPACE`, `VIUR_TESTING_TOKENLESS`) with a single `VIUR_TESTING=<mode>[:<namespace>]`.

**Architecture:** A new tiny `mode.py` parses the value into `(mode, namespace)` with three modes (`off`/`test`/`dev`); `dev` implies tokenless and requires a namespace. `setup()` consumes the parsed result, dropping its three env-var parameters. Clean break — no fallback to the old vars.

**Tech Stack:** Python 3.12, pytest, 100 % branch coverage enforced (`--cov-fail-under=100`).

All paths below are relative to `sources/viur-testing/`. Run all commands from that directory with the test venv active (`uv venv .venv-test && . .venv-test/bin/activate && uv pip install -e ".[test]"`).

---

## File Structure

- **Create** `src/viur/testing/mode.py` — the parser + mode constants + dev-namespace validation. One responsibility: turn the env-var string (or explicit mode/namespace) into a validated `(mode, namespace)` pair.
- **Modify** `src/viur/testing/__init__.py` — `setup()` signature + wiring; import from `mode`.
- **Modify** `src/viur/testing/constants.py` — remove `TOKENLESS_ENV_VAR`.
- **Modify** `src/viur/testing/mirror.py` — docstring references to the removed env var.
- **Modify** `src/viur/testing/activation.py` — docstring reference to `VIUR_TESTING_NAMESPACE`.
- **Create** `tests/test_mode.py` — table-driven parser tests.
- **Modify** `tests/test_package.py` — rewrite the `setup()` and tokenless wiring tests.
- **Modify** `tests/test_runner.py` — docstring/comment references.
- **Modify** docs: `README.md`, `docs/getting-started.md`, `docs/dev-mirror-mode.md`, `CHANGELOG.md`.
- **Modify** Playwright text/comments: `playwright/src/bin/init.ts`, `playwright/bin/init.mjs`, `playwright/src/test-mode.ts`, `playwright/src/vite-plugin.ts`.

---

## Task 1: Parser module `mode.py`

**Files:**
- Create: `src/viur/testing/mode.py`
- Test: `tests/test_mode.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_mode.py`:

```python
"""Tests for viur.testing.mode — the VIUR_TESTING value parser."""

import pytest

from viur.testing.mode import (
    MODE_DEV,
    MODE_OFF,
    MODE_TEST,
    parse_spec,
    validate_spec,
)


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, (MODE_OFF, None)),
        ("", (MODE_OFF, None)),
        ("   ", (MODE_OFF, None)),
        ("0", (MODE_OFF, None)),
        ("off", (MODE_OFF, None)),
        ("OFF", (MODE_OFF, None)),
        ("false", (MODE_OFF, None)),
        ("1", (MODE_TEST, None)),
        ("true", (MODE_TEST, None)),
        ("on", (MODE_TEST, None)),
        ("test", (MODE_TEST, None)),
        ("TEST", (MODE_TEST, None)),
        ("test:ak", (MODE_TEST, "ak")),
        (" test : ak ", (MODE_TEST, "ak")),
        ("dev:ak", (MODE_DEV, "ak")),
        ("DEV:AK", (MODE_DEV, "AK")),  # namespace stays case-sensitive
    ],
)
def test_parse_spec_valid(value, expected):
    assert parse_spec(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "dev",        # dev requires a namespace
        "dev:",       # empty namespace after colon
        "test:",      # empty namespace after colon
        ":ak",        # empty mode before colon
        "foo",        # unknown mode keyword
        "off:ak",     # off does not take a namespace
    ],
)
def test_parse_spec_invalid(value):
    with pytest.raises(ValueError):
        parse_spec(value)


def test_validate_spec_dev_requires_namespace():
    with pytest.raises(ValueError):
        validate_spec(MODE_DEV, None)


def test_validate_spec_allows_dev_with_namespace():
    validate_spec(MODE_DEV, "ak")  # no raise


def test_validate_spec_allows_test_without_namespace():
    validate_spec(MODE_TEST, None)  # no raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_mode.py -q`
Expected: collection/import error — `ModuleNotFoundError: No module named 'viur.testing.mode'`.

- [ ] **Step 3: Write the parser**

Create `src/viur/testing/mode.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_mode.py -q`
Expected: PASS (all parametrized cases green).

- [ ] **Step 5: Commit**

```bash
git add src/viur/testing/mode.py tests/test_mode.py
git commit -m "feat: add VIUR_TESTING value parser (mode:namespace)"
```

---

## Task 2: Rewire `setup()` and remove the old env-var params

**Files:**
- Modify: `src/viur/testing/__init__.py` (imports near line 61; `setup()` lines 152-249)
- Modify: `src/viur/testing/constants.py` (remove `TOKENLESS_ENV_VAR`, lines 48-57)
- Test: `tests/test_package.py` (replace lines 256-439 setup/tokenless blocks)

- [ ] **Step 1: Rewrite the setup/tokenless tests**

In `tests/test_package.py`, replace everything from `def test_setup_skips_api_loading_when_test_mode_off` (line 256) through the end of the file (line 439) with:

```python
def test_setup_skips_api_loading_when_test_mode_off(monkeypatch, tmp_path):
    """Without test mode, `api_dir` is ignored entirely — even
    a valid wrapper is left untouched."""
    api_pkg = tmp_path / "testing" / "api"
    api_pkg.mkdir(parents=True)
    (api_pkg / "__init__.py").write_text("MARKER = 'should-not-load'\n")

    monkeypatch.delenv("VIUR_TESTING", raising=False)
    monkeypatch.setattr(viur.testing, "protect", lambda: None)

    import sys
    sys.modules.pop("api", None)
    viur.testing.setup(api_dir="testing")
    assert "api" not in sys.modules


def test_setup_skips_api_loading_when_api_dir_is_none(monkeypatch):
    """`api_dir=None` is the explicit opt-out: never touch sys.modules['api']."""
    monkeypatch.setenv("VIUR_TESTING", "test")
    monkeypatch.setattr(viur.testing, "activate", lambda **kw: None)
    monkeypatch.setattr(viur.testing, "protect", lambda: None)

    import sys
    sys.modules.pop("api", None)
    viur.testing.setup(api_dir=None)
    assert "api" not in sys.modules


def test_heavy_classes_not_on_top_level():
    """TestModule/ConfigModule/TokenValidator/ProductionGuardValidator
    are intentionally NOT re-exported on the package root — they would
    trigger ``viur.core`` import at ``import viur.testing`` time, which
    must stay clean so ``activate()`` can swap the datastore client first.
    """
    for name in ("TestModule", "ConfigModule", "TokenValidator", "ProductionGuardValidator"):
        assert not hasattr(viur.testing, name), name


# ---------------------------------------------------------------------------
# setup()
# ---------------------------------------------------------------------------


def test_setup_calls_activate_when_mode_test(monkeypatch):
    """VIUR_TESTING=test → activate() with default db/ns, then protect()."""
    calls: list = []
    monkeypatch.setenv("VIUR_TESTING", "test")
    monkeypatch.setattr(
        viur.testing, "activate", lambda **kw: calls.append(("activate", kw))
    )
    monkeypatch.setattr(viur.testing, "protect", lambda: calls.append(("protect",)))
    viur.testing.setup(api_dir=None)
    assert calls == [
        ("activate", {"database": "viur-tests", "namespace": None}),
        ("protect",),
    ]


def test_setup_accepts_numeric_alias(monkeypatch):
    """VIUR_TESTING=1 is an alias for test mode."""
    calls: list = []
    monkeypatch.setenv("VIUR_TESTING", "1")
    monkeypatch.setattr(
        viur.testing, "activate", lambda **kw: calls.append(("activate", kw))
    )
    monkeypatch.setattr(viur.testing, "protect", lambda: calls.append(("protect",)))
    viur.testing.setup(api_dir=None)
    assert calls[0] == ("activate", {"database": "viur-tests", "namespace": None})


def test_setup_skips_activate_when_off(monkeypatch):
    calls: list = []
    monkeypatch.delenv("VIUR_TESTING", raising=False)
    monkeypatch.setattr(
        viur.testing, "activate", lambda **kw: calls.append(("activate", kw))
    )
    monkeypatch.setattr(viur.testing, "protect", lambda: calls.append(("protect",)))
    viur.testing.setup(api_dir=None)
    assert calls == [("protect",)]


def test_setup_skips_activate_when_empty_string(monkeypatch):
    calls: list = []
    monkeypatch.setenv("VIUR_TESTING", "")
    monkeypatch.setattr(
        viur.testing, "activate", lambda **kw: calls.append(("activate", kw))
    )
    monkeypatch.setattr(viur.testing, "protect", lambda: calls.append(("protect",)))
    viur.testing.setup(api_dir=None)
    assert calls == [("protect",)]


def test_setup_honours_custom_env_var_and_database(monkeypatch):
    calls: list = []
    monkeypatch.setenv("MY_TEST_FLAG", "test")
    monkeypatch.setattr(
        viur.testing, "activate", lambda **kw: calls.append(("activate", kw))
    )
    monkeypatch.setattr(viur.testing, "protect", lambda: calls.append(("protect",)))
    viur.testing.setup(env_var="MY_TEST_FLAG", database="alt-tests", api_dir=None)
    assert calls == [
        ("activate", {"database": "alt-tests", "namespace": None}),
        ("protect",),
    ]


def test_setup_reads_namespace_from_env_var(monkeypatch):
    """VIUR_TESTING=test:alice feeds the namespace into activate()."""
    calls: list = []
    monkeypatch.setenv("VIUR_TESTING", "test:alice")
    monkeypatch.setattr(
        viur.testing, "activate", lambda **kw: calls.append(("activate", kw))
    )
    monkeypatch.setattr(viur.testing, "protect", lambda: calls.append(("protect",)))
    viur.testing.setup(api_dir=None)
    assert calls[0] == ("activate", {"database": "viur-tests", "namespace": "alice"})


def test_setup_explicit_kwargs_override_env_var(monkeypatch):
    """Explicit mode/namespace kwargs win over the env var."""
    calls: list = []
    monkeypatch.setenv("VIUR_TESTING", "test:from-env")
    monkeypatch.setattr(
        viur.testing, "activate", lambda **kw: calls.append(("activate", kw))
    )
    monkeypatch.setattr(viur.testing, "protect", lambda: calls.append(("protect",)))
    viur.testing.setup(namespace="from-call", api_dir=None)
    assert calls[0] == ("activate", {"database": "viur-tests", "namespace": "from-call"})


def test_setup_explicit_empty_namespace_means_default(monkeypatch):
    """An explicit namespace="" is normalised to the default slice."""
    calls: list = []
    monkeypatch.delenv("VIUR_TESTING", raising=False)
    monkeypatch.setattr(
        viur.testing, "activate", lambda **kw: calls.append(("activate", kw))
    )
    monkeypatch.setattr(viur.testing, "protect", lambda: calls.append(("protect",)))
    viur.testing.setup(namespace="", api_dir=None)
    assert calls[0] == ("activate", {"database": "viur-tests", "namespace": None})


def test_setup_unknown_mode_raises(monkeypatch):
    monkeypatch.setenv("VIUR_TESTING", "bogus")
    monkeypatch.setattr(viur.testing, "protect", lambda: None)
    with pytest.raises(ValueError):
        viur.testing.setup(api_dir=None)


# ---------------------------------------------------------------------------
# setup() — dev mode / tokenless-browsing wiring
# ---------------------------------------------------------------------------


def test_setup_dev_mode_arms_tokenless(monkeypatch):
    """VIUR_TESTING=dev:ak → activate() then arm_tokenless_browsing()."""
    calls: list = []
    monkeypatch.setenv("VIUR_TESTING", "dev:ak")
    monkeypatch.setattr(
        viur.testing, "activate", lambda **kw: calls.append(("activate", kw))
    )
    monkeypatch.setattr(viur.testing, "protect", lambda: calls.append(("protect",)))
    monkeypatch.setattr(
        viur.testing,
        "arm_tokenless_browsing",
        lambda **kw: calls.append(("tokenless", kw)),
    )
    viur.testing.setup(api_dir=None, tokenless_app_ids=["proj-x"])
    assert calls == [
        ("activate", {"database": "viur-tests", "namespace": "ak"}),
        ("tokenless", {"tokenless_app_ids": ["proj-x"]}),
        ("protect",),
    ]


def test_setup_test_mode_skips_tokenless(monkeypatch):
    calls: list = []
    monkeypatch.setenv("VIUR_TESTING", "test:ak")
    monkeypatch.setattr(viur.testing, "activate", lambda **kw: None)
    monkeypatch.setattr(viur.testing, "protect", lambda: None)
    monkeypatch.setattr(
        viur.testing, "arm_tokenless_browsing", lambda **kw: calls.append(kw)
    )
    viur.testing.setup(api_dir=None)
    assert calls == []


def test_setup_dev_without_namespace_raises(monkeypatch):
    """VIUR_TESTING=dev (no namespace) is rejected at boot."""
    monkeypatch.setenv("VIUR_TESTING", "dev")
    monkeypatch.setattr(viur.testing, "protect", lambda: None)
    with pytest.raises(ValueError):
        viur.testing.setup(api_dir=None)
```

Make sure `import pytest` is present at the top of `tests/test_package.py` (add it if missing).

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_package.py -q`
Expected: FAIL — `setup()` still has the old signature (`TypeError: setup() got an unexpected keyword argument 'env_var'`) and ignores `VIUR_TESTING`.

- [ ] **Step 3: Rewrite `setup()` and its imports**

In `src/viur/testing/__init__.py`, change the constants import (line 61) from:

```python
from .constants import DEFAULT_DATABASE, TOKEN_HEADER, TOKENLESS_ENV_VAR
```

to:

```python
from .constants import DEFAULT_DATABASE, TOKEN_HEADER
from .mode import MODE_DEV, MODE_OFF, MODE_TEST, parse_spec, validate_spec
```

Then replace the entire `def setup(...)` definition (lines 152-249) with:

```python
def setup(
    *,
    env_var: str = "VIUR_TESTING",
    mode: str | None = None,
    namespace: str | None = None,
    database: str = DEFAULT_DATABASE,
    api_dir: str | None = "testing",
    tokenless_app_ids: list[str] | None = None,
) -> None:
    """One-call host-side wiring for ``main.py``.

    Must be the **first** line of code in ``main.py`` — before any
    ``from viur.core ...`` import. Internally:

    1. Resolves the mode + namespace. If ``mode`` and ``namespace`` are
       both ``None`` (the usual case), parses ``os.environ[env_var]``
       (default ``VIUR_TESTING``) via :func:`viur.testing.mode.parse_spec`.
       Otherwise the explicit kwargs win and the env var is ignored.
    2. For ``test`` / ``dev`` mode, calls :func:`activate` (datastore
       client swap to ``database`` + ``namespace``, probe, validator).
    3. For ``dev`` mode additionally calls :func:`arm_tokenless_browsing`
       (PIN-gated tokenless browsing of the seeded slice).
    4. Calls :func:`protect` unconditionally to install the production
       header guard.

    The single env var replaces the former trio
    (``VIUR_TESTING_ENABLE`` / ``_NAMESPACE`` / ``_TOKENLESS``)::

        $ VIUR_TESTING=test          # test mode, default namespace
        $ VIUR_TESTING=test:ak       # test mode, namespace ak
        $ VIUR_TESTING=dev:ak        # dev mode (test + tokenless), namespace ak

    ``1`` / ``true`` / ``on`` are accepted as aliases for ``test``;
    unset / ``""`` / ``0`` / ``off`` / ``false`` mean off. ``dev``
    requires a namespace. See :func:`viur.testing.mode.parse_spec`.

    :param env_var: Name of the single variable to read. Default
        ``VIUR_TESTING``.
    :param mode: Explicit mode override (``"test"``/``"dev"``/``"off"``).
        When given (or ``namespace`` is given), the env var is not read.
    :param namespace: Explicit Datastore namespace override. An empty
        string is normalised to ``None`` (default slice).
    :param database: Name of the test database to swap to. Default
        ``viur-tests``.
    :param api_dir: Wrapper directory containing an ``api/`` subfolder
        with the project test API package; ``None`` to skip. See the
        original docstring section below for the resolution rules.
    :param tokenless_app_ids: Whitelist of GCP project ids allowed to
        enable tokenless browsing in ``dev`` mode. Kept in ``main.py``
        so it is reviewed in PRs. ``None``/empty disables tokenless even
        in dev mode (``arm_tokenless_browsing`` then refuses).
    :raises ValueError: on an unparseable / illegal ``VIUR_TESTING``
        value (unknown mode, dev without namespace, …) — aborts the boot.
    """
    if mode is None and namespace is None:
        mode, namespace = parse_spec(_os.environ.get(env_var))
    else:
        if mode is None:
            mode = MODE_TEST
        if namespace == "":
            namespace = None
        validate_spec(mode, namespace)

    if mode != MODE_OFF:
        activate(database=database, namespace=namespace)
        if mode == MODE_DEV:
            arm_tokenless_browsing(tokenless_app_ids=tokenless_app_ids)
        if api_dir is not None:
            _load_project_api(api_dir)
    protect()
```

> Note: keep the `api_dir` resolution prose from the original docstring if you want the full detail; it is unchanged behaviour. The helper functions `_load_project_api`, `_load_api_package`, `register_modules`, and the `register_*` hooks below are untouched.

- [ ] **Step 4: Remove `TOKENLESS_ENV_VAR` from constants**

In `src/viur/testing/constants.py`, delete the `TOKENLESS_ENV_VAR` definition and its docstring (lines 48-57):

```python
TOKENLESS_ENV_VAR = "VIUR_TESTING_TOKENLESS"
"""Env var that opts a dev-server boot into **tokenless browsing**.
...
``viur-mirror`` console script (:mod:`viur.testing.cli`).
"""
```

(Leave `MIRROR_EXCLUDE_KINDS` and everything else intact.)

- [ ] **Step 5: Run the package + mode tests to verify they pass**

Run: `python -m pytest tests/test_package.py tests/test_mode.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/viur/testing/__init__.py src/viur/testing/constants.py tests/test_package.py
git commit -m "feat: single VIUR_TESTING env var; drop ENABLE/NAMESPACE/TOKENLESS"
```

---

## Task 3: Clean up remaining docstring references in code

**Files:**
- Modify: `src/viur/testing/mirror.py:82` (and the surrounding docstring)
- Modify: `src/viur/testing/activation.py:328`
- Modify: `tests/test_runner.py` (comments around lines 108-110)
- Modify: `tests/test_activation.py` (comment around lines 699-700)

- [ ] **Step 1: Update `mirror.py` docstring**

In `src/viur/testing/arm_tokenless_browsing` docstring (`src/viur/testing/mirror.py`), replace the sentence referencing the env var:

Old (around line 81-82):
```python
    Intended to run inside :func:`viur.testing.setup` after
    :func:`viur.testing.activate`, when ``VIUR_TESTING_TOKENLESS`` is set.
```
New:
```python
    Intended to run inside :func:`viur.testing.setup` after
    :func:`viur.testing.activate`, when the resolved mode is ``dev``
    (``VIUR_TESTING=dev:<ns>``).
```

- [ ] **Step 2: Update `activation.py` docstring**

In `src/viur/testing/activation.py`, the `activate()` docstring `:param namespace:` (around lines 327-330) references `VIUR_TESTING_NAMESPACE`. Replace:

Old:
```python
        normalised to ``None`` — same convention as
        :data:`VIUR_TESTING_NAMESPACE` in :func:`viur.testing.setup`,
        so direct programmatic activation and env-var-driven boot
        behave identically.
```
New:
```python
        normalised to ``None`` — same convention as the ``VIUR_TESTING``
        namespace part in :func:`viur.testing.setup`, so direct
        programmatic activation and env-var-driven boot behave identically.
```

- [ ] **Step 3: Update test comments**

In `tests/test_runner.py` (around lines 108-110) and `tests/test_activation.py` (around lines 699-700), replace any literal `VIUR_TESTING_NAMESPACE` in comments/docstrings with `the VIUR_TESTING namespace part`. These are comments only — no behaviour change.

Run to find them:
```bash
grep -rn "VIUR_TESTING_NAMESPACE\|VIUR_TESTING_ENABLE\|VIUR_TESTING_TOKENLESS" src/ tests/
```
Expected after edits: no matches.

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS, 100 % coverage.

- [ ] **Step 5: Commit**

```bash
git add src/viur/testing/mirror.py src/viur/testing/activation.py tests/test_runner.py tests/test_activation.py
git commit -m "docs: drop old env-var names from code docstrings"
```

---

## Task 4: Documentation & CHANGELOG

**Files:**
- Modify: `README.md`, `docs/getting-started.md`, `docs/dev-mirror-mode.md`, `CHANGELOG.md`
- Modify: `playwright/src/bin/init.ts`, `playwright/bin/init.mjs`, `playwright/src/test-mode.ts`, `playwright/src/vite-plugin.ts`

- [ ] **Step 1: Update README and docs**

Find every occurrence and replace with the new grammar:
```bash
grep -rn "VIUR_TESTING_ENABLE\|VIUR_TESTING_NAMESPACE\|VIUR_TESTING_TOKENLESS" README.md docs/
```

Replacement mapping to apply in prose and code fences:
- `VIUR_TESTING_ENABLE=1 viur run` → `VIUR_TESTING=1 viur run` (or `VIUR_TESTING=test`)
- `VIUR_TESTING_ENABLE=1 VIUR_TESTING_NAMESPACE=ak viur run` → `VIUR_TESTING=test:ak viur run`
- `VIUR_TESTING_ENABLE=1 VIUR_TESTING_NAMESPACE=ak VIUR_TESTING_TOKENLESS=1 viur run develop` → `VIUR_TESTING=dev:ak viur run develop`
- Any standalone mention of the three vars → describe the single `VIUR_TESTING=<mode>[:<namespace>]` var.

Specifically:
- `README.md` — the "Running the dev server", banner examples, and "Concurrency" sections.
- `docs/getting-started.md` — boot instructions.
- `docs/dev-mirror-mode.md` — the "Tokenless browsing — at boot" section (replace the 3-var boot line with `VIUR_TESTING=dev:ak viur run develop`) and the "Non-negotiables" line about not setting `VIUR_TESTING_TOKENLESS` in CI → "do not use `dev` mode in CI".

- [ ] **Step 2: Update Playwright text/comments**

These files only *mention* the vars in console output / comments (the runner never sets them). Replace `VIUR_TESTING_ENABLE=1` with `VIUR_TESTING=test` (or `VIUR_TESTING=1`) and the `VIUR_TESTING_NAMESPACE` mentions with "the VIUR_TESTING namespace part":
```bash
grep -rn "VIUR_TESTING_ENABLE\|VIUR_TESTING_NAMESPACE" playwright/
```
Edit `playwright/src/bin/init.ts`, `playwright/bin/init.mjs`, `playwright/src/test-mode.ts`, `playwright/src/vite-plugin.ts`. No TypeScript logic changes — strings/comments only.

- [ ] **Step 3: Add the CHANGELOG entry**

In `CHANGELOG.md`, under `## [Unreleased]`, add a `### Changed` (Breaking) entry:

```markdown
### Changed

- **BREAKING — single boot env var.** The three server-side boot
  variables `VIUR_TESTING_ENABLE`, `VIUR_TESTING_NAMESPACE` and
  `VIUR_TESTING_TOKENLESS` are replaced by one
  `VIUR_TESTING=<mode>[:<namespace>]` (`mode` = `test` or `dev`;
  `1`/`true`/`on` alias `test`; unset/`0`/`off`/`false` = off).
  `dev` mode (= test mode + tokenless browsing) now **requires** a
  namespace. Migration:

      VIUR_TESTING_ENABLE=1                                   → VIUR_TESTING=1   (or =test)
      VIUR_TESTING_ENABLE=1 VIUR_TESTING_NAMESPACE=ak         → VIUR_TESTING=test:ak
      VIUR_TESTING_ENABLE=1 VIUR_TESTING_NAMESPACE=ak \
        VIUR_TESTING_TOKENLESS=1                              → VIUR_TESTING=dev:ak

  `setup()` drops `enable_env_var`, `namespace_env_var` and
  `tokenless_env_var`; it gains `env_var` (default `VIUR_TESTING`) plus
  explicit `mode`/`namespace` overrides.
```

Also move the existing `[Unreleased]` Dev-Mirror notes that mention `VIUR_TESTING_TOKENLESS` to use the new `VIUR_TESTING=dev:<ns>` form.

- [ ] **Step 4: Verify no stale references remain anywhere**

Run:
```bash
grep -rn "VIUR_TESTING_ENABLE\|VIUR_TESTING_NAMESPACE\|VIUR_TESTING_TOKENLESS\|enable_env_var\|namespace_env_var\|tokenless_env_var" \
  --include="*.py" --include="*.ts" --include="*.mjs" --include="*.md" .
```
Expected: no matches (the only acceptable matches are inside `CHANGELOG.md` migration examples).

- [ ] **Step 5: Commit**

```bash
git add README.md docs/ CHANGELOG.md playwright/
git commit -m "docs: document single VIUR_TESTING env var; migration notes"
```

---

## Task 5: Final verification

- [ ] **Step 1: Run the full suite with coverage gate**

Run: `python -m pytest -q`
Expected: all tests pass; coverage report shows `mode.py` at 100 % and `TOTAL ... 100%`; the run ends with `Required test coverage of 100% reached.`

- [ ] **Step 2: Smoke-check the parser by hand (optional)**

Run:
```bash
python -c "from viur.testing.mode import parse_spec; print(parse_spec('dev:ak'), parse_spec('1'), parse_spec(None))"
```
Expected: `('dev', 'ak') ('test', None) ('off', None)`

- [ ] **Step 3: Clean up the temp venv artifacts (if created in-repo)**

```bash
rm -rf .venv-test htmlcov coverage.xml .coverage
git status --short
```
Expected: working tree clean.

---

## Self-Review notes (already applied)

- **Spec coverage:** grammar table → `test_mode.py` (Task 1); single-var `setup()` → Task 2; clean break / removed surface → Tasks 2-3; hardening (dev needs ns) → `validate_spec` (Task 1) + boot test (Task 2); `=1` alias → `_TEST_ALIASES` (Task 1); affected files & migration → Tasks 3-4.
- **Type consistency:** `parse_spec`/`validate_spec`/`MODE_OFF`/`MODE_TEST`/`MODE_DEV` names are used identically across `mode.py`, `__init__.py`, and the tests.
- **No placeholders:** every code/edit step shows the concrete code or exact grep/replace.
