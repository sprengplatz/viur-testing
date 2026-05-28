/**
 * Custom Playwright `test` extension that injects the viur-testing
 * token header into EVERY request the suite makes.
 *
 * Two layers:
 *
 * 1. `context` — the browser context all `page.goto` / fetch / XHR
 *    calls from inside the page flow through. We override the default
 *    `context` fixture so every page in the suite is born with
 *    `extraHTTPHeaders: { 'X-Viur-Test-Token': <token> }`.
 *
 * 2. `backendApi` — Playwright's APIRequestContext for direct HTTP calls
 *    from the test code itself. Same treatment.
 *
 * The token is provisioned once in `globalSetup` (see
 * `createGlobalSetup`), persisted to disk under `.auth/token.json`,
 * and read back here. The token-header rule is non-negotiable: any
 * request without the header is rejected with 403 by viur-testing's
 * TokenValidator (only the `/json/_test/config/{status,finish}`
 * bootstrap endpoints are exempt, and those run inside `test-mode.ts`
 * with their own dedicated contexts).
 */

import { test as base, expect, type APIRequestContext, type BrowserContext } from "@playwright/test"
import { readFileSync } from "node:fs"

import { TOKEN_HEADER, authenticatedApi, type ServerStatus } from "./test-mode.js"
import { tokenFilePath } from "./token-storage.js"

function loadServerStatus(): ServerStatus {
  const path = tokenFilePath()
  try {
    return JSON.parse(readFileSync(path, "utf8")) as ServerStatus
  } catch (err) {
    throw new Error(
      `Could not read viur-testing session info from ${path}. ` +
        `Did globalSetup run? Original error: ${(err as Error).message}`,
    )
  }
}

export interface TestModeFixtures {
  /** Full server status returned by `/json/_test/config/status`. */
  serverStatus: ServerStatus
  /** Direct backend APIRequestContext that already carries the token header. */
  backendApi: APIRequestContext
}

interface TestModeWorkerFixtures {
  /**
   * Worker-scoped cache of the server status JSON, populated by reading
   * `.auth/token.json` exactly once per worker process. Both the
   * `context` override and the `backendApi` fixture (and the
   * `serverStatus` fixture itself) consume this so the JSON file is
   * not re-read for every spec.
   *
   * Underscore-prefixed and not re-exported as part of the public
   * surface — it is an implementation detail, callers go through
   * `serverStatus`/`backendApi`/`context` instead.
   */
  _viurTestingStatus: ServerStatus
}

export const test = base.extend<TestModeFixtures, TestModeWorkerFixtures>({
  _viurTestingStatus: [
    async ({}, use) => {
      await use(loadServerStatus())
    },
    { scope: "worker" },
  ],

  // Override the built-in `context` fixture so every page gets the
  // token header on every request automatically. Pages spawned via
  // `await context.newPage()` and via the standard `page` fixture
  // both inherit this.
  context: async ({ browser, _viurTestingStatus }, use) => {
    const ctx: BrowserContext = await browser.newContext({
      extraHTTPHeaders: { [TOKEN_HEADER]: _viurTestingStatus.token },
    })
    await use(ctx)
    await ctx.close()
  },

  serverStatus: async ({ _viurTestingStatus }, use) => {
    await use(_viurTestingStatus)
  },

  backendApi: async ({ _viurTestingStatus }, use) => {
    const backendUrl = process.env.E2E_BACKEND_URL ?? "http://localhost:8080"
    const ctx = await authenticatedApi({
      backendUrl, token: _viurTestingStatus.token,
    })
    await use(ctx)
    await ctx.dispose()
  },
})

export { expect }
