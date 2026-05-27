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
6. **Runner preflight** calls `/json/_test/config/status` and refuses to run
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

## Install

The PyPI distribution name is `spltz-viur-testing` (experimental
prefix); the Python import path stays `viur.testing`:

```sh
pip install spltz-viur-testing
```

```python
import viur.testing
viur.testing.setup()
```

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

That exposes `POST /json/_test/config/status` and `POST /json/_test/config/finish`.
Both endpoints re-verify `conf.instance.is_dev_server` and the active
datastore database before performing any work — defence in depth on
top of the `TestModule.__init__` guard.

If you need more control, the two functions wrap underlying primitives
you can call yourself: `viur.testing.activate(database=...)`,
`viur.testing.protect()`, plus direct mounting via
`from viur.testing._test import TestModule`.

## Running the dev server with test mode

Toggle test mode at boot by setting the env var that `setup()` reads:

```sh
VIUR_TESTING_ENABLE=1 viur run
```

Without the env var, `setup()` skips `activate()` and the process boots
against the default database as if the package were not installed.

When test mode is active, the dev-server boot banner gains two extra
lines — `database = …` and `namespace = …` — so the running slice is
visible at a glance. The namespace line is rendered unconditionally;
without `VIUR_TESTING_NAMESPACE` it falls back to `(default)`, making
it obvious that test mode is armed but namespace isolation is **not**
in effect:

```
# With VIUR_TESTING_NAMESPACE=alice
################## LOCAL DEVELOPMENT SERVER IS UP AND RUNNING ##################
#                          project = my-viur-project                           #
#                               python = 3.13.0                                #
#                                viur = 3.8.25                                 #
#                            database = viur-tests                             #
#                              namespace = alice                               #
################################################################################

# Without VIUR_TESTING_NAMESPACE (or with empty value)
################## LOCAL DEVELOPMENT SERVER IS UP AND RUNNING ##################
#                          project = my-viur-project                           #
#                               python = 3.13.0                                #
#                                viur = 3.8.25                                 #
#                            database = viur-tests                             #
#                            namespace = (default)                             #
################################################################################
```

## Concurrency: sharing one test database across multiple testers

The `viur-tests` database is a shared GCP resource. If two engineers
both boot a dev server with the same database and run tests at the
same time, their entities will collide — Person A's seed wipes
Person B's user, Person B's test queries find leftovers from Person A.

The fix is the optional `namespace` argument. ViUR-testing passes it
to `google.cloud.datastore.Client(database=…, namespace=…)` and rewires
`viur.core.db.Key` so every read and write in the process is scoped
to that namespace. Different namespaces in the same database are
fully isolated — no separate DB provisioning needed.

Boot each dev server with its own namespace:

```sh
# Alice's machine
VIUR_TESTING_ENABLE=1 VIUR_TESTING_NAMESPACE=alice viur run

# Bob's machine
VIUR_TESTING_ENABLE=1 VIUR_TESTING_NAMESPACE=bob viur run

# CI for PR #42
VIUR_TESTING_ENABLE=1 VIUR_TESTING_NAMESPACE=ci-pr-42 viur run
```

The runner-side `require_test_mode` can assert the expected namespace
to fail fast when somebody points at the wrong slice::

    from viur.testing import require_test_mode

    status = require_test_mode(
        "http://localhost:8080",
        expected_namespace="alice",  # omit to skip; pass None for default
    )

`VIUR_TESTING_NAMESPACE` may be empty or unset — both mean "no
namespace, use the Datastore default". This is the existing behaviour
when no namespaces are needed (e.g. single-developer setup).

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
