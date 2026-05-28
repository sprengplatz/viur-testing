# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] — 2026-05-28

`@spltz/viur-testing` only — the Python package stays at 0.2.0.
Introduces **Guarded Mode**: automatic detection of whether the
target backend is in test mode, with an interactive PIN gate for
the live-backend case. Lets Playwright drive read-only smoke tests
against a deployed application without spinning up a dedicated
test backend, while keeping the bilateral guarantee for everything
that does have one.

### Added

- **Auto mode detection** in `createGlobalSetup()` —
  `POST /json/_test/config/status` decides the run mode:
  - 200 + valid payload → **Test Mode** (unchanged flow).
  - 404 → **Guarded Mode** + interactive PIN challenge.
  - 5xx / timeout / malformed / integrity-fail → hard error,
    never a silent downgrade.
- **6-digit PIN challenge** (`runPinChallenge`): fresh code per
  run, displayed yellow + space-separated above the backend URL.
  Wrong PIN → abort. No TTY → "Run from an interactive terminal."
  No persisted ACK file, no env-var bypass — every run is its own
  human-in-the-loop decision.
- **Mode propagation via `VIUR_TESTING_MODE` env var**
  (exported as `MODE_ENV_VAR`). Workers inherit and the fixtures
  branch on it.
- New public exports: `detectMode`, `probeStatusEndpoint`,
  `runPinChallenge` + their option types, for hosts that want to
  build custom setup flows on top.
- `createGlobalSetup({ backendUrl })` — explicit option in
  addition to the existing `E2E_BACKEND_URL` env var (option
  wins when both are set).
- **`viur-testing-init` scaffolder picks the mode interactively.**
  On a TTY the CLI asks `[1] Test Mode / [2] Guarded Mode`,
  defaulting to Test. Non-TTY runs (CI scaffolding) default to
  Test silently. Skip the prompt with `--mode test|guarded` or
  the `--guarded` shortcut. The Guarded preset drops Vite,
  `.env.e2e`, and the `serverStatus`-using example spec; the
  generated `playwright.config.ts` points `baseURL` at the
  deployed backend instead of a local Vite dev server.

### Changed

- **`context` fixture is mode-aware.** In Test Mode it injects the
  `X-Viur-Test-Token` header as before; in Guarded Mode it
  returns a vanilla browser context (no headers, no overrides) so
  Playwright behaves like a real browser against the live
  application.
- **`serverStatus`, `backendApi` fixtures auto-skip in Guarded
  Mode** via `testInfo.skip(true, "uses _test infrastructure, ...")`.
  The consuming test counts as **skipped**, not **failed** —
  the spec stays valid in both modes without conditional code.
- **`callTestModule` / `callTestModuleRaw` auto-skip in Guarded
  Mode** via `test.skip(...)`. Called from `test.beforeAll` skips
  all tests in the describe; called from a test body skips that
  test only.
- **`global-teardown` is a no-op in Guarded Mode** — no session
  token was issued, nothing to release.

### Documentation

- Top-level README has a new "Guarded Mode" section pointing at
  the Playwright README for details.
- Playwright README has a full auto-detect table and the
  Guarded-Mode contract (TTY-required, no persisted ACK, what
  auto-skips).
- **mkdocs site has a dedicated `Guarded Mode` page**
  (`docs/guarded-mode.md`) with the auto-detect table, PIN
  display/input rules, fixture auto-skip semantics and the
  `--guarded` scaffold flag.
- **Getting Started + top-level README runner section rewritten
  around the npm package.** The pytest `conftest.py` example is
  gone — the canonical e2e wiring is now
  `npx viur-testing-init` → `npm test`. The Python primitives
  (`require_test_mode`, `finish`, `ServerStatus`) remain
  documented in the API reference for hosts that drive their own
  Python-side runner.

### Internal

- `test-mode.ts`: `requireTestMode` is now a thin wrapper over a
  shared `probeStatusEndpoint` helper that returns
  `{ kind: "armed", status } | { kind: "unarmed" }`. Both the
  explicit "require" path and the auto-detect path use it.
