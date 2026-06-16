# viur-testing

Safe test-mode for ViUR core projects — primarily for Playwright
end-to-end tests.

## Why viur-testing?

`viur-testing` swaps the running viur-core process onto a dedicated
**named Datastore database** (default: `viur-tests`) and refuses to let
any request reach a module unless the caller can prove they deliberately
meant to talk to the test instance. This is backed by several
interlocking [security mechanisms](#security-mechanisms).

## Contents

The project ships as a PyPI package
([spltz-viur-testing](https://pypi.org/project/spltz-viur-testing)) and
an npm package
([`@spltz/viur-testing`](https://www.npmjs.com/package/@spltz/viur-testing)).
The PyPI package provides the backend extension; the npm package
provides the Playwright API and a stub generator.

**Python package:**

- ViUR 3 core patches for multi-Datastore and namespace support.
- Request validator for header checking.
- `viur-mirror` tool for copying data into a namespaced Datastore
  instance.
- PIN confirmation before start.

**npm package:**

- Header injection for Vite applications.
- PIN confirmation before start.
- Playwright patches that enforce the security mechanisms.
- `init` tool to generate a stub.

## Security mechanisms

1. **`activate()` refuses outside `conf.instance.is_dev_server`** — no
   test mode on a production instance.
2. **DB roundtrip** — a write+read cycle against the target database
   verifies the client swap landed before the application continues
   booting.
3. **`TestModule` and `ConfigModule`** refuse to instantiate outside the
   dev server or without a prior `activate()`.
4. **Test API outside `deploy/`** — the project-specific test modules
   live outside the deploy folder and are therefore never shipped to
   production.
5. **Per-request token `X-Viur-Test-Token`** — every request must carry
   the negotiated token, otherwise it is rejected.
6. **Runner preflight** — `require_test_mode()` calls
   `/_test/config/status` and refuses to start tests if the server
   reports a different database, project id or token hash than expected.
7. **`protect()`** — guards live instances against accidental requests
   that carry the testing header.

## Endpoints

- `POST /_test/config/status` — provisions (or returns) the session
  token in the test database, re-verifies dev-server + database,
  returns JSON `{test_mode, is_dev_server, database, project_id,
  token, token_hash, version}`. POST-only to block drive-by GETs
  from parallel browser tabs.
- `POST /_test/config/finish` — deletes the token entity from the
  test database, ending the session.

Both are exposed by [`ConfigModule`](api/config.md) under the
[`TestModule`](api/test.md) container. Test suites hang as additional
submodules under the same `/_test/` umbrella.

## Minimal example

Two one-liners in the host. `main.py`:

```python
import viur.testing
viur.testing.setup()

from viur.core import setup as core_setup
import modules, render
app = core_setup(modules, render)
```

`modules/__init__.py`:

```python
import viur.testing
viur.testing.register_modules(globals())
```

Runner-side:

```python
from viur.testing import require_test_mode, finish

status = require_test_mode("http://localhost:8080")
try:
    # run tests, sending X-Viur-Test-Token: status.token
    ...
finally:
    finish("http://localhost:8080", status.token)
```

## Where to go next

- [Getting started](getting-started.md) — step-by-step host + runner
  wiring with the GCP-side prep (named Datastore database).
- [Development Mode](dev-mirror-mode.md) — relaxed variant that
  simplifies test development.
- [Guarded Mode](guarded-mode.md) — variant that can run, within limits,
  against any database (including live).
- [Changelog](changelog.md).
