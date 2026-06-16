# @spltz/viur-testing

Playwright fixtures, global setup/teardown helpers and spec-level
utilities for projects driven by
[`viur-testing`](https://github.com/sprengplatz/viur-testing).

The Python `viur-testing` package puts the server into test mode and
issues a session token; this package is the TypeScript-side glue that
sets that token as the `viur-test-token` cookie on every Playwright
context, drives the preflight/cleanup handshake, and offers ergonomic
helpers for the per-spec backend fixture endpoints under
`/json/_test/<spec>/…`.

## What's in here

| Export | Purpose |
|---|---|
| `test`, `expect` | Drop-in replacement for `@playwright/test`. The `context` fixture is overridden so every page in the suite carries the `viur-test-token` cookie. |
| `backendApi` fixture | Direct-to-backend APIRequestContext carrying the token cookie. |
| `serverStatus` fixture | The parsed `/json/_test/config/status` payload (token, db, namespace, project_id, …). |
| `callTestModule`, `callTestModuleRaw` | POST `/json/_test/<spec>/<action>` and parse the JSON response. `Raw` variant also returns the cookies — useful for backend session forging. |
| `createGlobalSetup`, `createGlobalTeardown` | Factories for `playwright.config.ts` that wire the preflight and cleanup. |
| `assertNoDirectPlaywrightImports` | Hard guard called from `globalSetup` — refuses to start the run if any spec imports `@playwright/test` directly. |

## Quick start

For a new project, scaffold the standard e2e file set with the
package's CLI. Run from the repo root — the suite lands under
`testing/e2e/` by default:

```sh
npx viur-testing-init
```

Custom location? Pass a path:

```sh
npx viur-testing-init e2e             # → ./e2e
npx viur-testing-init tests/playwright # → ./tests/playwright
npx viur-testing-init /tmp/scratch    # → absolute paths work too
```

The init drops a working `package.json`, `tsconfig.json`,
`playwright.config.ts`, `vite.e2e.config.ts`, `.env.e2e`, `.gitignore`
and an example spec. Files that already exist are skipped — re-runs
are safe.

The generated `vite.e2e.config.ts` is a stand-alone, **plain** backend
proxy: it boots Vite on `:8081` and proxies the standard ViUR routes
(`/vi`, `/json`, `/static`, `/resources`) to the backend on `:8080`. It
injects nothing — the browser carries the `viur-test-token` cookie, so
the proxy just routes. Inline `TODO` markers point at the `BACKEND`
constant and the proxy paths. If your project also has a Vite frontend
whose `vite.config` you want to layer on top, the file has a commented
`OVERLAY` block at the bottom showing the `mergeConfig(appConfig,
e2eConfig)` form.

## Wiring

**playwright.config.ts:**

```ts
import { defineConfig, devices } from "@playwright/test"
import { createGlobalSetup, createGlobalTeardown } from "@spltz/viur-testing"

export default defineConfig({
  testDir: "./tests",
  globalSetup: createGlobalSetup(),
  globalTeardown: createGlobalTeardown(),
  use: { baseURL: "http://localhost:8081/app/" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
})
```

**Specs:**

```ts
import { test, expect, callTestModule } from "@spltz/viur-testing"

test.describe("user login", () => {
  let creds: { name: string; password: string }

  test.beforeAll(async () => {
    const { credentials } = await callTestModule<{ credentials: typeof creds }>(
      "userLogin", "setup"
    )
    creds = credentials
  })
  test.afterAll(() => callTestModule("userLogin", "teardown"))

  test("logs in", async ({ page }) => {
    await page.goto("login")
    await page.locator('input[name="username"]').fill(creds.name)
    await page.locator('input[name="current-password"]').fill(creds.password)
    await page.locator('input[name="current-password"]').press("Enter")
    await expect(page).toHaveURL(/\/app\/?$/)
  })
})
```

**Manual browsing (no proxy token injection needed):**

The token rides as the `viur-test-token` cookie, so the Vite dev server
is a plain proxy and the browser carries the cookie itself. To browse
the test instance by hand, navigate once to
`http://localhost:8080/json/_test/config/enter` — the backend sets the
cookie (`SameSite=Strict; HttpOnly; Path=/`) and every subsequent
request, hard navigations included, is authorised. See the
[Development Mode](https://sprengplatz.github.io/viur-testing/dev-mirror-mode/)
docs.

## Environment variables

Read by `createGlobalSetup()` (and indirectly by the fixtures):

| Var | Default | Effect |
|---|---|---|
| `E2E_BACKEND_URL` | `http://localhost:8080` | Backend origin for preflight + APIRequestContexts. |
| `E2E_TEST_DATABASE` | `viur-tests` | Asserted in preflight. |
| `E2E_TEST_NAMESPACE` | _(unset)_ | Unset = skip namespace check; empty string = expect default namespace; non-empty = expect exact match. |
| `E2E_TEST_PROJECT_ID` | _(unset)_ | When set, the server's reported GCP `project_id` must match exactly — useful in CI where the dev server is pinned to a specific project. |

## Run modes (auto-detect)

`createGlobalSetup()` probes `POST /json/_test/config/status` on the
configured backend and picks the mode automatically:

| Probe outcome | Mode | What happens |
|---|---|---|
| 200 + valid test-mode payload | **Test Mode** | Token issued, `.auth/token.json` written, fixtures set the `viur-test-token` cookie on the context. |
| 404 | **Guarded Mode** | Interactive 6-digit PIN prompt on the terminal. On confirmation, the suite runs against the live backend without any token injection. Specs that depend on `_test/` infrastructure (`serverStatus`, `backendApi`, `callTestModule`) are **auto-skipped**, not failed. |
| 5xx, timeout, malformed JSON, integrity check fail | **Hard error** | Ambiguous server state — never silently falls back to Guarded Mode. |

Guarded Mode is meant for **read-only smoke tests against public
pages** of a deployed application (landing page renders, footer links
exist, login form shows, …) where spinning up a dedicated test
backend would be overkill or impossible. The PIN prompt is the
mandatory human-in-the-loop gate: it forces you to look at the URL
on the screen and type a fresh 6-digit code every run. No persisted
ACK, no env-var bypass.

If `stdin` is not a TTY (CI, background process, IDE task without an
attached terminal), Guarded Mode aborts immediately — there is no
human to confirm. CI either points at a test-mode-armed backend
(falls into Test Mode automatically) or fails the run.

The detected mode is propagated to workers via `VIUR_TESTING_MODE`
(`"test"` or `"guarded"`). Fixtures and `callTestModule` read this
to decide whether to skip.

## Hard guarantee

Specs **must** import `test` and `expect` from `@spltz/viur-testing`
(directly or via a project re-export), never from `@playwright/test`.
`createGlobalSetup` calls `assertNoDirectPlaywrightImports(testsDir)`
which walks the spec tree and refuses to start the run if any file
imports the bare Playwright fixture set — the bypass would skip the
mandatory token cookie and every backend call would 403.

ESLint can catch this at lint time too, but the global-setup check is
the non-bypassable safety net: `npx playwright test` skips lint, the
global-setup runs unconditionally.