- New files: `pin-challenge.ts` (interactive 6-digit gate with
  injectable IO surface for tests) and `mode-detect.ts`
  (`detectMode` orchestrator).

### Quality

- TypeScript smoke harness covers the three probe outcomes
  (armed/unarmed/ambiguous), the PIN challenge (success / wrong
  PIN / no-TTY), the mode-detect dispatcher, and the
  `globalSetup` env-var plumbing. All 17 checks green.

## [0.2.0] — 2026-05-28

Post-design audit: tightens the bilateral guarantee, mostly on the
runner-side TypeScript half, and normalises namespace handling
end-to-end. No public API breaks; `tokenFile` is the only removal.

### Added

- TS runner: `expectedProjectId` option + `E2E_TEST_PROJECT_ID`
  env var, mirroring Python's `expected_project_id`.
- TS runner: SHA-256 `token_hash` verification and runtime
  `is_dev_server` check in `requireTestMode` — closes parity gap
  with Python's `require_test_mode`.
- TS Vite plugin: cached token auto-refreshes on observed HTTP
  403 and after a configurable TTL (default 1 h). New option
  `refreshIntervalMs` (0 disables TTL refresh; 403 path always on).
- TS fixtures: worker-scoped `_viurTestingStatus` reads
  `.auth/token.json` once per worker; `serverStatus`/`context`/
  `backendApi` consume it (was 3× per test).

### Changed

- Python: namespace `""` → `None` normalisation now applied in
  `activate()`, `ConfigModule.set_active()`, and
  `require_test_mode()` — was previously only in `setup()`.
- Python: `closed_system_allowed_paths` uses renderer-agnostic
  wildcards `*/_test/*` + `_test/*` (was `json/_test/*` only).
- Python: `TokenValidator` bootstrap-path check is now an exact
  segment-shape match (`/<renderer>?/_test/config/<action>`)
  instead of a permissive `path.endswith()`.
- Python: `register_test_submodule` enforces
  `^[a-z][a-z0-9_-]*$` and rejects names shadowing existing
  `TestModule`/`Module` attributes (e.g. `json`, `handler`).
- Python: banner injection detects viur-core's banner width at
  runtime (falls back to 80 if detection misses).
- Python: `_load_project_api` walks past every `viur.testing`
  frame instead of hard-coding `inspect.stack()[2]`.
- TS: `expectedNamespace=""` is normalised to `null`, matching
  the server-side `VIUR_TESTING_NAMESPACE=` convention.
- TS: `assertNoDirectPlaywrightImports` skips `node_modules`,
  `.git`, `dist`, `build`, `coverage`, `playwright-report`,
  `test-results`, `.next`; strips line + block comments before
  scanning; clear error when `testsDir` does not exist.
