# Getting started

This page walks through the minimum setup required to put a viur-core
project into a safe Playwright-friendly test mode.

## Prerequisites

- Python ≥ 3.12
- viur-core ≥ 3.7, < 4 (with `google-cloud-datastore` ≥ 2.18, which
  supports named databases via the `database=` kwarg)
- A Google Cloud Datastore project where you can create a named
  database

## 1. Create the test database

In the GCP console, create a new named Datastore database in the
*same project* as your live database. Default name: **`viur-tests`**.
You can pick another name and pass it to `setup(database=…)`.

You do not need to migrate data into the new database — viur-testing
will let viur-core's startup tasks populate it on first boot
(initial admin user, `viur-conf` entity, etc.).

## 2. Install viur-testing

Add it as a runtime dependency in your project. With pipenv:

```bash
pipenv install -e ./sources/viur-testing
```

Or in pyproject.toml/setup.cfg add `viur-testing` alongside
`viur-core`.

## 3. Wire `main.py`

```python
# main.py — viur.testing.setup() MUST be the first lines, before any
# ``from viur.core ...`` import.
import viur.testing
viur.testing.setup()

# Only now may viur.core be imported.
from viur.core import setup as core_setup
import modules, render

app = core_setup(modules, render)
```

`setup()` does, in order:

1. Reads `os.environ["VIUR_TESTING_ENABLE"]`.
2. If truthy, calls [`activate(database="viur-tests")`][viur.testing.activation.activate]
   which:
    - verifies `viur.core.db.transport` has not been imported yet,
    - verifies `conf.instance.is_dev_server`,
    - builds a `datastore.Client(database="viur-tests")`,
    - runs a probe write+read roundtrip,
    - patches `viur.core.db.transport.__client__`,
    - patches `viur.core.db.types.Key.__init__` to default
      `database=` to the test database (otherwise every Key viur-core
      builds is for the default DB and Datastore rejects the call),
    - extends `conf.security.closed_system_allowed_paths` with the
      bootstrap endpoints,
    - primes the in-process state on `ConfigModule`,
    - installs the [`TokenValidator`](api/validator.md).
3. Always calls [`protect()`][viur.testing.protection.protect] to
   install the [`ProductionGuardValidator`](api/validator.md) — that
   guard 403s any `X-Viur-Test-Token` header outside dev,
   regardless of value.

## 4. Wire `modules/__init__.py`

```python
# modules/__init__.py — after your usual auto-discovery
import viur.testing
viur.testing.register_modules(globals())
```

`register_modules()` is idempotent. In production (no `activate()`)
it's a no-op; in test mode it registers
[`TestModule`](api/test.md) as a class so viur-core's `__build_app`
picks it up and routes `/_test/config/status` + `/_test/config/finish`.

## 5. Run the dev server in test mode

```bash
VIUR_TESTING_ENABLE=1 viur run develop
```

On first boot you should see in the log:

- viur-core's startup task creating an admin user in `viur-tests`
- a new `viur-conf` entity
- a new `hmacKey` entity

…all in the **`viur-tests`** database. Your live database stays
untouched.

## 6. Hook up the runner

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

[`require_test_mode`](api/runner.md) is the runner-side preflight: it
calls `POST /_test/config/status`, verifies the server's reply
(`test_mode`, `is_dev_server`, `database`, `project_id`, and the
SHA-256 token hash matches the returned token) and returns a
[`ServerStatus`](api/runner.md) carrying the session token. On any
mismatch it raises
[`TestModePreflightError`](api/runner.md) — no test ever runs.

For Playwright, inject the token on every browser request:

```python
@pytest.fixture
def context(browser, test_session):
    return browser.new_context(
        extra_http_headers={"X-Viur-Test-Token": test_session.token},
    )
```

## 7. Production deployment

Leave both wiring calls in place. In a cloud deployment:

- `VIUR_TESTING_ENABLE` is unset → `setup()` skips `activate()` and
  only installs the production header guard.
- `register_modules()` checks `ConfigModule.is_active()` and is a
  no-op → the `/_test/*` routes never mount.
- Any inbound request carrying `X-Viur-Test-Token` is 403'd by
  the production guard.

If anything goes wrong (env var accidentally set on a cloud run),
`activate()` itself refuses because `conf.instance.is_dev_server` is
false — the app fails to boot rather than silently switching to a
test database.
