# viur-testing

[![Tests](https://github.com/sprengplatz/viur-testing/actions/workflows/test.yml/badge.svg)](https://github.com/sprengplatz/viur-testing/actions/workflows/test.yml)
[![Docs](https://github.com/sprengplatz/viur-testing/actions/workflows/docs.yml/badge.svg)](https://sprengplatz.github.io/viur-testing/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Safe test-mode for ViUR core projects — primarily for Playwright
end-to-end tests. Swaps the default datastore database out for a
dedicated named database (default: `viur-tests`), with a bilateral
handshake that refuses to let any test or endpoint run unless both the
server **and** the runner agree they are talking to the test instance.

## Bilateral guarantee in six lines

1. **`activate()` refuses outside `conf.instance.is_dev_server`** —
   read from viur-core's canonical flag.
2. **Synchronous datastore probe** in the target database has to
   succeed before the client swap is applied.
3. **`TestModule` *and* `ConfigModule` both refuse to instantiate**
   outside the dev server *or* without a prior `activate()` call —
   both `__init__`s raise in either case. Even a host that bypasses
   the `TestModule` container and mounts `ConfigModule` directly is
   subject to the same checks, so a forgotten activate or a stray
   production mount fails loudly at boot.
4. **Per-request token validator** (`X-Viur-Test-Token`) blocks every
   request that does not carry the session token, except the two
   bootstrap endpoints.
5. **`protect()` installs a production-side header guard** that 403s
   any request carrying the test token header outside dev, regardless
   of its value. Installed in every environment.
6. **Runner preflight** calls `/_test/config/status` and refuses to run
   any test if the server's reply (database, project_id, token hash)
   does not match.

The session token is stored only in the test database itself
(kind `viur-tests`, entity `auth-token`) — never on disk. App Engine
file-system writes are not needed.

## Module layout

```
/_test/                    TestModule (container, refuses outside dev mode)
  /_test/config/status     ConfigModule.status — issues/returns token
  /_test/config/finish     ConfigModule.finish — deletes token entity
```

Future test flavours (load test, integration helpers, …) go in as
sibling submodules under the same `_test` container.

## Requirements

- Python ≥ 3.12
- viur-core ≥ 3.7, < 4
- A named Datastore database (default name: `viur-tests`) created in
  your GCP project alongside `(default)`.

## Server-side wiring

Two one-liners. `main.py` — **as the first lines, before any
`viur.core` import**:

```python
import viur.testing
viur.testing.setup()

# Only now may viur.core be imported by your own code.
from viur.core import setup as core_setup
import modules
import render

core_setup(modules, render)
```

`viur.testing.setup()` checks the `VIUR_TESTING_ENABLE` env var; if
truthy it calls `activate()` (datastore client swap + key-factory
patch + closed-system whitelist + state priming + validator install)
and always installs the production header guard via `protect()`.

In `modules/__init__.py` register the test endpoints — idempotent and
safe to leave in place for production deployments (no-op when test
mode isn't armed):

```python
# modules/__init__.py
import viur.testing
viur.testing.register_modules(globals())
```

That exposes `POST /_test/config/status` and `POST /_test/config/finish`.
Both endpoints re-verify `conf.instance.is_dev_server` and the active
datastore database before performing any work — defence in depth on
top of the `TestModule.__init__` guard.

If you need more control, the two functions wrap underlying primitives
you can call yourself: `viur.testing.activate(database=...)`,
`viur.testing.protect()`, plus direct mounting via
`from viur.testing._test import TestModule`.

## Runner-side wiring (pytest + Playwright)

```python
# tests/conftest.py
import pytest
from viur.testing import require_test_mode, finish

_BASE_URL = "http://localhost:8080"


@pytest.fixture(scope="session")
def test_session():
    status = require_test_mode(_BASE_URL)
    yield status
    finish(_BASE_URL, status.token)
```

If the server is not in test mode, points at the wrong database, or
the token hash does not match the returned token, `require_test_mode`
raises `TestModePreflightError` and no test ever runs.

For Playwright, inject the token as a default header on the browser
context:

```python
@pytest.fixture
def context(browser, test_session):
    return browser.new_context(
        extra_http_headers={"X-Viur-Test-Token": test_session.token},
    )
```

## Naming

The Python package keeps its repository name `viur-testing` for stability,
but everything inside it speaks the generic *test* vocabulary so future
test flavours can be added under the same `TestModule` umbrella
without churn. The `_test` URL prefix's leading underscore signals
"system-internal, not for production callers".

## Development

```bash
git clone git@github.com:sprengplatz/viur-testing.git
cd viur-testing
pip install -e ".[dev]"
pytest                  # 100% coverage required
mkdocs serve            # docs at http://localhost:8000
```

## Documentation

See [sprengplatz.github.io/viur-testing](https://sprengplatz.github.io/viur-testing/).

## Changelog

See [CHANGELOG.md](CHANGELOG.md).

## License

MIT — see [LICENSE](LICENSE).