- TS: `finishTestMode` sends `X-Viur-Test-Token` (symmetry with
  Python's `finish()`).
- TS: `callTestModuleRaw` cookies carry the full Playwright
  `Cookie` shape (`sameSite`, `secure`, `httpOnly`, `expires`
  added), derived from `APIRequestContext.storageState()`.
- TS: `viur-testing-init` pins generated `package.json` to
  `^<own-version>` instead of `"*"`.
- TS: `viur-testing-init` `vite.e2e.config.ts` template is now
  stand-alone; the Sprengplatz-specific `appConfig` overlay
  moved into a commented `OVERLAY` block at the bottom. The
  `dev:frontend` script is dropped from the default scripts.

### Removed

- TS: `tokenFile` option on `createGlobalSetup` /
  `createGlobalTeardown`. The path was a footgun — changing it
  silently broke the fixtures that hard-coded
  `.auth/token.json`. A single internal `tokenFilePath()` helper
  is now the source of truth across globalSetup, globalTeardown,
  fixtures, and test-module helpers.

### Fixed

- Python: `_patch_key_factory` + `_patch_legacy_urlsafe` are now
  idempotent — repeated `activate()` no longer stacks wrapper
  layers (relevant for test re-entry).

### Documentation

- README clarifies token persistence: server side never writes
  to disk; runner side caches under `.auth/token.json` +
  `process.env.E2E_TEST_TOKEN`.
- Playwright README documents Vite token refresh and the
  `E2E_TEST_PROJECT_ID` env var; init-template description
  updated for the stand-alone Vite config.

### Quality

- 212 pytest cases (was 187), 100% branch coverage held.
- TS smoke-test harness covers the preflight branches, the
  forbidden-imports walker, the Vite refresh paths, and the
  init scaffolder's version pin.

## [0.1.0] — initial design

The initial design pre-dates the audit round. Entries below
document the design as shipped before 0.2.0.

### Distribution

- The Python package ships on PyPI as **`spltz-viur-testing`** (the
  experimental `spltz-` prefix marks it pre-1.0). The Python import
  path stays `viur.testing` — namespace package, no rename in host
  code. Install with `pip install spltz-viur-testing`.
- A companion npm package **`@spltz/viur-testing`** lives in
  `playwright/` next to the Python sources. It bundles Playwright
  fixtures, the global-setup / global-teardown factories, the
  forbidden-import guard, test-module helpers, the Vite plugin and
  a `viur-testing-init` CLI for scaffolding new e2e suites.

### Test-mode activation

- `viur.testing.setup()` and `viur.testing.register_modules()` — two
  one-liner host wrappers around the underlying primitives. `main.py`
  is reduced to `import viur.testing; viur.testing.setup()` and
  `modules/__init__.py` to `viur.testing.register_modules(globals())`.
  Both are no-ops in production (env var unset / state inactive).
- `viur.testing.activate()` — atomic test-mode activation. Order of
  checks: `viur.core.db.transport` not yet imported, then
  `conf.instance.is_dev_server` true, then builds a
  `datastore.Client(database=…, namespace=…)` against the test
  database, runs a synchronous probe roundtrip, patches
  `transport.__client__`, monkey-patches
  `viur.core.db.types.Key.__init__` to inject `database=` /
  `namespace=` on every newly constructed Key, monkey-patches
  `google.cloud.datastore.Key.to_legacy_urlsafe` so it tolerates
  named databases, extends
  `conf.security.closed_system_allowed_paths` with broad `_test/*`
  wildcards, primes `ConfigModule`, installs the request validator
  and wraps `viur.core.setup` so the dev-server boot banner shows
  the test-mode parameters. No on-disk state.
- `viur.testing.protect()` and `ProductionGuardValidator` — host
  installs the guard via `protect()` in every environment. On a
  non-dev server, any request carrying an `X-Viur-Test-Token`
  header is rejected with 403 regardless of the header's value. In
  dev the guard is a no-op (the full `TokenValidator` already
  handles the header).
- `setup(api_dir="testing")` — registers the project-side test API
  package as importable top-level `api` via `importlib.util`. The
  directory lives outside `deploy/` (so `gcloud app deploy` never
  uploads it) and is wired in by resolving `<dirname(main.py)>/../<api_dir>/api/__init__.py`.
  Walks `inspect.stack()` to anchor the path at the caller's
  `main.py` so the host needs nothing but `viur.testing.setup()`.
  Prints a one-line info message when the directory does not exist
  rather than crashing.

### Datastore namespace isolation

- `activate(database=…, namespace=…)` and the
  `VIUR_TESTING_NAMESPACE` env var — partition writes inside one
  `viur-tests` database so several engineers (or CI runs) can share
  the database without colliding on each other's entities. Empty
  string or unset = no namespace (default Datastore namespace).
- `_patch_key_factory` injects both `database=` and `namespace=`
  defaults into `viur.core.db.Key.__init__`, so every Key
  viur-core builds during test mode points at the same slice as
  the active client.
- `_patch_legacy_urlsafe` monkey-patches
  `google.cloud.datastore.Key.to_legacy_urlsafe` to temporarily
  clear `self._database` around the legacy serialisation. Without
  this every successful login crashed the server (viur-core uses
  `str(key)` in session save + JSON renders, which calls
  `to_legacy_urlsafe` which refuses named databases). The patch
  restores `_database` in `finally` so the key stays consistent
  even on exception paths.
- `ConfigModule.current_namespace()` and `_namespace` class state —
  reported back to runners via `/json/_test/config/status` so the
  preflight can assert the expected namespace.
- `require_test_mode(expected_namespace=…)` — runner-side check
  with `_UNSET` sentinel: pass a string for an exact namespace,
  `None` to assert the default namespace, omit the field to skip
  the check entirely.

### Bilateral session handshake

- `viur.testing._test.TestModule` — host-mountable container module
  under `/_test`. Carries `json = True` so viur-core's
  `__build_app` registers it under the JSON renderer. Refuses to
  instantiate outside a local dev server *or* when `activate()`
  has not run yet — structural last line of defence against
  accidental production mounts and silent
  "mounted-but-unactivated" states.
- `viur.testing._test.config.ConfigModule` — the bootstrap config
  submodule mounted as `/_test/config`. Carries the per-process
  class-level state (`_database`, `_namespace`, `_project_id`,
  `_token`, `_status_hooks`, `_finish_hooks`) and the same two
  mount guards as `TestModule` so a host that bypasses the
  container and mounts `ConfigModule` directly is still caught.
  Endpoint bodies are emitted as JSON strings (`Content-Type:
  application/json` + `json.dumps`) so viur-core's WSGI layer
  forwards a proper JSON body rather than a Python `repr` of a
  dict. Exposes two endpoints:
  - `POST /json/_test/config/status` — re-verifies dev-server +
    datastore database, then reads/creates the session token entity
    in the test database (kind `viur-tests`, entity `auth-token`)
    and returns it to the runner. Response carries `token`,
    `token_hash`, `database`, `namespace`, `project_id`,
    `version`, plus any extra keys returned from status hooks.
    Idempotent. POST-only so a parallel browser tab cannot
    drive-by trigger the endpoint via a simple GET (CORS
    preflight stops the cross-origin POST).
  - `POST /json/_test/config/finish` — re-verifies, deletes the
    token entity, clears the in-process token. Response includes
    extra keys returned from finish hooks. Test-mode itself stays
    armed.
- `viur.testing.validator.TokenValidator` — `RequestValidator`
  rejecting every non-bootstrap request that lacks a matching
  `X-Viur-Test-Token` header (constant-time compare).
  Auto-installed by `activate()`. Paths ending in
  `/_test/config/status` or `/_test/config/finish` bypass the
  token check so the runner can bootstrap a session before one
  exists.
- `viur.testing.require_test_mode()` — runner preflight: calls
  `/json/_test/config/status`, verifies test-mode + dev-server +
  database (and optionally namespace + project_id), checks the
  token's sha256 matches the server-reported `token_hash`,
  returns a `ServerStatus` with all session info.
- `viur.testing.finish()` — runner cleanup: deletes the token
  entity via `POST /json/_test/config/finish`.

### Host-registered test fixtures

- `viur.testing.register_test_submodule(name, cls)` — registers a
  project-specific submodule that mounts under `/_test/<name>/…`
  alongside the built-in `config`. Names are normalised to
  lowercase (viur-core lower-cases URL segments at request time),
  `config` is reserved, empty names are refused. Late registration
  via class-level dict on `TestModule`, consumed at mount time.
- `viur.testing.register_status_hook(hook)` and
  `register_finish_hook(hook)` — let project code attach callbacks
  that run inside the `/json/_test/config/status` and `…/finish`
  endpoints. Hook signature is `() -> dict | None`; returned dicts
  are merged into the JSON response (later hooks win on key
  conflicts). Use for project-specific test-mode prep (feature
  flags, seed-data references) and for surfacing extra info to
  runners. Side effects on `viur.core.conf` are allowed.

### Dev-server boot banner

- `viur.testing.banner.install_banner_patch(database, namespace)` —
  wraps `viur.core.setup()` so its `LOCAL DEVELOPMENT SERVER IS UP
  AND RUNNING` ASCII banner gains two extra lines: `database = …`
  (always) and `namespace = …` (rendered as `(default)` when not
  set). Pattern-matches the banner title and trailer instead of
  hard-counting line indices, so a future viur-core banner format
  change degrades gracefully. Idempotent — re-entry from
  `activate()` does not stack wrappers.

### Top-level package surface

- `viur.testing/__init__.py` re-exports only the viur-core-free
  surface: `activate`, `protect`, `setup`, `register_modules`,
  `register_test_submodule`, `register_status_hook`,
  `register_finish_hook`, `require_test_mode`, `finish`, plus
  dataclasses (`ServerStatus`), errors (`TestModePreflightError`)
  and constants (`TOKEN_HEADER`, `DEFAULT_DATABASE`). The heavy
  classes (`TestModule`, `ConfigModule`, `TokenValidator`,
  `ProductionGuardValidator`) live in their concrete submodules
  and must be imported from there — so `import viur.testing` does
  not trigger `viur.core` before the datastore client swap.

### Quality

- pytest suite against `viur-light-mock` + local stubs, **100%
  line + branch coverage** required. 182 tests at the time of
  writing.
- `smoke_test.py` — end-to-end script that walks every refuse path
  in a fresh subprocess and additionally exercises `activate()`
  all the way through to a real `datastore.Client(database=
  "viur-tests")` + probe roundtrip when run against a workstation
  with valid GCP credentials.

### Lessons learned from booting against a real viur-core project

These surprises only surfaced when the package was wired into the
real `deploy/` project and not into mocks. Each one is now built
in:

1. **Reserved Datastore kind prefix.** Original `PROBE_KIND` was
   `__viur_test_probe__`. Google Cloud Datastore reserves `__*__`
   for system-internal use and 400s the write with `The kind … is
   reserved`. Final name is `viur-test-probe`.
2. **Multi-database Key construction.** viur-core's `Key` class
   forwards `project=` to `google.cloud.datastore.Key` but **not**
   `database=` or `namespace=`. With a named-DB client every Key
   viur-core builds is for the default database, and Datastore
   rejects the call with `mismatched databases within request`.
   Solved by `_patch_key_factory` wrapping `Key.__init__`.
3. **`to_legacy_urlsafe` refuses named databases.** viur-core's
   `Key.__str__` calls `to_legacy_urlsafe()`, which raises on any
   key with `database` set. Triggers on session-save and
   login-success JSON render. Solved by `_patch_legacy_urlsafe`.
4. **viur-core lower-cases URL segments at routing time.**
   `register_submodule("userLogin", …)` would register under the
   mixed-case key but the router looks up `userlogin`, so the
   route silently 404'd. `register_submodule` now lower-cases the
   key.
5. **Closed-system gate.** Many host projects set
   `conf.security.closed_system = True`. Once on, every URL not
   in `closed_system_allowed_paths` returns 401 before the route
   is resolved. `activate()` extends the allow-list with broad
   `_test/*` / `*/_test/*` wildcards so both the built-in
   bootstrap and host-registered fixture submodules pass through;
   the `TokenValidator` is the actual access control.
6. **Render-name opt-in.** `__build_app` only registers a module
   class for a given renderer if `getattr(cls, render_name,
   False)` is truthy. Without `TestModule.json = True` the routes
   are silently not mounted, and the actual HTTP URL becomes
   `/json/_test/config/…` (JSON renderer prefix) — not
   `/_test/config/…` as one might expect from the module
   hierarchy.
7. **Class vs. instance in modules namespace.** `__build_app`
   iterates `vars(modules)` and only picks up subclasses of
   `Module` (or already-instanced `InstancedModule`). A bare
   module instance is silently skipped. The host-side wiring
   registers `TestModule` as a *class*, not as an instance.

[Unreleased]: https://github.com/sprengplatz/viur-testing/compare/v0.3.0-npm...HEAD
[0.3.0]: https://github.com/sprengplatz/viur-testing/releases/tag/v0.3.0-npm
[0.2.0]: https://github.com/sprengplatz/viur-testing/releases/tag/v0.2.0
[0.1.0]: https://github.com/sprengplatz/viur-testing/releases/tag/v0.1.0
