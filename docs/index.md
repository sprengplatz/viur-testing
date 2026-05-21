# viur-testing

Safe test-mode for ViUR core projects — primarily for Playwright
end-to-end tests.

## What it gives you

`viur-testing` swaps the running viur-core process onto a dedicated
**named Datastore database** (default: `viur-tests`) and refuses to
let any request reach a module unless the caller can prove they meant
to talk to the test instance.

## Six lines of defence

1. **`activate()` refuses outside `conf.instance.is_dev_server`**.
2. **Synchronous probe** — a write+read roundtrip against the target
   database verifies the client swap landed before the application
   continues booting.
3. **`TestModule` and `ConfigModule` both refuse to instantiate
   outside dev or without prior `activate()`** — structural last-line
   guard: either condition raises, so an accidental production mount
   or a forgotten activate-call fails loudly at boot. The guard sits
   on both classes so a host that bypasses the container is still
   caught.
4. **Per-request `X-Viur-Test-Token`** — every non-bootstrap request
   must carry it, constant-time compared. 403 otherwise.
5. **`protect()` installs the production header guard** that 403s any
   request carrying the test token header outside dev, regardless of
   value. Installed in every environment.
6. **Runner preflight** — `require_test_mode()` calls
   `/_test/config/status` and refuses to start tests if the server
   reports a different database, project id or token hash than
   expected.

## Endpoints

- `POST /_test/config/status` — provisions (or returns) the session
  token in the test database, re-verifies dev-server + database,
  returns JSON `{test_mode, is_dev_server, database, project_id,
  token, token_hash, version}`. POST-only to block drive-by GETs
  from parallel browser tabs.
- `POST /_test/config/finish` — deletes the token entity from the
  test database, ending the session.

Both are exposed by [`ConfigModule`](api/config.md) under the
[`TestModule`](api/test.md) container. Future test flavours go under
the same `/_test/` umbrella as additional submodules.

## Quick taste

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
- [Host API](api/host.md) — `setup`, `register_modules`, `activate`,
  `protect`.
- [Runner API](api/runner.md) — `require_test_mode`, `finish`,
  `ServerStatus`, `TestModePreflightError`.
- [TestModule](api/test.md) and [ConfigModule](api/config.md) — the
  viur-core modules behind the endpoints.
- [Validators](api/validator.md) — `TokenValidator` and
  `ProductionGuardValidator`.
- [Changelog](changelog.md).
