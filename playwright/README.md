# @spltz/viur-testing

Playwright fixtures, global setup/teardown helpers, spec-level utilities
and a Vite plugin for projects driven by
[`viur-testing`](https://github.com/sprengplatz/viur-testing).

The Python `viur-testing` package puts the server into test mode and
issues a session token; this package is the TypeScript-side glue that
guarantees every Playwright request carries that token, drives the
preflight/cleanup handshake, and offers ergonomic helpers for the
per-spec backend fixture endpoints under `/json/_test/<spec>/…`.

## What's in here

| Export | Purpose |
|---|---|
| `test`, `expect` | Drop-in replacement for `@playwright/test`. The `context` fixture is overridden so every page in the suite carries `X-Viur-Test-Token`. |
| `backendApi` fixture | Direct-to-backend APIRequestContext with the token already attached. |
| `serverStatus` fixture | The parsed `/json/_test/config/status` payload (token, db, namespace, project_id, …). |
| `callTestModule`, `callTestModuleRaw` | POST `/json/_test/<spec>/<action>` and parse the JSON response. `Raw` variant also returns the cookies — useful for backend session forging. |
| `createGlobalSetup`, `createGlobalTeardown` | Factories for `playwright.config.ts` that wire the preflight and cleanup. |
| `assertNoDirectPlaywrightImports` | Hard guard called from `globalSetup` — refuses to start the run if any spec imports `@playwright/test` directly. |
| `viurTestingTokenFetch`, `withTokenInjection` | Vite plugin + proxy entry factory. Makes the dev server a transparent test-mode-aware reverse proxy so engineers can open the app in a browser without a token round-trip. |

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

The generated `vite.e2e.config.ts` is a stand-alone backend-proxy
config: it boots Vite on `:8081`, proxies the standard ViUR routes
(`/vi`, `/json`, `/static`, `/resources`) to the backend on `:8080`,
and stamps `X-Viur-Test-Token` on every forwarded request. Inline
`TODO` markers point at the two values you usually want to review —
the `BACKEND` constant and the proxy paths. If your project also has
a Vite frontend whose `vite.config` you want to layer on top, the
file has a commented `OVERLAY` block at the bottom showing the
`mergeConfig(appConfig, e2eConfig)` form.

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

**vite.config.ts (or an overlay for e2e mode):**

```ts
import { defineConfig } from "vite"
import { viurTestingTokenFetch, withTokenInjection } from "@spltz/viur-testing"

const BACKEND = "http://localhost:8080"

export default defineConfig({
  plugins: [viurTestingTokenFetch({ backendUrl: BACKEND })],
  server: {
    port: 8081,
    proxy: {
      "/vi/": withTokenInjection(BACKEND),
      "/json": withTokenInjection(BACKEND),
      "/static": { target: BACKEND, changeOrigin: false },
      "/resources": { target: BACKEND, changeOrigin: false },
    },
  },
})
```

The Vite plugin **refreshes the cached token automatically** — both
when a proxied backend response comes back with HTTP 403 (the symptom
of another runner having ended the session via `/_test/config/finish`
while this Vite dev server was running) and after the configurable
`refreshIntervalMs` (default: 1 hour) of idle time. A long-running
`vite dev` session will therefore self-heal rather than serving 403s
indefinitely. Pass `refreshIntervalMs: 0` to either factory to
disable TTL refresh and keep only the 403 path.

## Environment variables

Read by `createGlobalSetup()` (and indirectly by the fixtures):

| Var | Default | Effect |
|---|---|---|
| `E2E_BACKEND_URL` | `http://localhost:8080` | Backend origin for preflight + APIRequestContexts. |
| `E2E_TEST_DATABASE` | `viur-tests` | Asserted in preflight. |
| `E2E_TEST_NAMESPACE` | _(unset)_ | Unset = skip namespace check; empty string = expect default namespace; non-empty = expect exact match. |
| `E2E_TEST_PROJECT_ID` | _(unset)_ | When set, the server's reported GCP `project_id` must match exactly — useful in CI where the dev server is pinned to a specific project. |

## Hard guarantee

Specs **must** import `test` and `expect` from `@spltz/viur-testing`
(directly or via a project re-export), never from `@playwright/test`.
`createGlobalSetup` calls `assertNoDirectPlaywrightImports(testsDir)`
which walks the spec tree and refuses to start the run if any file
imports the bare Playwright fixture set — the bypass would skip the
mandatory token header and every backend call would 403.

ESLint can catch this at lint time too, but the global-setup check is
the non-bypassable safety net: `npx playwright test` skips lint, the
global-setup runs unconditionally.
