# Getting started

This page covers the minimum setup required to put a viur-core project into a
safe, Playwright-ready test mode.

## Test mode

Test mode is the safest mode and the default: all security mechanisms are
active. It is the only mode that starts without a PIN prompt — and therefore the
only one usable in automated CI/CD.

Limitation: regular requests, e.g. from the Admin, are rejected because they do
not carry a valid `viur-test-token` cookie. See [Development Mode](dev-mirror-mode.md)
for how to use them anyway.

## Prerequisites

- Python ≥ 3.12
- viur-core ≥ 3.7, < 4

## Create the test database

In the GCP console, create a new named Datastore database in the *same project*
as your live database. Default name: **`viur-tests`**. A different name is
possible and is passed to `setup(database=…)`.

No data migration is needed — viur-core's startup tasks populate the database on
first boot (initial admin user, `viur-conf` entity, etc.).

## Install viur-testing

Add it as a **runtime** dependency (the package is also imported in production
to install the `protect()` guard). With pipenv:

```bash
pipenv install spltz-viur-testing
```

or with uv:

```bash
uv add spltz-viur-testing
uv sync
```

## Wire `main.py`

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

`setup()` installs all patches and validators and must therefore be called
first — before any `from viur.core …` import.

## Wire `modules/__init__.py`

```python
# modules/__init__.py — after your usual auto-discovery
import viur.testing
viur.testing.register_modules(globals())
```

`register_modules()` registers the nested `TestModule` together with
`ConfigModule`, so the endpoints `_test/config/status` and
`_test/config/finish` become available. In production (without a prior
`activate()`) the call is a no-op.

## Run the dev server in test mode

```bash
VIUR_TESTING=1 viur run develop
```

On first boot you should see in the log:

- viur-core's startup task creating an admin user in `viur-tests`,
- a new `viur-conf` entity,
- a new `hmacKey` entity —

…all in the **`viur-tests`** database. Your live database stays untouched.
Additionally, the boot banner shows the database and namespace information.

## Scaffold the Playwright suite

The companion npm package
[`@spltz/viur-testing`](https://www.npmjs.com/package/@spltz/viur-testing)
ships a one-shot scaffolder:

```sh
npx viur-testing-init
```

The scaffolder always creates a **Test Mode** suite. Without a path argument it
walks up the directory tree until it finds the `deploy/` folder and proposes
`<root>/testing/e2e` as the target — the path can be confirmed or adjusted
before writing. Existing files are skipped on re-runs.

## Install and boot the suite

In the scaffolded directory:

```sh
cd testing/e2e
npm install
npx playwright install --with-deps chromium
```

The generated `playwright.config.ts` calls `createGlobalSetup()` (from
`@spltz/viur-testing`) which:

- probes `POST /json/_test/config/status` against `E2E_BACKEND_URL`,
- on **HTTP 200** validates the bilateral handshake (`test_mode`,
  `is_dev_server`, `database`, `project_id`; the SHA-256 `token_hash` matches
  the returned token) and writes the session token to `.auth/token.json` for the
  worker fixtures to pick up,
- on **HTTP 404** falls into Guarded Mode (interactive PIN gate),
- on anything else (5xx, malformed JSON, integrity failure) aborts the run — no
  silent downgrades.

Run the suite against your local test-mode-armed backend:

```sh
npm test
```
